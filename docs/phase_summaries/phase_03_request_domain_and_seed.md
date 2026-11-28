# Tổng kết Giai đoạn 3 — Phân hệ Tiếp nhận Yêu cầu, Tác vụ Con người & Dữ liệu Mẫu

- **Trạng thái:** Đã hoàn thành
- **Thời gian hoàn tất:** 27/11/2026
- **Mục tiêu:** Xây dựng trọn vẹn phân hệ tiếp nhận yêu cầu công việc (`INCIDENT`, `CHANGE`, `SERVICE_REQUEST`, `ONBOARDING`, `INTERNAL_TASK`), bộ làm sạch và ẩn thông tin cá nhân nhạy cảm, phát hiện dấu hiệu cài cắm câu lệnh, cơ chế cô lập tuyệt đối dữ liệu khách hàng với nhân viên nội bộ, vòng đời đầu việc con người, bản nâng cấp CSDL `0002` và kịch bản nạp dữ liệu mẫu chạy lại an toàn.

---

## 1. Danh sách tệp đã tạo mới và chỉnh sửa

### 1.1 Phân hệ Yêu cầu & Điều chỉnh Lõi (`app/modules/requests/`, `app/`)
| Đường dẫn tệp | Hành động | Vai trò / Nội dung chính |
|---|---|---|
| [app/core/errors.py](file:///c:/GitHub/VADIRAS-FLOW/app/core/errors.py) | Chỉnh sửa nhỏ | Thay hằng số lỗi `422` để loại bỏ hoàn toàn cảnh báo Starlette khi chạy kiểm thử |
| [app/modules/requests/__init__.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/requests/__init__.py) | Tạo mới | Khởi tạo gói phân hệ Yêu cầu & Tác vụ |
| [app/modules/requests/models.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/requests/models.py) | Tạo mới | 6 bảng dữ liệu: `requests`, `request_participants`, `request_attachments`, `request_messages`, `request_analyses`, `human_tasks` |
| [app/modules/requests/intake.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/requests/intake.py) | Tạo mới | Ẩn thông tin nhạy cảm (`EMAIL`, `PHONE`, `PAYMENT_CARD`, `SECRET_OR_TOKEN`), phát hiện dấu hiệu cài cắm lệnh, tính mã băm SHA-256 và gợi ý phòng ban mặc định |
| [app/modules/requests/schemas.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/requests/schemas.py) | Tạo mới | Tách riêng khuôn mẫu đầu ra `RequestCustomerOut` (ẩn hoàn toàn dữ liệu nội bộ) và `RequestInternalOut` (dành cho nhân viên) |
| [app/modules/requests/repository.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/requests/repository.py) | Tạo mới | Truy vấn bất đồng bộ lọc chặt theo `organization_id`, quyền sở hữu khách hàng, mã chống trùng và làm mới dữ liệu quan hệ (`populate_existing`) |
| [app/modules/requests/service.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/requests/service.py) | Tạo mới | Xử lý tạo/lấy/cập nhật yêu cầu, gửi bình luận, làm rõ thông tin (`NEEDS_INFORMATION -> OPEN`) và vòng đời đầu việc (`claim`, `block`, `complete`) |
| [app/modules/requests/router.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/requests/router.py) | Tạo mới | 12 tuyến API `/api/v1/requests*` và `/api/v1/tasks*` |
| [app/validator.py](file:///c:/GitHub/VADIRAS-FLOW/app/validator.py) | Cập nhật | Hiện thực hóa hàm `validate_and_sanitize` dùng chung bộ ẩn thông tin nhạy cảm từ `intake.py` |
| [app/main.py](file:///c:/GitHub/VADIRAS-FLOW/app/main.py) | Cập nhật | Gắn bộ định tuyến của phân hệ `requests` vào ứng dụng FastAPI |

### 1.2 Nâng cấp CSDL & Dữ liệu mẫu (`alembic/`, `data/seeds/`, `scripts/`)
| Đường dẫn tệp | Hành động | Vai trò / Nội dung chính |
|---|---|---|
| [alembic/env.py](file:///c:/GitHub/VADIRAS-FLOW/alembic/env.py) | Cập nhật | Nạp mô hình phân hệ `requests` để Alembic quản lý đầy đủ 18 bảng |
| [0002_request_domain.py](file:///c:/GitHub/VADIRAS-FLOW/alembic/versions/0002_request_domain.py) | Tạo mới | Tạo 6 bảng mới của phân hệ yêu cầu kèm khóa ngoại và chỉ mục tối ưu |
| [data/seeds/__init__.py](file:///c:/GitHub/VADIRAS-FLOW/data/seeds/__init__.py) | Tạo mới | Khởi tạo gói dữ liệu mẫu |
| [data/seeds/demo_seed.py](file:///c:/GitHub/VADIRAS-FLOW/data/seeds/demo_seed.py) | Tạo mới | Hàm `seed_demo_data` chạy nhiều lần an toàn: nạp 1 tổ chức, 6 phòng ban, 12 quyền, 6 vai trò, 7 tài khoản thử nghiệm, 9 trợ lý AI và 5 yêu cầu mẫu |
| [scripts/__init__.py](file:///c:/GitHub/VADIRAS-FLOW/scripts/__init__.py) | Tạo mới | Khởi tạo gói công cụ dòng lệnh |
| [scripts/seed_demo.py](file:///c:/GitHub/VADIRAS-FLOW/scripts/seed_demo.py) | Tạo mới | Lệnh dòng lệnh `python -m scripts.seed_demo` nạp dữ liệu mẫu vào CSDL cấu hình |

### 1.3 Bộ kiểm thử (`tests/`)
| Đường dẫn tệp | Hành động | Vai trò / Nội dung chính |
|---|---|---|
| [tests/conftest.py](file:///c:/GitHub/VADIRAS-FLOW/tests/conftest.py) | Cập nhật | Bổ sung các quyền mới cho yêu cầu và đầu việc vào dữ liệu mẫu kiểm thử |
| [test_migrations_and_health.py](file:///c:/GitHub/VADIRAS-FLOW/tests/integration/test_migrations_and_health.py) | Cập nhật | Mở rộng kiểm chứng đầy đủ 18 bảng sau `upgrade head` -> `downgrade base` -> `upgrade head` |
| [test_request_intake.py](file:///c:/GitHub/VADIRAS-FLOW/tests/unit/test_request_intake.py) | Tạo mới | 4 bài kiểm thử đơn vị cho che thông tin nhạy cảm, phát hiện cài cắm lệnh, mã băm nội dung và `app.validator` |
| [test_requests_and_tasks.py](file:///c:/GitHub/VADIRAS-FLOW/tests/integration/test_requests_and_tasks.py) | Tạo mới | 3 bài kiểm thử tích hợp cho 5 loại yêu cầu, mã `Idempotency-Key`, làm rõ thông tin, vòng đời đầu việc và tính an toàn khi chạy `seed_demo_data` lặp lại |
| [test_customer_isolation.py](file:///c:/GitHub/VADIRAS-FLOW/tests/security/test_customer_isolation.py) | Tạo mới | Bài kiểm thử bảo mật cô lập tuyệt đối dữ liệu giữa 2 khách hàng, ẩn ghi chú nội bộ và cô lập giữa 2 tổ chức |

---

## 2. Chi tiết các phần đã xây dựng & Tài khoản mẫu cục bộ

1. **Làm sạch và bảo vệ dữ liệu tiếp nhận:** Khi tạo yêu cầu mới, văn bản gốc được giữ nguyên trong `description`, đồng thời tạo bản sạch `sanitized_description` đã che email, số điện thoại, số thẻ và khóa bí mật để chuẩn bị đưa sang phân hệ AI ở Giai đoạn 4. Các cụm từ cài cắm câu lệnh bất thường được ghi nhận vào `injection_flags_json` để cảnh báo nội bộ.
2. **Cô lập khách hàng nhiều lớp:** Tài khoản `CUSTOMER_CONTACT` chỉ truy vấn được yêu cầu của chính mình hoặc cùng mã khách hàng (`customer_account_ref`), chỉ nhận dữ liệu qua khuôn mẫu `RequestCustomerOut` (không có `pii_redactions`, `injection_flags`, `sanitized_description`, `human_tasks`, `metadata`) và chỉ thấy tin nhắn có nhãn `CUSTOMER_VISIBLE`.
3. **Danh sách 7 tài khoản thử nghiệm trong `demo_seed.py` (CHỈ DÙNG CHO MÔI TRƯỜNG PHÁT TRIỂN CỤC BỘ, mật khẩu mẫu `VadirasDemo#2026`):**
   - `admin@vadiras.local` (Quản trị viên — Phòng Quản lý)
   - `manager@vadiras.local` (Quản lý phòng ban — Phòng Kỹ thuật)
   - `security@vadiras.local` (Kiểm toán & Bảo mật — Phòng An toàn thông tin)
   - `worker@vadiras.local` (Kỹ sư xử lý — Phòng Vận hành hạ tầng)
   - `employee@vadiras.local` (Nhân viên gửi yêu cầu — Phòng Sản phẩm)
   - `customer.a@acme.local` (Khách hàng Acme — `CUST-ACME`)
   - `customer.b@globex.local` (Khách hàng Globex — `CUST-GLOBEX`)

---

## 3. Kiểm thử & Kết quả chi tiết

- **Có chạy kiểm thử tự động hay không:** **Có** (tổng cộng 18 bài kiểm thử gồm 8 bài mới của Giai đoạn 3 và 10 bài hồi quy của Giai đoạn 2).
- **Lệnh kiểm tra cú pháp:** `python -m py_compile ...` trên toàn bộ 13 tệp mới/chỉnh sửa -> **Đạt** (mã thoát `0`).
- **Lệnh kiểm thử đã chạy:** `python -m pytest -v`
- **Tổng kết kết quả:** **18/18 bài kiểm thử ĐẠT (`18 passed in 20.56s`, 0 lỗi, 0 cảnh báo, mã thoát `0`)**.

| STT | Nhóm / Tên bài kiểm thử | Nội dung kiểm chứng | Kết quả thực tế |
|---|---|---|---|
| 1–4 | `tests/unit/test_security_and_logging.py` (4 bài) | Hồi quy Argon2id, JWT, HMAC-SHA256 và che dữ liệu nhạy cảm trong nhật ký | **4/4 PASSED** |
| 5–6 | `tests/integration/test_migrations_and_health.py` (2 bài) | Nâng/hạ cấp Alembic đủ 18 bảng từ CSDL trống và `/health/live`, `/health/ready` | **2/2 PASSED** |
| 7–10 | `tests/integration/test_auth_and_rbac.py` (4 bài) | Hồi quy đăng nhập, nạp quyền mới từ CSDL, xoay vòng thẻ làm mới và phân quyền | **4/4 PASSED** |
| 11 | `tests/unit/test_request_intake.py::test_redact_pii_masks_email_phone_card_and_tokens` | Che email, số điện thoại, số thẻ thanh toán và khóa bí mật | **PASSED** |
| 12 | `tests/unit/test_request_intake.py::test_detect_prompt_injection_signals` | Nhận diện các cụm từ cài cắm câu lệnh vượt quyền | **PASSED** |
| 13 | `tests/unit/test_request_intake.py::test_content_hash_and_department_suggestion` | Tính mã băm SHA-256 ổn định và gợi ý đúng phòng ban cho 5 loại yêu cầu | **PASSED** |
| 14 | `tests/unit/test_request_intake.py::test_legacy_validator_adapter_works` | Xác nhận hàm `app.validator.validate_and_sanitize` hoạt động đúng hợp đồng | **PASSED** |
| 15 | `tests/integration/test_requests_and_tasks.py::test_create_all_five_request_types_and_idempotency` | Tạo đủ 5 loại yêu cầu (`INCIDENT`, `CHANGE`, `SERVICE_REQUEST`, `ONBOARDING`, `INTERNAL_TASK`) và gửi lặp cùng `Idempotency-Key` không tạo trùng | **PASSED** |
| 16 | `tests/integration/test_requests_and_tasks.py::test_clarification_flow_and_human_task_lifecycle` | Chuyển `NEEDS_INFORMATION -> OPEN` khi làm rõ và chạy trọn vẹn vòng đời đầu việc `OPEN -> CLAIMED -> BLOCKED -> CLAIMED -> COMPLETED` | **PASSED** |
| 17 | `tests/integration/test_requests_and_tasks.py::test_demo_seed_is_idempotent_across_repeated_runs` | Chạy `seed_demo_data` 2 lần liên tiếp bảo đảm đúng 6 phòng ban, 7 tài khoản, 9 trợ lý AI và 5 yêu cầu không trùng lặp | **PASSED** |
| 18 | `tests/security/test_customer_isolation.py::test_customer_isolation_and_internal_field_filtering` | Chặn khách hàng A xem yêu cầu của khách hàng B và việc nội bộ; ẩn hoàn toàn `INTERNAL_ONLY` và trường nhạy cảm; chặn sửa/xem đầu việc và cô lập tổ chức | **PASSED** |

---

## 4. Ghi chú cho Giai đoạn 4

- Giai đoạn 4 sẽ xây dựng phân hệ Trí tuệ AI (`app/modules/ai_intelligence/`): giao diện nhà cung cấp chung `LLMProvider`, bộ giả lập `MockLLMProvider` chạy không cần khóa API thật, bộ đọc câu lệnh theo phiên bản trong `prompts/`, nhóm 9 trợ lý AI có giới hạn (tối đa 4 việc song song, tối đa 2 vòng soát chéo, không lưu suy nghĩ ẩn) và ghi nhận chi phí gọi AI vào `llm_call_records`.
