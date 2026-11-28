"""Mô hình bảng bộ nhớ tri thức 5 nhóm tương thích `pgvector` trên PostgreSQL và JSON trên SQLite."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

DEFAULT_EMBEDDING_DIMENSIONS = 64

# Trên PostgreSQL dùng kiểu Vector(64) chuẩn của pgvector; trên SQLite cục bộ dùng JSON
VectorType = sa.JSON().with_variant(Vector(DEFAULT_EMBEDDING_DIMENSIONS), "postgresql")


class MemoryClass(str, Enum):
    """5 nhóm bộ nhớ tách biệt mục đích sử dụng và quy tắc kiểm soát."""

    REQUEST_MEMORY = "REQUEST_MEMORY"
    WORKFLOW_MEMORY = "WORKFLOW_MEMORY"
    EXECUTION_MEMORY = "EXECUTION_MEMORY"
    KNOWLEDGE_MEMORY = "KNOWLEDGE_MEMORY"
    FEEDBACK_MEMORY = "FEEDBACK_MEMORY"


class MemoryVerificationStatus(str, Enum):
    """Mức độ xác thực nguồn gốc của mục tri thức trước khi được phép dùng lại."""

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    HUMAN_APPROVED = "HUMAN_APPROVED"


class MemoryReviewStatus(str, Enum):
    """Trạng thái duyệt thăng hạng (chỉ `PROMOTED` mới được phép trả ra khi tìm kiếm)."""

    DRAFT = "DRAFT"
    PROMOTED = "PROMOTED"
    REVOKED = "REVOKED"


class MemoryItem(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, Base):
    """Một mục tri thức hoặc kinh nghiệm xử lý gắn chặt với tổ chức và phân loại quyền xem."""

    __tablename__ = "memory_items"

    department_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("departments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    memory_class: Mapped[str] = mapped_column(sa.String(32), nullable=False, index=True)
    access_classification: Mapped[str] = mapped_column(
        sa.String(32),
        default="INTERNAL_ONLY",
        nullable=False,
        index=True,
    )
    request_type: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    provenance_source: Mapped[str] = mapped_column(sa.String(128), default="manual", nullable=False)
    provenance_ref: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        sa.String(32),
        default=MemoryVerificationStatus.UNVERIFIED.value,
        nullable=False,
        index=True,
    )
    review_status: Mapped[str] = mapped_column(
        sa.String(32),
        default=MemoryReviewStatus.DRAFT.value,
        nullable=False,
        index=True,
    )
    confidence_score: Mapped[float] = mapped_column(sa.Float, default=0.5, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    embedding_model: Mapped[str] = mapped_column(
        sa.String(128),
        default="deterministic-hash-v1",
        nullable=False,
    )
    embedding_provider: Mapped[str] = mapped_column(sa.String(64), default="local", nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(
        sa.Integer,
        default=DEFAULT_EMBEDDING_DIMENSIONS,
        nullable=False,
    )
    embedding_vector: Mapped[list[float]] = mapped_column(VectorType, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
