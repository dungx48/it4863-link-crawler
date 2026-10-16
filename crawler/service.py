"""One crawler process, triggered by midnight in Vietnam or an authenticated API."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
import hmac
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from filelock import FileLock, Timeout

from config import BASE_DIR, OUTPUT_FILE

log = logging.getLogger(__name__)
VIETNAM = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")


def next_midnight(now: datetime) -> datetime:
    local = now.astimezone(VIETNAM)
    return (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


class CrawlBusy(Exception):
    pass


class CrawlManager:
    def __init__(self, output_dir: Path, max_pages: int, depth: int, timeout: int):
        self.output_dir = output_dir
        self.max_pages = max_pages
        self.depth = depth
        self.timeout = timeout
        self.mutex = threading.Lock()
        self.file_lock = FileLock(output_dir / ".crawl.lock", thread_local=False)
        self.process = None
        self.worker = None
        self.stopping = False
        self.next_run = next_midnight(datetime.now(timezone.utc))
        self.status_path = output_dir / "crawl-status.json"
        self.last_run = None
        if self.status_path.exists():
            self.last_run = json.loads(self.status_path.read_text(encoding="utf-8"))
            if self.last_run["status"] == "running":
                self.last_run["status"] = "interrupted"
                self.last_run["finished_at"] = datetime.now(timezone.utc).isoformat()
                self._save()

    def _save(self):
        temporary = self.status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.last_run), encoding="utf-8")
        temporary.replace(self.status_path)

    def snapshot(self):
        with self.mutex:
            return {
                "running": self.process is not None,
                "next_scheduled_at": self.next_run.isoformat(),
                "last_run": dict(self.last_run) if self.last_run else None,
            }

    def start(self, source: str):
        with self.mutex:
            if self.stopping or self.process is not None:
                raise CrawlBusy()
            try:
                self.file_lock.acquire(timeout=0)
            except Timeout as exc:
                raise CrawlBusy() from exc
            run = {
                "id": uuid4().hex,
                "source": source,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "exit_code": None,
            }
            try:
                # A fresh process avoids restarting Twisted's reactor in the API process.
                process = subprocess.Popen([
                    sys.executable, "-m", "scrapy", "crawl", "hust",
                    "-a", f"max_pages={self.max_pages}",
                    "-s", f"DEPTH_LIMIT={self.depth}",
                    "-s", "HTTPCACHE_ENABLED=False",
                ], cwd=BASE_DIR, env={
                    **{key: value for key, value in os.environ.items() if key != "CRAWLER_API_TOKEN"},
                    "_HUST_CRAWL_LOCK_HELD": "1",
                })
                self.process = process
                self.last_run = run
                self._save()
                self.worker = threading.Thread(target=self._watch, args=(process,), daemon=True)
                self.worker.start()
            except Exception:
                if self.process is not None:
                    self._terminate(self.process)
                if self.last_run is run:
                    self.last_run.update(
                        status="failed", finished_at=datetime.now(timezone.utc).isoformat(),
                        exit_code=self.process.returncode if self.process is not None else None,
                    )
                    with suppress(OSError):
                        self._save()
                self.process = None
                self.file_lock.release()
                raise
            log.info("Crawl %s started (%s)", run["id"], source)
            return dict(run)

    @staticmethod
    def _terminate(process):
        if process.poll() is None:
            with suppress(ProcessLookupError):
                process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                process.kill()
            process.wait()

    def _watch(self, process):
        outcome = "finished"
        try:
            process.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            outcome = "timed_out"
            self._terminate(process)
        except Exception:
            outcome = "failed"
            log.exception("Cannot wait for crawl process")
            self._terminate(process)
        finally:
            with self.mutex:
                self.last_run.update(
                    status="interrupted" if self.stopping else outcome,
                    finished_at=datetime.now(timezone.utc).isoformat(),
                    exit_code=process.returncode,
                )
                if outcome == "finished" and process.returncode != 0 and not self.stopping:
                    self.last_run["status"] = "failed"
                try:
                    self._save()
                except OSError:
                    log.exception("Cannot save crawl status")
                finally:
                    self.process = None
                    self.file_lock.release()
                log.info("Crawl %s ended: %s", self.last_run["id"], self.last_run["status"])

    def run_due(self, now: datetime):
        with self.mutex:
            if now < self.next_run:
                return
            self.next_run = next_midnight(now)
        try:
            self.start("schedule")
        except CrawlBusy:
            log.info("Skipped midnight crawl: another crawl is running")
        except Exception:
            log.exception("Cannot start scheduled crawl; next attempt is next midnight")

    def stop(self):
        with self.mutex:
            self.stopping = True
            process, worker = self.process, self.worker
        if process is not None:
            self._terminate(process)
        if worker is not None:
            worker.join()


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        token = os.getenv("CRAWLER_API_TOKEN", "")
        if len(token) < 32 or not token.isascii():
            raise RuntimeError("Set CRAWLER_API_TOKEN to an ASCII secret of at least 32 characters")
        max_pages = int(os.getenv("CRAWLER_MAX_PAGES", "2500"))
        depth = int(os.getenv("CRAWLER_DEPTH_LIMIT", "4"))
        timeout = int(os.getenv("CRAWLER_TIMEOUT_SECONDS", "21600"))
        if min(max_pages, depth, timeout) <= 0:
            raise RuntimeError("Crawl limits must be positive integers")
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Prevent multiple API workers/replicas from each scheduling a midnight crawl.
        service_lock = FileLock(OUTPUT_FILE.parent / ".service.lock")
        with service_lock.acquire(timeout=0):
            manager = CrawlManager(OUTPUT_FILE.parent, max_pages, depth, timeout)
            app.state.manager = manager
            app.state.token = token

            async def schedule():
                while True:
                    await asyncio.to_thread(manager.run_due, datetime.now(timezone.utc))
                    await asyncio.sleep(1)

            scheduler = asyncio.create_task(schedule())
            try:
                yield
            finally:
                scheduler.cancel()
                with suppress(asyncio.CancelledError):
                    await scheduler
                await asyncio.to_thread(manager.stop)

    app = FastAPI(title="HUST crawler", lifespan=lifespan, docs_url=None, redoc_url=None)
    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None or not hmac.compare_digest(
            credentials.credentials.encode("utf-8"), app.state.token.encode("ascii")
        ):
            raise HTTPException(401, "Invalid bearer token", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/crawl", status_code=202, dependencies=[Depends(authenticate)])
    def crawl():
        try:
            return app.state.manager.start("api")
        except CrawlBusy:
            raise HTTPException(409, "A crawl is already running or the service is stopping") from None
        except OSError:
            log.exception("Cannot start manual crawl")
            raise HTTPException(503, "Cannot start crawl; check service logs") from None

    @app.get("/crawl", dependencies=[Depends(authenticate)])
    def status():
        return app.state.manager.snapshot()

    return app


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(), host="0.0.0.0", port=8000, workers=1)
