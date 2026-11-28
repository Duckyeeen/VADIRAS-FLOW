"""Lớp bảng cơ sở SQLAlchemy 2 và kiểu dữ liệu tương thích đa cơ sở dữ liệu."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

# Quy ước đặt tên ràng buộc cố định giúp Alembic sinh tên chỉ mục và khóa ngoại nhất quán
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Kiểu JSON linh hoạt: dùng JSONB tối ưu trên PostgreSQL và tự chuyển sang JSON trên SQLite
JSONType = sa.JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Lớp cha chung cho toàn bộ các bảng dữ liệu trong hệ thống."""

    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)
