"""Ghi link thu được ra một file txt (mỗi dòng một URL, đã khử trùng)."""
from __future__ import annotations

import os

from filelock import FileLock

from config import OUTPUT_FILE


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
