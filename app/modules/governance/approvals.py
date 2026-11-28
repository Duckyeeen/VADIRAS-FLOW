"""Cơ chế kiểm tra 7 yếu tố ràng buộc hiệu lực của một lệnh phê duyệt."""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.errors import AuthorizationError

from .models import ApprovalRequest, ApprovalRequestStatus


def _normalize_utc(dt: datetime) -> datetime:
    """Chuẩn hóa thời điểm về múi giờ UTC để so sánh an toàn trên cả SQLite và PostgreSQL."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def verify_approval_binding(
    approval: ApprovalRequest,
    *,
    workflow_version_id: str | None,
    node_id: str,
    action: str,
    parameter_hash: str,
    resource_scope: str,
    policy_version: str,
    now: datetime | None = None,
) -> None:
    """Kiểm tra lệnh phê duyệt có khớp chính xác 7 yếu tố ràng buộc hay không.

    7 yếu tố bắt buộc phải trùng khớp hoàn toàn:
    1. Trạng thái lệnh duyệt phải là `APPROVED`.
    2. Thời điểm kiểm tra chưa vượt quá hạn `expires_at`.
    3. Khớp `workflow_version_id` (nếu có).
    4. Khớp `node_id`.
    5. Khớp `action`.
    6. Khớp `parameter_hash` (bất kỳ thay đổi nhỏ nào ở tham số đều làm mất hiệu lực duyệt).
    7. Khớp `resource_scope` và `policy_version`.
    """
    current_time = now or datetime.now(timezone.utc)
    if approval.status != ApprovalRequestStatus.APPROVED.value:
        raise AuthorizationError(
            f"Yêu cầu phê duyệt `{approval.id}` đang ở trạng thái `{approval.status}`, chưa được duyệt.",
            code="APPROVAL_NOT_APPROVED",
        )

    if _normalize_utc(approval.expires_at) <= _normalize_utc(current_time):
        raise AuthorizationError(
            f"Lệnh phê duyệt `{approval.id}` đã hết hạn hiệu lực.",
            code="APPROVAL_EXPIRED",
        )

    mismatches: list[str] = []
    if workflow_version_id is not None and approval.workflow_version_id != workflow_version_id:
        mismatches.append("workflow_version_id")
    if approval.node_id != node_id:
        mismatches.append("node_id")
    if approval.action.strip().lower() != action.strip().lower():
        mismatches.append("action")
    if approval.parameter_hash != parameter_hash:
        mismatches.append("parameter_hash")
    if approval.resource_scope.strip() != resource_scope.strip():
        mismatches.append("resource_scope")
    if approval.policy_version != policy_version:
        mismatches.append("policy_version")

    if mismatches:
        raise AuthorizationError(
            f"Lệnh phê duyệt `{approval.id}` không khớp ngữ cảnh thực thi hiện tại ({', '.join(mismatches)}).",
            code="APPROVAL_BINDING_MISMATCH",
        )
