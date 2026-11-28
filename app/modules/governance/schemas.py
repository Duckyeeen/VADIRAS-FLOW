"""Khuôn mẫu dữ liệu vào/ra API cho yêu cầu phê duyệt và đánh giá quy tắc."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.modules.identity.schemas import PaginationMeta
from app.core.schemas import ContractModel


class CreateApprovalIn(ContractModel):
    """Dữ liệu tạo một yêu cầu phê duyệt gắn chặt 7 yếu tố ràng buộc."""

    request_id: str = Field(min_length=36, max_length=36)
    workflow_run_id: str | None = Field(default=None, min_length=36, max_length=36)
    workflow_version_id: str | None = Field(default=None, min_length=36, max_length=36)
    node_id: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=2, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    resource_scope: str = Field(min_length=2, max_length=255)
    policy_version: str = Field(default="v1", min_length=1, max_length=64)
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "HIGH"
    required_role: str = Field(default="department_manager", min_length=2, max_length=64)
    expires_in_hours: int = Field(default=24, ge=1, le=720)


class ApprovalDecisionIn(ContractModel):
    """Quyết định đồng ý hoặc từ chối một yêu cầu phê duyệt."""

    decision: Literal["APPROVED", "REJECTED"]
    rationale: str = Field(min_length=3, max_length=2_000)


class ApprovalDecisionOut(ContractModel):
    """Thông tin chi tiết quyết định đã ghi nhận cho yêu cầu phê duyệt."""

    id: str
    approver_membership_id: str
    decision: str
    rationale: str
    authority_verified: bool
    decided_at: datetime


class ApprovalRequestOut(ContractModel):
    """Thông tin đầy đủ của một yêu cầu phê duyệt kèm mã băm tham số và phạm vi."""

    id: str
    organization_id: str
    request_id: str
    workflow_run_id: str | None
    workflow_version_id: str | None
    node_id: str
    action: str
    parameters: dict[str, Any]
    parameter_hash: str
    resource_scope: str
    policy_version: str
    risk_level: str
    required_role: str
    status: str
    requested_by_actor_id: str
    expires_at: datetime
    created_at: datetime
    decision_record: ApprovalDecisionOut | None = None


class ApprovalListResponse(ContractModel):
    """Danh sách yêu cầu phê duyệt có phân trang thuộc tổ chức hiện tại."""

    items: list[ApprovalRequestOut]
    pagination: PaginationMeta


class GovernanceEvaluateIn(ContractModel):
    """Dữ liệu đánh giá thử quy tắc kiểm soát và mức độ rủi ro cho một hành động."""

    actor_type: Literal["USER", "AGENT", "SYSTEM"] = "AGENT"
    actor_id: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=2, max_length=128)
    resource_scope: str = Field(default="", max_length=255)
    parameters: dict[str, Any] = Field(default_factory=dict)
    request_type: str = Field(default="SERVICE_REQUEST", min_length=2, max_length=64)
    side_effect_class: Literal["NONE", "READ", "WRITE"] = "WRITE"
    impact_score: int = Field(default=2, ge=1, le=5)
    likelihood_score: int = Field(default=2, ge=1, le=5)
    estimated_cost_usd: float = Field(default=0.05, ge=0.0)
    max_cost_usd: float = Field(default=5.0, ge=0.0)
    injection_flags: list[str] = Field(default_factory=list)


class GovernanceEvaluateOut(ContractModel):
    """Kết quả đánh giá cố định từ Bộ kiểm soát quy tắc."""

    decision: str
    risk_level: str
    policy_version: str
    parameter_hash: str
    triggered_rules: list[str]
    required_role: str | None
    reason: str
