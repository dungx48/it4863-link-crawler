"""Persist discovered URLs in PostgreSQL, or an explicitly selected text file."""
from __future__ import annotations

import os

from filelock import FileLock
import psycopg

from config import OUTPUT_FILE


class PostgresLinkPipeline:
    @classmethod
    def from_crawler(cls, crawler):
        pipeline = cls()
        pipeline.crawler = crawler
        return pipeline

    def open_spider(self, spider=None):
        self.connection = None
        self.lock = None
        self.seen = set()
        try:
            OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            if os.getenv("_HUST_CRAWL_LOCK_HELD") != "1":
                self.lock = FileLock(OUTPUT_FILE.parent / ".crawl.lock")
                self.lock.acquire(timeout=0)
            # Use libpq PG* environment variables; never interpolate credentials into SQL.
            self.connection = psycopg.connect(
                autocommit=True, connect_timeout=10,
                options="-c statement_timeout=10000 -c lock_timeout=10000",
            )
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    url TEXT NOT NULL UNIQUE
                        CONSTRAINT links_http_url CHECK (url ~ '^https?://'),
                    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
        except Exception:
            self.crawler.stats.inc_value("storage/errors")
            self.close_spider()
            raise

    def process_item(self, item, spider=None):
        url = item["url"]
        if url in self.seen:
            return item
        try:
            self.connection.execute("""
                INSERT INTO links (url)
                VALUES (%s)
                ON CONFLICT (url) DO UPDATE
                SET last_seen_at = CURRENT_TIMESTAMP
            """, (url,))
        except Exception:
            self.crawler.stats.inc_value("storage/errors")
            raise
        self.seen.add(url)
        self.crawler.stats.inc_value("storage/links_saved")
        return item

    def close_spider(self, spider=None):
        try:
            if self.connection is not None:
                self.connection.close()
        finally:
            if self.lock is not None:
                self.lock.release()


class LinkFilePipeline:
    def open_spider(self, spider=None):
        self.seen: set[str] = set()
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.lock = None
        # The API parent already holds this same lock for managed child processes.
        if os.getenv("_HUST_CRAWL_LOCK_HELD") != "1":
            self.lock = FileLock(OUTPUT_FILE.parent / ".crawl.lock")
            self.lock.acquire(timeout=0)
        # Ghi dần từng dòng để dừng giữa chừng (Ctrl+C) vẫn giữ được kết quả.
        try:
            self.fh = open(OUTPUT_FILE, "w", encoding="utf-8")
        except Exception:
            if self.lock is not None:
                self.lock.release()
            raise

    def process_item(self, item, spider=None):
        url = item["url"]
        if url not in self.seen:
            self.seen.add(url)
            self.fh.write(url + "\n")
            self.fh.flush()
        return item

    def close_spider(self, spider=None):
        try:
            self.fh.close()
            # Sắp xếp lại cho dễ đọc / dễ diff giữa các lần chạy.
            lines = sorted(self.seen)
            OUTPUT_FILE.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            print(f"Đã ghi {len(lines)} link -> {OUTPUT_FILE}")
        finally:
            if self.lock is not None:
                self.lock.release()
