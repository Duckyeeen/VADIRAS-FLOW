"""Khuôn mẫu dữ liệu vào và ra cho API xem kết quả xác minh, bằng chứng và nhật ký kiểm toán."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.modules.identity.schemas import PaginationMeta
from app.core.schemas import ContractModel


class ExecutionEvidenceOut(ContractModel):
    """Thông tin một bằng chứng đối chiếu ngược đã thu thập (có phân loại quyền xem)."""

    id: str
    verification_run_id: str
    source_type: str
    source_ref: str
    captured_at: datetime
    actor_id: str
    resource_identifier: str
    content_hash: str
    verification_rule: str
    is_fresh: bool
    access_classification: str
    evidence_summary: dict[str, Any]


class VerificationRunOut(ContractModel):
    """Kết quả một lượt đánh giá xác minh kèm tiêu chí và danh sách bằng chứng."""

    id: str
    organization_id: str
    request_id: str
    workflow_run_id: str | None = None
    node_id: str | None = None
    evaluator_type: str
    outcome: str
    postconditions: list[str]
    evaluated_criteria: list[dict[str, Any]]
    rationale_summary: str
    freshness_seconds: int
    requires_human_confirmation: bool
    human_confirmed_by_membership_id: str | None = None
    verified_at: datetime
    evidences: list[ExecutionEvidenceOut] = Field(default_factory=list)


class RequestVerificationResponse(ContractModel):
    """Tổng hợp kết quả xác minh của một yêu cầu công việc theo quyền người xem."""

    request_id: str
    business_outcome: str
    request_status: str
    verification_runs: list[VerificationRunOut]


class RunEvidenceResponse(ContractModel):
    """Danh sách toàn bộ bằng chứng thu thập được trong một lượt chạy quy trình."""

    workflow_run_id: str
    evidences: list[ExecutionEvidenceOut]


class AuditLogOut(ContractModel):
    """Một bản ghi trong nhật ký kiểm toán chỉ thêm mới (đã làm sạch khóa nhạy cảm)."""

    id: str
    organization_id: str
    actor_type: str
    actor_id: str
    request_id: str | None = None
    workflow_run_id: str | None = None
    node_id: str | None = None
    action: str
    resource: str
    correlation_id: str | None = None
    policy_decision: str | None = None
    policy_version: str | None = None
    approval_id: str | None = None
    outcome: str
    evidence_ref: str | None = None
    parameter_hash: str | None = None
    safe_metadata: dict[str, Any]
    occurred_at: datetime


class AuditLogListResponse(ContractModel):
    """Danh sách nhật ký kiểm toán có phân trang."""

    items: list[AuditLogOut]
    pagination: PaginationMeta
