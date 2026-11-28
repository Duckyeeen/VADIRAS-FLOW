"""Quản lý động cơ kết nối và phiên làm việc bất đồng bộ với cơ sở dữ liệu."""

from __future__ import annotations

from collections.abc import AsyncIterator

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine_and_session_factory(
    database_url: str,
    *,
    echo: bool = False,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Khởi tạo động cơ kết nối bất đồng bộ và bộ tạo phiên làm việc SQLAlchemy.

    1. Bật `pool_pre_ping=True` đối với PostgreSQL để tự phát hiện kết nối bị ngắt.
    2. Nếu dùng SQLite cho môi trường kiểm thử cục bộ, bỏ qua tham số hồ bơi kết nối
       không phù hợp và bật kiểm tra khóa ngoại `PRAGMA foreign_keys=ON`.
    Đầu ra: bộ đôi `(AsyncEngine, async_sessionmaker)`.
    """
    is_sqlite = database_url.startswith("sqlite")
    engine_kwargs: dict[str, object] = {"echo": echo}
    if not is_sqlite:
        engine_kwargs["pool_pre_ping"] = True

    engine = create_async_engine(database_url, **engine_kwargs)

    if is_sqlite:
        @sa.event.listens_for(engine.sync_engine, "connect")
        def _enable_sqlite_fk(dbapi_connection: object, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return engine, session_factory


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Cung cấp một phiên làm việc cơ sở dữ liệu riêng cho mỗi yêu cầu HTTP.

    Lấy `session_factory` từ trạng thái ứng dụng (`app.state.session_factory`) để
    dễ dàng thay thế bằng cơ sở dữ liệu kiểm thử độc lập.
    """
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def check_database_health(session_factory: async_sessionmaker[AsyncSession]) -> bool:
    """Kiểm tra nhanh khả năng kết nối tới cơ sở dữ liệu bằng truy vấn `SELECT 1`.

    Đầu ra: `True` nếu cơ sở dữ liệu phản hồi bình thường, `False` nếu gặp lỗi.
    """
    try:
        async with session_factory() as session:
            await session.execute(sa.text("SELECT 1"))
        return True
    except Exception:
        return False
