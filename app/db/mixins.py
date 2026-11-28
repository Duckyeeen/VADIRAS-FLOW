"""Các nhóm cột dùng chung cho bảng dữ liệu: khóa chính UUID, dấu thời gian và mã tổ chức."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column


def utc_now() -> datetime:
    """Trả về thời điểm hiện tại theo chuẩn múi giờ UTC."""
    return datetime.now(timezone.utc)


class UUIDPrimaryKeyMixin:
    """Bổ sung cột khóa chính `id` dạng chuỗi UUID dài 36 ký tự."""

    id: Mapped[str] = mapped_column(
        sa.String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )


class TimestampMixin:
    """Bổ sung cặp cột `created_at` và `updated_at` có múi giờ UTC."""

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class OrgScopedMixin:
    """Bắt buộc gắn mã tổ chức `organization_id` có chỉ mục để cô lập dữ liệu từng tổ chức."""

    organization_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
