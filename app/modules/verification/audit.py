"""Nhật ký kiểm toán chỉ được phép thêm mới và tự động lọc sạch thông tin nhạy cảm."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id

from .models import AuditLog

# Các từ khóa nhạy cảm tuyệt đối không được xuất hiện rõ trong nhật ký kiểm toán
_FORBIDDEN_AUDIT_KEY_FRAGMENTS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "private_key",
    "authorization",
    "api_key",
    "cookie",
    "reasoning_trace",
    "chain_of_thought",
    "hidden_cot",
)


def _is_forbidden_key(key: str) -> bool:
    lowered = key.strip().lower()
    return any(fragment in lowered for fragment in _FORBIDDEN_AUDIT_KEY_FRAGMENTS)


def sanitize_audit_metadata(value: Any) -> Any:
    """Làm sạch đệ quy toàn bộ khóa bí mật, thẻ truy cập và suy nghĩ ẩn AI trước khi ghi kiểm toán."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for k, v in value.items():
            key_str = str(k)
            if _is_forbidden_key(key_str):
                # Loại bỏ hoàn toàn suy nghĩ ẩn của AI, che giấu các khóa bí mật khác
                if any(cot in key_str.lower() for cot in ("reasoning_trace", "chain_of_thought", "hidden_cot")):
                    continue
                cleaned[key_str] = "[DA_AN]"
            else:
                cleaned[key_str] = sanitize_audit_metadata(v)
        return cleaned
    if isinstance(value, list):
        return [sanitize_audit_metadata(item) for item in value]
    return value


async def record_audit_log(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_type: str,
    actor_id: str,
    action: str,
    resource: str,
    outcome: str,
    request_id: str | None = None,
    workflow_run_id: str | None = None,
    node_id: str | None = None,
    correlation_id: str | None = None,
    policy_decision: str | None = None,
    policy_version: str | None = None,
    approval_id: str | None = None,
    evidence_ref: str | None = None,
    parameter_hash: str | None = None,
    safe_metadata: dict[str, Any] | None = None,
    commit: bool = False,
) -> AuditLog:
    """Thêm mới một bản ghi kiểm toán vào bảng `audit_logs` (chỉ thêm mới, không chỉnh sửa)."""
    sanitized_meta = sanitize_audit_metadata(safe_metadata or {})
    if not isinstance(sanitized_meta, dict):
        sanitized_meta = {}

    entry = AuditLog(
        organization_id=organization_id,
        actor_type=actor_type.strip().upper(),
        actor_id=actor_id,
        request_id=request_id,
        workflow_run_id=workflow_run_id,
        node_id=node_id,
        action=action,
        resource=resource,
        correlation_id=correlation_id or get_correlation_id(),
        policy_decision=policy_decision,
        policy_version=policy_version,
        approval_id=approval_id,
        outcome=outcome,
        evidence_ref=evidence_ref,
        parameter_hash=parameter_hash,
        safe_metadata_json=sanitized_meta,
        occurred_at=datetime.now(timezone.utc),
    )
    session.add(entry)
    await session.flush()
    if commit:
        await session.commit()
    return entry
