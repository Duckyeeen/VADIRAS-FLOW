"""Danh mục đăng ký chính thức 12 loại bước quy trình và năng lực được phép."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .dsl.schemas import (
    AgentTaskConfig,
    AIAnalysisConfig,
    ApprovalConfig,
    ClassifyConfig,
    ConditionConfig,
    ConnectorActionConfig,
    EndConfig,
    HumanTaskConfig,
    NodeType,
    NotificationConfig,
    TriggerConfig,
    VerificationConfig,
    WaitEventConfig,
)

# Danh sách các năng lực kết nối và trợ lý AI đã đăng ký hợp lệ trong bản thử nghiệm
REGISTERED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "github:create_issue",
        "github:update_issue",
        "github:read_issue",
        "github:comment_issue",
        "github:assign_issue",
        "mock_github:create_issue",
        "mock_github:update_issue",
        "mock_github:read_issue",
        "mock_github:comment_issue",
        "swarm:orchestrate",
        "request:classify",
        "tech:analyze_dependencies",
        "ops:route_department",
        "security:scan_risk",
        "verification:read_back_evidence",
    }
)

# Các hành động nhạy cảm bị cấm tuyệt đối trong phạm vi bản thử nghiệm
FORBIDDEN_DEMO_ACTIONS: frozenset[str] = frozenset(
    {
        "deploy_production",
        "delete_user_data",
        "grant_admin_role",
        "modify_policy",
        "rotate_root_keys",
    }
)


@dataclass(frozen=True, slots=True)
class RegisteredNodeSpec:
    """Mô tả một loại bước đã đăng ký trong hệ thống kèm khuôn mẫu cấu hình riêng."""

    node_type: NodeType
    display_name: str
    description: str
    side_effect_class: str  # NONE | READ | WRITE
    config_model: type[BaseModel]
    default_output_keys: tuple[str, ...]


class NodeRegistry:
    """Sổ đăng ký tập trung 12 loại bước được phép xuất hiện trong sơ đồ quy trình."""

    def __init__(self) -> None:
        self._specs: dict[str, RegisteredNodeSpec] = {
            NodeType.TRIGGER.value: RegisteredNodeSpec(
                node_type=NodeType.TRIGGER,
                display_name="Khởi phát quy trình",
                description="Điểm bắt đầu duy nhất tiếp nhận dữ liệu yêu cầu vào quy trình.",
                side_effect_class="NONE",
                config_model=TriggerConfig,
                default_output_keys=("request_id", "request_type", "priority"),
            ),
            NodeType.CLASSIFY.value: RegisteredNodeSpec(
                node_type=NodeType.CLASSIFY,
                display_name="Phân loại & Chuẩn hóa",
                description="Kiểm tra phân loại loại yêu cầu và độ đầy đủ thông tin.",
                side_effect_class="READ",
                config_model=ClassifyConfig,
                default_output_keys=("request_type", "department_code", "missing_information"),
            ),
            NodeType.AI_ANALYSIS.value: RegisteredNodeSpec(
                node_type=NodeType.AI_ANALYSIS,
                display_name="Phân tích AI chuyên sâu",
                description="Điều phối chuyên viên AI đánh giá kỹ thuật, vận hành hoặc rủi ro.",
                side_effect_class="READ",
                config_model=AIAnalysisConfig,
                default_output_keys=("risk_level", "decision_summary", "findings"),
            ),
            NodeType.CONDITION.value: RegisteredNodeSpec(
                node_type=NodeType.CONDITION,
                display_name="Rẽ nhánh điều kiện",
                description="Phân nhánh luồng chạy dựa trên biểu thức điều kiện cấu trúc an toàn.",
                side_effect_class="NONE",
                config_model=ConditionConfig,
                default_output_keys=("branch_taken",),
            ),
            NodeType.AGENT_TASK.value: RegisteredNodeSpec(
                node_type=NodeType.AGENT_TASK,
                display_name="Tác vụ trợ lý AI",
                description="Giao một nhiệm vụ cụ thể trong phạm vi năng lực cho vai trò AI.",
                side_effect_class="READ",
                config_model=AgentTaskConfig,
                default_output_keys=("agent_output", "confidence"),
            ),
            NodeType.HUMAN_TASK.value: RegisteredNodeSpec(
                node_type=NodeType.HUMAN_TASK,
                display_name="Đầu việc nhân sự",
                description="Tạo đầu việc cho nhân viên hoặc phòng ban xử lý và nộp kết quả.",
                side_effect_class="WRITE",
                config_model=HumanTaskConfig,
                default_output_keys=("task_id", "completion_note", "evidence"),
            ),
            NodeType.APPROVAL.value: RegisteredNodeSpec(
                node_type=NodeType.APPROVAL,
                display_name="Cổng phê duyệt",
                description="Tạm dừng chờ người có thẩm quyền phê duyệt trước hành động rủi ro.",
                side_effect_class="NONE",
                config_model=ApprovalConfig,
                default_output_keys=("approval_id", "approval_status", "approved_by"),
            ),
            NodeType.CONNECTOR_ACTION.value: RegisteredNodeSpec(
                node_type=NodeType.CONNECTOR_ACTION,
                display_name="Thao tác bộ kết nối ngoài",
                description="Gọi hành động đã cấp phép ra hệ thống ngoài thông qua cổng kiểm soát.",
                side_effect_class="WRITE",
                config_model=ConnectorActionConfig,
                default_output_keys=("external_id", "external_url", "operation_id"),
            ),
            NodeType.WAIT_EVENT.value: RegisteredNodeSpec(
                node_type=NodeType.WAIT_EVENT,
                display_name="Chờ sự kiện phản hồi",
                description="Tạm chờ sự kiện từ webhook hoặc bộ quét đồng bộ trong giới hạn thời gian.",
                side_effect_class="NONE",
                config_model=WaitEventConfig,
                default_output_keys=("event_id", "event_payload"),
            ),
            NodeType.NOTIFICATION.value: RegisteredNodeSpec(
                node_type=NodeType.NOTIFICATION,
                display_name="Gửi thông báo",
                description="Gửi thông báo cập nhật cho nhân sự nội bộ hoặc khách hàng.",
                side_effect_class="WRITE",
                config_model=NotificationConfig,
                default_output_keys=("notification_sent",),
            ),
            NodeType.VERIFICATION.value: RegisteredNodeSpec(
                node_type=NodeType.VERIFICATION,
                display_name="Kiểm chứng đối chiếu ngược",
                description="Đọc ngược dữ liệu từ hệ thống đích và đánh giá bằng chứng hoàn tất.",
                side_effect_class="READ",
                config_model=VerificationConfig,
                default_output_keys=("verification_outcome", "evidence_refs"),
            ),
            NodeType.END.value: RegisteredNodeSpec(
                node_type=NodeType.END,
                display_name="Kết thúc quy trình",
                description="Điểm kết thúc chính thức kèm kết quả nghiệp vụ cuối cùng.",
                side_effect_class="NONE",
                config_model=EndConfig,
                default_output_keys=("final_outcome",),
            ),
        }

    def get_spec(self, node_type: str) -> RegisteredNodeSpec | None:
        """Lấy thông tin đăng ký của một loại bước theo mã `node_type`."""
        return self._specs.get(node_type.strip().upper())

    def list_types(self) -> list[str]:
        """Trả danh sách 12 mã loại bước đã đăng ký."""
        return list(self._specs.keys())

    def export_for_frontend(self) -> list[dict[str, Any]]:
        """Xuất toàn bộ danh mục 12 bước kèm JSON Schema cấu hình cho bảng vẽ React Flow."""
        exported: list[dict[str, Any]] = []
        for spec in self._specs.values():
            exported.append(
                {
                    "type": spec.node_type.value,
                    "display_name": spec.display_name,
                    "description": spec.description,
                    "side_effect_class": spec.side_effect_class,
                    "default_output_keys": list(spec.default_output_keys),
                    "config_schema": spec.config_model.model_json_schema(),
                }
            )
        return exported


default_node_registry = NodeRegistry()
