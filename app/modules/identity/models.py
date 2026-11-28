"""Các bảng cơ sở dữ liệu cho định danh, tổ chức, 6 phòng ban, phân quyền và trợ lý AI."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType
from app.db.mixins import OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class UserKind(str, Enum):
    """Phân loại người dùng: nhân viên nội bộ hoặc liên hệ khách hàng bên ngoài."""

    EMPLOYEE = "EMPLOYEE"
    CUSTOMER_CONTACT = "CUSTOMER_CONTACT"


class MembershipStatus(str, Enum):
    """Trạng thái hoạt động của thành viên trong tổ chức."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tổ chức thuê bao hoặc doanh nghiệp sở hữu toàn bộ dữ liệu nghiệp vụ."""

    __tablename__ = "organizations"

    slug: Mapped[str] = mapped_column(sa.String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    settings_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)


class Department(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Phòng ban trực thuộc tổ chức (mẫu chuẩn gồm 6 phòng ban)."""

    __tablename__ = "departments"
    __table_args__ = (
        sa.UniqueConstraint("organization_id", "code", name="uq_departments_org_code"),
    )

    code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    description: Mapped[str] = mapped_column(sa.String(500), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tài khoản đăng nhập của con người (lưu mật khẩu đã băm bằng Argon2id)."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(sa.String(254), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)


class Membership(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Liên kết một tài khoản người dùng với một tổ chức, phòng ban và loại thành viên."""

    __tablename__ = "memberships"
    __table_args__ = (
        sa.UniqueConstraint("organization_id", "user_id", name="uq_memberships_org_user"),
    )

    user_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    department_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_kind: Mapped[str] = mapped_column(
        sa.String(32),
        default=UserKind.EMPLOYEE.value,
        nullable=False,
    )
    customer_account_ref: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        default=MembershipStatus.ACTIVE.value,
        nullable=False,
    )

    user: Mapped[User] = relationship("User")
    department: Mapped[Department | None] = relationship("Department")
    organization: Mapped[Organization] = relationship("Organization")


class Role(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Vai trò phân quyền trong phạm vi một tổ chức (ví dụ quản trị viên, quản lý, nhân viên)."""

    __tablename__ = "roles"
    __table_args__ = (
        sa.UniqueConstraint("organization_id", "code", name="uq_roles_org_code"),
    )

    code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    description: Mapped[str] = mapped_column(sa.String(500), default="", nullable=False)


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Định nghĩa một quyền thao tác cụ thể trong hệ thống (ví dụ `users:read`)."""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(sa.String(128), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(sa.String(300), default="", nullable=False)


class RolePermission(Base):
    """Bảng nối giữa vai trò và danh sách quyền được phép."""

    __tablename__ = "role_permissions"

    role_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    )


class MembershipRole(Base):
    """Bảng nối gán vai trò cho từng thành viên thuộc tổ chức."""

    __tablename__ = "membership_roles"

    membership_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("memberships.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )


class RefreshTokenSession(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Lưu vết các phiên thẻ làm mới JWT để hỗ trợ xoay vòng và phát hiện dùng lại thẻ bị lộ."""

    __tablename__ = "refresh_token_sessions"

    membership_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    jti: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    replaced_by_jti: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)


class AgentIdentity(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Danh tính dịch vụ tách biệt cho từng vai trò trợ lý AI (không dùng chung quyền con người)."""

    __tablename__ = "agent_identities"
    __table_args__ = (
        sa.UniqueConstraint("organization_id", "role_code", name="uq_agent_identities_org_role"),
    )

    role_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(32), default="ACTIVE", nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    limits_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)


class AgentCapability(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Khai báo năng lực nghiệp vụ mà một danh tính trợ lý AI được đăng ký đảm nhiệm."""

    __tablename__ = "agent_capabilities"
    __table_args__ = (
        sa.UniqueConstraint("agent_identity_id", "capability_code", name="uq_agent_cap_code"),
    )

    agent_identity_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("agent_identities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    capability_code: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)


class AgentToolGrant(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Giấy phép phạm vi hẹp cho phép trợ lý AI gọi đúng một công cụ trên một tài nguyên cụ thể."""

    __tablename__ = "agent_tool_grants"

    agent_identity_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("agent_identities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    resource_scope: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    policy_version: Mapped[str] = mapped_column(sa.String(64), default="v1", nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
