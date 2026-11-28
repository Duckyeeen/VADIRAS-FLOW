"""Bổ sung 4 bảng cho cài đặt bộ kết nối, phạm vi kho, nhật ký chống trùng lặp và hộp thư webhook.

Mã bản nâng cấp: 0006_connectors_and_webhooks
Kế thừa từ: 0005_governance_and_approvals
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_connectors_and_webhooks"
down_revision: str | tuple[str, ...] | None = "0005_governance_and_approvals"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    """Tạo 4 bảng phục vụ tích hợp GitHub App, chống trùng giao dịch và hộp thư webhook."""
    # 1. Bảng lưu thông tin cài đặt bộ kết nối theo tổ chức
    op.create_table(
        "connector_installations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("connector_type", sa.String(length=64), nullable=False),
        sa.Column("installation_external_id", sa.String(length=128), nullable=False),
        sa.Column("account_login", sa.String(length=128), nullable=False),
        sa.Column("app_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("permissions_json", JSON_TYPE, nullable=False),
        sa.Column("config_json", JSON_TYPE, nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_cursor", sa.String(length=255), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "connector_type",
            "installation_external_id",
            name="uq_connector_installations_org_type_ext",
        ),
    )
    op.create_index("ix_connector_installations_organization_id", "connector_installations", ["organization_id"])
    op.create_index("ix_connector_installations_connector_type", "connector_installations", ["connector_type"])
    op.create_index("ix_connector_installations_status", "connector_installations", ["status"])

    # 2. Bảng giới hạn danh sách kho hoặc tài nguyên được phép thao tác
    op.create_table(
        "connector_resource_scopes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("connector_installation_id", sa.String(length=36), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_identifier", sa.String(length=255), nullable=False),
        sa.Column("allowed_actions_json", JSON_TYPE, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["connector_installation_id"], ["connector_installations.id"], name="fk_connector_scopes_installation_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connector_installation_id",
            "resource_identifier",
            name="uq_connector_scopes_inst_res",
        ),
    )
    op.create_index("ix_connector_resource_scopes_organization_id", "connector_resource_scopes", ["organization_id"])
    op.create_index(
        "ix_connector_resource_scopes_connector_installation_id",
        "connector_resource_scopes",
        ["connector_installation_id"],
    )
    op.create_index(
        "ix_connector_resource_scopes_resource_identifier",
        "connector_resource_scopes",
        ["resource_identifier"],
    )

    # 3. Bảng nhật ký giao dịch bộ kết nối chống tạo trùng khi thử lại
    op.create_table(
        "connector_operation_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("connector_installation_id", sa.String(length=36), nullable=True),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("node_id", sa.String(length=64), nullable=True),
        sa.Column("connector_type", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_scope", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("external_number", sa.Integer(), nullable=True),
        sa.Column("external_url", sa.String(length=1024), nullable=True),
        sa.Column("response_summary_json", JSON_TYPE, nullable=False),
        sa.Column("error_class", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["connector_installation_id"], ["connector_installations.id"], name="fk_connector_ops_installation_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_id"], ["requests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_connector_ops_org_idempotency"),
    )
    op.create_index("ix_connector_operation_records_organization_id", "connector_operation_records", ["organization_id"])
    op.create_index("ix_connector_operation_records_connector_installation_id", "connector_operation_records", ["connector_installation_id"])
    op.create_index("ix_connector_operation_records_request_id", "connector_operation_records", ["request_id"])
    op.create_index("ix_connector_operation_records_workflow_run_id", "connector_operation_records", ["workflow_run_id"])
    op.create_index("ix_connector_operation_records_connector_type", "connector_operation_records", ["connector_type"])
    op.create_index("ix_connector_operation_records_status", "connector_operation_records", ["status"])
    op.create_index("ix_connector_operation_records_external_id", "connector_operation_records", ["external_id"])

    # 4. Bảng hộp thư webhook tiếp nhận và chống trùng theo X-GitHub-Delivery
    op.create_table(
        "webhook_inbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("connector_type", sa.String(length=64), nullable=False),
        sa.Column("delivery_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("installation_external_id", sa.String(length=128), nullable=True),
        sa.Column("repository_full_name", sa.String(length=255), nullable=True),
        sa.Column("signature_verified", sa.Boolean(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("minimal_payload_json", JSON_TYPE, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("correlated_run_id", sa.String(length=36), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id", name="uq_webhook_inbox_delivery_id"),
    )
    op.create_index("ix_webhook_inbox_organization_id", "webhook_inbox", ["organization_id"])
    op.create_index("ix_webhook_inbox_connector_type", "webhook_inbox", ["connector_type"])
    op.create_index("ix_webhook_inbox_event_type", "webhook_inbox", ["event_type"])
    op.create_index("ix_webhook_inbox_installation_external_id", "webhook_inbox", ["installation_external_id"])
    op.create_index("ix_webhook_inbox_status", "webhook_inbox", ["status"])
    op.create_index("ix_webhook_inbox_correlated_run_id", "webhook_inbox", ["correlated_run_id"])


def downgrade() -> None:
    """Xóa 4 bảng bộ kết nối và webhook theo đúng thứ tự phụ thuộc ngược."""
    op.drop_table("webhook_inbox")
    op.drop_table("connector_operation_records")
    op.drop_table("connector_resource_scopes")
    op.drop_table("connector_installations")
