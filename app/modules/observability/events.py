"""Danh mục sự kiện nghiệp vụ chuẩn và hàm ghi sự kiện vào hàng đợi giao dịch `outbox_events`."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.modules.verification.audit import sanitize_audit_metadata

from .models import OutboxEvent, OutboxStatus

DOMAIN_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "REQUEST_CREATED",
        "REQUEST_CLASSIFIED",
        "CLARIFICATION_REQUIRED",
        "WORKFLOW_PROPOSED",
        "WORKFLOW_VALIDATED",
        "APPROVAL_REQUESTED",
        "APPROVAL_GRANTED",
        "APPROVAL_REJECTED",
        "WORKFLOW_STARTED",
        "NODE_STARTED",
        "NODE_COMPLETED",
        "NODE_FAILED",
        "EXTERNAL_EVENT_RECEIVED",
        "SLA_WARNING",
        "WORKFLOW_REPLAN_PROPOSED",
        "WORKFLOW_REPLAN_APPROVED",
        "VERIFICATION_COMPLETED",
        "REQUEST_VERIFIED",
        "WORKFLOW_COMPLETED",
        "WORKFLOW_FAILED",
    }
)


async def enqueue_outbox_event(
    session: AsyncSession,
    *,
    organization_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    actor_type: str,
    actor_id: str,
    payload: dict[str, Any] | None = None,
    request_id: str | None = None,
    workflow_run_id: str | None = None,
    node_run_id: str | None = None,
    aggregate_version: int = 1,
    access_classification: str = "INTERNAL_ONLY",
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> OutboxEvent:
    """Ghi một sự kiện vào bảng `outbox_events` trong cùng giao dịch CSDL của nghiệp vụ."""
    cleaned = sanitize_audit_metadata(payload or {})
    if not isinstance(cleaned, dict):
        cleaned = {}

    ev = OutboxEvent(
        organization_id=organization_id,
        event_id=str(uuid4()),
        event_type=event_type.strip().upper(),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        request_id=request_id,
        workflow_run_id=workflow_run_id,
        node_run_id=node_run_id,
        actor_type=actor_type.strip().upper(),
        actor_id=actor_id,
        correlation_id=correlation_id or get_correlation_id(),
        causation_id=causation_id,
        schema_version="1.0",
        access_classification=access_classification,
        payload_json=cleaned,
        status=OutboxStatus.PENDING.value,
        attempts=0,
        occurred_at=datetime.now(timezone.utc),
    )
    session.add(ev)
    await session.flush()
    return ev
