"""Bổ sung 6 bảng cho bộ chính sách, quyết định kiểm soát, phê duyệt ràng buộc 7 yếu tố và giấy phép hẹp.

Mã bản nâng cấp: 0005_governance_and_approvals
Kế thừa từ: 0004_workflow_and_runtime
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_governance_and_approvals"
down_revision: str | tuple[str, ...] | None = "0004_workflow_and_runtime"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    """Tạo 6 bảng cho phân hệ Kiểm soát Quản trị và Phê duyệt."""
    # 1. Bảng tập hợp chính sách theo phiên bản
    op.create_table(
        "policy_sets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_policy_sets_created_by_user_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_policy_sets_organization_id_organizations", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_policy_sets"),
        sa.UniqueConstraint("organization_id", "version", name="uq_policy_sets_org_ver"),
    )
    op.create_index("ix_policy_sets_organization_id", "policy_sets", ["organization_id"], unique=False)

    # 2. Bảng quy tắc chi tiết trong từng bộ chính sách
    op.create_table(
        "policy_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("policy_set_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("action_pattern", sa.String(length=128), nullable=False),
        sa.Column("risk_band", sa.String(length=32), nullable=False),
        sa.Column("effect", sa.String(length=32), nullable=False),
        sa.Column("required_approver_role", sa.String(length=64), nullable=True),
        sa.Column("conditions_json", JSON_TYPE, nullable=False),
        sa.Column("priority_order", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_policy_rules_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_set_id"], ["policy_sets.id"], name="fk_policy_rules_policy_set_id_policy_sets", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_policy_rules"),
        sa.UniqueConstraint("policy_set_id", "code", name="uq_policy_rules_set_code"),
    )
    op.create_index("ix_policy_rules_organization_id", "policy_rules", ["organization_id"], unique=False)
    op.create_index("ix_policy_rules_policy_set_id", "policy_rules", ["policy_set_id"], unique=False)

    # 3. Bảng lưu vết quyết định kiểm soát trước mỗi thao tác
    op.create_table(
        "policy_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("node_id", sa.String(length=64), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_scope", sa.String(length=255), nullable=False),
        sa.Column("parameter_hash", sa.String(length=64), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("triggered_rules_json", JSON_TYPE, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_policy_decisions_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], name="fk_policy_decisions_request_id_requests", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], name="fk_policy_decisions_workflow_run_id_workflow_runs", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_policy_decisions"),
    )
    op.create_index("ix_policy_decisions_organization_id", "policy_decisions", ["organization_id"], unique=False)
    op.create_index("ix_policy_decisions_request_id", "policy_decisions", ["request_id"], unique=False)
    op.create_index("ix_policy_decisions_workflow_run_id", "policy_decisions", ["workflow_run_id"], unique=False)

    # 4. Bảng yêu cầu phê duyệt ràng buộc 7 yếu tố
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_version_id", sa.String(length=36), nullable=True),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("parameters_json", JSON_TYPE, nullable=False),
        sa.Column("parameter_hash", sa.String(length=64), nullable=False),
        sa.Column("resource_scope", sa.String(length=255), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("required_role", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_by_actor_id", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_decision_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_approval_requests_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_decision_id"], ["policy_decisions.id"], name="fk_approval_requests_policy_decision_id_policy_decisions", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], name="fk_approval_requests_request_id_requests", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], name="fk_approval_requests_workflow_run_id_workflow_runs", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_version_id"], ["workflow_versions.id"], name="fk_approval_requests_workflow_version_id_workflow_versions", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_approval_requests"),
    )
    op.create_index("ix_approval_requests_organization_id", "approval_requests", ["organization_id"], unique=False)
    op.create_index("ix_approval_requests_request_id", "approval_requests", ["request_id"], unique=False)
    op.create_index("ix_approval_requests_workflow_run_id", "approval_requests", ["workflow_run_id"], unique=False)
    op.create_index("ix_approval_requests_workflow_version_id", "approval_requests", ["workflow_version_id"], unique=False)
    op.create_index("ix_approval_requests_parameter_hash", "approval_requests", ["parameter_hash"], unique=False)
    op.create_index("ix_approval_requests_status", "approval_requests", ["status"], unique=False)

    # 5. Bảng kết quả phê duyệt của người có thẩm quyền
    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("approval_request_id", sa.String(length=36), nullable=False),
        sa.Column("approver_membership_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("authority_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["approval_request_id"], ["approval_requests.id"], name="fk_approval_decisions_approval_request_id_approval_requests", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["approver_membership_id"], ["memberships.id"], name="fk_approval_decisions_approver_membership_id_memberships", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_approval_decisions_organization_id_organizations", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_approval_decisions"),
        sa.UniqueConstraint("approval_request_id", name="uq_approval_decisions_approval_request_id"),
    )
    op.create_index("ix_approval_decisions_organization_id", "approval_decisions", ["organization_id"], unique=False)

    # 6. Bảng cấp giấy phép hẹp có thời hạn cho trợ lý AI
    op.create_table(
        "permission_grants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("agent_identity_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_scope", sa.String(length=255), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("granted_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_identity_id"], ["agent_identities.id"], name="fk_permission_grants_agent_identity_id_agent_identities", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], name="fk_permission_grants_granted_by_user_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_permission_grants_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], name="fk_permission_grants_workflow_run_id_workflow_runs", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_permission_grants"),
    )
    op.create_index("ix_permission_grants_organization_id", "permission_grants", ["organization_id"], unique=False)
    op.create_index("ix_permission_grants_agent_identity_id", "permission_grants", ["agent_identity_id"], unique=False)
    op.create_index("ix_permission_grants_workflow_run_id", "permission_grants", ["workflow_run_id"], unique=False)


def downgrade() -> None:
    """Gỡ bỏ 6 bảng của bản nâng cấp 0005 theo thứ tự ngược lại."""
    op.drop_table("permission_grants")
    op.drop_table("approval_decisions")
    op.drop_table("approval_requests")
    op.drop_table("policy_decisions")
    op.drop_table("policy_rules")
    op.drop_table("policy_sets")
