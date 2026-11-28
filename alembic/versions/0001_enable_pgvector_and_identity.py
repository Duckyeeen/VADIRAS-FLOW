"""Khởi tạo tiện ích pgvector và 12 bảng định danh, tổ chức, phòng ban, phân quyền, danh tính AI.

Mã bản nâng cấp: 0001_enable_pgvector_and_identity
Kế thừa từ: None
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_enable_pgvector_and_identity"
down_revision: str | tuple[str, ...] | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# Kiểu JSON tự động dùng JSONB trên PostgreSQL và JSON tiêu chuẩn trên SQLite
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    """Tạo phần mở rộng vector (trên PostgreSQL) và toàn bộ 12 bảng nền tảng định danh."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 1. Bảng tổ chức
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("settings_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)

    # 2. Bảng người dùng (mật khẩu lưu dạng Argon2id)
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # 3. Bảng quyền hệ thống
    op.create_table(
        "permissions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_permissions"),
    )
    op.create_index("ix_permissions_code", "permissions", ["code"], unique=True)

    # 4. Bảng phòng ban trực thuộc tổ chức
    op.create_table(
        "departments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_departments_organization_id_organizations", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_departments"),
        sa.UniqueConstraint("organization_id", "code", name="uq_departments_org_code"),
    )
    op.create_index("ix_departments_organization_id", "departments", ["organization_id"], unique=False)

    # 5. Bảng vai trò theo tổ chức
    op.create_table(
        "roles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_roles_organization_id_organizations", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("organization_id", "code", name="uq_roles_org_code"),
    )
    op.create_index("ix_roles_organization_id", "roles", ["organization_id"], unique=False)

    # 6. Bảng nối vai trò - quyền
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("permission_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], name="fk_role_permissions_permission_id_permissions", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_role_permissions_role_id_roles", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permissions"),
    )

    # 7. Bảng tư cách thành viên (phân tách nhân viên nội bộ và khách hàng)
    op.create_table(
        "memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=36), nullable=True),
        sa.Column("user_kind", sa.String(length=32), nullable=False),
        sa.Column("customer_account_ref", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], name="fk_memberships_department_id_departments", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_memberships_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_memberships_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_memberships_org_user"),
    )
    op.create_index("ix_memberships_organization_id", "memberships", ["organization_id"], unique=False)
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"], unique=False)
    op.create_index("ix_memberships_department_id", "memberships", ["department_id"], unique=False)
    op.create_index("ix_memberships_customer_account_ref", "memberships", ["customer_account_ref"], unique=False)

    # 8. Bảng nối thành viên - vai trò
    op.create_table(
        "membership_roles",
        sa.Column("membership_id", sa.String(length=36), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], name="fk_membership_roles_membership_id_memberships", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_membership_roles_role_id_roles", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("membership_id", "role_id", name="pk_membership_roles"),
    )

    # 9. Bảng lưu phiên thẻ làm mới JWT
    op.create_table(
        "refresh_token_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("membership_id", sa.String(length=36), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_jti", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], name="fk_refresh_token_sessions_membership_id_memberships", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_refresh_token_sessions_organization_id_organizations", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_token_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_token_sessions_token_hash"),
    )
    op.create_index("ix_refresh_token_sessions_organization_id", "refresh_token_sessions", ["organization_id"], unique=False)
    op.create_index("ix_refresh_token_sessions_membership_id", "refresh_token_sessions", ["membership_id"], unique=False)
    op.create_index("ix_refresh_token_sessions_jti", "refresh_token_sessions", ["jti"], unique=True)

    # 10. Bảng danh tính dịch vụ của trợ lý AI
    op.create_table(
        "agent_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("role_code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("limits_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_agent_identities_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name="fk_agent_identities_owner_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_agent_identities"),
        sa.UniqueConstraint("organization_id", "role_code", name="uq_agent_identities_org_role"),
    )
    op.create_index("ix_agent_identities_organization_id", "agent_identities", ["organization_id"], unique=False)

    # 11. Bảng năng lực đăng ký cho trợ lý AI
    op.create_table(
        "agent_capabilities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("agent_identity_id", sa.String(length=36), nullable=False),
        sa.Column("capability_code", sa.String(length=128), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_identity_id"], ["agent_identities.id"], name="fk_agent_capabilities_agent_identity_id_agent_identities", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_agent_capabilities_organization_id_organizations", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_agent_capabilities"),
        sa.UniqueConstraint("agent_identity_id", "capability_code", name="uq_agent_cap_code"),
    )
    op.create_index("ix_agent_capabilities_organization_id", "agent_capabilities", ["organization_id"], unique=False)
    op.create_index("ix_agent_capabilities_agent_identity_id", "agent_capabilities", ["agent_identity_id"], unique=False)

    # 12. Bảng cấp phép công cụ phạm vi hẹp cho trợ lý AI
    op.create_table(
        "agent_tool_grants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("agent_identity_id", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("resource_scope", sa.String(length=255), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_identity_id"], ["agent_identities.id"], name="fk_agent_tool_grants_agent_identity_id_agent_identities", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_agent_tool_grants_organization_id_organizations", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_agent_tool_grants"),
    )
    op.create_index("ix_agent_tool_grants_organization_id", "agent_tool_grants", ["organization_id"], unique=False)
    op.create_index("ix_agent_tool_grants_agent_identity_id", "agent_tool_grants", ["agent_identity_id"], unique=False)


def downgrade() -> None:
    """Gỡ bỏ toàn bộ 12 bảng của bản nâng cấp 0001 theo thứ tự ngược lại."""
    op.drop_table("agent_tool_grants")
    op.drop_table("agent_capabilities")
    op.drop_table("agent_identities")
    op.drop_table("refresh_token_sessions")
    op.drop_table("membership_roles")
    op.drop_table("memberships")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("departments")
    op.drop_table("permissions")
    op.drop_table("users")
    op.drop_table("organizations")
