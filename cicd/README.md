# CI và Docker cho link-crawler

Stack: Python 3.13, Scrapy, FastAPI/Uvicorn, unittest và Ruff. CI không cần secrets;
service API cần token runtime. Chưa có database.
GitHub Actions chạy hai job `test` và `docker` khi push lên `main` hoặc tạo/cập nhật
PR vào `main`. Push nhánh khác không chạy CI nếu không cập nhật PR đang mở vào
`main`; không có trigger chạy thủ công. Job Docker build image, nhận diện spider và kiểm tra quyền ghi
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
bằng UID/GID 10001. Service một lượt `crawler` không mở cổng, không tự restart; root filesystem chỉ
đọc, `/tmp` dùng tmpfs. Hai named volumes `links` và `httpcache` giữ dữ liệu khi
container thoát. Mỗi lần crawl ghi đè kết quả trước đó theo pipeline hiện có.
Không dùng `down --volumes` nếu cần giữ kết quả/cache.

## Chạy thường trực: lịch 00:00 và API

Lịch chạy cố định **00:00 mỗi ngày theo UTC+7 (giờ Việt Nam)**, độc lập múi giờ
của host. Đây là scheduler trong service API, không phải workflow GitHub Actions
hoặc cron của host. Dùng một instance, một Uvicorn worker; không dùng `--reload`.

Chuẩn bị trên server Linux (chỉ copy file mẫu khi chưa có `.env`):

```bash
cp cicd/.env.example cicd/.env
# Tạo token riêng, lưu trong file bị Git ignore; không commit file này.
printf '\nCRAWLER_API_TOKEN=%s\n' "$(openssl rand -hex 32)" >> cicd/.env
chmod 600 cicd/.env
docker compose --env-file cicd/.env -f cicd/compose.yaml config --quiet
docker compose --env-file cicd/.env -f cicd/compose.yaml up -d --build crawler-api
docker compose --env-file cicd/.env -f cicd/compose.yaml logs -f crawler-api
```

Không chạy lệnh `config` in toàn bộ cấu hình nếu không muốn lộ token ra terminal;
dùng `config --quiet`. Sau lần tạo token đầu, giữ nguyên `.env` khi cập nhật code.
`restart: unless-stopped` khởi động lại service sau khi Docker restart, trừ khi
đã chủ động dừng nó. Docker trên server cần được bật cùng hệ thống.

| API | Xác thực | Kết quả |
|---|---|---|
| `GET /health` | Không | `200` khi API đã khởi động |
| `POST /crawl` | `Authorization: Bearer <token>` | `202` + job ID; `409` nếu bận; `503` nếu không khởi động được process |
| `GET /crawl` | Cùng token | Trạng thái đang chạy, job gần nhất, giờ lịch tiếp theo |

```bash
curl -X POST http://127.0.0.1:8000/crawl \
  -H 'Authorization: Bearer <CRAWLER_API_TOKEN>'
curl http://127.0.0.1:8000/crawl \
  -H 'Authorization: Bearer <CRAWLER_API_TOKEN>'
```

Thay placeholder bằng token đã lưu trong `.env`. API không nhận URL hoặc command
tùy ý; mọi lượt dùng cùng cấu hình crawl của server. Không tự retry `POST` khi
mất kết nối; kiểm tra `GET /crawl` trước để tránh tạo lượt mới ngoài ý muốn.

Port chỉ bind `127.0.0.1` trên host. Để gọi từ máy cá nhân có thể mở SSH tunnel:

```bash
ssh -L 8000:127.0.0.1:8000 user@your-server
```

Sau đó gọi `http://127.0.0.1:8000` trên máy cá nhân. Nếu cung cấp API cho
microservice khác máy, cấu hình reverse proxy HTTPS và giữ bearer token.

Biến runtime:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `CRAWLER_API_TOKEN` | Bắt buộc | Bí mật ASCII ít nhất 32 ký tự; thiếu thì service không khởi động |
| `CRAWLER_API_PORT` | `8000` | Cổng loopback trên host |
| `CRAWLER_MAX_PAGES` | `2500` | Giới hạn trang HTML mỗi lượt, phải lớn hơn 0 |
| `CRAWLER_DEPTH_LIMIT` | `4` | Độ sâu, phải lớn hơn 0 |
| `CRAWLER_TIMEOUT_SECONDS` | `21600` | Giới hạn 6 giờ mỗi lượt; quá hạn thì dừng process |

- Không crawl ngay khi service khởi động. Lần tự động đầu là 00:00 kế tiếp.
- Không chạy bù khi host/service tắt lúc 00:00. Nếu đang có job tại thời điểm
  lịch, bỏ qua lượt lịch đó và ghi log; API thủ công không dịch lịch tự động.
- Khóa trên volume `links` ngăn chạy chồng giữa API/lịch và bảo vệ pipeline ghi
  file khi chạy CLI trực tiếp. Không đặt biến nội bộ `_HUST_CRAWL_LOCK_HELD`
  bằng tay; biến này chỉ dành cho process con do service đã giữ khóa khởi tạo.
- Service thứ hai dùng chung volume bị từ chối khởi động để tránh trùng scheduler.
- Khi dừng service, process con được yêu cầu kết thúc; nếu không thoát trong
  30 giây sẽ bị kill. Thông tin job gần nhất lưu tại `crawl-status.json` trong
  volume `links`; không phải lịch sử đầy đủ. Job đang chạy khi service chết được
  đánh dấu `interrupted` ở lần khởi động sau.
- Trạng thái `finished`/exit code 0 chỉ nói process đã thoát bình thường, không
  bảo đảm mọi URL đều tải thành công; xem log Scrapy để biết lỗi hoặc đạt giới hạn.
- Các lượt từ service tắt HTTP cache để lấy phản hồi mới. `links.txt` vẫn ghi
  đè mỗi lượt, chưa có database chống trùng qua các lượt hoặc lưu HTML thô.
- Log API và crawler xuất stdout/stderr, xem bằng `docker compose logs`.

Cập nhật code trên server:

```bash
git pull
docker compose --env-file cicd/.env -f cicd/compose.yaml up -d --build crawler-api
```

Lệnh cập nhật có thể dừng lượt đang chạy; kiểm tra `GET /crawl` và cập nhật lúc
nhàn rỗi. Đây là cập nhật thủ công, chưa phải CD tự động.

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
