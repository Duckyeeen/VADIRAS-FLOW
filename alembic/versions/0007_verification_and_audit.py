"""Bổ sung 3 bảng cho Bộ máy Xác minh Bằng chứng và Nhật ký Kiểm toán chỉ thêm mới.

Mã bản nâng cấp: 0007_verification_and_audit
Kế thừa từ: 0006_connectors_and_webhooks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_verification_and_audit"
down_revision: str | tuple[str, ...] | None = "0006_connectors_and_webhooks"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    """Tạo 3 bảng `verification_runs`, `execution_evidence` và `audit_logs`."""
    # 1. Bảng kết quả từng lượt đánh giá xác minh
    op.create_table(
        "verification_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("node_id", sa.String(length=64), nullable=True),
        sa.Column("evaluator_type", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("postconditions_json", JSON_TYPE, nullable=False),
        sa.Column("evaluated_criteria_json", JSON_TYPE, nullable=False),
        sa.Column("rationale_summary", sa.Text(), nullable=False),
        sa.Column("freshness_seconds", sa.Integer(), nullable=False),
        sa.Column("requires_human_confirmation", sa.Boolean(), nullable=False),
        sa.Column("human_confirmed_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_verification_runs_organization_id", "verification_runs", ["organization_id"])
    op.create_index("ix_verification_runs_request_id", "verification_runs", ["request_id"])
    op.create_index("ix_verification_runs_workflow_run_id", "verification_runs", ["workflow_run_id"])
    op.create_index("ix_verification_runs_outcome", "verification_runs", ["outcome"])

    # 2. Bảng bằng chứng đối chiếu ngược thu thập được
    op.create_table(
        "execution_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("verification_run_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("resource_identifier", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("verification_rule", sa.String(length=128), nullable=False),
        sa.Column("is_fresh", sa.Boolean(), nullable=False),
        sa.Column("access_classification", sa.String(length=32), nullable=False),
        sa.Column("evidence_summary_json", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verification_run_id"], ["verification_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_execution_evidence_organization_id", "execution_evidence", ["organization_id"])
    op.create_index("ix_execution_evidence_verification_run_id", "execution_evidence", ["verification_run_id"])
    op.create_index("ix_execution_evidence_request_id", "execution_evidence", ["request_id"])
    op.create_index("ix_execution_evidence_workflow_run_id", "execution_evidence", ["workflow_run_id"])
    op.create_index("ix_execution_evidence_source_type", "execution_evidence", ["source_type"])
    op.create_index("ix_execution_evidence_access_classification", "execution_evidence", ["access_classification"])

    # 3. Bảng nhật ký kiểm toán chỉ được phép thêm mới
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("node_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("policy_decision", sa.String(length=64), nullable=True),
        sa.Column("policy_version", sa.String(length=64), nullable=True),
        sa.Column("approval_id", sa.String(length=36), nullable=True),
        sa.Column("outcome", sa.String(length=64), nullable=False),
        sa.Column("evidence_ref", sa.String(length=255), nullable=True),
        sa.Column("parameter_hash", sa.String(length=64), nullable=True),
        sa.Column("safe_metadata_json", JSON_TYPE, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_organization_id", "audit_logs", ["organization_id"])
    op.create_index("ix_audit_logs_actor_type", "audit_logs", ["actor_type"])
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])
    op.create_index("ix_audit_logs_workflow_run_id", "audit_logs", ["workflow_run_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_correlation_id", "audit_logs", ["correlation_id"])
    op.create_index("ix_audit_logs_outcome", "audit_logs", ["outcome"])
    op.create_index("ix_audit_logs_occurred_at", "audit_logs", ["occurred_at"])


def downgrade() -> None:
    """Xóa 3 bảng xác minh và kiểm toán theo đúng thứ tự phụ thuộc ngược."""
    op.drop_table("audit_logs")
    op.drop_table("execution_evidence")
    op.drop_table("verification_runs")
