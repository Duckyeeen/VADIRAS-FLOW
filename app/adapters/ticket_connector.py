"""Giao diện kết nối để tạo phiếu công việc trên hệ thống bên ngoài (tương thích cũ)."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.core.config import get_settings
from app.modules.connectors.providers.base import ConnectorExecutionContext
from app.modules.connectors.providers.factory import build_github_connector

from .schemas import ExternalReferences, ProposedAction


def create_ticket(action: ProposedAction) -> ExternalReferences:
    """Thực thi hành động tạo phiếu `ProposedAction` đã được duyệt và trả về `ExternalReferences`."""
    settings = get_settings()
    allowed_repos = settings.get_github_allowed_repos_list() or ["Duckyeeen/VADIRAS-FLOW"]
    target_repo = allowed_repos[0]
    connector = build_github_connector(settings)
    ctx = ConnectorExecutionContext(
        organization_id="legacy-adapter",
        repository=target_repo,
        idempotency_key=f"legacy-ticket-{uuid4().hex}",
    )
    payload = {
        "title": action.ticket_title or f"[{action.action_type}] Phiếu công việc VADIRAS FLOW",
        "body": action.message_draft or "",
        "labels": list(action.labels or []),
    }

    async def _run() -> ExternalReferences:
        res = await connector.execute_action("create_issue", payload, ctx)
        return ExternalReferences(
            ticket_id=res.external_id,
            ticket_url=res.external_url,
            sla_breached=False,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run())

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _run()).result()
