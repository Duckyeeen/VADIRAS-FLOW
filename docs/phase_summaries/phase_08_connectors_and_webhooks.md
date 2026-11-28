# Tổng kết Giai đoạn 8 — Kết nối GitHub App, Bộ giả lập GitHub, Webhook HMAC-SHA256 & Quét đồng bộ dự phòng

- **Trạng thái:** Đã hoàn thành
- **Thời gian hoàn tất:** 27/11/2026
- **Mục tiêu:** Xây dựng phân hệ kết nối hệ thống ngoài (`app/modules/connectors/`) với 4 bảng CSDL mới (bản nâng cấp `0006`, nâng tổng số lên 37 bảng), giao diện chuẩn 6 phương thức cho cả `MockGitHubConnector` và `GitHubAppConnector` (ký JWT RS256, giữ thẻ cài đặt ngắn hạn trên RAM, giới hạn kho cho phép), lớp điều phối chống trùng lặp giao dịch `ConnectorOperationExecutor`, bộ tiếp nhận webhook kiểm tra chữ ký thô `X-Hub-Signature-256` + chống trùng `X-GitHub-Delivery`, bộ quét đồng bộ dự phòng `GitHubReconciler`, 5 tuyến API `/api/v1/connectors*` & `/api/v1/webhooks/github`, cùng việc nối vào `RuntimeActivities` và `app/ticket_connector.py`.

---

## 1. Danh sách tệp đã tạo mới và chỉnh sửa

| Đường dẫn tệp | Hành động | Vai trò / Nội dung chính |
|---|---|---|
| [app/core/config.py](file:///c:/GitHub/VADIRAS-FLOW/app/core/config.py) | Cập nhật | Bổ sung cấu hình `github_app_id`, `github_installation_id`, `github_private_key_path`, `github_api_base_url`, `github_webhook_secret`, `github_allowed_repos` và hàm tách danh sách kho hợp lệ |
| [alembic/env.py](file:///c:/GitHub/VADIRAS-FLOW/alembic/env.py) | Cập nhật | Nạp mô hình phân hệ `connectors` để Alembic quản lý đầy đủ 37 bảng |
| [0006_connectors_and_webhooks.py](file:///c:/GitHub/VADIRAS-FLOW/alembic/versions/0006_connectors_and_webhooks.py) | Tạo mới | Bản nâng cấp CSDL tạo 4 bảng: `connector_installations`, `connector_resource_scopes`, `connector_operation_records`, `webhook_inbox` |
| [app/modules/connectors/__init__.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/connectors/__init__.py) | Tạo mới | Khởi tạo gói phân hệ kết nối hệ thống ngoài |
| [app/modules/connectors/models.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/connectors/models.py) | Tạo mới | 4 mô hình bảng SQLAlchemy 2 cho cài đặt, phạm vi kho, nhật ký chống trùng giao dịch và hộp thư webhook |
| [app/modules/connectors/base.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/connectors/base.py) | Tạo mới | Giao diện chuẩn `BaseConnector`, phân loại lỗi `ConnectorTransientError`/`ConnectorPermanentError` và danh mục 5 hành động GitHub được phép |
| [app/modules/connectors/mock_github.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/connectors/mock_github.py) | Tạo mới | `MockGitHubConnector` lưu trữ Issue trên RAM, chặn kho ngoài phạm vi, mô phỏng lỗi tạm thời/vĩnh viễn/sai lệch đọc ngược |
| [app/modules/connectors/github_app.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/connectors/github_app.py) | Tạo mới | `GitHubAppConnector` ký JWT RS256, đổi và lưu đệm thẻ cài đặt ngắn hạn duy nhất trên RAM, gọi GitHub REST API qua `httpx` |
| [app/modules/connectors/factory.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/connectors/factory.py) | Tạo mới | Hàm `build_github_connector` chọn bộ giả lập hoặc GitHub App theo cấu hình hệ thống |
| [app/modules/connectors/idempotency.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/connectors/idempotency.py) | Tạo mới | `ConnectorOperationExecutor` kiểm tra và ghi nhận `connector_operation_records` bảo đảm thử lại không tạo 2 Issue trùng |
| [app/modules/connectors/webhook_inbox.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/connectors/webhook_inbox.py) | Tạo mới | Xác thực chữ ký thô `X-Hub-Signature-256`, chống trùng theo `X-GitHub-Delivery`, lọc phạm vi kho và gửi tín hiệu đánh thức quy trình Temporal |
| [app/modules/connectors/reconciler.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/connectors/reconciler.py) | Tạo mới | `GitHubReconciler` đọc ngược trạng thái Issue để đồng bộ bù các sự kiện webhook bị trễ hoặc thất lạc |
| [app/modules/connectors/schemas.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/connectors/schemas.py) | Tạo mới | Khuôn mẫu dữ liệu API cho bộ kết nối, cài đặt, trạng thái, biên nhận webhook và báo cáo đối soát |
| [app/modules/connectors/repository.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/connectors/repository.py) | Tạo mới | Truy vấn cài đặt, thống kê giao dịch và hộp thư webhook theo `organization_id` |
| [app/modules/connectors/service.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/connectors/service.py) | Tạo mới | Xử lý nghiệp vụ đăng ký cài đặt (chặn ký tự `*`), xem trạng thái và chạy đối soát dự phòng |
| [app/modules/connectors/router.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/connectors/router.py) | Tạo mới | 5 tuyến API: `GET /connectors`, `POST /connectors/github/installations`, `GET /connectors/github/status`, `POST /webhooks/github`, `POST /connectors/github/reconcile` |
| [app/modules/runtime/activities.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/runtime/activities.py) | Cập nhật | Nối `ToolBroker` với `ConnectorOperationExecutor` và `BaseConnector`, phân loại chuẩn lỗi `TRANSIENT` vs `PERMANENT` |
| [app/ticket_connector.py](file:///c:/GitHub/VADIRAS-FLOW/app/ticket_connector.py) | Cập nhật | Hiện thực hóa hàm `create_ticket` dựa trên bộ kết nối GitHub chuẩn, bỏ `NotImplementedError` |
| [app/main.py](file:///c:/GitHub/VADIRAS-FLOW/app/main.py) | Cập nhật | Gắn bộ định tuyến `connectors` và khởi tạo `app.state.github_connector` |
| [test_migrations_and_health.py](file:///c:/GitHub/VADIRAS-FLOW/tests/integration/test_migrations_and_health.py) | Cập nhật | Mở rộng danh sách kiểm chứng đủ 37 bảng sau `upgrade head` -> `downgrade base` -> `upgrade head` |
| [test_connectors_and_webhooks.py](file:///c:/GitHub/VADIRAS-FLOW/tests/unit/test_connectors_and_webhooks.py) | Tạo mới | 3 bài kiểm thử đơn vị cho `MockGitHubConnector`, `GitHubAppConnector` (JWT RS256 + `httpx.MockTransport`) và `app.ticket_connector` |
| [test_connectors_and_webhooks_api.py](file:///c:/GitHub/VADIRAS-FLOW/tests/integration/test_connectors_and_webhooks_api.py) | Tạo mới | 2 bài kiểm thử tích hợp cho API đăng ký/trạng thái, cô lập tổ chức, chống trùng giao dịch, chữ ký HMAC webhook và bộ quét đối soát |

---

## 2. Kiểm thử & Kết quả chi tiết

- **Có chạy kiểm thử tự động hay không:** **Có** (54 bài kiểm thử: 5 bài mới của Giai đoạn 8 + 49 bài hồi quy Giai đoạn 2–7).
- **Lệnh kiểm tra cú pháp:** `python -m py_compile ...` trên toàn bộ 22 tệp mới/chỉnh sửa -> **Đạt** (mã thoát `0`).
- **Lệnh kiểm thử đã chạy:** `python -m pytest -v`
- **Tổng kết kết quả:** **54/54 bài kiểm thử ĐẠT (`54 passed in 67.98s`, 0 lỗi, 0 cảnh báo, mã thoát `0`)**.

| STT | Nhóm / Tên bài kiểm thử | Nội dung kiểm chứng | Kết quả thực tế |
|---|---|---|---|
| 1–49 | Bộ kiểm thử Giai đoạn 2–7 (49 bài) | Hồi quy đầy đủ 37 bảng Alembic, Xác thực, Yêu cầu, AI, DSL 7 tầng, Phê duyệt 7 yếu tố và Temporal Runtime | **49/49 PASSED** |
| 50 | `tests/unit/test_connectors_and_webhooks.py::test_mock_github_connector_lifecycle_errors_and_verification` | 5 hành động giả lập, lỗi tạm thời rồi thành công, chống trùng lặp, đọc ngược đối chiếu và chặn kho ngoài phạm vi (`REPO_NOT_ALLOWED`) | **PASSED** |
| 51 | `tests/unit/test_connectors_and_webhooks.py::test_github_app_connector_jwt_token_cache_and_http_error_classification` | Ký JWT `RS256`, lưu đệm thẻ cài đặt trên RAM (chỉ đổi thẻ 1 lần), tạo/đọc Issue qua HTTP giả lập và phân loại 503 (`Transient`) vs 403 (`Permanent`) | **PASSED** |
| 52 | `tests/unit/test_connectors_and_webhooks.py::test_legacy_ticket_connector_creates_ticket_cleanly` | Xác nhận `app.ticket_connector.create_ticket` hoạt động chuẩn | **PASSED** |
| 53 | `tests/integration/test_connectors_and_webhooks_api.py::test_connector_installation_status_and_tenant_isolation` | Đăng ký cài đặt, chặn phạm vi `*` (`422`), xem trạng thái, chặn khách hàng (`403`) và cô lập dữ liệu giữa Tổ chức A/B | **PASSED** |
| 54 | `tests/integration/test_connectors_and_webhooks_api.py::test_idempotent_operation_webhook_hmac_dedup_and_reconciler` | Gửi trùng `idempotency_key` chỉ tạo đúng 1 Issue & 1 bản ghi giao dịch; thiếu `X-GitHub-Delivery` bị `422`; sai chữ ký HMAC bị `401`; trùng delivery bị đánh dấu `duplicate=True`; kho lạ bị `IGNORED`; `/reconcile` đồng bộ chuẩn trạng thái | **PASSED** |

---

## 3. Ghi chú cho Giai đoạn 9

- Giai đoạn 9 (**Cột mốc Chạy thử Xuyên suốt Đầu–Cuối cho Sự cố & Yêu cầu thay đổi**) sẽ triển khai **Phân hệ Xác minh Bằng chứng & Nhật ký Kiểm toán chỉ thêm mới (`app/modules/verification/`)**:
  - Tạo 4 bảng CSDL qua bản nâng cấp tiếp theo: `verification_runs`, `execution_evidence`, `audit_logs`, `audit_log_entries` (hoặc mô hình kiểm toán chỉ cho phép thêm mới).
  - Chấm đủ 4 trạng thái xác minh (`VERIFIED`, `PARTIALLY_VERIFIED`, `FAILED`, `UNVERIFIED`) dựa trên bằng chứng đọc ngược thực tế + kiểm tra độ mới của dữ liệu (`freshness_seconds`), cập nhật `business_outcome` của `Request`, nối vào bước `VERIFICATION` của `RuntimeActivities` và kiểm thử toàn trình đầu–cuối cho `INCIDENT` và `CHANGE`.
