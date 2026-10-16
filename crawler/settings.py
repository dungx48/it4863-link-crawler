"""Cấu hình Scrapy — ưu tiên crawl "lịch sự" (polite) với site của trường."""
import os
import sys
from pathlib import Path

# Cho phép import config/storage/extract từ thư mục gốc dự án.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import USER_AGENT  # noqa: E402

BOT_NAME = "hust_links"
SPIDER_MODULES = ["crawler.spiders"]
NEWSPIDER_MODULE = "crawler.spiders"

USER_AGENT = USER_AGENT
ROBOTSTXT_OBEY = True                 # tôn trọng robots.txt của hust.edu.vn

# --- Tốc độ: chậm & đều, tránh gây tải cho server trường ---
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 4
DOWNLOAD_DELAY = 0.5
RANDOMIZE_DOWNLOAD_DELAY = True
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.5
AUTOTHROTTLE_MAX_DELAY = 15.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 3.0

# --- Độ bền ---
RETRY_ENABLED = True
RETRY_TIMES = 5
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]
BACKOFF_FACTOR = 2.0            # xem crawler/middlewares.py
BACKOFF_MAX_DELAY = 30.0
DOWNLOAD_TIMEOUT = 60
DOWNLOAD_MAXSIZE = 20 * 1024 * 1024
AJAXCRAWL_ENABLED = True

# --- Giới hạn phạm vi (ghi đè bằng -s DEPTH_LIMIT=... khi chạy) ---
DEPTH_LIMIT = 5
DEPTH_PRIORITY = 1                        # BFS: ưu tiên trang nông trước
SCHEDULER_DISK_QUEUE = "scrapy.squeues.PickleFifoDiskQueue"
SCHEDULER_MEMORY_QUEUE = "scrapy.squeues.FifoMemoryQueue"

# --- HTTP cache: chạy lại/parse lại mà không đập vào server ---
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 86400
HTTPCACHE_DIR = str(Path(__file__).resolve().parent.parent / ".cache" / "httpcache")
HTTPCACHE_IGNORE_HTTP_CODES = [404, 500, 502, 503, 504]

ITEM_PIPELINES = {
    ("crawler.pipelines.LinkFilePipeline" if os.getenv("HUST_STORAGE") == "file"
     else "crawler.pipelines.PostgresLinkPipeline"): 300,
}
COMMANDS_MODULE = "crawler.commands"

# OffsiteMiddleware ở tầng downloader chặn cả redirect ra ngoài hust.edu.vn.
DOWNLOADER_MIDDLEWARES = {
    "scrapy.downloadermiddlewares.offsite.OffsiteMiddleware": 500,
    # Chạy TRƯỚC RetryMiddleware (550) để đã giãn nhịp rồi mới retry.
    "crawler.middlewares.BackoffOn429": 545,
    "scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware": 810,
}
# (Scrapy >= 2.16 đã bỏ bản spider-middleware của Offsite; bản downloader ở trên
# là đủ và còn chặn được cả redirect.)

LOG_LEVEL = "INFO"
FEED_EXPORT_ENCODING = "utf-8"
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
