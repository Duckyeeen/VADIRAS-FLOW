"""Bộ tiếp nhận webhook GitHub: xác thực chữ ký thô HMAC-SHA256, chống trùng và đối soát lượt chạy."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, ValidationAppError
from app.core.security import verify_hmac_sha256
from app.modules.runtime.contracts import ExternalEventSignalPayload
from app.modules.runtime.temporal_client import TemporalRuntimeGateway
from app.modules.workflows.models import WorkflowRun

from . import repository
from .models import ConnectorOperationRecord, WebhookInbox, WebhookInboxStatus
from .schemas import WebhookReceiptOut

# Chỉ đăng ký xử lý 3 loại sự kiện tối thiểu phục vụ quy trình hỗ trợ
SUPPORTED_GITHUB_EVENTS: frozenset[str] = frozenset({"issues", "issue_comment", "ping"})


async def ingest_github_webhook(
    session: AsyncSession,
    *,
    raw_body: bytes,
    signature_header: str | None,
    delivery_id: str | None,
    event_type: str | None,
    webhook_secret: str,
    default_allowed_repos: list[str],
    runtime_gateway: TemporalRuntimeGateway | None = None,
) -> WebhookReceiptOut:
    """Tiếp nhận, xác thực chữ ký thô HMAC-SHA256 và lưu hộp thư webhook an toàn.

    Các lớp bảo vệ theo thứ tự:
    1. Bắt buộc có tiêu đề `X-GitHub-Delivery` để định danh chống gửi trùng.
    2. Xác thực `X-Hub-Signature-256` trên dữ liệu thô dạng `bytes` bằng phép so sánh hằng thời gian.
    3. Nếu `delivery_id` đã tồn tại trong `webhook_inbox` -> trả ngay `duplicate=True`, không xử lý lại.
    4. Coi nội dung payload là dữ liệu không tin cậy, chỉ trích xuất trường tối thiểu.
    5. Kiểm tra sự kiện và tên kho nằm trong phạm vi cho phép trước khi đối chiếu với lượt chạy.
    """
    cleaned_delivery = (delivery_id or "").strip()
    if not cleaned_delivery:
        raise ValidationAppError(
            "Thiếu tiêu đề `X-GitHub-Delivery` để chống nhận trùng webhook.",
            code="MISSING_DELIVERY_ID",
        )

    if not verify_hmac_sha256(raw_body, signature_header, webhook_secret):
        raise AuthenticationError(
            "Chữ ký `X-Hub-Signature-256` của webhook không hợp lệ.",
            code="INVALID_WEBHOOK_SIGNATURE",
        )

    existing = await repository.get_webhook_by_delivery_id(session, delivery_id=cleaned_delivery)
    if existing is not None:
        return WebhookReceiptOut(
            accepted=True,
            duplicate=True,
            delivery_id=existing.delivery_id,
            event_type=existing.event_type,
            status=existing.status,
            inbox_id=existing.id,
            correlated_run_id=existing.correlated_run_id,
            reason="Sự kiện đã được ghi nhận trước đó theo mã giao nhận.",
        )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Payload webhook phải là đối tượng JSON.")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValidationAppError(
            f"Nội dung webhook không đúng định dạng JSON hợp lệ: {exc}",
            code="INVALID_WEBHOOK_PAYLOAD",
        ) from exc

    cleaned_event = (event_type or "unknown").strip().lower()
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    now = datetime.now(timezone.utc)

    repo_obj = payload.get("repository") if isinstance(payload.get("repository"), dict) else {}
    inst_obj = payload.get("installation") if isinstance(payload.get("installation"), dict) else {}
    issue_obj = payload.get("issue") if isinstance(payload.get("issue"), dict) else {}
    comment_obj = payload.get("comment") if isinstance(payload.get("comment"), dict) else {}

    repo_full_name = str(repo_obj.get("full_name") or "").strip() or None
    inst_ext_id = str(inst_obj.get("id") or "").strip() or None
    issue_number = issue_obj.get("number")

    installation = None
    if inst_ext_id is not None:
        installation = await repository.find_installation_by_external_id_any_org(
            session, installation_external_id=inst_ext_id
        )

    org_id = installation.organization_id if installation is not None else None
    allowed_repos = set(default_allowed_repos)
    if installation is not None and installation.resource_scopes:
        allowed_repos = {
            s.resource_identifier for s in installation.resource_scopes if s.is_active
        }

    minimal_payload: dict[str, Any] = {
        "action": str(payload.get("action") or ""),
        "repository": repo_full_name,
        "installation_id": inst_ext_id,
        "issue_number": issue_number,
        "issue_state": issue_obj.get("state"),
        "issue_labels": [
            str(lbl.get("name") if isinstance(lbl, dict) else lbl)
            for lbl in (issue_obj.get("labels") or [])
        ],
        "comment_id": comment_obj.get("id"),
    }

    inbox = WebhookInbox(
        organization_id=org_id,
        connector_type="github",
        delivery_id=cleaned_delivery,
        event_type=cleaned_event,
        installation_external_id=inst_ext_id,
        repository_full_name=repo_full_name,
        signature_verified=True,
        payload_hash=payload_hash,
        minimal_payload_json=minimal_payload,
        status=WebhookInboxStatus.RECEIVED.value,
        received_at=now,
    )
    session.add(inbox)
    await session.flush()

    # Kiểm tra sự kiện và phạm vi kho trước khi đối soát
    if cleaned_event not in SUPPORTED_GITHUB_EVENTS:
        inbox.status = WebhookInboxStatus.IGNORED.value
        inbox.error_message = f"Loại sự kiện `{cleaned_event}` không nằm trong danh sách đăng ký."
        inbox.processed_at = datetime.now(timezone.utc)
        await session.commit()
        return WebhookReceiptOut(
            accepted=True,
            duplicate=False,
            delivery_id=inbox.delivery_id,
            event_type=inbox.event_type,
            status=inbox.status,
            inbox_id=inbox.id,
            reason=inbox.error_message,
        )

    if cleaned_event != "ping" and (not repo_full_name or repo_full_name not in allowed_repos):
        inbox.status = WebhookInboxStatus.IGNORED.value
        inbox.error_message = f"Kho mã `{repo_full_name}` nằm ngoài danh sách cho phép."
        inbox.processed_at = datetime.now(timezone.utc)
        await session.commit()
        return WebhookReceiptOut(
            accepted=True,
            duplicate=False,
            delivery_id=inbox.delivery_id,
            event_type=inbox.event_type,
            status=inbox.status,
            inbox_id=inbox.id,
            reason=inbox.error_message,
        )

    # Đối chiếu tìm giao dịch và lượt chạy quy trình tương ứng theo mã phiếu ngoài
    correlated_run_id: str | None = None
    if repo_full_name and issue_number is not None:
        ext_id = f"{repo_full_name}#{issue_number}"
        op_stmt = (
            sa.select(ConnectorOperationRecord)
            .where(ConnectorOperationRecord.external_id == ext_id)
            .order_by(ConnectorOperationRecord.created_at.desc())
            .limit(1)
        )
        op_row = (await session.execute(op_stmt)).scalar_one_or_none()
        if op_row is not None:
            if inbox.organization_id is None:
                inbox.organization_id = op_row.organization_id
            correlated_run_id = op_row.workflow_run_id
            op_row.response_summary_json = {
                **dict(op_row.response_summary_json or {}),
                "last_webhook_action": minimal_payload["action"],
                "state": minimal_payload["issue_state"],
                "labels": minimal_payload["issue_labels"],
                "last_delivery_id": cleaned_delivery,
            }

            if correlated_run_id and runtime_gateway is not None:
                run_row = (
                    await session.execute(
                        sa.select(WorkflowRun).where(
                            WorkflowRun.id == correlated_run_id,
                            WorkflowRun.organization_id == op_row.organization_id,
                        )
                    )
                ).scalar_one_or_none()
                if run_row is not None:
                    await runtime_gateway.signal_external_event(
                        run_row.temporal_workflow_id,
                        ExternalEventSignalPayload(
                            node_id=op_row.node_id or "wait_event",
                            event_source="github",
                            event_type=f"{cleaned_event}.{minimal_payload['action'] or 'updated'}",
                            payload=minimal_payload,
                        ),
                    )

    inbox.correlated_run_id = correlated_run_id
    inbox.status = WebhookInboxStatus.PROCESSED.value
    inbox.processed_at = datetime.now(timezone.utc)
    await session.commit()

    return WebhookReceiptOut(
        accepted=True,
        duplicate=False,
        delivery_id=inbox.delivery_id,
        event_type=inbox.event_type,
        status=inbox.status,
        inbox_id=inbox.id,
        correlated_run_id=correlated_run_id,
        reason="Đã xác thực chữ ký và ghi nhận xử lý sự kiện thành công.",
    )
