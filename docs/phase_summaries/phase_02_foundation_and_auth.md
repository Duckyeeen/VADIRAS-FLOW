# Tổng kết Giai đoạn 2 — Dựng Nền tảng: Cấu hình, Nhật ký, CSDL, Alembic & Đăng nhập/Phân quyền

- **Trạng thái:** Đã hoàn thành
- **Thời gian hoàn tất:** 27/11/2026
- **Mục tiêu:** Thiết lập bộ khung kỹ thuật cốt lõi cho phần xử lý nền: đọc cấu hình an toàn, gắn mã theo dõi xuyên suốt, ghi nhật ký JSON có che thông tin nhạy cảm, kết nối cơ sở dữ liệu bất đồng bộ, quản lý nâng cấp bảng qua Alembic (`0001`), đăng nhập JWT + Argon2id, xoay vòng thẻ làm mới, phân quyền theo vai trò và cô lập chặt theo tổ chức.

---

## 1. Danh sách tệp đã tạo mới và chỉnh sửa

### 1.1 Tệp cấu hình dự án và Alembic
| Đường dẫn tệp | Hành động | Vai trò / Nội dung chính |
|---|---|---|
| [requirements.txt](file:///c:/GitHub/VADIRAS-FLOW/requirements.txt) | Cập nhật | Bổ sung và khóa dải phiên bản cho SQLAlchemy 2, `asyncpg`, `aiosqlite`, `alembic`, `pgvector`, `pyjwt[crypto]`, `argon2-cffi`, `python-json-logger`, `email-validator`, `pytest-asyncio` |
| [.env.example](file:///c:/GitHub/VADIRAS-FLOW/.env.example) | Cập nhật | Bổ sung biến cấu hình mẫu (chỉ chứa giá trị giữ chỗ an toàn) cho PostgreSQL, Temporal, JWT, AI và GitHub App kèm chú thích tiếng Việt |
| [alembic.ini](file:///c:/GitHub/VADIRAS-FLOW/alembic.ini) | Tạo mới | Cấu hình đường dẫn thư mục nâng cấp CSDL Alembic |
| [alembic/script.py.mako](file:///c:/GitHub/VADIRAS-FLOW/alembic/script.py.mako) | Tạo mới | Khuôn mẫu sinh tệp nâng cấp bảng Alembic |
| [alembic/env.py](file:///c:/GitHub/VADIRAS-FLOW/alembic/env.py) | Tạo mới | Bộ điều phối chạy Alembic bất đồng bộ hỗ trợ cả PostgreSQL và SQLite |
| [0001_enable_pgvector_and_identity.py](file:///c:/GitHub/VADIRAS-FLOW/alembic/versions/0001_enable_pgvector_and_identity.py) | Tạo mới | Bản nâng cấp CSDL `0001`: bật `vector` trên PostgreSQL và tạo 12 bảng định danh, tổ chức, 6 phòng ban, phân quyền, phiên thẻ làm mới và danh tính AI |

### 1.2 Lớp lõi (`app/core/`) và Lớp cơ sở dữ liệu (`app/db/`)
| Đường dẫn tệp | Hành động | Vai trò / Nội dung chính |
|---|---|---|
| [app/core/__init__.py](file:///c:/GitHub/VADIRAS-FLOW/app/core/__init__.py) | Tạo mới | Khởi tạo gói lớp lõi |
| [app/core/config.py](file:///c:/GitHub/VADIRAS-FLOW/app/core/config.py) | Tạo mới | Đọc cấu hình từ biến môi trường / `.env`, kiểm tra hợp lệ `CORS_ALLOWED_ORIGINS` (chặn dấu `*`) |
| [app/core/correlation.py](file:///c:/GitHub/VADIRAS-FLOW/app/core/correlation.py) | Tạo mới | Middleware tự động đọc/tạo và trả về tiêu đề `X-Correlation-ID` xuyên suốt từng lượt gọi |
| [app/core/logging.py](file:///c:/GitHub/VADIRAS-FLOW/app/core/logging.py) | Tạo mới | Ghi nhật ký dạng JSON kèm bộ lọc `SensitiveDataRedactionFilter` tự động che mật khẩu, token, khóa API, khóa riêng và suy nghĩ ẩn thành `[DA_AN]` |
| [app/core/errors.py](file:///c:/GitHub/VADIRAS-FLOW/app/core/errors.py) | Tạo mới | Hệ thống ngoại lệ nghiệp vụ (`401`, `403`, `404`, `409`, `422`) và khuôn mẫu phản hồi lỗi JSON thống nhất |
| [app/core/security.py](file:///c:/GitHub/VADIRAS-FLOW/app/core/security.py) | Tạo mới | Băm/đối chiếu mật khẩu Argon2id, tạo/giải mã JWT có kiểm tra `iss`/`aud`/`exp`/`type`, băm SHA-256 thẻ làm mới và kiểm tra HMAC-SHA256 hằng thời gian |
| [app/db/__init__.py](file:///c:/GitHub/VADIRAS-FLOW/app/db/__init__.py) | Tạo mới | Khởi tạo gói CSDL |
| [app/db/base.py](file:///c:/GitHub/VADIRAS-FLOW/app/db/base.py) | Tạo mới | Lớp bảng nền SQLAlchemy 2, quy ước đặt tên ràng buộc và kiểu `JSONType` (dùng `JSONB` trên PostgreSQL, `JSON` trên SQLite) |
| [app/db/mixins.py](file:///c:/GitHub/VADIRAS-FLOW/app/db/mixins.py) | Tạo mới | Các nhóm cột dùng chung: khóa chính UUID, dấu thời gian UTC và cột `organization_id` có chỉ mục |
| [app/db/session.py](file:///c:/GitHub/VADIRAS-FLOW/app/db/session.py) | Tạo mới | Tạo động cơ kết nối bất đồng bộ, cung cấp phiên CSDL theo từng lượt gọi và hàm kiểm tra sức khỏe `SELECT 1` |

### 1.3 Phân hệ Định danh, Tổ chức & Máy chủ FastAPI (`app/modules/identity/`, `app/main.py`)
| Đường dẫn tệp | Hành động | Vai trò / Nội dung chính |
|---|---|---|
| [app/modules/__init__.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/__init__.py) | Tạo mới | Khởi tạo gói các phân hệ nghiệp vụ |
| [app/modules/identity/__init__.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/identity/__init__.py) | Tạo mới | Khởi tạo phân hệ Định danh & Tổ chức |
| [app/modules/identity/models.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/identity/models.py) | Tạo mới | 12 mô hình bảng SQLAlchemy 2 (`organizations`, `departments`, `users`, `memberships`, `roles`, `permissions`, `role_permissions`, `membership_roles`, `refresh_token_sessions`, `agent_identities`, `agent_capabilities`, `agent_tool_grants`) |
| [app/modules/identity/schemas.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/identity/schemas.py) | Tạo mới | Khuôn mẫu Pydantic kế thừa `ContractModel` (ẩn hoàn toàn `password_hash`, phân trang chuẩn) |
| [app/modules/identity/repository.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/identity/repository.py) | Tạo mới | Các hàm truy vấn bất đồng bộ luôn lọc chặt theo `organization_id` |
| [app/modules/identity/service.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/identity/service.py) | Tạo mới | Nghiệp vụ đăng nhập, xoay vòng thẻ làm mới (tự thu hồi toàn bộ phiên nếu phát hiện dùng lại thẻ cũ), đăng xuất, nạp quyền mới nhất từ CSDL và kiểm tra quyền/tổ chức |
| [app/modules/identity/dependencies.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/identity/dependencies.py) | Tạo mới | Hàm phụ thuộc FastAPI xác thực Bearer token và kiểm tra quyền ở tuyến API |
| [app/modules/identity/router.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/identity/router.py) | Tạo mới | 6 tuyến API: `/api/v1/auth/login`, `/refresh`, `/logout`, `/me`, `/departments`, `/users` |
| [app/main.py](file:///c:/GitHub/VADIRAS-FLOW/app/main.py) | Tạo mới | Khởi tạo ứng dụng FastAPI, gắn middleware CORS/theo dõi/lỗi, `/health/live`, `/health/ready` và router định danh |

### 1.4 Bộ kiểm thử Giai đoạn 2 (`tests/`)
| Đường dẫn tệp | Hành động | Vai trò / Nội dung chính |
|---|---|---|
| [tests/__init__.py](file:///c:/GitHub/VADIRAS-FLOW/tests/__init__.py) | Tạo mới | Khởi tạo gói kiểm thử |
| [tests/conftest.py](file:///c:/GitHub/VADIRAS-FLOW/tests/conftest.py) | Tạo mới | Dựng CSDL sạch chạy Alembic trước mỗi bài test và nạp dữ liệu mẫu 2 tổ chức, 6 phòng ban, 4 vai trò và 6 tài khoản |
| [test_security_and_logging.py](file:///c:/GitHub/VADIRAS-FLOW/tests/unit/test_security_and_logging.py) | Tạo mới | 4 bài kiểm thử đơn vị cho Argon2id, JWT, HMAC-SHA256 và bộ lọc che thông tin nhạy cảm trong nhật ký |
| [test_migrations_and_health.py](file:///c:/GitHub/VADIRAS-FLOW/tests/integration/test_migrations_and_health.py) | Tạo mới | 2 bài kiểm thử tích hợp cho nâng/hạ cấp Alembic từ CSDL trống và các tuyến `/health/live`, `/health/ready` |
| [test_auth_and_rbac.py](file:///c:/GitHub/VADIRAS-FLOW/tests/integration/test_auth_and_rbac.py) | Tạo mới | 4 bài kiểm thử tích hợp & bảo mật cho đăng nhập, nạp quyền mới từ CSDL, xoay vòng thẻ làm mới, phân quyền RBAC và cô lập tổ chức/khách hàng |

---

## 2. Chi tiết các phần đã xây dựng

1. **Bảo mật xác thực & chống dùng quyền cũ:** Thẻ truy cập JWT chỉ mang các mã định danh tối thiểu. Mỗi khi người dùng gọi `/api/v1/auth/me`, `/api/v1/departments` hoặc `/api/v1/users`, hệ thống luôn truy vấn lại trạng thái tài khoản, trạng thái thành viên và danh sách vai trò/quyền mới nhất từ CSDL. Nếu tài khoản vừa bị khóa hoặc bị thu hồi quyền, yêu cầu tiếp theo bị từ chối ngay lập tức.
2. **Xoay vòng thẻ làm mới & phát hiện đánh cắp:** Khi gọi `/api/v1/auth/refresh`, thẻ cũ bị đánh dấu đã thu hồi và gắn vết trỏ sang thẻ mới. Nếu thẻ cũ bị dùng lại lần thứ hai, hệ thống thu hồi toàn bộ phiên làm mới còn lại của thành viên đó (`REFRESH_TOKEN_REUSED`).
3. **Cô lập tổ chức & tách biệt khách hàng:** Mọi truy vấn phòng ban và danh sách thành viên đều lọc theo `organization_id` của người gọi. Tài khoản khách hàng (`CUSTOMER_CONTACT`) bị chặn hoàn toàn khi truy cập danh sách phòng ban và thành viên nội bộ (`403 INTERNAL_ONLY_RESOURCE`).

---

## 3. Kiểm thử & Kết quả chi tiết

- **Có chạy kiểm thử tự động hay không:** **Có** (bao gồm 4 kiểm thử đơn vị và 6 kiểm thử tích hợp/bảo mật).
- **Lệnh kiểm tra cú pháp đã chạy:**
  `python -m py_compile app\main.py app\core\config.py app\core\correlation.py app\core\logging.py app\core\errors.py app\core\security.py app\db\base.py app\db\mixins.py app\db\session.py app\modules\identity\models.py app\modules\identity\schemas.py app\modules\identity\repository.py app\modules\identity\service.py app\modules\identity\dependencies.py app\modules\identity\router.py alembic\env.py alembic\versions\0001_enable_pgvector_and_identity.py` -> **Đạt** (mã thoát `0`).
- **Lệnh kiểm thử đã chạy:** `python -m pytest -v`
- **Tổng kết kết quả:** **10/10 bài kiểm thử ĐẠT (`10 passed, 1 warning in 8.05s`, mã thoát `0`)**.

| STT | Tệp & Tên bài kiểm thử | Loại | Nội dung kiểm chứng | Kết quả thực tế |
|---|---|---|---|---|
| 1 | `tests/unit/test_security_and_logging.py::test_argon2id_password_hashing_and_verification` | Đơn vị | Kiểm tra băm Argon2id tạo muối ngẫu nhiên, đối chiếu đúng/sai mật khẩu | **PASSED** |
| 2 | `tests/unit/test_security_and_logging.py::test_jwt_access_and_refresh_token_validation` | Đơn vị | Kiểm tra tạo/giải mã JWT, phát hiện hết hạn, sai chữ ký, chặn dùng nhầm thẻ refresh làm thẻ access | **PASSED** |
| 3 | `tests/unit/test_security_and_logging.py::test_hmac_sha256_verification` | Đơn vị | Kiểm tra xác thực chữ ký HMAC-SHA256 đúng, sai chữ ký, sai tiền tố và thiếu chữ ký | **PASSED** |
| 4 | `tests/unit/test_security_and_logging.py::test_sensitive_data_redaction_in_logs` | Đơn vị | Kiểm tra che dấu `password`, `access_token`, `private_key`, `api_key`, `chain_of_thought` trong log | **PASSED** |
| 5 | `tests/integration/test_migrations_and_health.py::test_alembic_upgrade_and_downgrade_from_clean_database` | Tích hợp | Chạy `upgrade head` -> xác nhận đủ 12 bảng -> `downgrade base` -> `upgrade head` trên CSDL trống | **PASSED** |
| 6 | `tests/integration/test_migrations_and_health.py::test_health_live_and_ready_endpoints` | Tích hợp | Kiểm tra `/health/live`, `/health/ready` (`database: up`) và tiêu đề `X-Correlation-ID` | **PASSED** |
| 7 | `tests/integration/test_auth_and_rbac.py::test_login_success_wrong_password_and_suspended_membership` | Tích hợp | Kiểm tra đăng nhập thành công, sai mật khẩu (`401`) và tài khoản bị tạm khóa (`401`) | **PASSED** |
| 8 | `tests/integration/test_auth_and_rbac.py::test_auth_me_does_not_leak_password_and_enforces_fresh_db_state` | Bảo mật | Xác nhận `/auth/me` không lộ `password_hash`; thu hồi vai trò hoặc khóa thành viên có hiệu lực ngay với token còn hạn | **PASSED** |
| 9 | `tests/integration/test_auth_and_rbac.py::test_refresh_rotation_reuse_detection_and_logout` | Bảo mật | Xác nhận xoay vòng thẻ làm mới, chặn và khóa toàn bộ phiên khi thẻ cũ bị dùng lại, và thu hồi khi đăng xuất | **PASSED** |
| 10 | `tests/integration/test_auth_and_rbac.py::test_rbac_customer_isolation_and_organization_scoping` | Bảo mật | Xác nhận Admin A chỉ thấy 6 phòng ban/5 người của tổ chức A, Admin B chỉ thấy tổ chức B, nhân viên/khách hàng bị chặn `403`, kiểm tra `page_size=500` trả `422` | **PASSED** |

---

## 4. Ghi chú môi trường & Điểm lưu ý cho Giai đoạn 3

- Trong phiên kiểm thử cục bộ này, Docker Desktop trên máy chưa được bật nên bộ kiểm thử tích hợp chạy trên cơ sở dữ liệu tạm `sqlite+aiosqlite` (chạy qua đúng quy trình nâng cấp bảng Alembic `0001`). Bản nâng cấp `0001` đã viết sẵn nhánh tự động chạy `CREATE EXTENSION IF NOT EXISTS vector` và cột `JSONB` khi kết nối PostgreSQL 16 (sẽ kiểm chứng trực tiếp trên container PostgreSQL ở giai đoạn thiết lập Docker Compose).
- Cảnh báo nhẹ duy nhất trong `pytest`: Starlette cảnh báo hằng số `HTTP_422_UNPROCESSABLE_ENTITY` sắp đổi tên thành `HTTP_422_UNPROCESSABLE_CONTENT` (không ảnh hưởng chức năng, có thể cập nhật ở giai đoạn sau).
- Giai đoạn 3 tiếp theo sẽ xây dựng phân hệ tiếp nhận yêu cầu (`requests`), bộ làm sạch/ẩn thông tin cá nhân, 5 nhóm yêu cầu mẫu, cô lập quyền xem của khách hàng và kịch bản nạp dữ liệu mẫu `scripts/seed_demo.py`.
