"""Các bảng cơ sở dữ liệu cho hàng đợi sự kiện giao dịch (`outbox_events`) và chính sách thời hạn (`sla_policies`)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType
from app.db.mixins import OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class OutboxStatus(str, Enum):
    """Trạng thái phát hành của một sự kiện trong bảng hàng đợi giao dịch."""

    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class OutboxEvent(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Lưu sự kiện hệ thống trong cùng giao dịch CSDL để đẩy ra SSE an toàn, không thất lạc."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        sa.UniqueConstraint("event_id", name="uq_outbox_events_event_id"),
    )

    event_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    aggregate_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    aggregate_version: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    request_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    workflow_run_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    node_run_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    actor_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)
    causation_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    schema_version: Mapped[str] = mapped_column(sa.String(16), default="1.0", nullable=False)
    access_classification: Mapped[str] = mapped_column(
        sa.String(32),
        default="INTERNAL_ONLY",
        nullable=False,
        index=True,
    )
    payload_json: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        default=OutboxStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False, index=True)
    published_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class SlaPolicy(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Chính sách cam kết thời gian phản hồi và giải quyết theo loại yêu cầu và mức độ ưu tiên."""

    __tablename__ = "sla_policies"
    __table_args__ = (
        sa.UniqueConstraint("organization_id", "code", name="uq_sla_policies_org_code"),
    )

    code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    request_type: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    target_response_minutes: Mapped[int] = mapped_column(sa.Integer, default=15, nullable=False)
    target_resolution_minutes: Mapped[int] = mapped_column(sa.Integer, default=240, nullable=False)
    warning_threshold_ratio: Mapped[float] = mapped_column(sa.Float, default=0.8, nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
