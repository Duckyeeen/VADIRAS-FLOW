"""Lệnh nạp dữ liệu mẫu cho môi trường phát triển cục bộ (`python -m scripts.seed_demo`)."""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.db.session import create_engine_and_session_factory
from data.seeds.demo_seed import seed_demo_data


async def _run() -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_session_factory(settings.database_url)
    try:
        async with session_factory() as session:
            summary = await seed_demo_data(session)
        print(
            f"Đã nạp dữ liệu mẫu thành công: org={summary.organization_id}, "
            f"phòng_ban={summary.departments_count}, tài_khoản={summary.users_count}, "
            f"trợ_lý_AI={summary.agents_count}, yêu_cầu={summary.requests_count}"
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
