"""Spider crawl hust.edu.vn và chỉ xuất ra danh sách link.

    seed (sitemap + tab Giới thiệu + tin tức)
        -> tải HTML
        -> tìm link trong trang
        -> lọc link thuộc hust.edu.vn
        -> tải tiếp (đệ quy)
        -> gặp .pdf/.doc/... thì chỉ ghi link, không tải

Mỗi trang HTML tải thành công (HTTP 200) và mỗi link tài liệu tìm được sẽ được
ghi vào output/links.txt (xem crawler/pipelines.py).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import scrapy
from scrapy.http import Response

from config import ALLOWED_DOMAINS, PRIORITY_PREFIXES, SITEMAP_INDEX, START_URLS
from crawler.urlutils import in_scope, is_document, normalize, should_skip


class HustSpider(scrapy.Spider):
    name = "hust"
    # Chặn cứng phạm vi: OffsiteMiddleware sẽ loại cả request lẫn *redirect*
    # dẫn ra ngoài (vd. /mail -> mail.office365.com).
    allowed_domains = ALLOWED_DOMAINS

    custom_settings = {"DEPTH_STATS_VERBOSE": True}

    def __init__(self, use_sitemap: str = "1", max_pages: str = "0",
                 start: str = "", urlfile: str = "", follow: str = "1",
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.use_sitemap = use_sitemap == "1"
        self.max_pages = int(max_pages)      # 0 = không giới hạn
        self.n_pages = 0
        self.extra_start = [u for u in start.split(",") if u.strip()]
        # Nạp seed từ file (danh sách URL quá dài để truyền qua dòng lệnh).
        if urlfile:
            self.extra_start += [ln.strip() for ln in open(urlfile, encoding="utf-8")
                                 if ln.strip().startswith("http")]
        # follow=0: chỉ tải đúng các URL seed, không đi theo link tìm được.
        self.follow = follow == "1"

    # ------------------------------------------------------------------ seeds
    async def start(self):
        """Scrapy >= 2.13 dùng async generator `start()` thay cho start_requests()."""
        for url in self.extra_start or START_URLS:
            yield scrapy.Request(url, callback=self.parse_page, priority=100)
        if self.use_sitemap:
            yield scrapy.Request(SITEMAP_INDEX, callback=self.parse_sitemap,
                                 priority=90)

    def parse_sitemap(self, response: Response):
        """sitemap.xml của HUST là sitemapindex -> đệ quy 1 cấp xuống các sitemap con."""
        body = response.text
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
        is_index = "<sitemapindex" in body[:600]
        self.logger.info("sitemap %s: %d loc (index=%s)", response.url, len(locs), is_index)
        for loc in locs:
            url = normalize(loc, response.url)
            if not url or not in_scope(url):
                continue
            if is_index:
                yield scrapy.Request(url, callback=self.parse_sitemap, priority=90)
            elif is_document(url):
                yield {"url": url}
            else:
                yield scrapy.Request(url, callback=self.parse_page, priority=50)

    # ------------------------------------------------------------------- HTML
    def parse_page(self, response: Response):
        if self._over_budget():
            return
        ctype = (response.headers.get("Content-Type", b"").decode("latin-1") or "").lower()
        if response.status == 200:
            yield {"url": normalize(response.url) or response.url}
        # Server trả về tài liệu dù URL không có đuôi -> chỉ ghi link, không parse.
        if not ctype.startswith(("text/html", "application/xhtml")):
            return
        self.n_pages += 1

        # --- theo link, chỉ trong hust.edu.vn ---
        if not self.follow:
            return
        seen = set()
        for href in response.xpath("//a/@href").getall():
            url = normalize(href, response.url)
            if not url or url in seen or not in_scope(url) or should_skip(url):
                continue
            seen.add(url)
            if is_document(url):
                yield {"url": url}
            else:
                yield scrapy.Request(url, callback=self.parse_page,
                                     priority=self._priority(url))

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _priority(url: str) -> int:
        path = urlparse(url).path
        return 40 if path.startswith(PRIORITY_PREFIXES) else 10

    def _over_budget(self) -> bool:
        if self.max_pages and self.n_pages >= self.max_pages:
            raise scrapy.exceptions.CloseSpider("max_pages reached")
        return False
