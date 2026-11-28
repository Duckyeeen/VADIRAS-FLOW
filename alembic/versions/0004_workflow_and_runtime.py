"""Bổ sung 5 bảng định nghĩa quy trình, phiên bản bất biến, lượt chạy, bước chạy và đề xuất lập lại.

Mã bản nâng cấp: 0004_workflow_and_runtime
Kế thừa từ: 0003_ai_and_agent_execution
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_workflow_and_runtime"
down_revision: str | tuple[str, ...] | None = "0003_ai_and_agent_execution"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    """Tạo 5 bảng quản lý sơ đồ quy trình và trạng thái thực thi."""
    # 1. Bảng định nghĩa quy trình
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("domain_pack", sa.String(length=64), nullable=False),
        sa.Column("request_type", sa.String(length=64), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_workflow_definitions_created_by_user_id_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_workflow_definitions_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], name="fk_workflow_definitions_updated_by_user_id_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_definitions"),
        sa.UniqueConstraint("organization_id", "code", name="uq_workflow_definitions_org_code"),
    )
    op.create_index("ix_workflow_definitions_organization_id", "workflow_definitions", ["organization_id"], unique=False)
    op.create_index("ix_workflow_definitions_request_type", "workflow_definitions", ["request_type"], unique=False)

    # 2. Bảng phiên bản sơ đồ quy trình
    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_definition_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("graph_json", JSON_TYPE, nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("validation_report_json", JSON_TYPE, nullable=False),
        sa.Column("score_summary_json", JSON_TYPE, nullable=False),
        sa.Column("created_from_analysis_id", sa.String(length=36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_workflow_versions_created_by_user_id_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_from_analysis_id"], ["request_analyses.id"], name="fk_workflow_versions_created_from_analysis_id_request_analyses", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_workflow_versions_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_definition_id"], ["workflow_definitions.id"], name="fk_workflow_versions_definition_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_versions"),
        sa.UniqueConstraint("workflow_definition_id", "version_number", name="uq_workflow_versions_def_num"),
    )
    op.create_index("ix_workflow_versions_organization_id", "workflow_versions", ["organization_id"], unique=False)
    op.create_index("ix_workflow_versions_workflow_definition_id", "workflow_versions", ["workflow_definition_id"], unique=False)
    op.create_index("ix_workflow_versions_status", "workflow_versions", ["status"], unique=False)
    op.create_index("ix_workflow_versions_content_hash", "workflow_versions", ["content_hash"], unique=False)

    # 3. Bảng lượt chạy quy trình
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_definition_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_version_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_content_hash", sa.String(length=64), nullable=False),
        sa.Column("temporal_workflow_id", sa.String(length=128), nullable=False),
        sa.Column("temporal_run_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("replan_count", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("started_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_summary_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_workflow_runs_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], name="fk_workflow_runs_request_id_requests", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["started_by_user_id"], ["users.id"], name="fk_workflow_runs_started_by_user_id_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workflow_definition_id"], ["workflow_definitions.id"], name="fk_workflow_runs_workflow_definition_id_workflow_definitions", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workflow_version_id"], ["workflow_versions.id"], name="fk_workflow_runs_workflow_version_id_workflow_versions", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_runs"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_workflow_runs_org_idempotency"),
    )
    op.create_index("ix_workflow_runs_organization_id", "workflow_runs", ["organization_id"], unique=False)
    op.create_index("ix_workflow_runs_request_id", "workflow_runs", ["request_id"], unique=False)
    op.create_index("ix_workflow_runs_workflow_version_id", "workflow_runs", ["workflow_version_id"], unique=False)
    op.create_index("ix_workflow_runs_temporal_workflow_id", "workflow_runs", ["temporal_workflow_id"], unique=False)
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"], unique=False)

    # 4. Bảng trạng thái từng bước trong lượt chạy
    op.create_table(
        "workflow_node_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("node_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("input_summary_json", JSON_TYPE, nullable=False),
        sa.Column("output_summary_json", JSON_TYPE, nullable=False),
        sa.Column("error_class", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_workflow_node_runs_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], name="fk_workflow_node_runs_workflow_run_id_workflow_runs", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_node_runs"),
        sa.UniqueConstraint("workflow_run_id", "node_id", "attempt", name="uq_node_runs_run_node_attempt"),
    )
    op.create_index("ix_workflow_node_runs_organization_id", "workflow_node_runs", ["organization_id"], unique=False)
    op.create_index("ix_workflow_node_runs_workflow_run_id", "workflow_node_runs", ["workflow_run_id"], unique=False)
    op.create_index("ix_workflow_node_runs_status", "workflow_node_runs", ["status"], unique=False)

    # 5. Bảng đề xuất lập lại sơ đồ quy trình khi có sự cố
    op.create_table(
        "workflow_replan_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=False),
        sa.Column("proposed_version_id", sa.String(length=36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("scope_delta_json", JSON_TYPE, nullable=False),
        sa.Column("risk_escalated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("proposed_by_actor_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_workflow_replan_proposals_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_version_id"], ["workflow_versions.id"], name="fk_replan_proposals_parent_version_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["proposed_version_id"], ["workflow_versions.id"], name="fk_replan_proposals_proposed_version_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], name="fk_workflow_replan_proposals_workflow_run_id_workflow_runs", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_replan_proposals"),
    )
    op.create_index("ix_workflow_replan_proposals_organization_id", "workflow_replan_proposals", ["organization_id"], unique=False)
    op.create_index("ix_workflow_replan_proposals_workflow_run_id", "workflow_replan_proposals", ["workflow_run_id"], unique=False)


def downgrade() -> None:
    """Gỡ bỏ 5 bảng của bản nâng cấp 0004 theo thứ tự ngược lại."""
    op.drop_table("workflow_replan_proposals")
    op.drop_table("workflow_node_runs")
    op.drop_table("workflow_runs")
    op.drop_table("workflow_versions")
    op.drop_table("workflow_definitions")
