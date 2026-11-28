# Sổ tay Vận hành & Trình diễn Hệ thống Backend VADIRAS FLOW

Tài liệu này hướng dẫn từng bước khởi động, nạp dữ liệu mẫu, chạy trình diễn toàn bộ luồng nghiệp vụ và cấu hình kết nối GitHub App an toàn cho hệ thống **VADIRAS FLOW**.

---

## 1. Khởi động Nhanh Bằng Docker Compose (6 Dịch vụ)

Hệ thống đóng gói gọn nhẹ gồm đúng 6 dịch vụ trong [docker-compose.yml](file:///c:/GitHub/VADIRAS-FLOW/docker-compose.yml):
1. `postgres`: Cơ sở dữ liệu PostgreSQL 16 tích hợp sẵn `pgvector` (cổng `5432`).
2. `temporal`: Máy chủ điều phối quy trình Temporal dùng chung PostgreSQL (cổng `7233`).
3. `temporal-ui`: Giao diện web theo dõi quy trình Temporal (cổng `8080`).
4. `api`: Máy chủ FastAPI — tự động chạy `alembic upgrade head`, nạp dữ liệu mẫu và phục vụ API (cổng `8000`).
5. `temporal-worker`: Tiến trình xử lý các bước quy trình và tác vụ I/O (`python -m app.modules.runtime.worker`).
6. `outbox-worker`: Tiến trình đọc hàng đợi `outbox_events` và đẩy sự kiện ra luồng SSE (`python -m app.modules.observability.outbox`).

### Các bước chạy trình diễn cục bộ với bộ giả lập (không tốn phí API)

1. Sao chép cấu hình mẫu (chỉ chỉnh giá trị cục bộ nếu cần, tuyệt đối không đưa `.env` lên Git):
   ```powershell
   Copy-Item .env.example .env
   ```
2. Khởi chạy toàn bộ 6 dịch vụ:
   ```powershell
   docker compose up --build -d
   ```
3. Kiểm tra tình trạng các dịch vụ và sức khỏe API:
   - API sống: `http://localhost:8000/health/live`
   - Kiểm tra kết nối CSDL & Temporal: `http://localhost:8000/health/ready`
   - Tài liệu API tương tác (Swagger UI): `http://localhost:8000/docs`
   - Giao diện Temporal UI: `http://localhost:8080`
4. Dừng hệ thống khi kết thúc trình diễn:
   ```powershell
   docker compose down
   ```

---

## 2. Chạy Cục bộ Không Cần Docker (Phát triển & Kiểm thử Nhanh)

1. Cài đặt thư viện Python 3.11+:
   ```powershell
   python -m pip install -r requirements.txt
   ```
2. Nâng cấp cơ sở dữ liệu (43 bảng qua 8 bản nâng cấp Alembic) và nạp dữ liệu mẫu chạy lại an toàn:
   ```powershell
   python -m alembic upgrade head
   python -m scripts.seed_demo
   ```
3. Chạy máy chủ API cục bộ:
   ```powershell
   uvicorn app.main:app --reload --port 8000
   ```
4. Chạy toàn bộ bộ kiểm thử tự động (đơn vị, tích hợp, bảo mật và đủ 10 kịch bản đầu–cuối):
   ```powershell
   python -m pytest -v
   ```

---

## 3. Tài khoản Mẫu Thử Nghiệm (Chỉ Dùng Cho Demo Cục Bộ)

Kịch bản [demo_seed.py](file:///c:/GitHub/VADIRAS-FLOW/data/seeds/demo_seed.py) tự động khởi tạo 1 tổ chức (`vadiras-demo`), 6 phòng ban (`SUPPORT`, `ENGINEERING`, `DEVOPS`, `SECURITY`, `PRODUCT`, `MANAGEMENT`), 9 danh tính trợ lý AI, 5 yêu cầu mẫu và 7 tài khoản đăng nhập với mật khẩu thử nghiệm chung `VadirasDemo#2026`:

| Email | Vai trò | Phòng ban | Quyền hạn trình diễn chính |
|---|---|---|---|
| `admin@vadiras.local` | Quản trị viên (`admin`) | `MANAGEMENT` | Toàn quyền quản trị tổ chức và điều phối |
| `manager@vadiras.local` | Quản lý (`department_manager`) | `ENGINEERING` | Phân tích AI, ban hành quy trình, phê duyệt, kiểm toán, thống kê |
| `security@vadiras.local` | Bảo mật & Kiểm toán (`security_auditor`) | `SECURITY` | Phê duyệt thay đổi, xem nhật ký kiểm toán và bằng chứng |
| `worker@vadiras.local` | Nhân viên xử lý (`worker`) | `DEVOPS` | Nhận và hoàn thành đầu việc nội bộ (`human_tasks`) |
| `employee@vadiras.local` | Nhân viên (`employee`) | `PRODUCT` | Gửi yêu cầu nội bộ và theo dõi yêu cầu của mình |
| `customer.a@acme.local` | Khách hàng A (`customer_contact`) | — | Gửi yêu cầu; chỉ xem dữ liệu `CUSTOMER_VISIBLE` của chính mình |
| `customer.b@globex.local` | Khách hàng B (`customer_contact`) | — | Kiểm chứng cô lập: không thấy dữ liệu của Khách hàng A |

---

## 4. Kịch bản Trình diễn Luồng Xuyên suốt Đầu–Cuối

### A. Luồng 1 — Yêu cầu Sự cố (`INCIDENT`) hoàn toàn tự động
1. **Đăng nhập:** Gọi `POST /api/v1/auth/login` bằng `customer.a@acme.local` lấy `access_token`.
2. **Gửi Sự cố:** Gọi `POST /api/v1/requests` (kèm `Idempotency-Key`) với `request_type: "INCIDENT"`.
3. **Phân tích AI & Đề xuất quy trình:** Đăng nhập `manager@vadiras.local`, gọi `POST /api/v1/requests/{id}/analyze` và `POST /api/v1/requests/{id}/propose-workflows` -> xem phân tích có cấu trúc, chi phí có nhãn nguồn (`ESTIMATED`) và không có suy nghĩ ẩn AI.
4. **Kiểm định 7 tầng & Ban hành:** Gọi `POST /api/v1/workflows/validate` -> `POST /api/v1/workflows` -> `POST /api/v1/workflows/{wf_id}/publish` (khóa bất biến kèm `content_hash`).
5. **Thực thi & Theo dõi trực tiếp:** Gọi `POST /api/v1/workflow-runs` -> mở luồng SSE `GET /api/v1/workflow-runs/{run_id}/events` để xem trạng thái từng bước.
6. **Xác minh & Kiểm toán:** Xem `GET /api/v1/requests/{id}/verification` (trạng thái `VERIFIED` kèm bằng chứng đọc ngược từ `MockGitHubConnector`) và `GET /api/v1/audit-logs`.

### B. Luồng 2 — Yêu cầu Thay đổi (`CHANGE`) qua Cổng Phê duyệt 7 Yếu tố
1. Gửi yêu cầu `CHANGE` và ban hành mẫu `change_request_v1.json`.
2. Khởi chạy bằng tài khoản `admin@vadiras.local` (`POST /api/v1/workflow-runs`). Quy trình tự động dừng tại `WAITING_APPROVAL` trước bước `CONNECTOR_ACTION` rủi ro cao.
3. Thử tự duyệt bằng chính `admin@vadiras.local` -> hệ thống chặn ngay với mã lỗi `403 SELF_APPROVAL_FORBIDDEN`.
4. Đăng nhập `manager@vadiras.local`, kiểm tra chi tiết ràng buộc tại `GET /api/v1/approvals/{approval_id}` rồi duyệt tại `POST /api/v1/approvals/{approval_id}/decision`.
5. `ExecutionGuard` kiểm tra lại đủ 7 yếu tố, `ToolBroker` tạo GitHub Issue kèm khóa chống trùng lặp và `VerificationEngine` đọc ngược chốt kết quả `VERIFIED`.

### C. Luồng 3 — Webhook Bảo mật, Quét Dự phòng, Bộ nhớ & Thống kê
- Gửi webhook giả lập kèm chữ ký `X-Hub-Signature-256` và `X-GitHub-Delivery` tới `POST /api/v1/webhooks/github`; gửi lại lần 2 trả `duplicate: true`.
- Chạy quét bù sự kiện trễ bằng `POST /api/v1/connectors/github/reconcile`.
- Lưu và thăng hạng tri thức bằng `POST /api/v1/memory/items` -> `POST /api/v1/memory/items/{id}/promote`, sau đó tìm kiếm ở `GET /api/v1/memory/search`.
- Xem 7 bảng thống kê: `GET /api/v1/metrics/{overview,sla,automation,cost,agents,departments,industries}`.

---

## 5. Hướng dẫn Tích hợp GitHub App Thật (Theo Nguyên tắc Quyền Tối thiểu)

Khi muốn chuyển từ `GITHUB_CONNECTOR_MODE=mock` sang kết nối kho GitHub thử nghiệm thật:
1. Tạo một GitHub App mới trong **GitHub Settings -> Developer settings -> GitHub Apps**.
2. Chỉ cấp quyền tối thiểu:
   - **Repository permissions:** `Metadata: Read-only`, `Issues: Read & write`.
   - **Subscribe to events:** chỉ chọn `Issues` và `Issue comment`.
3. Tải khóa riêng `.pem` và đặt **bên ngoài kho mã** (ví dụ `/run/secrets/github-app.pem` hoặc thư mục cục bộ không theo dõi bởi Git — đã chặn sẵn đuôi `*.pem` trong `.gitignore`).
4. Cài đặt GitHub App **chỉ trên đúng kho thử nghiệm** (ví dụ `Duckyeeen/VADIRAS-FLOW`).
5. Cấu hình biến môi trường (trong `.env` cục bộ, không commit):
   ```dotenv
   GITHUB_CONNECTOR_MODE=github_app
   GITHUB_APP_ID=<ma_app_cua_ban>
   GITHUB_INSTALLATION_ID=<ma_cai_dat_cua_ban>
   GITHUB_PRIVATE_KEY_PATH=/duong/dan/toi/private-key.pem
   GITHUB_WEBHOOK_SECRET=<chuoi_bi_mat_webhook_ngau_nhien>
   GITHUB_ALLOWED_REPOS=Duckyeeen/VADIRAS-FLOW
   ```
6. Nếu chạy máy cục bộ không mở cổng nhận webhook trực tiếp từ Internet, vẫn kích hoạt được cơ chế quét đồng bộ dự phòng qua `POST /api/v1/connectors/github/reconcile`.

---

## 6. Danh mục Kiểm tra Nghiệm thu Trình diễn

- [x] Khởi động gọn nhẹ đúng 6 dịch vụ với `.env.example` an toàn (`docker-compose.yml`).
- [x] Nâng cấp sạch 43 bảng Alembic và nạp dữ liệu mẫu idempotent (`VadirasDemoEnterprise`, 6 phòng ban, 9 trợ lý AI).
- [x] Đầy đủ 5 nhóm vai trò đăng nhập JWT + Argon2id và lọc quyền thời gian thực từ CSDL.
- [x] Tiếp nhận, phân tích AI có cấu trúc (không rò rỉ `reasoning_trace`), kiểm định 7 tầng và ban hành phiên bản bất biến cho đủ 5 loại yêu cầu.
- [x] Chặn thao tác rủi ro cao tại cổng phê duyệt 7 yếu tố (`ExecutionGuard`) và chống tự phê duyệt.
- [x] Hỗ trợ đầy đủ `MockGitHubConnector` và `GitHubAppConnector` kèm xác thực HMAC-SHA256 webhook, chống trùng lặp và quét dự phòng.
- [x] Chấm đủ 4 trạng thái xác minh (`VERIFIED`, `PARTIALLY_VERIFIED`, `FAILED`, `UNVERIFIED`), ghi nhật ký kiểm toán chỉ thêm mới, bộ nhớ `pgvector` lọc quyền, SSE và 7 API thống kê minh bạch chi phí.
