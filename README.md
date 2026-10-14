# link-crawler — crawl hust.edu.vn ra danh sách link

Crawler Scrapy đi đệ quy trong miền `hust.edu.vn` (kể cả subdomain) và xuất ra
**một file txt chỉ gồm link** (`output/links.txt`, mỗi dòng một URL, đã chuẩn hoá
và khử trùng). Không bóc nội dung, không lưu DB — file link này dùng làm đầu vào
cho bước thu thập/bóc tách của project.

## Cài đặt

```bash
cd link-crawler
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Chạy

```bash
# mặc định: seed = sitemap + trang chủ + Giới thiệu + Tin tức
scrapy crawl hust -a max_pages=2500 -s DEPTH_LIMIT=4

# chỉ crawl tab Giới thiệu, không dùng sitemap
scrapy crawl hust -a use_sitemap=0 -a start=https://hust.edu.vn/vi/about/ -s DEPTH_LIMIT=2

# seed từ file, chỉ kiểm tra đúng các URL đó (không đi theo link)
scrapy crawl hust -a urlfile=seeds.txt -a follow=0
```

| Tham số | Ý nghĩa |
|---|---|
| `-a max_pages=N` | Dừng sau N trang HTML (0 = không giới hạn) |
| `-a use_sitemap=0/1` | Có lấy seed từ `sitemap.xml` không |
| `-a start=url1,url2` | Seed tuỳ chọn (thay cho seed mặc định) |
| `-a urlfile=path` | Seed từ file txt |
| `-a follow=0/1` | Có đi theo link tìm được không |
| `-s DEPTH_LIMIT=N` | Độ sâu tối đa |
| `HUST_LINKS_OUT=path` | Đổi file kết quả (mặc định `output/links.txt`) |

## Link nào được ghi

- Trang HTML tải thành công (HTTP 200).
- Link tài liệu (`.pdf`, `.doc(x)`, `.xls(x)`, `.ppt(x)`, …) tìm thấy trong trang —
  chỉ ghi link, không tải file.

Bị loại: link ngoài `hust.edu.vn`, ảnh/CSS/JS, các nhánh quản trị/tìm kiếm/RSS/tag,
EZproxy thư viện (`0-*`), host test (xem `config.py`).

## Crawl lịch sự

Tôn trọng `robots.txt`, tối đa 4 request song song mỗi domain, delay 0,5s +
AutoThrottle, tự giãn nhịp khi gặp 429/503 (`crawler/middlewares.py`). Có HTTP
cache 1 ngày ở `.cache/httpcache` để chạy lại không tải lại.

## CI (GitHub Actions)

Workflow `.github/workflows/ci.yml` chạy khi push lên `main`, tạo/cập nhật pull
request vào `main`, hoặc chạy thủ công qua tab Actions. CI dùng Ubuntu và Python
3.13, cache pip theo `requirements.txt`, chỉ cấp quyền đọc repository và tự hủy
lượt chạy cũ trên cùng nhánh khi có lượt mới.

Các lệnh kiểm tra (chạy từ thư mục gốc):

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m ruff check config.py crawler tests
python -m scrapy list
python -X utf8 -m unittest discover -s tests -v
docker compose -f cicd/compose.yaml config --quiet
docker compose -f cicd/compose.yaml build
docker compose -f cicd/compose.yaml run --rm --no-deps crawler list
```

Tùy chọn `-X utf8` giúp in tiếng Việt khi chạy test trên Windows.
Test dùng HTML giả lập và file tạm để kiểm tra chuẩn hóa/lọc URL, spider và ghi
link không trùng; không gửi request tới HUST. Ruff kiểm tra lỗi cú pháp và biểu
thức không hợp lệ theo `ruff.toml`, chưa áp dụng quy tắc định dạng/style.
Job `docker` chạy sau test, kiểm tra Compose, build image ứng dụng và nhận diện
spider trong container mà không crawl. Image Docker là artifact build; không có
bước build package Python vì project chưa đóng gói. Chưa cấu hình CD/deploy.

Repository cần bật GitHub Actions và cho phép `actions/checkout`,
`actions/setup-python`; không cần secrets. Hai action dùng tag `v6` và không lưu
credentials checkout. Cache pip theo cả hai file requirements.

Sau khi commit các thay đổi, chạy `git push origin main`, rồi mở tab **Actions →
CI** để xem kết quả. Muốn chặn merge khi kiểm tra thất bại, cấu hình ruleset hoặc
branch protection cho `main` với required status checks `test` và `docker` sau
lượt chạy đầu.

## Docker Compose

Cấu hình và hướng dẫn chi tiết nằm trong [cicd/README.md](cicd/README.md).
Cần Docker Engine đang chạy và Docker Compose. `cicd/Dockerfile` dùng Python 3.13 slim,
chỉ cài binary wheels, chạy bằng UID/GID 10001. Compose chạy một tác vụ crawler,
không mở cổng, không tự khởi động lại; filesystem chỉ đọc, ngoại trừ `/tmp` và
hai named volume `links` (kết quả), `httpcache` (cache). Không cần database hay secrets.

```bash
docker compose -f cicd/compose.yaml config --quiet
docker compose -f cicd/compose.yaml build
# Chỉ kiểm tra cấu hình spider, không gửi request crawl:
docker compose -f cicd/compose.yaml run --rm --no-deps crawler list
# Lệnh dưới thực sự crawl HUST, ghi lại output/links.txt trong volume:
docker compose -f cicd/compose.yaml up --abort-on-container-exit --exit-code-from crawler
docker compose -f cicd/compose.yaml cp crawler:/app/output/links.txt ./links.txt
# Tham số tùy chỉnh; phần sau tên service thay CMD của image:
docker compose -f cicd/compose.yaml run --rm crawler crawl hust -a max_pages=100 -s DEPTH_LIMIT=2
```

Mỗi lần crawl ghi đè file kết quả trước đó theo hành vi hiện có của pipeline.
`docker compose -f cicd/compose.yaml down` giữ named volumes; không dùng `down --volumes` nếu cần giữ
kết quả/cache. Image hiện được build cục bộ/CI, chưa publish lên registry và chưa
triển khai production. Trước khi triển khai, cần publish image có tag cố định hoặc
digest và cấu hình môi trường đích riêng. Dependencies ứng dụng vẫn theo khoảng
version trong `requirements.txt`, chưa có lockfile nên build chưa tái lập hoàn toàn.
