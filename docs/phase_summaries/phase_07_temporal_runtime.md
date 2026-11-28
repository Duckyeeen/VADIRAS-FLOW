# Tổng kết Giai đoạn 7 — Bộ chạy Quy trình Bền vững Temporal & Chống trùng lặp

- **Trạng thái:** Đã hoàn thành
- **Thời gian hoàn tất:** 27/11/2026
- **Mục tiêu:** Cài đặt thư viện `temporalio` (`1.37.0`) và xây dựng trọn vẹn phân hệ thực thi quy trình bền vững (`app/modules/runtime/`), bao gồm quy trình thuần xác định `RequestOrchestrationWorkflow` (tách biệt hoàn toàn khỏi I/O để bảo đảm phát lại lịch sử an toàn), các tác vụ Temporal cho 12 loại bước quy trình, cổng kết nối `TemporalRuntimeGateway` kèm tiến trình worker độc lập, cơ chế máy trạng thái + khóa chống trùng lặp + giới hạn tối đa 2 lần lập lại phương án không tự nâng quyền, 7 tuyến API `/api/v1/workflow-runs*` và móc nối tín hiệu phê duyệt trực tiếp từ phân hệ `governance`.

---

## 1. Danh sách tệp đã tạo mới và chỉnh sửa

| Đường dẫn tệp | Hành động | Vai trò / Nội dung chính |
|---|---|---|
| [requirements.txt](file:///c:/GitHub/VADIRAS-FLOW/requirements.txt) | Cập nhật | Bổ sung và khóa phiên bản thư viện `temporalio>=1.7,<2.0` (`1.37.0`) |
| [app/modules/runtime/__init__.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/runtime/__init__.py) | Tạo mới | Khởi tạo gói phân hệ điều phối quy trình bền vững Temporal |
| [app/modules/runtime/contracts.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/runtime/contracts.py) | Tạo mới | Các khuôn mẫu dữ liệu `@dataclass` thuần thư viện chuẩn truyền giữa quy trình và tác vụ Temporal |
| [app/modules/runtime/state_machine.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/runtime/state_machine.py) | Tạo mới | Máy trạng thái lượt chạy/bước chạy, phân loại lỗi (`TRANSIENT` vs `PERMISSION`/`BUSINESS`/`PERMANENT`), khóa chống trùng lặp, trần 2 lần lập lại và `compute_replan_delta` phát hiện leo thang rủi ro/phạm vi |
| [app/modules/runtime/activities.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/runtime/activities.py) | Tạo mới | 3 Temporal Activities (`update_run_status_activity`, `persist_node_state_activity`, `execute_node_activity`) xử lý I/O CSDL, gọi AI, tạo đầu việc nhân sự, tạo lệnh phê duyệt 7 yếu tố và gọi `ToolBroker` cho cả 12 loại bước |
| [app/modules/runtime/workflows.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/runtime/workflows.py) | Tạo mới | Quy trình thuần xác định `RequestOrchestrationWorkflow` điều phối DAG theo phụ thuộc, chạy song song có giới hạn, bỏ qua nhánh không chọn, chờ tín hiệu duyệt/sự kiện/nhân sự kèm hết hạn, tạm dừng/tiếp tục/hủy |
| [app/modules/runtime/temporal_client.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/runtime/temporal_client.py) | Tạo mới | `TemporalRuntimeGateway` kết nối máy chủ Temporal, kiểm tra sức khỏe và hỗ trợ chế độ ghi nhận cục bộ an toàn khi chưa bật dịch vụ Temporal |
| [app/modules/runtime/worker.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/runtime/worker.py) | Tạo mới | Điểm khởi chạy tiến trình Worker độc lập (`python -m app.modules.runtime.worker`) |
| [app/modules/runtime/schemas.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/runtime/schemas.py) | Tạo mới | Khuôn mẫu dữ liệu vào/ra API cho lượt chạy, lịch sử từng bước và đề xuất lập lại |
| [app/modules/runtime/repository.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/runtime/repository.py) | Tạo mới | Truy vấn `workflow_runs`, `workflow_node_runs`, `workflow_replan_proposals` có lọc chặt theo `organization_id` |
| [app/modules/runtime/service.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/runtime/service.py) | Tạo mới | Tầng nghiệp vụ khởi phát lượt chạy từ bản `PUBLISHED`, chống trùng theo `Idempotency-Key`, tạm dừng/tiếp tục/hủy và lập lại sơ đồ giữ nguyên bản cũ bất biến |
| [app/modules/runtime/router.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/runtime/router.py) | Tạo mới | 7 tuyến API: `POST /workflow-runs`, `GET /workflow-runs`, `GET /workflow-runs/{run_id}`, `POST .../pause`, `POST .../resume`, `POST .../cancel`, `POST .../replan` |
| [app/modules/governance/router.py](file:///c:/GitHub/VADIRAS-FLOW/app/modules/governance/router.py) | Cập nhật | Sau khi lưu quyết định phê duyệt/từ chối vào CSDL, tự động gửi tín hiệu `submit_approval_decision` tới lượt chạy Temporal đang chờ |
| [app/main.py](file:///c:/GitHub/VADIRAS-FLOW/app/main.py) | Cập nhật | Gắn bộ định tuyến `runtime`, khởi tạo `TemporalRuntimeGateway` và cập nhật `/health/ready` kiểm tra thực tế trạng thái Temporal (`up`/`disconnected`) |
| [test_runtime_state_and_replan.py](file:///c:/GitHub/VADIRAS-FLOW/tests/unit/test_runtime_state_and_replan.py) | Tạo mới | 5 bài kiểm thử đơn vị cho máy trạng thái, phân loại lỗi, khóa chống trùng lặp, trần 2 lần lập lại và `compute_replan_delta` |
| [test_temporal_workflow.py](file:///c:/GitHub/VADIRAS-FLOW/tests/integration/test_temporal_workflow.py) | Tạo mới | 4 bài kiểm thử tích hợp với `WorkflowEnvironment.start_time_skipping` thật: DAG rẽ nhánh, tắt bật Worker vẫn giữ tiến độ chờ duyệt, quá hạn/hủy, thử lại lỗi tạm thời vs chặn thử lại lỗi quyền |
| [test_workflow_runs_api.py](file:///c:/GitHub/VADIRAS-FLOW/tests/integration/test_workflow_runs_api.py) | Tạo mới | 2 bài kiểm thử tích hợp API `/api/v1/workflow-runs`: chặn bản chưa `PUBLISHED`, chống trùng `Idempotency-Key`, tạm dừng/tiếp tục/hủy, lập lại giữ bất biến bản cũ + tự dừng duyệt khi nâng phạm vi, cô lập khách hàng/tổ chức |

---

## 2. Kiểm thử & Kết quả chi tiết

- **Có chạy kiểm thử tự động hay không:** **Có** (49 bài kiểm thử: 11 bài mới của Giai đoạn 7 + 38 bài hồi quy Giai đoạn 2–6).
- **Lệnh kiểm tra cú pháp:** `python -m py_compile ...` trên toàn bộ 16 tệp mới/chỉnh sửa -> **Đạt** (mã thoát `0`).
- **Lệnh kiểm thử đã chạy:** `python -m pytest -v`
- **Tổng kết kết quả:** **49/49 bài kiểm thử ĐẠT (`49 passed in 96.09s`, 0 lỗi, 0 cảnh báo, mã thoát `0`)**.

| STT | Nhóm / Tên bài kiểm thử | Nội dung kiểm chứng | Kết quả thực tế |
|---|---|---|---|
| 1–38 | Bộ kiểm thử Giai đoạn 2–6 (38 bài) | Hồi quy toàn bộ Xác thực, Yêu cầu, AI/Swarm, DSL 7 tầng, Quản trị/Phê duyệt và cô lập khách hàng | **38/38 PASSED** |
| 39 | `tests/unit/test_runtime_state_and_replan.py::test_run_state_transitions_and_terminal_locks` | Phép chuyển trạng thái hợp lệ và chặn tác động lên lượt chạy đã kết thúc (`INVALID_RUN_STATE_TRANSITION`) | **PASSED** |
| 40 | `tests/unit/test_runtime_state_and_replan.py::test_error_classification_retry_policy_and_idempotency_key` | Chỉ lỗi tạm thời `TRANSIENT` được thử lại; sinh khóa chống trùng lặp cố định theo lượt chạy/bước/lần thử | **PASSED** |
| 41 | `tests/unit/test_runtime_state_and_replan.py::test_replan_limit_enforced_at_hard_cap_2` | Khóa cứng giới hạn tối đa 2 lần lập lại phương án (`REPLAN_LIMIT_EXCEEDED`) | **PASSED** |
| 42 | `tests/unit/test_runtime_state_and_replan.py::test_compute_replan_delta_detects_no_escalation_on_safe_adjustment` | Điều chỉnh mô tả hoặc thêm thông báo nội bộ không bị đánh dấu tăng rủi ro | **PASSED** |
| 43 | `tests/unit/test_runtime_state_and_replan.py::test_compute_replan_delta_flags_scope_risk_and_approval_removal` | Mở rộng `resource_scope`, tăng `risk_class` hoặc xóa cổng `APPROVAL` đều bật `risk_escalated=True` | **PASSED** |
| 44 | `tests/integration/test_temporal_workflow.py::test_temporal_dag_branching_parallelism_and_skip_propagation` | Chạy đồ thị thực trên Temporal Test Server: nhánh không khớp điều kiện tự chuyển `SKIPPED`, truy vấn `get_progress` chính xác | **PASSED** |
| 45 | `tests/integration/test_temporal_workflow.py::test_temporal_approval_wait_survives_worker_restart` | Tạm dừng ở `WAITING_APPROVAL`, tắt hoàn toàn Worker cũ, gửi tín hiệu phê duyệt, bật Worker mới phát lại lịch sử từ đầu và chạy qua `ExecutionGuard` tới `COMPLETED` | **PASSED** |
| 46 | `tests/integration/test_temporal_workflow.py::test_temporal_approval_timeout_pause_resume_and_cancel` | Tua nhanh thời gian kiểm chứng tự động `TIMED_OUT` khi quá hạn duyệt và hủy ngang thành `CANCELLED` | **PASSED** |
| 47 | `tests/integration/test_temporal_workflow.py::test_temporal_retry_for_transient_error_vs_non_retryable_permission_error` | Lỗi tạm thời thử lại đủ 3 lần rồi thành công; lỗi quyền `PERMISSION` dừng ngay sau đúng 1 lần thử | **PASSED** |
| 48 | `tests/integration/test_workflow_runs_api.py::test_workflow_run_requires_published_version_and_deduplicates_idempotency_key` | Từ chối bản chưa `PUBLISHED` (`409`); khởi chạy thành công bản `PUBLISHED` (`202`); gửi lại cùng `Idempotency-Key` trả về đúng lượt chạy cũ | **PASSED** |
| 49 | `tests/integration/test_workflow_runs_api.py::test_workflow_run_controls_replan_safety_and_tenant_isolation` | Cô lập khách hàng (`403`) và tổ chức khác (`404`); tạm dừng/tiếp tục/hủy; lập lại lần 1 giữ nguyên bản gốc; lập lại lần 2 mở rộng kho ngoài tự chuyển `WAITING_APPROVAL` + sinh `ApprovalRequest`; lần 3 bị chặn `409` | **PASSED** |

---

## 3. Ghi chú cho Giai đoạn 8

- Các bảng `workflow_runs`, `workflow_node_runs`, `workflow_replan_proposals` đã được tạo từ bản nâng cấp `0004`, nên Giai đoạn 7 tái sử dụng trực tiếp mà không sinh bảng trùng lặp.
- Giai đoạn 8 sẽ triển khai **Kết nối GitHub App, Bộ giả lập GitHub, Webhook bảo mật (`X-Hub-Signature-256` + `X-GitHub-Delivery`), bảng `connector_operation_records` + `webhook_inbox` (bản nâng cấp `0006`) và bộ quét đồng bộ dự phòng**, đồng thời gắn vào `ToolBroker` và `app/ticket_connector.py`.
