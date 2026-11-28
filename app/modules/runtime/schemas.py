"""Khuôn mẫu dữ liệu vào và ra cho các API điều phối lượt chạy quy trình Temporal."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.modules.identity.schemas import PaginationMeta
from app.core.schemas import ContractModel


class StartWorkflowRunIn(ContractModel):
    """Dữ liệu đầu vào để khởi phát một lượt chạy từ phiên bản quy trình đã ban hành."""

    request_id: str = Field(min_length=1, max_length=36)
    workflow_version_id: str = Field(min_length=1, max_length=36)
    trigger_input: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class RunControlActionIn(ContractModel):
    """Lý do kèm theo khi tạm dừng, tiếp tục hoặc hủy bỏ một lượt chạy quy trình."""

    reason: str = Field(default="", max_length=500)


class ReplanWorkflowRunIn(ContractModel):
    """Đề xuất một sơ đồ quy trình thay thế khi lượt chạy hiện tại cần điều chỉnh."""

    reason: str = Field(min_length=5, max_length=1_000)
    proposed_graph: dict[str, Any]


class WorkflowNodeRunOut(ContractModel):
    """Thông tin chi tiết tiến độ thực thi của từng bước trong lượt chạy."""

    id: str
    node_id: str
    node_type: str
    status: str
    attempt: int
    idempotency_key: str
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    error_class: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ReplanProposalOut(ContractModel):
    """Thông tin một đề xuất lập lại quy trình gắn với lượt chạy."""

    id: str
    parent_version_id: str
    proposed_version_id: str | None = None
    reason: str
    scope_delta: dict[str, Any]
    risk_escalated: bool
    status: str
    proposed_by_actor_id: str
    created_at: datetime


class WorkflowRunOut(ContractModel):
    """Khuôn mẫu đầu ra đầy đủ của một lượt chạy quy trình bền vững."""

    id: str
    organization_id: str
    request_id: str
    workflow_definition_id: str
    workflow_version_id: str
    workflow_content_hash: str
    temporal_workflow_id: str
    temporal_run_id: str | None = None
    status: str
    replan_count: int
    idempotency_key: str | None = None
    started_by_user_id: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    idempotent_replay: bool = False
    node_runs: list[WorkflowNodeRunOut] = Field(default_factory=list)
    replan_proposals: list[ReplanProposalOut] = Field(default_factory=list)


class WorkflowRunListResponse(ContractModel):
    """Danh sách lượt chạy quy trình có phân trang."""

    items: list[WorkflowRunOut]
    pagination: PaginationMeta


class ReplanWorkflowRunOut(ContractModel):
    """Kết quả trả về khi tạo đề xuất lập lại sơ đồ cho một lượt chạy."""

    workflow_run_id: str
    run_status: str
    replan_count: int
    proposal: ReplanProposalOut
    new_version_id: str
    new_version_number: int
    new_version_status: str
    approval_request_id: str | None = None
