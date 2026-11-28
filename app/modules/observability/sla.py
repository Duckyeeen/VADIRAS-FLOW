"""Bộ tính toán trạng thái thời hạn cam kết xử lý (SLA) và cảnh báo sắp quá hạn."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def evaluate_request_sla(
    *,
    created_at: datetime,
    due_at: datetime | None,
    status: str,
    business_outcome: str,
    now: datetime | None = None,
    warning_threshold_ratio: float = 0.8,
    default_target_minutes: int = 240,
) -> dict[str, Any]:
    """Đánh giá trạng thái SLA của một yêu cầu công việc tại thời điểm `now`.

    Các trạng thái trả về:
    - `MET`: Đã hoàn tất xác minh đúng hạn.
    - `BREACHED`: Đã quá hạn `due_at` mà chưa hoàn tất xác minh.
    - `WARNING`: Đang mở và đã tiêu thụ từ 80% thời gian cho phép trở lên.
    - `ON_TRACK`: Đang trong hạn an toàn.
    """
    ref_now = _normalize_utc(now or datetime.now(timezone.utc))
    created_utc = _normalize_utc(created_at)
    effective_due = (
        _normalize_utc(due_at)
        if due_at is not None
        else created_utc + timedelta(minutes=default_target_minutes)
    )

    total_window_sec = max(1.0, (effective_due - created_utc).total_seconds())
    elapsed_sec = max(0.0, (ref_now - created_utc).total_seconds())
    elapsed_ratio = round(elapsed_sec / total_window_sec, 4)

    is_closed_ok = status == "RESOLVED" or business_outcome == "VERIFIED"
    breached = ref_now > effective_due and not is_closed_ok

    if is_closed_ok:
        sla_state = "BREACHED" if ref_now > effective_due and status != "RESOLVED" else "MET"
    elif breached:
        sla_state = "BREACHED"
    elif elapsed_ratio >= warning_threshold_ratio:
        sla_state = "WARNING"
    else:
        sla_state = "ON_TRACK"

    return {
        "sla_state": sla_state,
        "breached": breached,
        "elapsed_ratio": elapsed_ratio,
        "due_at": effective_due.isoformat(),
    }
