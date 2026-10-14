# CI và Docker cho link-crawler

Stack: Python 3.13, Scrapy, unittest và Ruff. Không cần secrets hay database.
GitHub Actions chạy hai job `test` và `docker` trên push/PR vào `main`, hoặc
chạy thủ công. Job Docker build image, nhận diện spider và kiểm tra quyền ghi
volume bằng user runtime; không gửi request crawl HUST.

## Kiểm tra từ thư mục gốc

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m ruff check config.py crawler tests
python -m scrapy list
python -X utf8 -m unittest discover -s tests -v
docker compose -f cicd/compose.yaml config -q
docker compose -f cicd/compose.yaml build
docker compose -f cicd/compose.yaml run --rm --no-deps crawler list
```

## Chạy crawler

```bash
# Thực sự crawl HUST; mặc định tối đa 2500 trang, sâu 4 cấp.
docker compose -f cicd/compose.yaml up --abort-on-container-exit --exit-code-from crawler
docker compose -f cicd/compose.yaml cp crawler:/app/output/links.txt ./links.txt

# Thay tham số mặc định; kết quả vẫn nằm trong volume links.
docker compose -f cicd/compose.yaml run --rm crawler crawl hust -a max_pages=100 -s DEPTH_LIMIT=2

# Trích kết quả sau run --rm (container đã được xóa).
docker compose -f cicd/compose.yaml run --rm --no-deps --entrypoint cat crawler /app/output/links.txt
docker compose -f cicd/compose.yaml down
```

Image multi-stage dùng `python:3.13-slim-bookworm`, cài binary wheels và chạy
bằng UID/GID 10001. Compose không mở cổng, không tự restart; root filesystem chỉ
đọc, `/tmp` dùng tmpfs. Hai named volumes `links` và `httpcache` giữ dữ liệu khi
container thoát. Mỗi lần crawl ghi đè kết quả trước đó theo pipeline hiện có.
Không dùng `down --volumes` nếu cần giữ kết quả/cache.

## Cấu hình tùy chọn

Copy `cicd/.env.example` thành `cicd/.env`, sửa user agent/phạm vi subdomain rồi dùng:

```bash
docker compose --env-file cicd/.env -f cicd/compose.yaml config -q
docker compose --env-file cicd/.env -f cicd/compose.yaml up --build --abort-on-container-exit --exit-code-from crawler
```

`HUST_LINKS_OUT` được cố định trong Compose tại `/app/output/links.txt` để kết quả
luôn nằm trong volume ghi được. Docker build context là repository root;
`.dockerignore` chỉ cho phép source và requirements runtime vào context.

## Publish/deploy

Chưa cấu hình publish hoặc CD vì chưa yêu cầu registry/môi trường đích.
Không cần GitHub secrets cho CI. Commit/push các file để GitHub chạy workflow;
có thể chọn required status checks `test` và `docker` trong ruleset của `main`.
Dependencies ứng dụng hiện theo khoảng version, chưa có lockfile nên build chưa
tái lập hoàn toàn. Actions dùng tag `v6`; xem tài liệu chính thức của
[checkout](https://github.com/actions/checkout) và
[setup-python](https://github.com/actions/setup-python).

## Kết quả kiểm tra local (2026-10-15)

Các lệnh Python bên trên chạy bằng `.venv/Scripts/python.exe` trên Windows:
cài requirements-dev, `pip check`, Ruff, `scrapy list` (nhận diện `hust`) và
unittest (5 test) đều exit 0. Compose `config -q` với cấu hình mặc định và với
`--env-file cicd/.env.example` đều exit 0.

`docker compose -f cicd/compose.yaml build` exit 1 do Docker Engine chưa chạy
(không tìm thấy pipe `dockerDesktopLinuxEngine`). Build image và smoke test
container chưa được xác nhận; bật Docker Desktop với Linux containers rồi chạy
lại ba lệnh Docker trong mục kiểm tra. Chưa chạy workflow trên GitHub.
