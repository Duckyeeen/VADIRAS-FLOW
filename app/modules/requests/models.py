"""Các bảng cơ sở dữ liệu cho yêu cầu công việc, thành viên tham gia, trao đổi, phân tích AI và việc giao cho người."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType
from app.db.mixins import OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class RequestType(str, Enum):
    """5 loại yêu cầu chuẩn của hệ thống (lưu dạng chuỗi để dễ mở rộng thêm loại mới)."""

    INCIDENT = "INCIDENT"
    CHANGE = "CHANGE"
    SERVICE_REQUEST = "SERVICE_REQUEST"
    ONBOARDING = "ONBOARDING"
    INTERNAL_TASK = "INTERNAL_TASK"


class RequestSource(str, Enum):
    """Kênh tiếp nhận yêu cầu vào hệ thống."""

    WEB = "WEB"
    API = "API"
    INTEGRATION = "INTEGRATION"
    MANUAL = "MANUAL"
    EMAIL = "EMAIL"


class RequestStatus(str, Enum):
    """Trạng thái xử lý của yêu cầu công việc."""

    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class BusinessOutcome(str, Enum):
    """Kết quả nghiệp vụ cuối cùng sau bước đối chiếu bằng chứng."""

    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class PriorityLevel(str, Enum):
    """Mức độ ưu tiên xử lý yêu cầu."""

    P1_CRITICAL = "P1_CRITICAL"
    P2_HIGH = "P2_HIGH"
    P3_MEDIUM = "P3_MEDIUM"
    P4_LOW = "P4_LOW"


class ImpactLevel(str, Enum):
    """Mức độ ảnh hưởng của yêu cầu tới hệ thống hoặc khách hàng."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class VisibilityLevel(str, Enum):
    """Phân loại quyền xem: khách hàng được thấy hay chỉ nội bộ nhân viên xem."""

    CUSTOMER_VISIBLE = "CUSTOMER_VISIBLE"
    INTERNAL_ONLY = "INTERNAL_ONLY"


class MessageKind(str, Enum):
    """Loại tin nhắn trao đổi gắn trên một yêu cầu."""

    COMMENT = "COMMENT"
    CLARIFICATION_QUESTION = "CLARIFICATION_QUESTION"
    CLARIFICATION_ANSWER = "CLARIFICATION_ANSWER"
    SYSTEM_NOTE = "SYSTEM_NOTE"


class HumanTaskStatus(str, Enum):
    """Trạng thái của đầu việc giao cho nhân viên xử lý."""

    OPEN = "OPEN"
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class Request(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Yêu cầu công việc chính (tách biệt dữ liệu gốc với dữ liệu đã làm sạch và phân tích AI)."""

    __tablename__ = "requests"
    __table_args__ = (
        sa.UniqueConstraint("organization_id", "request_number", name="uq_requests_org_number"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_requests_org_idempotency"),
    )

    request_number: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    title: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    sanitized_description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    pii_redactions_json: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    injection_flags_json: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    request_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(sa.String(32), default=RequestSource.API.value, nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        default=RequestStatus.OPEN.value,
        nullable=False,
        index=True,
    )
    business_outcome: Mapped[str] = mapped_column(
        sa.String(32),
        default=BusinessOutcome.PENDING.value,
        nullable=False,
    )
    priority: Mapped[str] = mapped_column(
        sa.String(32),
        default=PriorityLevel.P3_MEDIUM.value,
        nullable=False,
    )
    impact: Mapped[str] = mapped_column(
        sa.String(32),
        default=ImpactLevel.MEDIUM.value,
        nullable=False,
    )
    urgency: Mapped[str] = mapped_column(
        sa.String(32),
        default=ImpactLevel.MEDIUM.value,
        nullable=False,
    )

    requester_membership_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("memberships.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    requester_kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    customer_account_ref: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)
    department_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    proposed_departments_json: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    due_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    sla_policy_ref: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    content_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    created_by_user_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    updated_by_user_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    messages: Mapped[list[RequestMessage]] = relationship(
        "RequestMessage",
        back_populates="request",
        order_by="RequestMessage.created_at.asc()",
    )
    human_tasks: Mapped[list[HumanTask]] = relationship(
        "HumanTask",
        back_populates="request",
        order_by="HumanTask.created_at.asc()",
    )


class RequestParticipant(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Lưu danh sách thành viên liên quan tới một yêu cầu (người gửi, người theo dõi, người xử lý)."""

    __tablename__ = "request_participants"
    __table_args__ = (
        sa.UniqueConstraint(
            "request_id",
            "membership_id",
            "participant_role",
            name="uq_request_participants_member_role",
        ),
    )

    request_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    membership_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    participant_role: Mapped[str] = mapped_column(sa.String(32), nullable=False)


class RequestAttachment(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Thông tin tệp đính kèm gắn trên yêu cầu kèm mức hiển thị nội bộ hoặc khách hàng."""

    __tablename__ = "request_attachments"

    request_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by_membership_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("memberships.id", ondelete="RESTRICT"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    storage_ref: Mapped[str] = mapped_column(sa.String(1024), nullable=False)
    visibility: Mapped[str] = mapped_column(
        sa.String(32),
        default=VisibilityLevel.INTERNAL_ONLY.value,
        nullable=False,
    )


class RequestMessage(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Tin nhắn trao đổi và làm rõ thông tin (tách riêng nội bộ và phần khách hàng được xem)."""

    __tablename__ = "request_messages"

    request_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_membership_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("memberships.id", ondelete="RESTRICT"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    visibility: Mapped[str] = mapped_column(
        sa.String(32),
        default=VisibilityLevel.INTERNAL_ONLY.value,
        nullable=False,
        index=True,
    )
    message_kind: Mapped[str] = mapped_column(
        sa.String(32),
        default=MessageKind.COMMENT.value,
        nullable=False,
    )

    request: Mapped[Request] = relationship("Request", back_populates="messages")


class RequestAnalysis(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Lưu kết quả phân tích AI theo từng phiên bản (không lưu suy nghĩ ẩn của mô hình)."""

    __tablename__ = "request_analyses"
    __table_args__ = (
        sa.UniqueConstraint("request_id", "version_number", name="uq_request_analyses_req_ver"),
    )

    request_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    analysis_job_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    model: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    structured_output_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    decision_summary: Mapped[str] = mapped_column(sa.Text, default="", nullable=False)
    assumptions_json: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    evidence_refs_json: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    confidence_score: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)


class HumanTask(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Đầu việc giao cho nhân viên hoặc phòng ban xử lý kèm bằng chứng hoàn thành."""

    __tablename__ = "human_tasks"

    request_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_run_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    department_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assignee_membership_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("memberships.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    instructions: Mapped[str] = mapped_column(sa.Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        default=HumanTaskStatus.OPEN.value,
        nullable=False,
        index=True,
    )
    visibility: Mapped[str] = mapped_column(
        sa.String(32),
        default=VisibilityLevel.INTERNAL_ONLY.value,
        nullable=False,
    )
    due_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    completion_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    evidence_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    blocked_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    request: Mapped[Request] = relationship("Request", back_populates="human_tasks")
