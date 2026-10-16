# Vận hành crawler với PostgreSQL có sẵn

Docker Compose của repo chỉ chạy crawler/API, không tạo PostgreSQL mới.
Chạy các lệnh Compose từ thư mục gốc repository.

## Chuẩn bị database

Repo không chứa địa chỉ hay tài khoản DB thật. Điền thông tin PostgreSQL của
bạn vào `cicd/.env`; Compose sẽ báo lỗi nếu thiếu host, database, user hoặc password.
Nếu cần DB mới riêng, nhờ tài khoản quản trị tạo database và user:
Trong psql, dùng `\password` để đặt mật khẩu mà không ghi vào lịch sử SQL:

```sql
CREATE ROLE crawler LOGIN;
\password crawler
CREATE DATABASE crawler OWNER crawler;
```

Nếu database/user đã tồn tại và dành riêng cho crawler, dùng lại chúng.
User cần quyền kết nối, CREATE trong schema public và đọc/ghi bảng `links`.
Pipeline chỉ tự tạo bảng, không tạo database hay tài khoản. Không dùng DB của
ứng dụng khác nếu đã có bảng `links` với cấu trúc khác. Cấu trúc hỗ trợ là
`id bigint identity PRIMARY KEY`, `url text UNIQUE NOT NULL` (HTTP/HTTPS),
`first_seen_at` và `last_seen_at` kiểu timestamptz, default CURRENT_TIMESTAMP.

## Cấu hình kết nối

```bash
# Chỉ copy ở lần thiết lập đầu tiên.
cp cicd/.env.example cicd/.env
chmod 600 cicd/.env
```

Điền các biến sau trong `.env`, không gửi mật khẩu qua chat hay commit file:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `PGHOST` | Bắt buộc | Địa chỉ PostgreSQL nhìn từ container |
| `PGPORT` | `5432` | Cổng PostgreSQL |
| `PGDATABASE` | Bắt buộc | Database đã tạo |
| `PGUSER` | Bắt buộc | Tài khoản DB |
| `PGPASSWORD` | Bắt buộc | Mật khẩu tài khoản DB |
| `PGSSLMODE` | `prefer` | Chế độ TLS; dùng `require` nếu DB yêu cầu TLS |
| `CRAWLER_API_TOKEN` | Bắt buộc với API | Bearer token ASCII ít nhất 32 ký tự |
| `CRAWLER_API_PORT` | `8000` | Cổng API trên loopback |
| `CRAWLER_MAX_PAGES` | `2500` | Số trang HTML tối đa, lớn hơn 0 |
| `CRAWLER_DEPTH_LIMIT` | `4` | Độ sâu, lớn hơn 0 |
| `CRAWLER_TIMEOUT_SECONDS` | `21600` | Timeout mỗi lượt, mặc định 6 giờ |

Bỏ dấu `#` ở dòng `CRAWLER_API_TOKEN` trong file mẫu và điền token mới, có thể tạo
bằng `openssl rand -hex 32`. Nếu secret có ký tự đặc biệt như `$` hoặc `#`, đặt
giá trị trong dấu nháy đơn theo cú pháp dotenv. Không dùng `source cicd/.env`.

Chọn địa chỉ DB:

- PostgreSQL cài trực tiếp cùng server: dùng `PGHOST=host.docker.internal`.
  Compose ánh xạ tên này về host gateway trên Linux. `127.0.0.1` bên trong
  crawler là chính container, không phải server.
- PostgreSQL trong Docker cùng server: dùng địa chỉ host và cổng DB đã publish
  mà crawler có thể truy cập, hoặc nối crawler vào cùng Docker network rồi dùng
  tên service DB làm `PGHOST`.
- PostgreSQL ở server khác: dùng hostname/IP riêng của server DB và cổng của nó.

DB cần lắng nghe trên địa chỉ crawler truy cập được. Nếu DB hiện chỉ nghe
`127.0.0.1`, host gateway sẽ không kết nối được: cấu hình `listen_addresses` cho
địa chỉ cần dùng và thêm rule `pg_hba.conf` giới hạn đúng user/database/subnet
của crawler với xác thực `scram-sha-256`. Không mở truy cập cho toàn Internet.
Cấu hình cụ thể phụ thuộc cách PostgreSQL hiện đang chạy; giữ nguyên quyền của
các ứng dụng đang dùng DB. Tham khảo [Docker extra_hosts](https://docs.docker.com/reference/compose-file/services/#extra_hosts)
và [PostgreSQL client authentication](https://www.postgresql.org/docs/current/auth-pg-hba-conf.html).

## Kiểm tra kết nối và chạy

```bash
docker compose --env-file cicd/.env -f cicd/compose.yaml config --quiet
docker compose --env-file cicd/.env -f cicd/compose.yaml build crawler
docker compose --env-file cicd/.env -f cicd/compose.yaml run --rm --entrypoint python crawler \
  -c 'import psycopg; c = psycopg.connect(connect_timeout=10); print(c.execute("SELECT 1").fetchone()); c.close()'
docker compose --env-file cicd/.env -f cicd/compose.yaml up -d --build crawler-api
curl --fail http://127.0.0.1:8000/health
```

Dùng `config --quiet` để không in secret. Bước SELECT phải thành công trước khi
chạy job. GET `/health` chỉ kiểm tra API, không kiểm tra DB. Container crawler
chạy UID/GID 10001 với root filesystem chỉ đọc. Volume `links` giữ khóa/trạng
thái job; `httpcache` giữ cache CLI. Dữ liệu DB do PostgreSQL hiện có quản lý.

## Lịch và API

Lịch cố định 00:00 mỗi ngày theo UTC+7, không phụ thuộc múi giờ host.
Không crawl ngay lúc khởi động, không chạy bù lượt bị lỡ khi service tắt.
Nếu đang có job lúc 00:00, bỏ qua lượt lịch đó. Dùng một instance, một worker.
Docker cần bật cùng hệ thống để service tự khởi động lại sau reboot.

```bash
# Thay placeholder bằng token thực.
curl -X POST http://127.0.0.1:8000/crawl \
  -H 'Authorization: Bearer <CRAWLER_API_TOKEN>'
curl http://127.0.0.1:8000/crawl \
  -H 'Authorization: Bearer <CRAWLER_API_TOKEN>'
docker compose --env-file cicd/.env -f cicd/compose.yaml logs --tail=100 crawler-api
```

POST trả `202` ngay khi tạo process; `409` nếu bận; `401` nếu thiếu/sai token;
`503` nếu không khởi tạo được process. Nếu mất kết nối sau POST, kiểm tra GET
trước khi gọi lại. Lỗi lưu DB khiến job `failed`. `finished`/exit 0 không bảo đảm
mọi URL đều tải thành công: xem log Scrapy.

API chỉ bind localhost. Để truy cập từ máy cá nhân:

```bash
ssh -L 8000:127.0.0.1:8000 user@server
```

Sau đó gọi API qua localhost trên máy cá nhân.

## Xem dữ liệu, export và backup

Dùng bảng `links` hiện có; chỉ tạo nếu chưa có. URL mới được thêm; URL cũ giữ
`first_seen_at` và cập nhật `last_seen_at`. Timestamps dùng `timestamptz`.
Không lưu HTML thô hay xóa URL không còn xuất hiện. Mỗi URL được commit riêng;
lượt thất bại vẫn có thể đã ghi một phần dữ liệu. File txt cũ không tự nhập vào DB.

Dùng psql/pgAdmin kết nối tới database crawler, chạy:

```sql
SELECT count(*) FROM links;
SELECT id, url, first_seen_at, last_seen_at
FROM links ORDER BY last_seen_at DESC LIMIT 20;
```

Trên máy có PostgreSQL client và kết nối tới DB, thay các placeholder bằng giá
trị thực. Dùng `.pgpass` (quyền 600) hoặc nhập mật khẩu khi client hỏi:

```bash
psql -h <DB_HOST> -p <DB_PORT> -U crawler -d crawler \
  -Atc 'SELECT url FROM links ORDER BY url;' > links.txt
umask 077
pg_dump -h <DB_HOST> -p <DB_PORT> -U crawler -d crawler \
  -Fc -f crawler-backup.dump
```

Kiểm tra exit code và lưu backup ngoài server. Dùng pg_dump phù hợp phiên bản
server. Nếu hệ thống đã có backup PostgreSQL, đưa database crawler vào lịch đó.
Phục hồi vào DB đích trống đã tạo, dừng crawler trước và không ghi đè DB của
ứng dụng khác:

```bash
pg_restore -h <DB_HOST> -p <DB_PORT> -U crawler -d <EMPTY_TARGET_DB> \
  --exit-on-error crawler-backup.dump
```

## Cập nhật và dừng

Kiểm tra GET `/crawl` và đợi job kết thúc trước khi cập nhật:

```bash
git pull --ff-only origin main
docker compose --env-file cicd/.env -f cicd/compose.yaml up -d --build crawler-api
# Dừng crawler/API:
docker compose --env-file cicd/.env -f cicd/compose.yaml down
```

Compose không quản lý vòng đời PostgreSQL có sẵn. Không dùng `down --volumes`
nếu cần giữ khóa/trạng thái/cache crawler. Cập nhật có thể ngắt job đang chạy.
Trạng thái job gần nhất ở `crawl-status.json` trong volume `links`, không phải
lịch sử tất cả các lượt.

## CI và kiểm chứng

CI dùng PostgreSQL 17 tạm riêng để kiểm tra SQL, không kết nối DB của server.
Sau đó build Docker và kiểm tra spider/API/quyền ghi volume, không crawl HUST.
Đặt `TEST_POSTGRES_DSN` trỏ tới DB test riêng để bật test tích hợp local.
Chưa có CD tự động hay publish image. Dependencies chưa có lockfile.
