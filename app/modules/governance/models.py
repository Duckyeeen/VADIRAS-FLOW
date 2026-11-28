"""Các bảng cơ sở dữ liệu cho chính sách quy tắc, quyết định kiểm soát, phê duyệt và giấy phép hẹp."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType
from app.db.mixins import OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class PolicyEffect(str, Enum):
    """Hiệu lực quyết định của một quy tắc kiểm soát."""

    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


class ApprovalRequestStatus(str, Enum):
    """Trạng thái của một yêu cầu phê duyệt ràng buộc 7 yếu tố."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class PolicySet(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Bộ chính sách có phiên bản của một tổ chức."""

    __tablename__ = "policy_sets"
    __table_args__ = (
        sa.UniqueConstraint("organization_id", "version", name="uq_policy_sets_org_ver"),
    )

    version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    rules: Mapped[list[PolicyRule]] = relationship(
        "PolicyRule",
        back_populates="policy_set",
        order_by="PolicyRule.priority_order.asc()",
    )


class PolicyRule(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Một quy tắc cụ thể nằm trong bộ chính sách cố định."""

    __tablename__ = "policy_rules"
    __table_args__ = (
        sa.UniqueConstraint("policy_set_id", "code", name="uq_policy_rules_set_code"),
    )

    policy_set_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("policy_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    action_pattern: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    risk_band: Mapped[str] = mapped_column(sa.String(32), default="ANY", nullable=False)
    effect: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    required_approver_role: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    conditions_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    priority_order: Mapped[int] = mapped_column(sa.Integer, default=100, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)

    policy_set: Mapped[PolicySet] = relationship("PolicySet", back_populates="rules")


class PolicyDecision(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Lưu vết mọi lượt đánh giá quy tắc trước khi thực thi hành động có tác động ngoài."""

    __tablename__ = "policy_decisions"

    request_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workflow_run_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    node_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    actor_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    action: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    resource_scope: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    parameter_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    decision: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    triggered_rules_json: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    reason: Mapped[str] = mapped_column(sa.Text, default="", nullable=False)


class ApprovalRequest(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Yêu cầu phê duyệt gắn chặt 7 yếu tố: phiên bản, bước, hành động, mã băm, phạm vi, chính sách, hạn."""

    __tablename__ = "approval_requests"

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
    workflow_version_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("workflow_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    node_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    action: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    parameters_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    parameter_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    resource_scope: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    policy_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    required_role: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        default=ApprovalRequestStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    requested_by_actor_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    policy_decision_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("policy_decisions.id", ondelete="SET NULL"),
        nullable=True,
    )

    decision_record: Mapped[ApprovalDecision | None] = relationship(
        "ApprovalDecision",
        back_populates="approval_request",
        uselist=False,
    )


class ApprovalDecision(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Quyết định đồng ý hoặc từ chối kèm danh tính người duyệt và kết quả kiểm tra thẩm quyền."""

    __tablename__ = "approval_decisions"

    approval_request_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("approval_requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    approver_membership_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("memberships.id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(sa.Text, default="", nullable=False)
    authority_verified: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)

    approval_request: Mapped[ApprovalRequest] = relationship(
        "ApprovalRequest",
        back_populates="decision_record",
    )


class PermissionGrant(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Giấy phép phạm vi hẹp, có thời hạn, cấp riêng cho trợ lý AI thực thi một tác vụ cụ thể."""

    __tablename__ = "permission_grants"

    agent_identity_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("agent_identities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_run_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    node_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    action: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    resource_scope: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    policy_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    granted_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
