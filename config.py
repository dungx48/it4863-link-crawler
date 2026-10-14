"""Cấu hình phạm vi crawl hust.edu.vn."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = Path(os.getenv("HUST_LINKS_OUT", BASE_DIR / "output" / "links.txt"))

# --- Phạm vi crawl ---
ALLOWED_DOMAINS = ["hust.edu.vn"]
# Chỉ nhận các host thuộc hust.edu.vn (bao gồm subdomain). Đặt False để chỉ lấy
# đúng www/apex domain.
ALLOW_SUBDOMAINS = os.getenv("HUST_ALLOW_SUBDOMAINS", "1") == "1"

START_URLS = [
    "https://hust.edu.vn/vi/about/",          # tab Giới thiệu (yêu cầu B1)
    "https://hust.edu.vn/vi/news/",           # tin tức
    "https://hust.edu.vn/",                   # trang chủ
]
SITEMAP_INDEX = "https://hust.edu.vn/sitemap.xml"

# Ưu tiên các nhánh nội dung; phần còn lại vẫn crawl nhưng độ ưu tiên thấp hơn.
PRIORITY_PREFIXES = ("/vi/about", "/vi/news", "/vi/co-cau-to-chuc")

# Host bị loại dù vẫn thuộc hust.edu.vn.
# EZproxy của thư viện (0-ieeexplore-ieee-org.libopac..., 0-ebookcentral-proquest-com...)
# chỉ là địa chỉ viết lại của IEEE / ProQuest / SAGE — nội dung thuộc nhà xuất bản
# bên ngoài, có bản quyền, và hầu hết chặn sau màn hình đăng nhập.
DENY_HOST_RE = (r"^0-", r"^demots\.", r"^test\.")

# Không đi vào các nhánh này (trùng robots.txt + các nhánh không có nội dung).
DENY_PATH_RE = (
    r"/admin/", r"/users/", r"/statistics/", r"/includes/", r"/modules/",
    r"/install/", r"/data/", r"/assets/", r"/themes/", r"/uploads/sys/logo",
    r"/print/", r"/rss/", r"/tag/", r"/search",
    r"[?&](?:print|comment|rating|nv_redirect)=",
)

# Đuôi file tài liệu -> chỉ ghi link, không tải về.
DOC_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".rtf", ".odt")
# Đuôi file bỏ qua hoàn toàn.
SKIP_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp",
    ".css", ".js", ".mp4", ".mp3", ".avi", ".zip", ".rar", ".7z", ".exe",
    ".woff", ".woff2", ".ttf", ".eot",
)

USER_AGENT = os.getenv(
    "HUST_UA",
    "HustIRBot/1.0 (+academic information-retrieval coursework; contact: local)",
)
