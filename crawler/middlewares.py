"""Middleware: lùi nhịp khi server trả 429/503.

AutoThrottle của Scrapy chỉ điều chỉnh theo *độ trễ* phản hồi, nó không hiểu
429 Too Many Requests. Vài subdomain của HUST (fed., smse., …) chạy trên server
nhỏ và trả 429 rất sớm, nên cần tự nhân đôi delay của đúng slot đó.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class BackoffOn429:
    """Gặp 429/503 -> nhân đôi delay của download slot tương ứng, rồi thử lại."""

    def __init__(self, factor: float = 2.0, max_delay: float = 30.0):
        self.factor = factor
        self.max_delay = max_delay

    @classmethod
    def from_crawler(cls, crawler):
        obj = cls(factor=crawler.settings.getfloat("BACKOFF_FACTOR", 2.0),
                  max_delay=crawler.settings.getfloat("BACKOFF_MAX_DELAY", 30.0))
        obj.crawler = crawler
        return obj

    def process_response(self, request, response, spider=None):
        if response.status not in (429, 503):
            return response
        spider = spider or self.crawler.spider
        key, slot = self.crawler.engine.downloader._get_slot(request, spider)
        old = slot.delay
        slot.delay = min(max(old, 0.5) * self.factor, self.max_delay)
        if slot.delay > old:
            log.info("429/503 từ %s -> giãn delay %.1fs -> %.1fs", key, old, slot.delay)
        return response
