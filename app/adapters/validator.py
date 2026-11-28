"""Bộ kiểm tra tính hợp lệ, ẩn thông tin nhạy cảm và chống xử lý trùng lặp đầu vào (bản tương thích cũ)."""

from __future__ import annotations

import hashlib

from app.modules.requests.intake import detect_prompt_injection_signals, redact_pii

from .schemas import InboundRequest, PreprocessedContext


def validate_and_sanitize(request: InboundRequest) -> PreprocessedContext:
    """Kiểm tra một `InboundRequest` và trả về `PreprocessedContext` đã làm sạch.

    Các bước thực hiện:
    1. Gộp tiêu đề, mô tả và hành động mong muốn rồi ẩn thông tin cá nhân nhạy cảm
       (email, số điện thoại, số thẻ, khóa bí mật) bằng bộ lọc chuẩn của phân hệ `requests`.
    2. Quét dấu hiệu nghi vấn cài cắm câu lệnh AI trái phép.
    3. Tính mã băm SHA-256 cố định đại diện cho nội dung yêu cầu để phát hiện gửi trùng.
    """
    raw_combined = "\n".join(
        [
            f"Chủ đề: {request.subject}",
            f"Mô tả: {request.description}",
            f"Hành động mong muốn: {request.requested_action}",
        ]
    )
    sanitized_text, pii_redactions = redact_pii(raw_combined)
    injection_flags = detect_prompt_injection_signals(raw_combined)

    missing_fields: list[str] = []
    if not request.subject.strip():
        missing_fields.append("subject")
    if not request.description.strip():
        missing_fields.append("description")
    if injection_flags:
        pii_redactions.extend([f"INJECTION:{flag}" for flag in injection_flags])

    hash_source = "|".join(
        [
            request.customer.organization,
            request.customer.customer_id,
            request.subject,
            request.description,
            request.requested_action,
        ]
    )
    idempotency_hash = hashlib.sha256(hash_source.encode("utf-8")).hexdigest()

    return PreprocessedContext(
        request_id=request.request_id,
        idempotency_hash=idempotency_hash,
        is_duplicate=False,
        validation_status="FAILED" if missing_fields else "PASSED",
        missing_mandatory_fields=missing_fields,
        pii_redactions=pii_redactions,
        sanitized_text=sanitized_text,
    )
