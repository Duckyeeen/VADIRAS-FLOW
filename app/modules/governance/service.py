"""Tầng xử lý nghiệp vụ phê duyệt, kiểm tra thẩm quyền người duyệt và đánh giá quy tắc."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthorizationError, ConflictError, NotFoundError
from app.modules.identity.schemas import PaginationMeta
from app.modules.identity.service import AuthenticatedActor, require_employee, require_permission
from app.modules.observability.events import enqueue_outbox_event
from app.modules.requests import repository as request_repo
from app.modules.verification.audit import record_audit_log

from . import repository
from .models import ApprovalDecision, ApprovalRequest, ApprovalRequestStatus
from .policy_engine import (
    PolicyEvaluationContext,
    compute_parameter_hash,
    evaluate_policy,
)
from .schemas import (
    ApprovalDecisionIn,
    ApprovalDecisionOut,
    ApprovalListResponse,
    ApprovalRequestOut,
    CreateApprovalIn,
    GovernanceEvaluateIn,
    GovernanceEvaluateOut,
)


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_approval_out(approval: ApprovalRequest) -> ApprovalRequestOut:
    """Chuyển bản ghi `ApprovalRequest` sang khuôn mẫu đầu ra API."""
    decision_out = None
    if approval.decision_record is not None:
        decision_out = ApprovalDecisionOut(
            id=approval.decision_record.id,
            approver_membership_id=approval.decision_record.approver_membership_id,
            decision=approval.decision_record.decision,
            rationale=approval.decision_record.rationale,
            authority_verified=approval.decision_record.authority_verified,
            decided_at=approval.decision_record.decided_at,
        )
    return ApprovalRequestOut(
        id=approval.id,
        organization_id=approval.organization_id,
        request_id=approval.request_id,
        workflow_run_id=approval.workflow_run_id,
        workflow_version_id=approval.workflow_version_id,
        node_id=approval.node_id,
        action=approval.action,
        parameters=dict(approval.parameters_json or {}),
        parameter_hash=approval.parameter_hash,
        resource_scope=approval.resource_scope,
        policy_version=approval.policy_version,
        risk_level=approval.risk_level,
        required_role=approval.required_role,
        status=approval.status,
        requested_by_actor_id=approval.requested_by_actor_id,
        expires_at=approval.expires_at,
        created_at=approval.created_at,
        decision_record=decision_out,
    )


async def create_approval_request_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    payload: CreateApprovalIn,
) -> ApprovalRequestOut:
    """Tạo một yêu cầu phê duyệt ràng buộc 7 yếu tố cho thao tác nhạy cảm."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:update")

    req = await request_repo.get_request_by_id(
        session,
        organization_id=actor.organization_id,
        request_id=payload.request_id,
    )
    if req is None:
        raise NotFoundError("Không tìm thấy yêu cầu gốc trong tổ chức.", code="REQUEST_NOT_FOUND")

    param_hash = compute_parameter_hash(
        action=payload.action,
        parameters=payload.parameters,
        resource_scope=payload.resource_scope,
    )
    expires_at = datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours)
    approval = ApprovalRequest(
        organization_id=actor.organization_id,
        request_id=req.id,
        workflow_run_id=payload.workflow_run_id,
        workflow_version_id=payload.workflow_version_id,
        node_id=payload.node_id,
        action=payload.action.strip().lower(),
        parameters_json=payload.parameters,
        parameter_hash=param_hash,
        resource_scope=payload.resource_scope.strip(),
        policy_version=payload.policy_version,
        risk_level=payload.risk_level,
        required_role=payload.required_role,
        status=ApprovalRequestStatus.PENDING.value,
        requested_by_actor_id=actor.membership_id,
        expires_at=expires_at,
    )
    session.add(approval)
    await session.commit()

    refreshed = await repository.get_approval_by_id(
        session,
        organization_id=actor.organization_id,
        approval_id=approval.id,
    )
    assert refreshed is not None
    return _to_approval_out(refreshed)


async def list_approvals_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    page: int,
    page_size: int,
    status: str | None = None,
    request_id: str | None = None,
) -> ApprovalListResponse:
    """Liệt kê yêu cầu phê duyệt thuộc phạm vi tổ chức của nhân viên gọi API."""
    require_employee(actor)
    if "approvals:decide" not in actor.permissions:
        require_permission(actor, "requests:read_all")

    rows, total = await repository.list_approvals(
        session,
        organization_id=actor.organization_id,
        page=page,
        page_size=page_size,
        status=status,
        request_id=request_id,
    )
    return ApprovalListResponse(
        items=[_to_approval_out(row) for row in rows],
        pagination=PaginationMeta(page=page, page_size=page_size, total=total),
    )


async def get_approval_detail_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    approval_id: str,
) -> ApprovalRequestOut:
    """Xem chi tiết yêu cầu phê duyệt và toàn bộ thông số ràng buộc bảo mật."""
    require_employee(actor)
    if "approvals:decide" not in actor.permissions:
        require_permission(actor, "requests:read_all")

    approval = await repository.get_approval_by_id(
        session,
        organization_id=actor.organization_id,
        approval_id=approval_id,
    )
    if approval is None:
        raise NotFoundError("Không tìm thấy yêu cầu phê duyệt.", code="APPROVAL_NOT_FOUND")
    return _to_approval_out(approval)


async def decide_approval_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    approval_id: str,
    payload: ApprovalDecisionIn,
) -> ApprovalRequestOut:
    """Phê duyệt hoặc từ chối một yêu cầu phê duyệt kèm kiểm tra thẩm quyền nghiêm ngặt.

    Quy tắc kiểm soát:
    1. Chỉ nhân viên nội bộ có quyền `approvals:decide` mới được xử lý.
    2. Chặn tuyệt đối hành vi tự phê duyệt yêu cầu do chính mình tạo (`SELF_APPROVAL_FORBIDDEN`).
    3. Người duyệt phải có vai trò phù hợp với `required_role` hoặc là `admin` của tổ chức.
    4. Chỉ xử lý yêu cầu đang `PENDING` và chưa hết hạn `expires_at`.
    """
    require_employee(actor)
    require_permission(actor, "approvals:decide")

    approval = await repository.get_approval_by_id(
        session,
        organization_id=actor.organization_id,
        approval_id=approval_id,
    )
    if approval is None:
        raise NotFoundError("Không tìm thấy yêu cầu phê duyệt.", code="APPROVAL_NOT_FOUND")

    if approval.requested_by_actor_id == actor.membership_id:
        raise AuthorizationError(
            "Không được phép tự phê duyệt yêu cầu do chính mình đề xuất.",
            code="SELF_APPROVAL_FORBIDDEN",
        )

    if "admin" not in actor.roles and approval.required_role not in actor.roles:
        raise AuthorizationError(
            f"Cần vai trò `{approval.required_role}` hoặc quản trị viên để quyết định yêu cầu này.",
            code="APPROVER_ROLE_INSUFFICIENT",
        )

    if approval.status != ApprovalRequestStatus.PENDING.value:
        raise ConflictError(
            f"Yêu cầu phê duyệt đã ở trạng thái `{approval.status}` nên không thể xử lý lại.",
            code="APPROVAL_ALREADY_DECIDED",
        )

    now = datetime.now(timezone.utc)
    if _normalize_utc(approval.expires_at) <= now:
        approval.status = ApprovalRequestStatus.EXPIRED.value
        await session.commit()
        raise ConflictError("Yêu cầu phê duyệt đã quá hạn hiệu lực.", code="APPROVAL_EXPIRED")

    approval.status = payload.decision
    decision_record = ApprovalDecision(
        organization_id=actor.organization_id,
        approval_request_id=approval.id,
        approver_membership_id=actor.membership_id,
        decision=payload.decision,
        rationale=payload.rationale,
        authority_verified=True,
        decided_at=now,
    )
    session.add(decision_record)
    await record_audit_log(
        session,
        organization_id=actor.organization_id,
        actor_type="USER",
        actor_id=actor.membership_id,
        action="approval:decided",
        resource=approval.resource_scope,
        outcome=payload.decision,
        request_id=approval.request_id,
        workflow_run_id=approval.workflow_run_id,
        node_id=approval.node_id,
        policy_version=approval.policy_version,
        approval_id=approval.id,
        parameter_hash=approval.parameter_hash,
        safe_metadata={
            "action": approval.action,
            "required_role": approval.required_role,
            "rationale": payload.rationale,
        },
    )
    await enqueue_outbox_event(
        session,
        organization_id=actor.organization_id,
        event_type="APPROVAL_GRANTED" if payload.decision == "APPROVED" else "APPROVAL_REJECTED",
        aggregate_type="approval_request",
        aggregate_id=approval.id,
        actor_type="USER",
        actor_id=actor.membership_id,
        request_id=approval.request_id,
        workflow_run_id=approval.workflow_run_id,
        payload={"decision": payload.decision, "node_id": approval.node_id},
    )
    await session.commit()

    refreshed = await repository.get_approval_by_id(
        session,
        organization_id=actor.organization_id,
        approval_id=approval.id,
    )
    assert refreshed is not None
    return _to_approval_out(refreshed)


def evaluate_policy_preview_for_actor(
    actor: AuthenticatedActor,
    *,
    payload: GovernanceEvaluateIn,
) -> GovernanceEvaluateOut:
    """Chạy thử Bộ kiểm soát quy tắc trên một ngữ cảnh giả lập cho nhân viên nội bộ."""
    require_employee(actor)
    result = evaluate_policy(
        PolicyEvaluationContext(
            organization_id=actor.organization_id,
            actor_type=payload.actor_type,
            actor_id=payload.actor_id,
            action=payload.action,
            resource_scope=payload.resource_scope,
            parameters=payload.parameters,
            request_type=payload.request_type,
            side_effect_class=payload.side_effect_class,
            impact_score=payload.impact_score,
            likelihood_score=payload.likelihood_score,
            estimated_cost_usd=payload.estimated_cost_usd,
            max_cost_usd=payload.max_cost_usd,
            injection_flags=tuple(payload.injection_flags),
        )
    )
    return GovernanceEvaluateOut(
        decision=result.decision,
        risk_level=result.risk_level,
        policy_version=result.policy_version,
        parameter_hash=result.parameter_hash,
        triggered_rules=result.triggered_rules,
        required_role=result.required_role,
        reason=result.reason,
    )
