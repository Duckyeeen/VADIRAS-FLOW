"""Tầng xử lý nghiệp vụ truy xuất kết quả xác minh, bằng chứng và nhật ký kiểm toán theo phân quyền."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthorizationError, NotFoundError
from app.modules.identity.models import UserKind
from app.modules.identity.schemas import PaginationMeta
from app.modules.identity.service import AuthenticatedActor, require_employee, require_permission
from app.modules.requests import repository as request_repo
from app.modules.requests.models import VisibilityLevel
from app.modules.runtime import repository as runtime_repo

from . import repository
from .models import AuditLog, ExecutionEvidence, VerificationRun
from .schemas import (
    AuditLogListResponse,
    AuditLogOut,
    ExecutionEvidenceOut,
    RequestVerificationResponse,
    RunEvidenceResponse,
    VerificationRunOut,
)


def _to_evidence_out(ev: ExecutionEvidence) -> ExecutionEvidenceOut:
    return ExecutionEvidenceOut(
        id=ev.id,
        verification_run_id=ev.verification_run_id,
        source_type=ev.source_type,
        source_ref=ev.source_ref,
        captured_at=ev.captured_at,
        actor_id=ev.actor_id,
        resource_identifier=ev.resource_identifier,
        content_hash=ev.content_hash,
        verification_rule=ev.verification_rule,
        is_fresh=ev.is_fresh,
        access_classification=ev.access_classification,
        evidence_summary=dict(ev.evidence_summary_json or {}),
    )


def _to_ver_run_out(vr: VerificationRun, *, customer_only: bool) -> VerificationRunOut:
    evs = [
        _to_evidence_out(e)
        for e in vr.evidences
        if (not customer_only or e.access_classification == VisibilityLevel.CUSTOMER_VISIBLE.value)
    ]
    return VerificationRunOut(
        id=vr.id,
        organization_id=vr.organization_id,
        request_id=vr.request_id,
        workflow_run_id=vr.workflow_run_id,
        node_id=vr.node_id,
        evaluator_type=vr.evaluator_type,
        outcome=vr.outcome,
        postconditions=list(vr.postconditions_json or []),
        evaluated_criteria=list(vr.evaluated_criteria_json or []),
        rationale_summary=vr.rationale_summary,
        freshness_seconds=vr.freshness_seconds,
        requires_human_confirmation=vr.requires_human_confirmation,
        human_confirmed_by_membership_id=vr.human_confirmed_by_membership_id,
        verified_at=vr.verified_at,
        evidences=evs,
    )


def _to_audit_out(row: AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=row.id,
        organization_id=row.organization_id,
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        request_id=row.request_id,
        workflow_run_id=row.workflow_run_id,
        node_id=row.node_id,
        action=row.action,
        resource=row.resource,
        correlation_id=row.correlation_id,
        policy_decision=row.policy_decision,
        policy_version=row.policy_version,
        approval_id=row.approval_id,
        outcome=row.outcome,
        evidence_ref=row.evidence_ref,
        parameter_hash=row.parameter_hash,
        safe_metadata=dict(row.safe_metadata_json or {}),
        occurred_at=row.occurred_at,
    )


async def get_request_verification_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    request_id: str,
) -> RequestVerificationResponse:
    """Xem kết quả xác minh của một yêu cầu (khách hàng chỉ thấy bằng chứng `CUSTOMER_VISIBLE`)."""
    req = await request_repo.get_request_by_id(
        session,
        organization_id=actor.organization_id,
        request_id=request_id,
    )
    if req is None:
        raise NotFoundError("Không tìm thấy yêu cầu công việc trong tổ chức.", code="REQUEST_NOT_FOUND")

    is_customer = actor.user_kind == UserKind.CUSTOMER_CONTACT.value
    if is_customer:
        if req.requester_membership_id != actor.membership_id:
            raise AuthorizationError(
                "Khách hàng chỉ được phép xem kết quả xác minh của yêu cầu do chính mình gửi.",
                code="CROSS_CUSTOMER_ACCESS_DENIED",
            )
    elif "requests:read_all" not in actor.permissions and req.requester_membership_id != actor.membership_id:
        require_permission(actor, "requests:read_all")

    runs = await repository.list_verification_runs_for_request(
        session,
        organization_id=actor.organization_id,
        request_id=req.id,
    )
    return RequestVerificationResponse(
        request_id=req.id,
        business_outcome=req.business_outcome,
        request_status=req.status,
        verification_runs=[_to_ver_run_out(r, customer_only=is_customer) for r in runs],
    )


async def get_run_evidence_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    run_id: str,
) -> RunEvidenceResponse:
    """Liệt kê toàn bộ bằng chứng của một lượt chạy quy trình dành cho nhân viên nội bộ."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:read_all")

    run = await runtime_repo.get_run_by_id(
        session,
        organization_id=actor.organization_id,
        run_id=run_id,
    )
    if run is None:
        raise NotFoundError("Không tìm thấy lượt chạy quy trình.", code="WORKFLOW_RUN_NOT_FOUND")

    rows = await repository.list_evidence_for_run(
        session,
        organization_id=actor.organization_id,
        workflow_run_id=run.id,
    )
    return RunEvidenceResponse(
        workflow_run_id=run.id,
        evidences=[_to_evidence_out(r) for r in rows],
    )


async def list_audit_logs_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    page: int,
    page_size: int,
    request_id: str | None = None,
    workflow_run_id: str | None = None,
    actor_type: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
) -> AuditLogListResponse:
    """Xem nhật ký kiểm toán chỉ thêm mới trong đúng phạm vi tổ chức của nhân viên gọi API."""
    require_employee(actor)
    if not any(p in actor.permissions for p in ("approvals:decide", "users:read", "requests:read_all")):
        require_permission(actor, "requests:read_all")

    rows, total = await repository.list_audit_logs(
        session,
        organization_id=actor.organization_id,
        page=page,
        page_size=page_size,
        request_id=request_id,
        workflow_run_id=workflow_run_id,
        actor_type=actor_type,
        action=action,
        outcome=outcome,
    )
    return AuditLogListResponse(
        items=[_to_audit_out(r) for r in rows],
        pagination=PaginationMeta(page=page, page_size=page_size, total=total),
    )
