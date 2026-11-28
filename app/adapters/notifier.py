"""Giao diện gửi thông báo tới khách hàng hoặc người gửi yêu cầu kèm che giấu dữ liệu nhạy cảm."""

from __future__ import annotations

import logging

from app.modules.requests.intake import redact_pii

from .schemas import InboundRequest, ProposedAction

_logger = logging.getLogger("vadiras.notifier")


def send_notification(request: InboundRequest, action: ProposedAction) -> bool:
    """Gửi thông báo đã được cho phép đối với yêu cầu `InboundRequest`."""
    raw_message = (action.message_draft or "").strip()
    if not raw_message:
        return False

    safe_message, _ = redact_pii(raw_message)
    _logger.info(
        "notification_dispatched",
        extra={
            "request_id": request.request_id,
            "target_system": action.target_system,
            "action_type": action.action_type,
            "preview_length": len(safe_message),
        },
    )
    return True
