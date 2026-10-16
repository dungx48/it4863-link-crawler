# link-crawler — thu thập URL trong hust.edu.vn

Crawler Scrapy đi theo link trong `hust.edu.vn` và subdomain, lưu kết quả vào
**PostgreSQL**. Chỉ lưu URL, không tải tài liệu hay lưu nội dung HTML.

Dùng bảng `links` trong database đã cấu hình; chỉ tạo bảng nếu chưa có:

| Cột | Ý nghĩa |
|---|---|
| `id` | Khóa chính bigint, tự tăng |
| `url` | URL đã chuẩn hóa, UNIQUE, chỉ nhận HTTP/HTTPS |
| `first_seen_at` | Thời điểm phát hiện lần đầu |
| `last_seen_at` | Thời điểm phát hiện gần nhất |

Mỗi lượt thêm URL mới và cập nhật `last_seen_at` cho URL đã có; không xóa URL
của các lượt trước. Mỗi URL được commit ngay để giữ kết quả nếu crawl bị ngắt.
Lỗi kết nối/ghi DB khiến lệnh crawl trả exit code 1 và job API báo `failed`;
job thất bại vẫn có thể đã ghi một phần dữ liệu. File txt cũ không tự nhập vào DB.
`UNIQUE(url)` chống trùng cả khi nhiều tiến trình cùng ghi. URL quá dài vượt
giới hạn index PostgreSQL sẽ làm job báo lỗi.

## Chạy trên server Linux

Cần Git, Docker Engine đang chạy và Docker Compose v2.

```bash
git clone https://github.com/dungx48/it4863-link-crawler.git
cd it4863-link-crawler
# Chỉ copy ở lần thiết lập đầu tiên.
cp cicd/.env.example cicd/.env
chmod 600 cicd/.env
```

Tạo database và tài khoản riêng cho crawler trên PostgreSQL có sẵn (xem
[hướng dẫn](cicd/README.md)). Sửa `cicd/.env`: điền `PGHOST`, `PGPORT`,
`PGDATABASE`, `PGUSER`, `PGPASSWORD` theo DB đó. Bỏ dấu `#` ở dòng
`CRAWLER_API_TOKEN`, điền token ASCII ít nhất 32 ký tự (tạo bằng
`openssl rand -hex 32`). Không commit `.env`; giữ nguyên file khi cập nhật.

```bash
docker compose --env-file cicd/.env -f cicd/compose.yaml config --quiet
docker compose --env-file cicd/.env -f cicd/compose.yaml up -d --build crawler-api
curl --fail http://127.0.0.1:8000/health
```

Compose chỉ chạy crawler, kết nối tới PostgreSQL có sẵn. Kiểm tra kết nối trước:

```bash
docker compose --env-file cicd/.env -f cicd/compose.yaml run --rm --entrypoint python crawler \
  -c 'import psycopg; c = psycopg.connect(connect_timeout=10); print(c.execute("SELECT 1").fetchone()); c.close()'
```

API chạy thường trực,
**crawl lúc 00:00 mỗi ngày theo giờ Việt Nam (UTC+7)**, không cần cron.
Không crawl ngay khi khởi động. Kích hoạt lượt đầu và xem trạng thái:

```bash
curl -X POST http://127.0.0.1:8000/crawl \
  -H 'Authorization: Bearer <CRAWLER_API_TOKEN>'
curl http://127.0.0.1:8000/crawl \
  -H 'Authorization: Bearer <CRAWLER_API_TOKEN>'
```

Thay placeholder bằng token thực. POST trả `202`; đang crawl trả `409`;
thiếu/sai token trả `401`. Nếu POST mất kết nối, kiểm tra GET trước khi gọi lại.
GET `/health` kiểm tra API, không bảo đảm DB đang truy cập được.

API chỉ bind `127.0.0.1:8000`. Để gọi từ máy
cá nhân, dùng `ssh -L 8000:127.0.0.1:8000 user@server`. Xem hướng dẫn
[triển khai, truy vấn, export và backup](cicd/README.md).

## Chạy một lượt bằng Docker

Sau khi cấu hình `.env` như trên:

```bash
docker compose --env-file cicd/.env -f cicd/compose.yaml build crawler
docker compose --env-file cicd/.env -f cicd/compose.yaml run --rm crawler
# Giới hạn riêng cho lượt này:
docker compose --env-file cicd/.env -f cicd/compose.yaml run --rm crawler \
  crawl hust -a max_pages=100 -s DEPTH_LIMIT=2
```

Không chạy CLI đồng thời với job API trên cùng storage. Lịch/API/CLI dùng chung
khóa trong volume `links`. Chỉ chạy một API instance và một Uvicorn worker.

## Chạy Python trực tiếp

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PGHOST=127.0.0.1 PGPORT=5432 PGDATABASE=crawler PGUSER=crawler
# Đặt PGPASSWORD riêng hoặc dùng ~/.pgpass (chmod 600).
scrapy crawl hust -a max_pages=2500 -s DEPTH_LIMIT=4
```

DB phải tồn tại; user cần quyền tạo bảng và đọc/ghi bảng `links`. Kết nối dùng
biến môi trường libpq `PG*`; dùng `PGSSLMODE` khi kết nối DB bên ngoài cần TLS.

| Tham số | Ý nghĩa |
|---|---|
| `-a max_pages=N` | Dừng sau N trang HTML (0 = không giới hạn khi chạy CLI) |
| `-a use_sitemap=0/1` | Có dùng sitemap làm seed không |
| `-a start=url1,url2` | Seed tùy chỉnh |
| `-a urlfile=path` | Seed từ file txt |
| `-a follow=0/1` | Có đi theo link không |
| `-s DEPTH_LIMIT=N` | Độ sâu tối đa |

Nếu cần cách lưu file cũ, đặt `HUST_STORAGE=file` trước khi chạy Python. Khi đó
`HUST_LINKS_OUT` đổi đường dẫn mặc định `output/links.txt`; mỗi lượt ghi đè file.
Để dùng trong Compose: `run --rm -e HUST_STORAGE=file crawler`.

## Phạm vi và tốc độ

Lưu trang HTML HTTP 200 và URL tài liệu (`.pdf`, `.doc(x)`, `.xls(x)`, `.ppt(x)`, …)
phát hiện trong trang. Loại link ngoài miền, ảnh/CSS/JS, nhánh quản trị/tìm kiếm/
RSS/tag, EZproxy thư viện và host test (xem `config.py`).

Tôn trọng `robots.txt`, tối đa 4 request song song mỗi domain, delay 0,5 giây,
AutoThrottle và backoff khi gặp 429/503. CLI dùng HTTP cache một ngày; các lượt
do API quản lý tắt cache để lấy phản hồi mới.

## Kiểm tra và CI

`requirements.txt` chứa thư viện chạy ứng dụng; `requirements-dev.txt` dùng lại
file đó và bổ sung Ruff, HTTPX cho lint/test. Docker chỉ cài bản runtime;
máy phát triển và CI cài bản dev. Hai file có mục đích riêng, không khai báo
lặp lại dependency runtime.

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m ruff check config.py crawler tests
python -m scrapy list
python -X utf8 -m unittest discover -s tests -v
docker compose --env-file cicd/.env -f cicd/compose.yaml config --quiet
```

CI `.github/workflows/ci.yml` chạy khi push `main` hoặc mở/cập nhật PR vào `main`.
Job `test` chạy lint, test offline và test tích hợp PostgreSQL 17 trong DB tạm.
Test tích hợp xác nhận chống trùng qua hai lượt, giữ `first_seen_at`, cập nhật
`last_seen_at`, giữ `id` và lưu URL tài liệu. Local mặc định bỏ qua test DB; đặt
`TEST_POSTGRES_DSN` trỏ tới **DB test riêng** để chạy test đó.
Job `docker` build image và kiểm tra spider/API/quyền ghi storage, không crawl HUST.
Chưa có CD tự động hay publish image; triển khai bằng build trên server.

## Cấu hình riêng và tài liệu

`cicd/.env.example` là file mẫu công khai, chỉ chứa giá trị minh họa. Cấu hình
thật nằm trong `cicd/.env`, được Git ignore và loại khỏi Docker build context.
Compose yêu cầu điền đủ host, database, user và password thay vì dùng sẵn
thông tin máy chủ cá nhân. Không chạy `docker compose config` để chia sẻ cấu
hình; dùng `config --quiet` để tránh in secret.

Các biến thể `.env.*` cũng được ignore, ngoại trừ file mẫu `*.env.example`.
Dữ liệu chạy local (`output/`), cache và bản backup DB không đưa vào Git.
Nếu mật khẩu/token thật từng được commit hoặc chia sẻ, cần đổi chúng; thêm
ignore không xóa secret khỏi lịch sử Git.

Hướng dẫn vận hành hiện tại: [cicd/README.md](cicd/README.md).
Đề xuất thiết kế cũ được giữ ở [docs/archive/CRAWLER_DESIGN.md](docs/archive/CRAWLER_DESIGN.md)
để tham khảo lịch sử, không phải hướng dẫn triển khai hiện tại.
