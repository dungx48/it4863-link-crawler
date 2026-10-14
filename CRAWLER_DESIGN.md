# Thiết kế crawler HUST chạy định kỳ

Ngày ghi nhận: 15/10/2026.

Trạng thái: bản đề xuất và bàn giao để triển khai trên máy khác. Chưa thay đổi mã nguồn crawler, chưa cấu hình lịch chạy hoặc deploy. Các giá trị lịch chạy bên dưới là mặc định đề xuất, cần xác nhận trước khi vận hành.

## 1. Mục tiêu và ranh giới trách nhiệm

Xây dựng dịch vụ thu thập dữ liệu từ `hust.edu.vn` và các subdomain được phép, chạy định kỳ, lưu trạng thái qua nhiều lượt chạy và bàn giao dữ liệu cho microservice phía sau.

Crawler chịu trách nhiệm:

- Phát hiện URL từ seed, sitemap và liên kết trong HTML.
- Chuẩn hóa URL, lọc phạm vi, chống trùng URL giữa các lượt chạy.
- Tải trang theo lịch, ghi nhận HTTP status, retry và giới hạn tốc độ.
- Lưu phản hồi HTML thô cùng metadata để microservice khác xử lý.
- Nhận biết phiên bản phản hồi đã lưu để tránh tạo lại cùng một artifact.
- Xuất danh sách dữ liệu đã thu thập và thông tin đủ để bên nhận đọc lại.

Không thuộc phạm vi:

- Bóc tách nội dung bài viết, làm sạch văn bản, phân loại, NLP, embedding.
- Nhận biết hai bài viết có cùng ý nghĩa hoặc gộp nội dung tương đương.
- Xây dựng công cụ tìm kiếm, giao diện hoặc API nghiệp vụ.

Việc đọc HTML để tìm liên kết là một phần của crawl. Việc biến HTML thành dữ liệu nghiệp vụ do microservice phía sau đảm nhiệm.

## 2. Hiện trạng repository

- Python + Scrapy; spider `hust` trong `crawler/spiders/hust_spider.py`.
- Seed mặc định: trang chủ, Giới thiệu, Tin tức và sitemap.
- `crawler/urlutils.py` chuẩn hóa URL, lọc domain và các tài nguyên không cần crawl.
- `crawler/pipelines.py` ghi `output/links.txt`; khử trùng trong RAM trong một lượt chạy, ghi đè file khi bắt đầu lượt mới.
- Hiện chỉ xuất URL; chưa lưu HTML thô, chưa có database lịch sử crawl.
- Link PDF/Word/Excel/PowerPoint hiện chỉ được ghi lại, không chủ động tải file.
- Có robots.txt, AutoThrottle, retry, backoff khi gặp 429/503 và HTTP cache 24 giờ.
- Có test offline, CI GitHub Actions và Docker Compose. CI kiểm tra/build image, chưa publish image hoặc deploy.

Không dùng cache HTTP hoặc bộ lọc request của Scrapy làm lịch sử crawl lâu dài. Chúng không thay thế database trạng thái.

## 3. Phương án vận hành ban đầu

```text
PR vào main → CI: test + build (không publish/deploy)
Push/merge vào main → CI: test + build → Publish image → CD: cập nhật image trên server

Server Linux: cron mỗi giờ (đề xuất)
    ↓ lấy khóa, chỉ cho một lượt chạy
Docker Compose chạy crawler một lượt rồi thoát
    ↓
SQLite lưu URL, lượt chạy, phiên bản phản hồi
    + thư mục HTML thô và manifest trên volume bền vững
    ↓
Microservice phía sau đọc manifest + artifact
```

- Một server, một tiến trình crawler; chưa cần Redis, message broker hoặc scheduler riêng.
- Mỗi lượt có giới hạn số trang, độ sâu và thời gian chạy; không dùng vòng lặp crawl vô hạn.
- Lịch chạy chỉ kích hoạt công việc; database quyết định URL nào đến hạn tải lại.
- Nếu lượt trước còn chạy, bỏ qua lượt kích hoạt mới và ghi log; không hủy lượt trước để chạy lượt mới.
- SQLite phù hợp với phương án một crawler và lưu trên ổ đĩa của server. Nếu sau này cần nhiều worker/server cùng ghi, đánh giá chuyển sang database dùng chung.
- Dữ liệu, database và khóa chạy nằm ngoài container, không mất khi cập nhật image.

## 4. Chính sách crawl và chống trùng

### 4.1. URL và lịch tải lại

- Dùng URL đã chuẩn hóa làm khóa `UNIQUE` trong bảng `urls`.
- Khi phát hiện lại URL, cập nhật `last_seen`; không tạo bản ghi URL mới.
- URL mới đủ điều kiện được đưa vào lịch tải ngay; URL đã biết chỉ tải khi đến `next_fetch_at`.
- Không bỏ qua vĩnh viễn URL đã biết: nội dung trang và danh sách liên kết có thể đổi.
- Chạy lại seed/sitemap để phát hiện URL mới. Khi tải lại HTML, tiếp tục tìm liên kết dù phản hồi có hash đã biết.
- Mỗi lượt duyệt lại cả URL đến hạn trong database, không chỉ URL vừa xuất hiện từ seed. Giới hạn số trang không được khiến các URL cũ bị bỏ đói; ưu tiên URL chưa tải và URL quá hạn lâu nhất trong ngân sách phù hợp.
- URL chỉ được nhìn thấy không có nghĩa là tải thành công: tách `last_seen` khỏi `last_success_at`.
- HTTP 404/410 được ghi trạng thái và giãn lịch kiểm tra; không xóa lịch sử ngay. Lỗi tạm thời không được ghi đè phiên bản thành công gần nhất.
- Redirect phải được kiểm tra phạm vi; lưu cả URL yêu cầu và URL cuối. Không tự gộp hai URL khác nhau chỉ vì chúng chuyển tới cùng nơi nếu chưa có chính sách rõ ràng.

### 4.2. Phiên bản phản hồi thô

- Tính SHA-256 trên bytes của response body mà Scrapy cung cấp, trước mọi xử lý nội dung nghiệp vụ.
- Cặp `(url_id, body_sha256)` là duy nhất: cùng URL và cùng body thì không tạo phiên bản/artifact mới, nhưng vẫn cập nhật thời điểm kiểm tra và kết quả request.
- HTML thay đổi dù chỉ do timestamp/banner vẫn có thể tạo hash mới. Đây là kiểm tra bytes, không phải kiểm tra nội dung bài viết; xử lý trùng về nội dung thuộc microservice phía sau.
- Có thể dùng `ETag`/`Last-Modified` cho conditional request. HTTP 304 chỉ cập nhật trạng thái kiểm tra; giữ nguyên artifact cũ. Chỉ gửi điều kiện khi đã có body lưu thành công, và cần cách tải lại đầy đủ định kỳ để khám phá liên kết.
- Cache 24 giờ hiện tại có thể làm crawl mỗi giờ không thấy dữ liệu mới. Giai đoạn đầu nên tắt HTTP cache cho lượt cập nhật dữ liệu, dùng database và lịch tải lại để kiểm soát lượng request.
- Link tài liệu chỉ lưu metadata ở phiên bản đầu; tải tài liệu nhị phân là phạm vi cần chốt riêng với bên nhận dữ liệu.

## 5. Dữ liệu lưu bền vững

Schema tối thiểu đề xuất:

| Bảng | Trường chính | Mục đích |
|---|---|---|
| `urls` | `id`, `url UNIQUE`, `kind`, `first_seen`, `last_seen`, `last_attempt_at`, `last_success_at`, `last_status`, `next_fetch_at`, `etag`, `last_modified` | Danh sách URL và lịch tải lại |
| `crawl_runs` | `id`, `started_at`, `finished_at`, `status`, `stop_reason`, các bộ đếm | Theo dõi lượt chạy thành công, thất bại hoặc đạt giới hạn |
| `responses` | `id`, `url_id`, `run_id`, `final_url`, `fetched_at`, `status_code`, `content_type`, `body_sha256`, `body_path`, `byte_size` | Phiên bản phản hồi đã lưu; `UNIQUE(url_id, body_sha256)` |

Timestamps lưu theo UTC; giờ chạy cron phải cấu hình múi giờ rõ ràng trên server. Trạng thái lượt chạy phân biệt `completed`, `limited`, `failed`, `interrupted`; đạt giới hạn không có nghĩa là đã crawl hết website.

Cấu trúc storage minh họa:

```text
/data/
  crawler.sqlite3
  crawler.lock
  raw/<url_id>/<body_sha256>.html
  manifests/<run_id>.jsonl
  logs/
```

Ghi body vào file tạm rồi đổi tên atomically trước khi commit metadata. Nếu tiến trình chết giữa hai bước, có thể tồn tại file mồ côi; lượt chạy lại được phép tái sử dụng file đúng hash. Không đánh dấu phiên bản đã sẵn sàng khi file chưa ghi xong.

## 6. Hợp đồng bàn giao cho microservice phía sau

Phiên bản đầu dùng file artifact và manifest, chưa thêm broker hoặc endpoint nhận dữ liệu.

- Mỗi dòng JSONL mô tả một phiên bản HTML mới: `schema_version`, `response_id`, `run_id`, `url`, `final_url`, `fetched_at`, `status_code`, `content_type`, `body_sha256`, `byte_size`, `body_path`.
- `body_path` là đường dẫn tương đối trong storage đã thống nhất. Nếu hai service nằm khác máy, phải bổ sung kho object hoặc cơ chế chuyển file; không đưa đường dẫn local vào hợp đồng rồi giả định bên nhận đọc được.
- Bên nhận dùng `response_id` làm khóa xử lý idempotent. Việc nhận lại cùng manifest không được tạo công việc nghiệp vụ trùng.
- Chỉ xuất manifest cho artifact đã ghi và commit thành công. Tạo manifest từ database theo `run_id`, ghi file tạm rồi đổi tên để bên nhận không đọc file dở.
- Nếu crash sau commit nhưng trước khi xuất manifest, bước khôi phục phải tái tạo manifest từ database cho lượt bị ngắt. Không dựa hoàn toàn vào callback đóng spider để bàn giao.
- `links.txt` có thể tiếp tục được xuất như snapshot URL để tương thích; không dùng làm lịch sử hay nguồn bàn giao HTML chính.
- Tài liệu chỉ được phát hiện URL phải được biểu diễn riêng là `document_link`, không giả lập thành phản hồi đã tải thành công.
- Việc bên nhận đã xử lý artifact không thuộc trạng thái crawl. Chưa tự xóa dữ liệu trước khi chốt cơ chế xác nhận/retention với bên nhận.

## 7. CI/CD và lịch chạy

### CI

Chỉ kích hoạt khi push lên `main` hoặc mở, cập nhật commit, mở lại pull request có
nhánh đích là `main`. Push lên nhánh khác không có PR vào `main` không chạy CI.
Push thêm commit vào nhánh có PR đang mở vào `main` vẫn chạy kiểm tra PR. Không
cấu hình `workflow_dispatch` hoặc chạy CI/CD theo lịch. Lịch crawl độc lập trên server.

Giữ các kiểm tra hiện tại: dependencies, Ruff, nhận diện spider, unittest offline, kiểm tra Compose, build Docker và quyền ghi storage của user container. Test không gọi website HUST.

Bổ sung test cho database migration, khử trùng qua hai lượt chạy, lịch tải lại, body hash, crash recovery và manifest khi triển khai các phần đó.

### CD

- Chỉ publish image và deploy sau CI thành công cho sự kiện `push` vào `main`, bao gồm commit sau merge PR. Job publish/deploy phải kiểm tra cả `github.event_name == 'push'` và `github.ref == 'refs/heads/main'`; PR chỉ test/build, không publish hoặc deploy.
- Publish Docker image với tag commit SHA hoặc digest.
- Server pull image đã xác định và cập nhật cấu hình dùng cho lượt tiếp theo.
- Không dừng lượt crawl đang ghi dữ liệu để cập nhật. Deploy và crawl dùng chung cơ chế khóa khi thao tác schema/storage.
- Migration có phiên bản, backup trước khi đổi schema. Rollback image phải xét khả năng đọc schema hiện tại.
- Credentials registry/SSH nằm trong secrets triển khai, không commit vào repo.
- Chưa chọn server, registry hoặc cách xác thực; không coi CD là đã có sẵn.

### Lịch crawl

- Đề xuất kích hoạt mỗi giờ, kiểm tra lại trang thông thường sau 24 giờ; trang seed/Tin tức có thể mỗi giờ. Các giá trị này cần cấu hình được và xác nhận sau khi đo tải.
- Khóa dùng chung trên host ngăn chạy chồng cả cron lẫn chạy thủ công. Khóa tự giải phóng khi tiến trình chết; tránh chỉ dựa vào file tồn tại.
- Khi lượt chạy lỗi, giữ dữ liệu đã commit và ghi nguyên nhân. Lượt kế tiếp tiếp tục từ trạng thái bền vững; không cần triển khai resume nguyên hàng đợi Scrapy ở phiên bản đầu.
- Giữ robots.txt, giới hạn request mỗi domain và backoff hiện có; không tăng tốc chỉ vì chuyển lên server.

## 8. Thứ tự triển khai trên máy mới

1. Clone repository, đọc tài liệu này và README; chạy các kiểm tra offline hiện có để xác nhận môi trường.
2. Thêm SQLite, schema version và pipeline lưu URL; kiểm tra chống trùng qua nhiều lượt, vẫn giữ xuất `links.txt` nếu cần.
3. Thêm lịch tải lại dựa trên database; xử lý retry, status và ngân sách crawl mà không bỏ đói URL cũ.
4. Thêm lưu HTML thô, hash phiên bản và manifest; kiểm tra phục hồi khi dừng giữa chừng.
5. Cập nhật Docker Compose với volume `/data`, quyền ghi và cấu hình runtime.
6. Thiết lập khóa và lịch trên server đã chọn; thử một lượt nhỏ trước khi bật lịch thật.
7. Bổ sung publish image và CD sau khi có nơi triển khai và credentials phù hợp.

Không cần triển khai tất cả trong một thay đổi. Mỗi bước phải giữ crawler chạy được và có kiểm tra cho hành vi mới.

## 9. Tiêu chí nghiệm thu

- Cùng một URL được tìm thấy trong hai lượt chỉ có một bản ghi URL.
- Cùng URL/cùng body không sinh phiên bản hoặc artifact trùng; thời gian kiểm tra vẫn cập nhật.
- URL đến hạn được tải lại; URL mới được phát hiện sau khi trang seed thay đổi.
- HTML mới được lưu nguyên body và có manifest trỏ tới file đọc được.
- Lỗi mạng/429/503 không xóa dữ liệu thành công trước đó; retry hữu hạn.
- Dừng hoặc restart container không làm mất database và artifact đã commit.
- Lượt bị ngắt có thể phục hồi bàn giao; microservice nhận lại manifest vẫn xử lý idempotent.
- Hai lượt khởi động đồng thời chỉ có một lượt được phép ghi dữ liệu.
- Deploy image không làm mất volume, không ngắt lượt đang ghi, không chạy crawl trong CI.
- Logs có run ID, số URL mới, số lần tải, số phiên bản mới, lỗi và lý do dừng.

## 10. Những việc cần xác nhận trước khi vận hành

- Server Linux và registry nào được sử dụng? Ai quản lý credentials triển khai?
- Lịch kích hoạt, chu kỳ tải lại và giới hạn số trang/thời gian mỗi lượt?
- Bên nhận cần HTML thô hay chỉ URL? Đề xuất này mở rộng từ URL sang HTML thô, chưa được triển khai.
- Có cần tải tài liệu PDF/Word/Excel hay chỉ bàn giao link như hiện tại?
- Hai service có đọc chung storage không? Nếu không, chọn cơ chế chuyển artifact.
- Giới hạn dung lượng, retention và cách backup SQLite/artifact? Chưa xóa tự động khi chưa chốt chính sách.

## 11. Lời nhắn cho Codex ở máy tiếp theo

> Đọc CRAWLER_DESIGN.md và README.md, kiểm tra mã nguồn thực tế trước khi sửa. Đây là thiết kế đề xuất, chưa triển khai. Chỉ làm phần crawl và bàn giao dữ liệu thô; xử lý nội dung do microservice khác đảm nhiệm. Ưu tiên SQLite bền vững, chống trùng URL qua các lượt, lịch tải lại, HTML thô và manifest; giữ một crawler, không thêm broker hoặc nhiều worker khi chưa cần. Chưa tự deploy hoặc bật crawl định kỳ nếu chưa có server và lịch cụ thể.
