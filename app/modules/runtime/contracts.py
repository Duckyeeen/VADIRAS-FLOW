"""Các cấu trúc dữ liệu thuần thư viện chuẩn truyền giữa quy trình Temporal và tác vụ I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowRunInput:
    """Thông tin đầu vào cố định khi khởi phát một lượt chạy quy trình trên Temporal."""

    organization_id: str
    workflow_run_id: str
    request_id: str
    workflow_version_id: str
    workflow_content_hash: str
    graph_json: dict[str, Any]
    trigger_input: dict[str, Any]
    started_by_user_id: str
    started_by_membership_id: str
    max_parallelism: int = 4
    approval_timeout_seconds: int = 86_400
    event_timeout_seconds: int = 86_400


@dataclass
class RunStatusUpdateInput:
    """Dữ liệu cập nhật trạng thái tổng thể của một lượt chạy quy trình vào cơ sở dữ liệu."""

    organization_id: str
    workflow_run_id: str
    status: str
    started_at_iso: str | None = None
    finished_at_iso: str | None = None
    result_summary: dict[str, Any] | None = None


@dataclass
class NodeStatusUpdateInput:
    """Dữ liệu lưu vết trạng thái từng bước của lượt chạy vào bảng `workflow_node_runs`."""

    organization_id: str
    workflow_run_id: str
    node_id: str
    node_type: str
    status: str
    attempt: int = 1
    idempotency_key: str = ""
    input_summary: dict[str, Any] | None = None
    output_summary: dict[str, Any] | None = None
    error_class: str | None = None
    error_message: str | None = None
    started_at_iso: str | None = None
    finished_at_iso: str | None = None


@dataclass
class NodeExecutionInput:
    """Thông số truyền cho tác vụ Temporal khi thực thi một bước cụ thể trong sơ đồ."""

    organization_id: str
    workflow_run_id: str
    request_id: str
    workflow_version_id: str
    node_id: str
    node_type: str
    node_name: str
    node_config: dict[str, Any]
    resource_scope: str | None
    risk_class: str
    estimated_cost_usd: float
    resolved_inputs: dict[str, Any]
    idempotency_key: str
    attempt: int
    started_by_user_id: str
    started_by_membership_id: str
    approved_approval_id: str | None = None


@dataclass
class NodeExecutionOutput:
    """Kết quả trả về từ tác vụ thực thi bước, kèm cờ yêu cầu chờ tín hiệu ngoài nếu cần."""

    node_id: str
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    requires_wait: bool = False
    wait_kind: str | None = None  # "APPROVAL" | "EVENT" | "HUMAN_TASK"
    approval_id: str | None = None
    human_task_id: str | None = None


@dataclass
class ApprovalSignalPayload:
    """Tín hiệu phê duyệt hoặc từ chối gửi tới quy trình đang tạm dừng chờ duyệt."""

    approval_id: str
    node_id: str
    decision: str  # "APPROVED" | "REJECTED"
    decided_by: str
    rationale: str = ""


@dataclass
class ExternalEventSignalPayload:
    """Tín hiệu sự kiện từ hệ thống ngoài (như webhook GitHub) gửi tới quy trình đang chờ."""

    node_id: str
    event_source: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class HumanTaskSignalPayload:
    """Tín hiệu thông báo nhân sự đã hoàn tất hoặc gặp vướng mắc trên đầu việc."""

    task_id: str
    node_id: str
    status: str  # "COMPLETED" | "BLOCKED"
    completion_note: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowProgressSnapshot:
    """Ảnh chụp nhanh tiến độ hiện tại phục vụ truy vấn trực tiếp từ Temporal."""

    workflow_run_id: str
    status: str
    paused: bool
    cancelled: bool
    waiting_node_id: str | None
    pending_approval_id: str | None
    completed_nodes: list[str] = field(default_factory=list)
    failed_nodes: list[str] = field(default_factory=list)
    skipped_nodes: list[str] = field(default_factory=list)
    node_states: dict[str, str] = field(default_factory=dict)
