"""Bổ sung 6 bảng cho phân hệ Tiếp nhận Yêu cầu, Thành viên, Đính kèm, Tin nhắn, Phân tích và Đầu việc.

Mã bản nâng cấp: 0002_request_domain
Kế thừa từ: 0001_enable_pgvector_and_identity
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_request_domain"
down_revision: str | tuple[str, ...] | None = "0001_enable_pgvector_and_identity"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    """Tạo 6 bảng nghiệp vụ tiếp nhận yêu cầu công việc và tác vụ con người."""
    # 1. Bảng yêu cầu công việc
    op.create_table(
        "requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("request_number", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sanitized_description", sa.Text(), nullable=False),
        sa.Column("pii_redactions_json", JSON_TYPE, nullable=False),
        sa.Column("injection_flags_json", JSON_TYPE, nullable=False),
        sa.Column("request_type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("business_outcome", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("impact", sa.String(length=32), nullable=False),
        sa.Column("urgency", sa.String(length=32), nullable=False),
        sa.Column("requester_membership_id", sa.String(length=36), nullable=False),
        sa.Column("requester_kind", sa.String(length=32), nullable=False),
        sa.Column("customer_account_ref", sa.String(length=128), nullable=True),
        sa.Column("department_id", sa.String(length=36), nullable=True),
        sa.Column("proposed_departments_json", JSON_TYPE, nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_policy_ref", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", JSON_TYPE, nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_requests_created_by_user_id_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], name="fk_requests_department_id_departments", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_requests_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_membership_id"], ["memberships.id"], name="fk_requests_requester_membership_id_memberships", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], name="fk_requests_updated_by_user_id_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_requests"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_requests_org_idempotency"),
        sa.UniqueConstraint("organization_id", "request_number", name="uq_requests_org_number"),
    )
    op.create_index("ix_requests_organization_id", "requests", ["organization_id"], unique=False)
    op.create_index("ix_requests_request_type", "requests", ["request_type"], unique=False)
    op.create_index("ix_requests_status", "requests", ["status"], unique=False)
    op.create_index("ix_requests_requester_membership_id", "requests", ["requester_membership_id"], unique=False)
    op.create_index("ix_requests_customer_account_ref", "requests", ["customer_account_ref"], unique=False)
    op.create_index("ix_requests_department_id", "requests", ["department_id"], unique=False)
    op.create_index("ix_requests_content_hash", "requests", ["content_hash"], unique=False)

    # 2. Bảng thành viên tham gia yêu cầu
    op.create_table(
        "request_participants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("membership_id", sa.String(length=36), nullable=False),
        sa.Column("participant_role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], name="fk_request_participants_membership_id_memberships", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_request_participants_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], name="fk_request_participants_request_id_requests", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_request_participants"),
        sa.UniqueConstraint("request_id", "membership_id", "participant_role", name="uq_request_participants_member_role"),
    )
    op.create_index("ix_request_participants_organization_id", "request_participants", ["organization_id"], unique=False)
    op.create_index("ix_request_participants_request_id", "request_participants", ["request_id"], unique=False)
    op.create_index("ix_request_participants_membership_id", "request_participants", ["membership_id"], unique=False)

    # 3. Bảng tệp đính kèm yêu cầu
    op.create_table(
        "request_attachments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("uploaded_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_ref", sa.String(length=1024), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_request_attachments_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], name="fk_request_attachments_request_id_requests", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_membership_id"], ["memberships.id"], name="fk_request_attachments_uploaded_by_membership_id_memberships", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_request_attachments"),
    )
    op.create_index("ix_request_attachments_organization_id", "request_attachments", ["organization_id"], unique=False)
    op.create_index("ix_request_attachments_request_id", "request_attachments", ["request_id"], unique=False)

    # 4. Bảng tin nhắn trao đổi gắn nhãn hiển thị khách hàng/nội bộ
    op.create_table(
        "request_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("author_membership_id", sa.String(length=36), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("message_kind", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["author_membership_id"], ["memberships.id"], name="fk_request_messages_author_membership_id_memberships", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_request_messages_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], name="fk_request_messages_request_id_requests", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_request_messages"),
    )
    op.create_index("ix_request_messages_organization_id", "request_messages", ["organization_id"], unique=False)
    op.create_index("ix_request_messages_request_id", "request_messages", ["request_id"], unique=False)
    op.create_index("ix_request_messages_visibility", "request_messages", ["visibility"], unique=False)

    # 5. Bảng lưu các phiên bản kết quả phân tích AI
    op.create_table(
        "request_analyses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("analysis_job_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("structured_output_json", JSON_TYPE, nullable=False),
        sa.Column("decision_summary", sa.Text(), nullable=False),
        sa.Column("assumptions_json", JSON_TYPE, nullable=False),
        sa.Column("evidence_refs_json", JSON_TYPE, nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_request_analyses_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], name="fk_request_analyses_request_id_requests", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_request_analyses"),
        sa.UniqueConstraint("request_id", "version_number", name="uq_request_analyses_req_ver"),
    )
    op.create_index("ix_request_analyses_organization_id", "request_analyses", ["organization_id"], unique=False)
    op.create_index("ix_request_analyses_request_id", "request_analyses", ["request_id"], unique=False)
    op.create_index("ix_request_analyses_analysis_job_id", "request_analyses", ["analysis_job_id"], unique=False)

    # 6. Bảng đầu việc giao cho con người xử lý
    op.create_table(
        "human_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("department_id", sa.String(length=36), nullable=True),
        sa.Column("assignee_membership_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("evidence_json", JSON_TYPE, nullable=False),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assignee_membership_id"], ["memberships.id"], name="fk_human_tasks_assignee_membership_id_memberships", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], name="fk_human_tasks_department_id_departments", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_human_tasks_organization_id_organizations", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], name="fk_human_tasks_request_id_requests", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_human_tasks"),
    )
    op.create_index("ix_human_tasks_organization_id", "human_tasks", ["organization_id"], unique=False)
    op.create_index("ix_human_tasks_request_id", "human_tasks", ["request_id"], unique=False)
    op.create_index("ix_human_tasks_workflow_run_id", "human_tasks", ["workflow_run_id"], unique=False)
    op.create_index("ix_human_tasks_department_id", "human_tasks", ["department_id"], unique=False)
    op.create_index("ix_human_tasks_assignee_membership_id", "human_tasks", ["assignee_membership_id"], unique=False)
    op.create_index("ix_human_tasks_status", "human_tasks", ["status"], unique=False)


def downgrade() -> None:
    """Gỡ bỏ toàn bộ 6 bảng của bản nâng cấp 0002 theo thứ tự ngược lại."""
    op.drop_table("human_tasks")
    op.drop_table("request_analyses")
    op.drop_table("request_messages")
    op.drop_table("request_attachments")
    op.drop_table("request_participants")
    op.drop_table("requests")
