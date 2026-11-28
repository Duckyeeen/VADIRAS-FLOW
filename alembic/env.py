"""Tệp điều phối chạy nâng cấp cơ sở dữ liệu Alembic theo chế độ bất đồng bộ."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.base import Base

# Nạp trước mô hình các bảng để Alembic nhận diện đầy đủ cấu trúc khi so sánh
import app.modules.ai_intelligence.models  # noqa: F401
import app.modules.connectors.models  # noqa: F401
import app.modules.governance.models  # noqa: F401
import app.modules.identity.models  # noqa: F401
import app.modules.memory.models  # noqa: F401
import app.modules.observability.models  # noqa: F401
import app.modules.requests.models  # noqa: F401
import app.modules.verification.models  # noqa: F401
import app.modules.workflows.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_database_url() -> str:
    """Ưu tiên đọc chuỗi kết nối từ biến môi trường `DATABASE_URL` hoặc cấu hình `alembic.ini`."""
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Sinh mã SQL nâng cấp bảng ở chế độ ngoại tuyến (không mở kết nối trực tiếp tới CSDL)."""
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _ensure_alembic_version_column_width(connection: Connection) -> None:
    """Mở rộng cột `version_num` của `alembic_version` trên PostgreSQL do tên revision dài hơn 32 ký tự."""
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            "version_num VARCHAR(128) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
            ")"
        )
    )
    connection.execute(
        sa.text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")
    )


def do_run_migrations(connection: Connection) -> None:
    """Chạy các bước nâng cấp bảng trên kết nối đồng bộ được cầu nối từ phiên bất đồng bộ."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        _ensure_alembic_version_column_width(connection)
        context.run_migrations()


async def run_async_migrations() -> None:
    """Mở kết nối bất đồng bộ tới PostgreSQL hoặc SQLite để chạy nâng cấp bảng."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _resolve_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Điểm vào chạy nâng cấp bảng trực tiếp lên cơ sở dữ liệu."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
