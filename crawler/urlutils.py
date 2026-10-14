"""Chuẩn hoá URL và kiểm tra phạm vi crawl (chỉ trong hust.edu.vn)."""
from __future__ import annotations

import re
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse, parse_qsl, urlencode

from config import (ALLOWED_DOMAINS, ALLOW_SUBDOMAINS, DENY_HOST_RE,
                    DENY_PATH_RE, DOC_EXTENSIONS, SKIP_EXTENSIONS)

_DENY = [re.compile(p, re.I) for p in DENY_PATH_RE]
_DENY_HOST = [re.compile(p, re.I) for p in DENY_HOST_RE]
# Tham số theo dõi -> bỏ để tránh tạo URL trùng nội dung.
_TRACKING = re.compile(r"^(utm_|fbclid|gclid|msclkid|ref|_ga)", re.I)


def normalize(url: str, base: str | None = None) -> str | None:
    """Chuẩn hoá URL: bỏ fragment, hạ host về chữ thường, bỏ tham số tracking,
    sắp xếp query. Trả về None nếu không phải http(s)."""
    if not url:
        return None
    url = url.strip()
    if url.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
        return None
    if base:
        url = urljoin(base, url)
    url, _ = urldefrag(url)
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return None
    host = p.netloc.lower()
    # Cắt userinfo: một số trang viết <a href="user@host"> làm urlparse hiểu
    # địa chỉ email thành tên miền (vd tuvanhoctap@soict.hust.edu.vn).
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if not host or host.startswith("."):
        return None
    if host.endswith(":80"):
        host = host[:-3]
    if host.endswith(":443"):
        host = host[:-4]
    if host.startswith("www."):
        host = host[4:]
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if not _TRACKING.match(k)]
    q.sort()
    path = re.sub(r"//+", "/", p.path) or "/"
    return urlunparse(("https", host, path, "", urlencode(q), ""))


def host_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def in_scope(url: str) -> bool:
    """True nếu URL nằm trong hust.edu.vn (kèm subdomain nếu bật)."""
    host = host_of(url)
    if any(rx.search(host) for rx in _DENY_HOST):
        return False
    for d in ALLOWED_DOMAINS:
        if host == d or (ALLOW_SUBDOMAINS and host.endswith("." + d)):
            return True
    return False


def ext_of(url: str) -> str:
    path = urlparse(url).path.lower()
    m = re.search(r"(\.[a-z0-9]{1,5})$", path)
    return m.group(1) if m else ""


def is_document(url: str) -> bool:
    return ext_of(url) in DOC_EXTENSIONS


def should_skip(url: str) -> bool:
    """Bỏ qua ảnh/CSS/JS và các nhánh bị chặn."""
    if ext_of(url) in SKIP_EXTENSIONS:
        return True
    target = urlparse(url).path + ("?" + urlparse(url).query if urlparse(url).query else "")
    return any(rx.search(target) for rx in _DENY)
