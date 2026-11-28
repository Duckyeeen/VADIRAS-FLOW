"""Kiểm thử đơn vị cho tạo vector nhúng, đánh giá SLA và 3 giao diện tương thích cũ."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.modules.memory.embeddings import DeterministicEmbeddingProvider, cosine_similarity
from app.modules.observability.sla import evaluate_request_sla
from app.adapters.notifier import send_notification
from app.adapters.retriever import retrieve_context
from app.adapters.schemas import (
    CustomerInfo,
    CustomerTier,
    InboundRequest,
    PreprocessedContext,
    ProductInfo,
    ProposedAction,
    SourceChannel,
    WorkflowAuditRecord,
    WorkflowStatus,
)
from app.adapters.sla_watchdog import evaluate_sla


def test_deterministic_embeddings_and_cosine_similarity() -> None:
    """Kiểm tra bộ tạo vector nhúng ổn định cùng một văn bản và văn bản tương đồng có điểm cao hơn."""
    provider = DeterministicEmbeddingProvider()
    v1 = provider.embed_text("Lỗi HTTP 500 khi xuất báo cáo PDF")
    v2 = provider.embed_text("Lỗi HTTP 500 khi xuất báo cáo PDF")
    v3 = provider.embed_text("Yêu cầu mua chuột không dây mới cho phòng nhân sự")

    assert len(v1) == 64
    assert v1 == v2
    assert cosine_similarity(v1, v2) > cosine_similarity(v1, v3)


def test_sla_evaluation_covers_on_track_warning_breached_and_met() -> None:
    """Đánh giá chính xác cả 4 trạng thái SLA: ON_TRACK, WARNING, BREACHED, MET."""
    t0 = datetime(2026, 11, 27, 8, 0, tzinfo=timezone.utc)
    due = t0 + timedelta(minutes=100)

    assert evaluate_request_sla(
        created_at=t0, due_at=due, status="OPEN", business_outcome="PENDING", now=t0 + timedelta(minutes=20)
    )["sla_state"] == "ON_TRACK"

    assert evaluate_request_sla(
        created_at=t0, due_at=due, status="IN_PROGRESS", business_outcome="PENDING", now=t0 + timedelta(minutes=85)
    )["sla_state"] == "WARNING"

    assert evaluate_request_sla(
        created_at=t0, due_at=due, status="IN_PROGRESS", business_outcome="PENDING", now=t0 + timedelta(minutes=110)
    )["sla_state"] == "BREACHED"

    assert evaluate_request_sla(
        created_at=t0, due_at=due, status="RESOLVED", business_outcome="VERIFIED", now=t0 + timedelta(minutes=50)
    )["sla_state"] == "MET"


def test_legacy_notifier_retriever_and_sla_watchdog_adapters() -> None:
    """Xác nhận cả 3 tệp tương thích cũ hoạt động chuẩn xác không còn `NotImplementedError`."""
    now = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)
    req = InboundRequest(
        request_id="req-legacy-01",
        source_channel=SourceChannel.WEB_FORM,
        submitted_at=now,
        customer=CustomerInfo(
            customer_id="c1",
            organization="Acme",
            contact_email="user@acme.local",
            tier=CustomerTier.ENTERPRISE,
        ),
        product=ProductInfo(name="VADIRAS", module="Reporting", version="1.0", environment="prod"),
        subject="Lỗi xuất báo cáo PDF HTTP 500",
        description="Gặp lỗi 500 khi xuất báo cáo PDF.",
        requested_action="Khắc phục lỗi xuất PDF",
        demo_sla_seconds=60,
    )
    action = ProposedAction(
        action_type="NOTIFY_CUSTOMER",
        target_system="email",
        message_draft="Xin chào, chúng tôi đã tiếp nhận yêu cầu của bạn qua user@acme.local.",
    )
    assert send_notification(req, action) is True
    assert send_notification(req, ProposedAction(action_type="NOTIFY", target_system="email", message_draft="")) is False

    ctx = PreprocessedContext(
        request_id="req-legacy-01",
        idempotency_hash="a" * 64,
        validation_status="PASSED",
        sanitized_text="Lỗi xuất báo cáo PDF HTTP 500",
    )
    enriched = retrieve_context(ctx)
    assert len(enriched.retrieved_kb) == 3
    assert len(enriched.similar_tickets) == 2

    audit = WorkflowAuditRecord(request_id="req-legacy-01", status=WorkflowStatus.RECEIVED)
    breached_audit = evaluate_sla(req, audit, now=now + timedelta(seconds=90))
    assert breached_audit.external_refs.sla_breached is True
    assert breached_audit.status == WorkflowStatus.SLA_BREACHED
