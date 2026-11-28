"""Bộ phát luồng sự kiện trực tiếp SSE cho lượt chạy quy trình có lọc quyền và tổ chức."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.runtime import repository as runtime_repo
from app.modules.runtime.state_machine import TERMINAL_RUN_STATUSES

from .models import OutboxEvent
from .outbox import OutboxBroadcaster, default_broadcaster


def _format_sse(event_name: str, payload: dict[str, Any], event_id: str | None = None) -> str:
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_name}")
    lines.append(f"data: {json.dumps(payload, ensure_ascii=False, default=str)}")
    return "\n".join(lines) + "\n\n"


async def stream_workflow_run_events(
    session: AsyncSession,
    *,
    organization_id: str,
    run_id: str,
    once: bool = False,
    broadcaster: OutboxBroadcaster | None = None,
) -> AsyncIterator[str]:
    """Phát ảnh chụp tiến độ ban đầu (`snapshot`) kèm các sự kiện `outbox_events` tiếp theo qua SSE."""
    run = await runtime_repo.get_run_by_id(
        session, organization_id=organization_id, run_id=run_id
    )
    if run is None:
        return

    node_runs = await runtime_repo.list_node_runs(
        session, organization_id=organization_id, workflow_run_id=run_id
    )
    snapshot_payload = {
        "workflow_run_id": run.id,
        "request_id": run.request_id,
        "status": run.status,
        "workflow_version_id": run.workflow_version_id,
        "replan_count": run.replan_count,
        "node_runs": [
            {
                "node_id": nr.node_id,
                "node_type": nr.node_type,
                "status": nr.status,
                "attempt": nr.attempt,
            }
            for nr in node_runs
        ],
    }
    yield _format_sse("snapshot", snapshot_payload, event_id=f"snapshot-{run.id}")

    # Phát các sự kiện đã có trong outbox gắn với lượt chạy này
    ev_stmt = (
        sa.select(OutboxEvent)
        .where(
            OutboxEvent.organization_id == organization_id,
            OutboxEvent.workflow_run_id == run_id,
        )
        .order_by(OutboxEvent.occurred_at.asc(), OutboxEvent.id.asc())
    )
    existing_events = list((await session.execute(ev_stmt)).scalars().all())
    for ev in existing_events:
        yield _format_sse(
            ev.event_type,
            {
                "event_id": ev.event_id,
                "event_type": ev.event_type,
                "occurred_at": ev.occurred_at.isoformat(),
                "workflow_run_id": ev.workflow_run_id,
                "request_id": ev.request_id,
                "actor_type": ev.actor_type,
                "actor_id": ev.actor_id,
                "payload": dict(ev.payload_json or {}),
            },
            event_id=ev.event_id,
        )

    if once or run.status in TERMINAL_RUN_STATUSES:
        return

    active_broadcaster = broadcaster or default_broadcaster
    queue = active_broadcaster.subscribe(run_id)
    try:
        for _ in range(3):
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield _format_sse(
                    str(item.get("event_type") or "WORKFLOW_EVENT"),
                    item,
                    event_id=str(item.get("event_id") or ""),
                )
            except asyncio.TimeoutError:
                yield _format_sse("ping", {"workflow_run_id": run_id})
                break
    finally:
        active_broadcaster.unsubscribe(run_id, queue)
