"""Bổ sung 4 bảng theo dõi phiên bản câu lệnh, tác vụ trợ lý AI, lượt chạy và chi phí gọi AI.

Mã bản nâng cấp: 0003_ai_and_agent_execution
Kế thừa từ: 0002_request_domain
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_ai_and_agent_execution"
down_revision: str | tuple[str, ...] | None = "0002_request_domain"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    """Tạo 4 bảng cho phân hệ Trí tuệ AI và theo dõi chi phí gọi mô hình."""
    # 1. Bảng lưu vết các phiên bản câu lệnh hệ thống
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("role_code", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("output_schema_name", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_prompt_versions_organization_id_organizations", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_versions"),
        sa.UniqueConstraint("organization_id", "role_code", "version", name="uq_prompt_versions_org_role_ver"),
    )
    op.create_index("ix_prompt_versions_organization_id", "prompt_versions", ["organization_id"], unique=False)

    # 2. Bảng đầu việc phân tích giao cho trợ lý AI
    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("analysis_job_id", sa.String(length=64), nullable=False),
        sa.Column("agent_identity_id", sa.String(length=36), nullable=True),
        sa.Column("role_code", sa.String(length=64), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_snapshot_json", JSON_TYPE, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_identity_id"], ["agent_identities.id"], name="fk_agent_tasks_agent_identity_id_agent_identities", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_agent_tasks_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], name="fk_agent_tasks_request_id_requests", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_agent_tasks"),
    )
    op.create_index("ix_agent_tasks_organization_id", "agent_tasks", ["organization_id"], unique=False)
    op.create_index("ix_agent_tasks_request_id", "agent_tasks", ["request_id"], unique=False)
    op.create_index("ix_agent_tasks_analysis_job_id", "agent_tasks", ["analysis_job_id"], unique=False)
    op.create_index("ix_agent_tasks_agent_identity_id", "agent_tasks", ["agent_identity_id"], unique=False)

    # 3. Bảng kết quả từng lượt chạy trợ lý AI
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("agent_task_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("analysis_job_id", sa.String(length=64), nullable=False),
        sa.Column("role_code", sa.String(length=64), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("structured_output_json", JSON_TYPE, nullable=False),
        sa.Column("decision_summary", sa.Text(), nullable=False),
        sa.Column("assumptions_json", JSON_TYPE, nullable=False),
        sa.Column("evidence_refs_json", JSON_TYPE, nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_task_id"], ["agent_tasks.id"], name="fk_agent_runs_agent_task_id_agent_tasks", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_agent_runs_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], name="fk_agent_runs_request_id_requests", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_agent_runs"),
    )
    op.create_index("ix_agent_runs_organization_id", "agent_runs", ["organization_id"], unique=False)
    op.create_index("ix_agent_runs_agent_task_id", "agent_runs", ["agent_task_id"], unique=False)
    op.create_index("ix_agent_runs_request_id", "agent_runs", ["request_id"], unique=False)
    op.create_index("ix_agent_runs_analysis_job_id", "agent_runs", ["analysis_job_id"], unique=False)

    # 4. Bảng theo dõi từng lượt gọi mô hình AI kèm chi phí và độ trễ
    op.create_table(
        "llm_call_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("agent_run_id", sa.String(length=36), nullable=True),
        sa.Column("analysis_job_id", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("repair_attempts", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("cost_source", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], name="fk_llm_call_records_agent_run_id_agent_runs", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_llm_call_records_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], name="fk_llm_call_records_request_id_requests", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_llm_call_records"),
    )
    op.create_index("ix_llm_call_records_organization_id", "llm_call_records", ["organization_id"], unique=False)
    op.create_index("ix_llm_call_records_request_id", "llm_call_records", ["request_id"], unique=False)
    op.create_index("ix_llm_call_records_agent_run_id", "llm_call_records", ["agent_run_id"], unique=False)
    op.create_index("ix_llm_call_records_analysis_job_id", "llm_call_records", ["analysis_job_id"], unique=False)


def downgrade() -> None:
    """Gỡ bỏ 4 bảng của bản nâng cấp 0003 theo thứ tự ngược lại."""
    op.drop_table("llm_call_records")
    op.drop_table("agent_runs")
    op.drop_table("agent_tasks")
    op.drop_table("prompt_versions")
