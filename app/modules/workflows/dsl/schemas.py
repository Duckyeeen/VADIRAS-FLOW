"""Khuôn mẫu chuẩn cho ngôn ngữ mô tả sơ đồ quy trình 12 loại bước."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Literal

from pydantic import Field

from app.core.schemas import ContractModel


class NodeType(str, Enum):
    """12 loại bước chính thức được phép sử dụng trong sơ đồ quy trình."""

    TRIGGER = "TRIGGER"
    CLASSIFY = "CLASSIFY"
    AI_ANALYSIS = "AI_ANALYSIS"
    CONDITION = "CONDITION"
    AGENT_TASK = "AGENT_TASK"
    HUMAN_TASK = "HUMAN_TASK"
    APPROVAL = "APPROVAL"
    CONNECTOR_ACTION = "CONNECTOR_ACTION"
    WAIT_EVENT = "WAIT_EVENT"
    NOTIFICATION = "NOTIFICATION"
    VERIFICATION = "VERIFICATION"
    END = "END"


class TriggerConfig(ContractModel):
    """Cấu hình cho bước khởi phát quy trình."""

    source: Literal["api", "manual", "webhook", "schedule"] = "api"


class ClassifyConfig(ContractModel):
    """Cấu hình cho bước chuẩn hóa và phân loại yêu cầu."""

    request_type: str = Field(min_length=2, max_length=64)
    require_completeness_check: bool = True


class AIAnalysisConfig(ContractModel):
    """Cấu hình cho bước gọi chuyên viên AI phân tích sâu."""

    roles: list[str] = Field(default_factory=lambda: ["request_analyst", "security_risk_analyst"], min_length=1)
    max_rounds: int = Field(default=1, ge=1, le=2)


class ConditionConfig(ContractModel):
    """Cấu hình cho bước rẽ nhánh dựa trên biểu thức an toàn."""

    default_branch_label: str = Field(default="mac_dinh", min_length=1, max_length=64)


class AgentTaskConfig(ContractModel):
    """Cấu hình giao một nhiệm vụ cho vai trò trợ lý AI cụ thể."""

    role_code: str = Field(min_length=2, max_length=64)
    capability: str = Field(min_length=2, max_length=128)


class HumanTaskConfig(ContractModel):
    """Cấu hình đầu việc giao cho phòng ban hoặc nhân sự xử lý."""

    department_code: str = Field(min_length=2, max_length=64)
    title: str = Field(min_length=3, max_length=200)
    instructions: str = Field(default="", max_length=2_000)


class ApprovalConfig(ContractModel):
    """Cấu hình cổng phê duyệt bắt buộc trước thao tác rủi ro."""

    required_role: str = Field(min_length=2, max_length=64)
    approval_timeout_hours: int = Field(default=24, ge=1, le=720)
    reason_template: str = Field(default="Phê duyệt thực thi bước nhạy cảm.", max_length=500)


class ConnectorActionConfig(ContractModel):
    """Cấu hình gọi hành động ra bộ kết nối ngoài thông qua cổng kiểm soát."""

    connector: str = Field(min_length=2, max_length=64)
    action: str = Field(min_length=2, max_length=64)
    target_repository: str = Field(default="", max_length=200)
    parameters: dict[str, Any] = Field(default_factory=dict)


class WaitEventConfig(ContractModel):
    """Cấu hình bước tạm chờ phản hồi từ webhook hoặc sự kiện ngoài."""

    event_source: str = Field(min_length=2, max_length=64)
    event_type: str = Field(min_length=2, max_length=64)
    timeout_hours: int = Field(default=48, ge=1, le=720)


class NotificationConfig(ContractModel):
    """Cấu hình bước gửi thông báo nội bộ hoặc cho khách hàng."""

    audience: Literal["INTERNAL_ONLY", "CUSTOMER_VISIBLE"] = "INTERNAL_ONLY"
    channel: Literal["in_app", "sse", "webhook"] = "in_app"
    template_code: str = Field(min_length=2, max_length=128)


class VerificationConfig(ContractModel):
    """Cấu hình bước kiểm chứng đối chiếu ngược bằng chứng trước khi kết thúc."""

    evaluator_type: Literal["DETERMINISTIC_FIRST", "HYBRID"] = "DETERMINISTIC_FIRST"
    require_read_back: bool = True
    postconditions: list[str] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)
    freshness_seconds: int = Field(default=300, ge=10, le=86_400)


class EndConfig(ContractModel):
    """Cấu hình điểm kết thúc chính thức của quy trình."""

    expected_outcome: Literal["VERIFIED", "PARTIALLY_VERIFIED"] = "VERIFIED"


class RetryPolicySpec(ContractModel):
    """Chính sách thử lại có giới hạn cho từng bước (tối đa 3 lần)."""

    max_attempts: int = Field(default=3, ge=1, le=3)
    initial_interval_seconds: int = Field(default=5, ge=1, le=300)
    backoff_coefficient: float = Field(default=2.0, ge=1.0, le=5.0)


class WorkflowLimitsSpec(ContractModel):
    """Các giới hạn an toàn tài nguyên của toàn bộ sơ đồ quy trình."""

    max_nodes: int = Field(default=30, ge=2, le=50)
    max_duration_seconds: int = Field(default=86_400, ge=30, le=2_592_000)
    max_retries: int = Field(default=3, ge=0, le=5)
    max_parallelism: int = Field(default=4, ge=1, le=10)
    max_estimated_cost_usd: float = Field(default=5.0, ge=0.0, le=100.0)
    max_replans: int = Field(default=2, ge=0, le=5)


class WorkflowNodeSpec(ContractModel):
    """Định nghĩa đầy đủ một bước trong sơ đồ quy trình JSON."""

    id: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1_000)
    config: dict[str, Any] = Field(default_factory=dict)
    input_mapping: dict[str, str] = Field(default_factory=dict)
    output_keys: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=300, ge=5, le=86_400)
    retry_policy: RetryPolicySpec = Field(default_factory=RetryPolicySpec)
    required_capabilities: list[str] = Field(default_factory=list)
    resource_scope: str | None = Field(default=None, max_length=255)
    risk_class: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"
    estimated_cost_usd: float = Field(default=0.01, ge=0.0, le=50.0)


class WorkflowEdgeSpec(ContractModel):
    """Định nghĩa cạnh nối giữa hai bước kèm điều kiện rẽ nhánh dạng cấu trúc an toàn."""

    id: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=64)
    condition: dict[str, Any] | str | None = None
    label: str | None = Field(default=None, max_length=120)


class WorkflowGraphSpec(ContractModel):
    """Khuôn mẫu hoàn chỉnh của một sơ đồ quy trình JSON có phiên bản."""

    workflow_id: str = Field(min_length=2, max_length=128)
    version: int = Field(default=1, ge=1)
    name: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=2_000)
    domain_pack: str = Field(default="enterprise_core", max_length=64)
    request_type: str = Field(min_length=2, max_length=64)
    input_schema: list[str] = Field(
        default_factory=lambda: ["request_id", "title", "sanitized_description", "request_type", "priority"]
    )
    output_schema: list[str] = Field(default_factory=lambda: ["verification_outcome", "evidence_refs"])
    nodes: list[WorkflowNodeSpec] = Field(default_factory=list)
    edges: list[WorkflowEdgeSpec] = Field(default_factory=list)
    limits: WorkflowLimitsSpec = Field(default_factory=WorkflowLimitsSpec)
    policy_requirements: list[str] = Field(default_factory=list)
    approval_requirements: list[str] = Field(default_factory=list)


def compute_graph_content_hash(graph_data: dict[str, Any]) -> str:
    """Tính mã băm SHA-256 cố định đại diện cho toàn bộ nội dung sơ đồ quy trình."""
    canonical = json.dumps(graph_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
