"""Bổ sung 3 bảng cho Bộ nhớ ngữ nghĩa pgvector, Hàng đợi sự kiện Outbox và Chính sách SLA.

Mã bản nâng cấp: 0008_memory_and_observability
Kế thừa từ: 0007_verification_and_audit
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0008_memory_and_observability"
down_revision: str | tuple[str, ...] | None = "0007_verification_and_audit"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
VECTOR_TYPE = sa.JSON().with_variant(Vector(64), "postgresql")


def upgrade() -> None:
    """Tạo 3 bảng `memory_items`, `outbox_events` và `sla_policies`."""
    # 1. Bảng bộ nhớ tri thức 5 nhóm (lọc quyền và thăng hạng trước khi tìm tương đồng vector)
    op.create_table(
        "memory_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("department_id", sa.String(length=36), nullable=True),
        sa.Column("memory_class", sa.String(length=32), nullable=False),
        sa.Column("access_classification", sa.String(length=32), nullable=False),
        sa.Column("request_type", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provenance_source", sa.String(length=128), nullable=False),
        sa.Column("provenance_ref", sa.String(length=255), nullable=True),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=False),
        sa.Column("embedding_provider", sa.String(length=64), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding_vector", VECTOR_TYPE, nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_items_organization_id", "memory_items", ["organization_id"])
    op.create_index("ix_memory_items_department_id", "memory_items", ["department_id"])
    op.create_index("ix_memory_items_memory_class", "memory_items", ["memory_class"])
    op.create_index("ix_memory_items_access_classification", "memory_items", ["access_classification"])
    op.create_index("ix_memory_items_request_type", "memory_items", ["request_type"])
    op.create_index("ix_memory_items_verification_status", "memory_items", ["verification_status"])
    op.create_index("ix_memory_items_review_status", "memory_items", ["review_status"])

    # 2. Bảng hàng đợi sự kiện giao dịch (outbox) đẩy luồng SSE tin cậy
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("node_run_id", sa.String(length=36), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("causation_id", sa.String(length=128), nullable=True),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("access_classification", sa.String(length=32), nullable=False),
        sa.Column("payload_json", JSON_TYPE, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_outbox_events_event_id"),
    )
    op.create_index("ix_outbox_events_organization_id", "outbox_events", ["organization_id"])
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_aggregate_type", "outbox_events", ["aggregate_type"])
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])
    op.create_index("ix_outbox_events_request_id", "outbox_events", ["request_id"])
    op.create_index("ix_outbox_events_workflow_run_id", "outbox_events", ["workflow_run_id"])
    op.create_index("ix_outbox_events_correlation_id", "outbox_events", ["correlation_id"])
    op.create_index("ix_outbox_events_access_classification", "outbox_events", ["access_classification"])
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"])
    op.create_index("ix_outbox_events_occurred_at", "outbox_events", ["occurred_at"])

    # 3. Bảng chính sách cam kết thời gian xử lý (SLA) theo tổ chức
    op.create_table(
        "sla_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("request_type", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("target_response_minutes", sa.Integer(), nullable=False),
        sa.Column("target_resolution_minutes", sa.Integer(), nullable=False),
        sa.Column("warning_threshold_ratio", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "code", name="uq_sla_policies_org_code"),
    )
    op.create_index("ix_sla_policies_organization_id", "sla_policies", ["organization_id"])
    op.create_index("ix_sla_policies_request_type", "sla_policies", ["request_type"])
    op.create_index("ix_sla_policies_priority", "sla_policies", ["priority"])


def downgrade() -> None:
    """Xóa 3 bảng bộ nhớ và quan sát theo thứ tự ngược lại."""
    op.drop_table("sla_policies")
    op.drop_table("outbox_events")
    op.drop_table("memory_items")
