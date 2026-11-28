"""Bộ điều phối hàng đợi sự kiện giao dịch và tiến trình `outbox-worker` chạy nền."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_engine_and_session_factory

from .models import OutboxEvent, OutboxStatus


class OutboxBroadcaster:
    """Kênh phát sự kiện trong bộ nhớ RAM giúp đẩy tức thì bản tin từ `outbox_worker` sang SSE."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        """Đăng ký hàng đợi nhận sự kiện trực tiếp của một lượt chạy quy trình."""
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers[run_id].add(q)
        return q

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Hủy đăng ký hàng đợi khi máy khách ngắt kết nối SSE."""
        subs = self._subscribers.get(run_id)
        if subs is not None:
            subs.discard(queue)
            if not subs:
                self._subscribers.pop(run_id, None)

    def publish_in_memory(self, run_id: str, event_payload: dict[str, Any]) -> None:
        """Gửi bản tin sự kiện tới toàn bộ kết nối đang lắng nghe lượt chạy `run_id`."""
        for q in list(self._subscribers.get(run_id, ())):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(event_payload)


default_broadcaster = OutboxBroadcaster()


class OutboxDispatcher:
    """Đọc các bản ghi `PENDING` từ `outbox_events`, phát sang luồng SSE và đánh dấu đã phát."""

    def __init__(self, broadcaster: OutboxBroadcaster | None = None) -> None:
        self._broadcaster = broadcaster or default_broadcaster

    async def publish_pending_batch(
        self,
        session: AsyncSession,
        *,
        limit: int = 50,
    ) -> int:
        """Đọc và phát tối đa `limit` sự kiện đang chờ, trả về số sự kiện đã phát thành công."""
        stmt = (
            sa.select(OutboxEvent)
            .where(OutboxEvent.status == OutboxStatus.PENDING.value)
            .order_by(OutboxEvent.occurred_at.asc(), OutboxEvent.id.asc())
            .limit(limit)
        )
        rows = list((await session.execute(stmt)).scalars().all())
        if not rows:
            return 0

        now = datetime.now(timezone.utc)
        published_count = 0
        for row in rows:
            row.attempts += 1
            envelope = {
                "event_id": row.event_id,
                "event_type": row.event_type,
                "occurred_at": row.occurred_at.isoformat(),
                "organization_id": row.organization_id,
                "aggregate_type": row.aggregate_type,
                "aggregate_id": row.aggregate_id,
                "aggregate_version": row.aggregate_version,
                "request_id": row.request_id,
                "workflow_run_id": row.workflow_run_id,
                "node_run_id": row.node_run_id,
                "actor_type": row.actor_type,
                "actor_id": row.actor_id,
                "correlation_id": row.correlation_id,
                "schema_version": row.schema_version,
                "payload": dict(row.payload_json or {}),
            }
            if row.workflow_run_id:
                self._broadcaster.publish_in_memory(row.workflow_run_id, envelope)
            row.status = OutboxStatus.PUBLISHED.value
            row.published_at = now
            published_count += 1

        await session.commit()
        return published_count


async def run_outbox_worker(*, poll_interval_seconds: float = 2.0) -> None:
    """Điểm khởi chạy tiến trình `outbox-worker` đọc hàng đợi liên tục."""
    settings = get_settings()
    configure_logging(settings.log_level)
    engine, session_factory = create_engine_and_session_factory(
        settings.database_url,
        echo=settings.database_echo,
    )
    dispatcher = OutboxDispatcher()
    try:
        while True:
            async with session_factory() as session:
                await dispatcher.publish_pending_batch(session, limit=50)
            await asyncio.sleep(poll_interval_seconds)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_outbox_worker())
