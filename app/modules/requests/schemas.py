"""Khuôn mẫu dữ liệu vào/ra đã kiểm tra chặt chẽ cho phân hệ Yêu cầu và Tác vụ Con người."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.modules.identity.schemas import PaginationMeta
from app.core.schemas import ContractModel

from .models import (
    ImpactLevel,
    MessageKind,
    PriorityLevel,
    RequestSource,
    RequestStatus,
    RequestType,
    VisibilityLevel,
)


class CreateRequestIn(ContractModel):
    """Dữ liệu đầu vào khi tạo một yêu cầu công việc mới."""

    title: str = Field(min_length=3, max_length=300)
    description: str = Field(min_length=5, max_length=20_000)
    request_type: str = Field(default=RequestType.SERVICE_REQUEST.value, min_length=2, max_length=64)
    source: RequestSource = RequestSource.API
    priority: PriorityLevel = PriorityLevel.P3_MEDIUM
    impact: ImpactLevel = ImpactLevel.MEDIUM
    urgency: ImpactLevel = ImpactLevel.MEDIUM
    department_code: str | None = Field(default=None, min_length=2, max_length=64)
    due_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateRequestIn(ContractModel):
    """Dữ liệu cập nhật yêu cầu (chỉ dành cho nhân viên nội bộ có quyền)."""

    title: str | None = Field(default=None, min_length=3, max_length=300)
    status: RequestStatus | None = None
    priority: PriorityLevel | None = None
    impact: ImpactLevel | None = None
    urgency: ImpactLevel | None = None
    department_code: str | None = Field(default=None, min_length=2, max_length=64)
    due_at: datetime | None = None


class CreateMessageIn(ContractModel):
    """Dữ liệu gửi bình luận hoặc ghi chú lên yêu cầu."""

    body: str = Field(min_length=1, max_length=10_000)
    visibility: VisibilityLevel = VisibilityLevel.INTERNAL_ONLY
    message_kind: MessageKind = MessageKind.COMMENT


class ClarificationIn(ContractModel):
    """Dữ liệu trả lời làm rõ thông tin cho yêu cầu đang thiếu dữ liệu."""

    answer: str = Field(min_length=1, max_length=10_000)
    visibility: VisibilityLevel = VisibilityLevel.CUSTOMER_VISIBLE


class CreateHumanTaskIn(ContractModel):
    """Dữ liệu tạo đầu việc giao cho nhân viên hoặc phòng ban xử lý."""

    title: str = Field(min_length=3, max_length=300)
    instructions: str = Field(default="", max_length=10_000)
    department_code: str | None = Field(default=None, min_length=2, max_length=64)
    assignee_membership_id: str | None = Field(default=None, min_length=36, max_length=36)
    due_at: datetime | None = None


class CompleteHumanTaskIn(ContractModel):
    """Dữ liệu báo hoàn tất đầu việc kèm ghi chú và bằng chứng."""

    completion_note: str = Field(min_length=1, max_length=5_000)
    evidence: dict[str, Any] = Field(default_factory=dict)


class BlockHumanTaskIn(ContractModel):
    """Dữ liệu báo vướng mắc khiến đầu việc tạm thời bị chặn."""

    blocked_reason: str = Field(min_length=1, max_length=5_000)


class RequestMessageOut(ContractModel):
    """Thông tin tin nhắn trao đổi đã lọc theo quyền xem."""

    id: str
    request_id: str
    author_membership_id: str
    body: str
    visibility: str
    message_kind: str
    created_at: datetime


class HumanTaskOut(ContractModel):
    """Thông tin đầy đủ của một đầu việc giao cho con người (chỉ dành cho nhân viên nội bộ)."""

    id: str
    organization_id: str
    request_id: str
    workflow_run_id: str | None
    department_id: str | None
    assignee_membership_id: str | None
    title: str
    instructions: str
    status: str
    visibility: str
    due_at: datetime | None
    completion_note: str | None
    evidence: dict[str, Any]
    blocked_reason: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RequestCustomerOut(ContractModel):
    """Thông tin yêu cầu trả cho khách hàng — ẩn tuyệt đối ghi chú, cờ rủi ro và việc nội bộ."""

    id: str
    organization_id: str
    request_number: str
    title: str
    description: str
    request_type: str
    status: str
    business_outcome: str
    priority: str
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime
    messages: list[RequestMessageOut] = Field(default_factory=list)


class RequestInternalOut(ContractModel):
    """Thông tin đầy đủ của yêu cầu dành riêng cho nhân viên nội bộ."""

    id: str
    organization_id: str
    request_number: str
    title: str
    description: str
    sanitized_description: str
    pii_redactions: list[str]
    injection_flags: list[str]
    request_type: str
    source: str
    status: str
    business_outcome: str
    priority: str
    impact: str
    urgency: str
    requester_membership_id: str
    requester_kind: str
    customer_account_ref: str | None
    department_id: str | None
    proposed_departments: list[str]
    due_at: datetime | None
    content_hash: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    messages: list[RequestMessageOut] = Field(default_factory=list)
    human_tasks: list[HumanTaskOut] = Field(default_factory=list)


class RequestListResponse(ContractModel):
    """Danh sách yêu cầu có phân trang (tự chọn khuôn mẫu khách hàng hoặc nội bộ theo vai trò)."""

    items: list[RequestInternalOut | RequestCustomerOut]
    pagination: PaginationMeta


class HumanTaskListResponse(ContractModel):
    """Danh sách đầu việc giao cho con người có phân trang."""

    items: list[HumanTaskOut]
    pagination: PaginationMeta
