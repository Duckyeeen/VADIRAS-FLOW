"""Giao diện kiểm tra thời hạn cam kết xử lý (SLA) của yêu cầu."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.modules.observability.sla import evaluate_request_sla

from .schemas import (
    InboundRequest,
    StateTransition,
    WorkflowAuditRecord,
    WorkflowStatus,
)


def evaluate_sla(
    request: InboundRequest,
    audit_record: WorkflowAuditRecord,
    now: datetime | None = None,
) -> WorkflowAuditRecord:
    """Đánh giá trạng thái thời hạn xử lý (SLA) của yêu cầu và cập nhật `WorkflowAuditRecord`."""
    ref_now = now or datetime.now(timezone.utc)
    if ref_now.tzinfo is None:
        ref_now = ref_now.replace(tzinfo=timezone.utc)

    due_at = request.submitted_at + timedelta(seconds=request.demo_sla_seconds)
    mapped_status = "RESOLVED" if audit_record.status == WorkflowStatus.VERIFIED_RESOLVED else audit_record.status.value
    mapped_outcome = "VERIFIED" if audit_record.status == WorkflowStatus.VERIFIED_RESOLVED else "PENDING"

    sla = evaluate_request_sla(
        created_at=request.submitted_at,
        due_at=due_at,
        status=mapped_status,
        business_outcome=mapped_outcome,
        now=ref_now,
    )
    updated_refs = audit_record.external_refs.model_copy(update={"sla_breached": bool(sla["breached"])})
    updated_history = list(audit_record.state_history)
    updated_status = audit_record.status

    if sla["breached"] and audit_record.status != WorkflowStatus.SLA_BREACHED:
        updated_status = WorkflowStatus.SLA_BREACHED
        updated_history.append(
            StateTransition(
                status=WorkflowStatus.SLA_BREACHED,
                changed_at=ref_now,
                detail=f"Yêu cầu đã vượt quá thời hạn SLA ({request.demo_sla_seconds} giây).",
            )
        )

    updated_timestamps = audit_record.timestamps.model_copy(update={"updated_at": ref_now})
    return audit_record.model_copy(
        update={
            "status": updated_status,
            "external_refs": updated_refs,
            "state_history": updated_history,
            "timestamps": updated_timestamps,
        }
    )
