"""Offline scheduling, authentication, process lifecycle and shared-lock tests."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from filelock import FileLock, Timeout

from crawler.pipelines import LinkFilePipeline
from crawler.service import CrawlBusy, CrawlManager, create_app, next_midnight

TOKEN = "test-token-" + "x" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeProcess:
    def __init__(self):
        self.done = threading.Event()
        self.returncode = None

    def finish(self, code=0):
        self.returncode = code
        self.done.set()

    def wait(self, timeout=None):
        if not self.done.wait(timeout):
            raise subprocess.TimeoutExpired("fake-crawl", timeout)
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        self.finish(-15)

    def kill(self):
        self.finish(-9)


class ServiceTests(unittest.TestCase):
    def test_midnight_is_vietnam_time_and_rolls_over_year(self):
        for now, expected in (
            ("2026-10-16T16:59:59+00:00", "2026-10-17T00:00:00+07:00"),
            ("2026-10-16T17:00:00+00:00", "2026-10-18T00:00:00+07:00"),
            ("2026-12-31T12:00:00+00:00", "2027-01-01T00:00:00+07:00"),
        ):
            with self.subTest(now=now):
                self.assertEqual(next_midnight(datetime.fromisoformat(now)).isoformat(), expected)

    def test_api_requires_token_starts_async_rejects_overlap_and_keeps_status(self):
        process = FakeProcess()
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"CRAWLER_API_TOKEN": TOKEN}), \
                patch("crawler.service.OUTPUT_FILE", Path(directory) / "links.txt"), \
                patch("crawler.service.subprocess.Popen", return_value=process) as spawn:
            app = create_app()
            with TestClient(app) as client:
                self.assertEqual(client.get("/health").status_code, 200)
                for headers in ({}, {"Authorization": "Bearer wrong"}):
                    self.assertEqual(client.post("/crawl", headers=headers).status_code, 401)
                    self.assertEqual(client.get("/crawl", headers=headers).status_code, 401)
                spawn.assert_not_called()
                response = client.post("/crawl", headers=AUTH)
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.json()["source"], "api")
                self.assertEqual(client.post("/crawl", headers=AUTH).status_code, 409)
                self.assertTrue(client.get("/crawl", headers=AUTH).json()["running"])
                self.assertIn("HTTPCACHE_ENABLED=False", spawn.call_args.args[0])
                self.assertNotIn("CRAWLER_API_TOKEN", spawn.call_args.kwargs["env"])
                process.finish()
                app.state.manager.worker.join(timeout=2)
                result = client.get("/crawl", headers=AUTH).json()
                self.assertFalse(result["running"])
                self.assertEqual(result["last_run"]["exit_code"], 0)
            saved = json.loads((Path(directory) / "crawl-status.json").read_text())
            self.assertEqual(saved["id"], response.json()["id"])

    def test_schedule_runs_once_and_skips_busy_midnight(self):
        with TemporaryDirectory() as directory, patch("crawler.service.subprocess.Popen", return_value=FakeProcess()) as spawn:
            manager = CrawlManager(Path(directory), 20, 2, 60)
            try:
                midnight = manager.next_run
                manager.run_due(midnight)
                self.assertEqual(manager.snapshot()["last_run"]["source"], "schedule")
                manager.run_due(midnight)
                manager.run_due(manager.next_run)
                self.assertEqual(spawn.call_count, 1)
                self.assertGreater(manager.next_run, midnight)
            finally:
                manager.stop()

    def test_external_lock_rejects_api_and_pipeline_without_truncating_output(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "links.txt"
            output.write_text("previous result\n")
            manager = CrawlManager(Path(directory), 20, 2, 60)
            with FileLock(Path(directory) / ".crawl.lock").acquire(timeout=0), \
                    patch("crawler.pipelines.OUTPUT_FILE", output):
                with self.assertRaises(CrawlBusy):
                    manager.start("api")
                with self.assertRaises(Timeout):
                    LinkFilePipeline().open_spider()
            self.assertEqual(output.read_text(), "previous result\n")

    def test_spawn_failure_releases_lock_for_retry(self):
        process = FakeProcess()
        with TemporaryDirectory() as directory, patch("crawler.service.subprocess.Popen", side_effect=[OSError("spawn failed"), process]):
            manager = CrawlManager(Path(directory), 20, 2, 60)
            try:
                with self.assertRaises(OSError):
                    manager.start("api")
                self.assertFalse(manager.snapshot()["running"])
                manager.start("api")
            finally:
                manager.stop()

    def test_real_child_exits_and_releases_shared_lock(self):
        real_popen = subprocess.Popen

        def offline_child(*args, **kwargs):
            self.assertIn("-m", args[0])
            return real_popen([sys.executable, "-c", "pass"], **kwargs)

        with TemporaryDirectory() as directory, patch("crawler.service.subprocess.Popen", side_effect=offline_child):
            manager = CrawlManager(Path(directory), 20, 2, 60)
            try:
                manager.start("api")
                manager.worker.join(timeout=5)
                self.assertFalse(manager.snapshot()["running"])
                self.assertEqual(manager.last_run["exit_code"], 0)
                with FileLock(Path(directory) / ".crawl.lock").acquire(timeout=0):
                    pass
            finally:
                manager.stop()

    def test_failed_exit_and_timeout_are_recorded(self):
        for timeout, code, expected in ((60, 1, "failed"), (0, None, "timed_out")):
            process = FakeProcess()
            if code is not None:
                process.finish(code)
            with self.subTest(expected=expected), TemporaryDirectory() as directory, \
                    patch("crawler.service.subprocess.Popen", return_value=process):
                manager = CrawlManager(Path(directory), 20, 2, timeout)
                manager.start("api")
                manager.worker.join(timeout=2)
                self.assertFalse(manager.snapshot()["running"])
                self.assertEqual(manager.snapshot()["last_run"]["status"], expected)
                manager.stop()

    def test_shutdown_terminates_child_and_restart_marks_stale_run(self):
        process = FakeProcess()
        with TemporaryDirectory() as directory, patch("crawler.service.subprocess.Popen", return_value=process):
            manager = CrawlManager(Path(directory), 20, 2, 60)
            manager.start("api")
            manager.stop()
            self.assertIsNotNone(process.returncode)
            self.assertEqual(manager.last_run["status"], "interrupted")
            saved = manager.last_run | {"status": "running"}
            manager.status_path.write_text(json.dumps(saved))
            restarted = CrawlManager(Path(directory), 20, 2, 60)
            self.assertEqual(restarted.last_run["status"], "interrupted")
            self.assertGreater(restarted.next_run, datetime.now(timezone.utc))

    def test_missing_token_fails_startup(self):
        with patch.dict(os.environ, {"CRAWLER_API_TOKEN": ""}):
            with self.assertRaisesRegex(RuntimeError, "CRAWLER_API_TOKEN"):
                with TestClient(create_app()):
                    pass

    def test_second_service_cannot_schedule_same_storage(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"CRAWLER_API_TOKEN": TOKEN}), \
                patch("crawler.service.OUTPUT_FILE", Path(directory) / "links.txt"):
            with TestClient(create_app()):
                with self.assertRaises(Timeout):
                    with TestClient(create_app()):
                        pass


if __name__ == "__main__":
    unittest.main()
