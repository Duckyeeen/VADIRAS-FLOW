"""Các bảng cơ sở dữ liệu cho cài đặt bộ kết nối, phạm vi kho, nhật ký chống trùng lặp và hộp thư webhook."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType
from app.db.mixins import OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class InstallationStatus(str, Enum):
    """Trạng thái hoạt động của một bản cài đặt bộ kết nối theo tổ chức."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class OperationRecordStatus(str, Enum):
    """Trạng thái thực thi của một thao tác gọi ra hệ thống ngoài gắn khóa chống trùng lặp."""

    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RECONCILED = "RECONCILED"


class WebhookInboxStatus(str, Enum):
    """Trạng thái tiếp nhận và đối chiếu của một sự kiện webhook gửi vào hệ thống."""

    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    IGNORED = "IGNORED"
    FAILED = "FAILED"


class ConnectorInstallation(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Thông tin cài đặt bộ kết nối (GitHub App hoặc Mock GitHub) gắn với từng tổ chức."""

    __tablename__ = "connector_installations"
    __table_args__ = (
        sa.UniqueConstraint(
            "organization_id",
            "connector_type",
            "installation_external_id",
            name="uq_connector_installations_org_type_ext",
        ),
    )

    connector_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    installation_external_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    account_login: Mapped[str] = mapped_column(sa.String(128), default="vadiras-demo", nullable=False)
    app_id: Mapped[str] = mapped_column(sa.String(64), default="", nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        default=InstallationStatus.ACTIVE.value,
        nullable=False,
        index=True,
    )
    permissions_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    config_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    sync_cursor: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    resource_scopes: Mapped[list[ConnectorResourceScope]] = relationship(
        "ConnectorResourceScope",
        back_populates="installation",
        cascade="all, delete-orphan",
    )


class ConnectorResourceScope(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Danh sách kho hoặc tài nguyên cụ thể mà bản cài đặt bộ kết nối được phép truy cập."""

    __tablename__ = "connector_resource_scopes"
    __table_args__ = (
        sa.UniqueConstraint(
            "connector_installation_id",
            "resource_identifier",
            name="uq_connector_scopes_inst_res",
        ),
    )

    connector_installation_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("connector_installations.id", ondelete="CASCADE", name="fk_connector_scopes_installation_id"),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[str] = mapped_column(sa.String(64), default="repository", nullable=False)
    resource_identifier: Mapped[str] = mapped_column(sa.String(255), nullable=False, index=True)
    allowed_actions_json: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)

    installation: Mapped[ConnectorInstallation] = relationship(
        "ConnectorInstallation",
        back_populates="resource_scopes",
    )


class ConnectorOperationRecord(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Nhật ký giao dịch ra hệ thống ngoài bảo đảm chống trùng lặp khi thử lại nhiều lần."""

    __tablename__ = "connector_operation_records"
    __table_args__ = (
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_connector_ops_org_idempotency",
        ),
    )

    connector_installation_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("connector_installations.id", ondelete="SET NULL", name="fk_connector_ops_installation_id"),
        nullable=True,
        index=True,
    )
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
    connector_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    resource_scope: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    request_payload_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        default=OperationRecordStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    external_id: Mapped[str | None] = mapped_column(sa.String(255), nullable=True, index=True)
    external_number: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    external_url: Mapped[str | None] = mapped_column(sa.String(1024), nullable=True)
    response_summary_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    error_class: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)


class WebhookInbox(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Hộp thư lưu sự kiện webhook đã xác thực chữ ký để chống nhận trùng và xử lý bất đồng bộ."""

    __tablename__ = "webhook_inbox"
    __table_args__ = (
        sa.UniqueConstraint("delivery_id", name="uq_webhook_inbox_delivery_id"),
    )

    organization_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    connector_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    delivery_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    installation_external_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)
    repository_full_name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    signature_verified: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    payload_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    minimal_payload_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        default=WebhookInboxStatus.RECEIVED.value,
        nullable=False,
        index=True,
    )
    correlated_run_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
