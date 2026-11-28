# VADIRAS FLOW — Nền tảng Điều phối Quy trình Doanh nghiệp Hỗ trợ AI

**VADIRAS FLOW** là phần xử lý nền (Backend) điều phối các quy trình xử lý yêu cầu công việc doanh nghiệp với sự hỗ trợ của nhóm trợ lý AI theo nguyên tắc kiến trúc cốt lõi:

> **AI đề xuất — Bộ kiểm soát quy tắc cấp phép — Temporal thực thi bền vững — Bộ máy xác minh chứng minh bằng bằng chứng thực tế.**

---

## Kiến trúc Tổng quan & Các Phân hệ Chính

- **Xác thực & Cô lập Tổ chức (`app/modules/identity/`):** Đăng nhập JWT ngắn hạn, xoay vòng thẻ làm mới, mã hóa Argon2id, kiểm tra lại quyền mới nhất từ CSDL và tách biệt hoàn toàn giữa nhân viên nội bộ với khách hàng (`CUSTOMER_CONTACT`).
- **Tiếp nhận Yêu cầu 5 Nhóm (`app/modules/requests/`):** Hỗ trợ `INCIDENT`, `CHANGE`, `SERVICE_REQUEST`, `ONBOARDING`, `INTERNAL_TASK`; che giấu PII; gắn cờ nghi ngờ chèn lệnh; khóa chống trùng lặp `Idempotency-Key` và quản lý đầu việc nhân sự.
- **Lớp AI Độc lập Nhà cung cấp & Nhóm 9 Trợ lý (`app/modules/ai_intelligence/`):** Giao diện `LLMProvider` hỗ trợ `MockLLMProvider` (mặc định không cần API key) và `OpenAICompatibleProvider`, sửa lỗi JSON có giới hạn, điều phối tối đa 4 chuyên viên song song và 2 vòng phản biện, không lưu suy nghĩ ẩn (`reasoning_trace`).
- **Ngôn ngữ Mô tả Quy trình 12 Bước & Kiểm định 7 Tầng (`app/modules/workflows/`):** Đọc điều kiện rẽ nhánh cấu trúc JSON (tuyệt đối không dùng `eval`), chấm điểm phương án và khóa bất biến phiên bản `PUBLISHED` bằng mã băm SHA-256.
- **Kiểm soát Quản trị & Phê duyệt 7 Yếu tố (`app/modules/governance/`):** Phân tầng rủi ro (`LOW`/`MEDIUM`/`HIGH`/`CRITICAL`), khóa lệnh phê duyệt theo phiên bản quy trình + mã bước + mã băm tham số + phạm vi tài nguyên + chính sách, qua cổng tập trung `ToolBroker` và `ExecutionGuard`.
- **Bộ chạy Bền vững Temporal (`app/modules/runtime/`):** Quy trình thuần xác định `RequestOrchestrationWorkflow`, chống trùng lặp thao tác, tạm dừng/tiếp tục/hủy bỏ, và giới hạn tối đa 2 lần lập lại không tự nâng quyền.
- **Kết nối GitHub App, Giả lập & Webhook (`app/modules/connectors/`):** Hỗ trợ `MockGitHubConnector` và `GitHubAppConnector` (JWT RS256 + thẻ ngắn hạn chỉ giữ trên RAM), kiểm tra chữ ký thô `X-Hub-Signature-256`, chống trùng theo `X-GitHub-Delivery` và bộ quét đồng bộ dự phòng.
- **Xác minh Bằng chứng & Kiểm toán (`app/modules/verification/`):** Đọc ngược tài nguyên đích chấm đủ 4 trạng thái (`VERIFIED`, `PARTIALLY_VERIFIED`, `FAILED`, `UNVERIFIED`) kèm độ mới dữ liệu và ghi nhật ký kiểm toán chỉ được phép thêm mới.
- **Bộ nhớ Ngữ nghĩa `pgvector`, Outbox, SSE & 7 API Thống kê (`app/modules/memory/`, `app/modules/observability/`):** Tìm kiếm tri thức đã kiểm chứng theo quyền xem, hàng đợi sự kiện `outbox_events`, luồng trực tiếp SSE, đánh giá SLA và 7 tuyến `/api/v1/metrics/*`.

---

## Khởi chạy & Kiểm thử Nhanh

### Chạy bằng Docker Compose (6 dịch vụ)

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

Sau khi khởi động thành công, truy cập:
- Tài liệu API tương tác: `http://localhost:8000/docs`
- Kiểm tra sức khỏe hệ thống: `http://localhost:8000/health/ready`
- Giao diện Temporal UI: `http://localhost:8080`

### Chạy & Kiểm thử Cục bộ (Python 3.11+)

```powershell
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m scripts.seed_demo
python -m pytest -v
```

---

## Tài liệu Tham khảo Dự án

- [Kế hoạch Triển khai Backend & 7 Sơ đồ Kiến trúc](file:///c:/GitHub/VADIRAS-FLOW/docs/BACKEND_IMPLEMENTATION_PLAN.md)
- [Sổ tay Vận hành, Kịch bản Trình diễn & Cấu hình GitHub App](file:///c:/GitHub/VADIRAS-FLOW/docs/DEMO_RUNBOOK.md)
- [Thư mục Báo cáo Tổng kết Từng Giai đoạn (Giai đoạn 1–11)](file:///c:/GitHub/VADIRAS-FLOW/docs/phase_summaries/README.md)
