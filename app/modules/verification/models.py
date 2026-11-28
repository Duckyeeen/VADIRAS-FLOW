"""Các bảng cơ sở dữ liệu cho lượt xác minh, bằng chứng thực thi và nhật ký kiểm toán chỉ thêm mới."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType
from app.db.mixins import OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class VerificationOutcome(str, Enum):
    """4 kết quả xác minh nghiệp vụ bắt buộc phân biệt rạch ròi với mã thành công kỹ thuật."""

    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"


class AuditActorType(str, Enum):
    """Phân loại chủ thể gây ra sự kiện được ghi vào nhật ký kiểm toán."""

    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"
    CONNECTOR = "CONNECTOR"


class VerificationRun(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Lưu kết quả một lần đánh giá xác minh dựa trên tập bằng chứng đối chiếu ngược."""

    __tablename__ = "verification_runs"

    request_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_run_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    node_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    evaluator_type: Mapped[str] = mapped_column(sa.String(64), default="DETERMINISTIC_FIRST", nullable=False)
    outcome: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    postconditions_json: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    evaluated_criteria_json: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    rationale_summary: Mapped[str] = mapped_column(sa.Text, default="", nullable=False)
    freshness_seconds: Mapped[int] = mapped_column(sa.Integer, default=300, nullable=False)
    requires_human_confirmation: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    human_confirmed_by_membership_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    verified_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    evidences: Mapped[list[ExecutionEvidence]] = relationship(
        "ExecutionEvidence",
        back_populates="verification_run",
        cascade="all, delete-orphan",
    )


class ExecutionEvidence(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Bằng chứng đối chiếu ngược thu thập từ hệ thống đích, lệnh duyệt hoặc đầu việc nhân sự."""

    __tablename__ = "execution_evidence"

    verification_run_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("verification_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_run_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    source_ref: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    resource_identifier: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    verification_rule: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    is_fresh: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    access_classification: Mapped[str] = mapped_column(sa.String(32), default="INTERNAL_ONLY", nullable=False, index=True)
    evidence_summary_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    verification_run: Mapped[VerificationRun] = relationship("VerificationRun", back_populates="evidences")


class AuditLog(UUIDPrimaryKeyMixin, OrgScopedMixin, Base):
    """Nhật ký kiểm toán chỉ được phép thêm mới (không chỉnh sửa, không chứa khóa bí mật hay suy nghĩ ẩn)."""

    __tablename__ = "audit_logs"

    actor_type: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    request_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    workflow_run_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    node_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    action: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    resource: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)
    policy_decision: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    outcome: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    evidence_ref: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    parameter_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    safe_metadata_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, index=True)
