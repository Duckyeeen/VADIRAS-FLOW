"""Tầng xử lý nghiệp vụ điều phối lượt chạy, điều khiển tạm dừng/hủy và lập lại sơ đồ an toàn."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.modules.governance.models import ApprovalRequest, ApprovalRequestStatus
from app.modules.governance.policy_engine import compute_parameter_hash
from app.modules.identity.schemas import PaginationMeta
from app.modules.identity.service import AuthenticatedActor, require_employee, require_permission
from app.modules.observability.events import enqueue_outbox_event
from app.modules.requests import repository as request_repo
from app.modules.verification.audit import record_audit_log
from app.modules.workflows.dsl.schemas import compute_graph_content_hash
from app.modules.workflows.models import (
    WorkflowReplanProposal,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowVersion,
    WorkflowVersionStatus,
)
from app.modules.workflows.scoring import score_candidate_workflows
from app.modules.workflows.validator import validate_workflow_graph
from datetime import datetime, timedelta, timezone

from . import repository
from .contracts import WorkflowRunInput
from .schemas import (
    ReplanProposalOut,
    ReplanWorkflowRunIn,
    ReplanWorkflowRunOut,
    StartWorkflowRunIn,
    WorkflowNodeRunOut,
    WorkflowRunListResponse,
    WorkflowRunOut,
)
from .state_machine import (
    TERMINAL_RUN_STATUSES,
    assert_replan_allowed,
    assert_valid_run_transition,
    compute_replan_delta,
)
from .temporal_client import TemporalRuntimeGateway


def _to_node_run_out(row) -> WorkflowNodeRunOut:
    return WorkflowNodeRunOut(
        id=row.id,
        node_id=row.node_id,
        node_type=row.node_type,
        status=row.status,
        attempt=row.attempt,
        idempotency_key=row.idempotency_key,
        input_summary=dict(row.input_summary_json or {}),
        output_summary=dict(row.output_summary_json or {}),
        error_class=row.error_class,
        error_message=row.error_message,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _to_replan_proposal_out(row: WorkflowReplanProposal) -> ReplanProposalOut:
    return ReplanProposalOut(
        id=row.id,
        parent_version_id=row.parent_version_id,
        proposed_version_id=row.proposed_version_id,
        reason=row.reason,
        scope_delta=dict(row.scope_delta_json or {}),
        risk_escalated=row.risk_escalated,
        status=row.status,
        proposed_by_actor_id=row.proposed_by_actor_id,
        created_at=row.created_at,
    )


def _to_run_out(
    run: WorkflowRun,
    *,
    node_runs: list | None = None,
    replan_proposals: list[WorkflowReplanProposal] | None = None,
    idempotent_replay: bool = False,
) -> WorkflowRunOut:
    return WorkflowRunOut(
        id=run.id,
        organization_id=run.organization_id,
        request_id=run.request_id,
        workflow_definition_id=run.workflow_definition_id,
        workflow_version_id=run.workflow_version_id,
        workflow_content_hash=run.workflow_content_hash,
        temporal_workflow_id=run.temporal_workflow_id,
        temporal_run_id=run.temporal_run_id,
        status=run.status,
        replan_count=run.replan_count,
        idempotency_key=run.idempotency_key,
        started_by_user_id=run.started_by_user_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        result_summary=dict(run.result_summary_json or {}),
        created_at=run.created_at,
        updated_at=run.updated_at,
        idempotent_replay=idempotent_replay,
        node_runs=[_to_node_run_out(nr) for nr in (node_runs or [])],
        replan_proposals=[_to_replan_proposal_out(rp) for rp in (replan_proposals or [])],
    )


async def _load_full_run_out(
    session: AsyncSession,
    *,
    organization_id: str,
    run: WorkflowRun,
    idempotent_replay: bool = False,
) -> WorkflowRunOut:
    node_runs = await repository.list_node_runs(
        session, organization_id=organization_id, workflow_run_id=run.id
    )
    proposals = await repository.list_replan_proposals(
        session, organization_id=organization_id, workflow_run_id=run.id
    )
    return _to_run_out(
        run,
        node_runs=node_runs,
        replan_proposals=proposals,
        idempotent_replay=idempotent_replay,
    )


async def start_workflow_run_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    payload: StartWorkflowRunIn,
    gateway: TemporalRuntimeGateway,
    header_idempotency_key: str | None = None,
) -> WorkflowRunOut:
    """Khởi phát một lượt chạy từ phiên bản quy trình đã `PUBLISHED` kèm khóa chống trùng lặp."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:update")

    idem_key = (header_idempotency_key or payload.idempotency_key or "").strip() or None
    if idem_key is not None:
        existing = await repository.get_run_by_idempotency_key(
            session,
            organization_id=actor.organization_id,
            idempotency_key=idem_key,
        )
        if existing is not None:
            return await _load_full_run_out(
                session,
                organization_id=actor.organization_id,
                run=existing,
                idempotent_replay=True,
            )

    req = await request_repo.get_request_by_id(
        session,
        organization_id=actor.organization_id,
        request_id=payload.request_id,
    )
    if req is None:
        raise NotFoundError("Không tìm thấy yêu cầu công việc trong tổ chức.", code="REQUEST_NOT_FOUND")

    version = await repository.get_version_by_id_in_org(
        session,
        organization_id=actor.organization_id,
        version_id=payload.workflow_version_id,
    )
    if version is None:
        raise NotFoundError("Không tìm thấy phiên bản quy trình trong tổ chức.", code="WORKFLOW_VERSION_NOT_FOUND")

    if version.status != WorkflowVersionStatus.PUBLISHED.value:
        raise ConflictError(
            f"Chỉ được phép chạy phiên bản ở trạng thái `PUBLISHED` (hiện tại là `{version.status}`).",
            code="WORKFLOW_VERSION_NOT_PUBLISHED",
        )

    run = WorkflowRun(
        organization_id=actor.organization_id,
        request_id=req.id,
        workflow_definition_id=version.workflow_definition_id,
        workflow_version_id=version.id,
        workflow_content_hash=version.content_hash,
        temporal_workflow_id="pending",
        status=WorkflowRunStatus.QUEUED.value,
        replan_count=0,
        idempotency_key=idem_key,
        started_by_user_id=actor.user_id,
    )
    session.add(run)
    await session.flush()
    run.temporal_workflow_id = f"wf-run-{run.id}"

    trigger_data = {
        "request_id": req.id,
        "title": req.title,
        "sanitized_description": req.sanitized_description,
        "request_type": req.request_type,
        "priority": req.priority,
        **dict(payload.trigger_input or {}),
    }
    graph_limits = dict((version.graph_json or {}).get("limits") or {})
    max_parallelism = min(int(graph_limits.get("max_parallelism", 4)), 4)

    temporal_run_id = await gateway.start_workflow(
        WorkflowRunInput(
            organization_id=actor.organization_id,
            workflow_run_id=run.id,
            request_id=req.id,
            workflow_version_id=version.id,
            workflow_content_hash=version.content_hash,
            graph_json=dict(version.graph_json or {}),
            trigger_input=trigger_data,
            started_by_user_id=actor.user_id,
            started_by_membership_id=actor.membership_id,
            max_parallelism=max_parallelism,
        )
    )
    run.temporal_run_id = temporal_run_id
    await record_audit_log(
        session,
        organization_id=actor.organization_id,
        actor_type="USER",
        actor_id=actor.membership_id,
        action="workflow_run:started",
        resource=f"workflow_version:{version.id}",
        outcome="QUEUED",
        request_id=req.id,
        workflow_run_id=run.id,
        safe_metadata={"content_hash": version.content_hash},
    )
    await enqueue_outbox_event(
        session,
        organization_id=actor.organization_id,
        event_type="WORKFLOW_STARTED",
        aggregate_type="workflow_run",
        aggregate_id=run.id,
        actor_type="USER",
        actor_id=actor.membership_id,
        request_id=req.id,
        workflow_run_id=run.id,
        payload={"workflow_version_id": version.id, "status": run.status},
    )
    await session.commit()

    refreshed = await repository.get_run_by_id(
        session, organization_id=actor.organization_id, run_id=run.id
    )
    assert refreshed is not None
    return await _load_full_run_out(session, organization_id=actor.organization_id, run=refreshed)


async def list_workflow_runs_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    page: int,
    page_size: int,
    status: str | None = None,
    request_id: str | None = None,
) -> WorkflowRunListResponse:
    """Liệt kê danh sách lượt chạy quy trình thuộc phạm vi tổ chức của nhân viên gọi API."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:read_all")

    rows, total = await repository.list_runs(
        session,
        organization_id=actor.organization_id,
        page=page,
        page_size=page_size,
        status=status,
        request_id=request_id,
    )
    return WorkflowRunListResponse(
        items=[_to_run_out(r) for r in rows],
        pagination=PaginationMeta(page=page, page_size=page_size, total=total),
    )


async def get_workflow_run_detail_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    run_id: str,
) -> WorkflowRunOut:
    """Xem chi tiết một lượt chạy quy trình kèm lịch sử từng bước và các đề xuất lập lại."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:read_all")

    run = await repository.get_run_by_id(
        session, organization_id=actor.organization_id, run_id=run_id
    )
    if run is None:
        raise NotFoundError("Không tìm thấy lượt chạy quy trình.", code="WORKFLOW_RUN_NOT_FOUND")
    return await _load_full_run_out(session, organization_id=actor.organization_id, run=run)


async def pause_workflow_run_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    run_id: str,
    reason: str,
    gateway: TemporalRuntimeGateway,
) -> WorkflowRunOut:
    """Tạm dừng một lượt chạy đang hoạt động và gửi tín hiệu xuống Temporal."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:update")

    run = await repository.get_run_by_id(
        session, organization_id=actor.organization_id, run_id=run_id
    )
    if run is None:
        raise NotFoundError("Không tìm thấy lượt chạy quy trình.", code="WORKFLOW_RUN_NOT_FOUND")

    assert_valid_run_transition(run.status, WorkflowRunStatus.PAUSED.value)
    run.status = WorkflowRunStatus.PAUSED.value
    await record_audit_log(
        session,
        organization_id=actor.organization_id,
        actor_type="USER",
        actor_id=actor.membership_id,
        action="workflow_run:paused",
        resource=f"workflow_run:{run.id}",
        outcome="PAUSED",
        request_id=run.request_id,
        workflow_run_id=run.id,
        safe_metadata={"reason": reason},
    )
    await session.commit()
    await gateway.signal_pause(run.temporal_workflow_id, reason)
    return await _load_full_run_out(session, organization_id=actor.organization_id, run=run)


async def resume_workflow_run_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    run_id: str,
    reason: str,
    gateway: TemporalRuntimeGateway,
) -> WorkflowRunOut:
    """Tiếp tục một lượt chạy đang tạm dừng và gửi tín hiệu xuống Temporal."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:update")

    run = await repository.get_run_by_id(
        session, organization_id=actor.organization_id, run_id=run_id
    )
    if run is None:
        raise NotFoundError("Không tìm thấy lượt chạy quy trình.", code="WORKFLOW_RUN_NOT_FOUND")

    if run.status != WorkflowRunStatus.PAUSED.value:
        raise ConflictError(
            f"Chỉ có thể tiếp tục lượt chạy đang ở trạng thái `PAUSED` (hiện tại là `{run.status}`).",
            code="INVALID_RUN_STATE_TRANSITION",
        )

    run.status = WorkflowRunStatus.RUNNING.value
    await record_audit_log(
        session,
        organization_id=actor.organization_id,
        actor_type="USER",
        actor_id=actor.membership_id,
        action="workflow_run:resumed",
        resource=f"workflow_run:{run.id}",
        outcome="RUNNING",
        request_id=run.request_id,
        workflow_run_id=run.id,
        safe_metadata={"reason": reason},
    )
    await session.commit()
    await gateway.signal_resume(run.temporal_workflow_id, reason)
    return await _load_full_run_out(session, organization_id=actor.organization_id, run=run)


async def cancel_workflow_run_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    run_id: str,
    reason: str,
    gateway: TemporalRuntimeGateway,
) -> WorkflowRunOut:
    """Hủy bỏ một lượt chạy chưa kết thúc và gửi tín hiệu dừng xuống Temporal."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:update")

    run = await repository.get_run_by_id(
        session, organization_id=actor.organization_id, run_id=run_id
    )
    if run is None:
        raise NotFoundError("Không tìm thấy lượt chạy quy trình.", code="WORKFLOW_RUN_NOT_FOUND")

    assert_valid_run_transition(run.status, WorkflowRunStatus.CANCELLED.value)
    run.status = WorkflowRunStatus.CANCELLED.value
    run.finished_at = datetime.now(timezone.utc)
    if reason:
        run.result_summary_json = {**dict(run.result_summary_json or {}), "cancel_reason": reason}
    await record_audit_log(
        session,
        organization_id=actor.organization_id,
        actor_type="USER",
        actor_id=actor.membership_id,
        action="workflow_run:cancelled",
        resource=f"workflow_run:{run.id}",
        outcome="CANCELLED",
        request_id=run.request_id,
        workflow_run_id=run.id,
        safe_metadata={"reason": reason},
    )
    await session.commit()
    await gateway.signal_cancel(run.temporal_workflow_id, reason)
    return await _load_full_run_out(session, organization_id=actor.organization_id, run=run)


async def replan_workflow_run_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    run_id: str,
    payload: ReplanWorkflowRunIn,
) -> ReplanWorkflowRunOut:
    """Đề xuất một phiên bản sơ đồ mới khi lượt chạy cần điều chỉnh nhưng không sửa đè bản cũ.

    Các bước bảo vệ:
    1. Chặn nếu lượt chạy đã vào trạng thái kết thúc hoặc đã chạm trần tối đa 2 lần lập lại.
    2. Kiểm định 7 tầng cho sơ đồ mới; từ chối ngay nếu sơ đồ mới vi phạm cấu trúc hoặc an toàn.
    3. So sánh chênh lệch phạm vi & rủi ro với phiên bản đang chạy qua `compute_replan_delta`.
    4. Tạo một `WorkflowVersion` hoàn toàn mới (giữ nguyên phiên bản cũ bất biến 100%).
    5. Nếu phát hiện tăng rủi ro hoặc mở rộng phạm vi -> tự động chuyển lượt chạy sang
       `WAITING_APPROVAL` và phát hành một `ApprovalRequest` chặn thực thi ngầm.
    """
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:update")

    run = await repository.get_run_by_id(
        session, organization_id=actor.organization_id, run_id=run_id
    )
    if run is None:
        raise NotFoundError("Không tìm thấy lượt chạy quy trình.", code="WORKFLOW_RUN_NOT_FOUND")

    if run.status in TERMINAL_RUN_STATUSES:
        raise ConflictError(
            f"Lượt chạy đã kết thúc với trạng thái `{run.status}` nên không thể lập lại phương án.",
            code="WORKFLOW_RUN_ALREADY_TERMINAL",
        )

    parent_version = await repository.get_version_by_id_in_org(
        session,
        organization_id=actor.organization_id,
        version_id=run.workflow_version_id,
    )
    if parent_version is None:
        raise NotFoundError("Không tìm thấy phiên bản quy trình gốc của lượt chạy.", code="WORKFLOW_VERSION_NOT_FOUND")

    parent_limits = dict((parent_version.graph_json or {}).get("limits") or {})
    assert_replan_allowed(run.replan_count, int(parent_limits.get("max_replans", 2)))

    report = validate_workflow_graph(payload.proposed_graph)
    if not report.valid:
        raise ValidationAppError(
            "Sơ đồ đề xuất lập lại không vượt qua bộ kiểm định 7 tầng.",
            code="REPLAN_GRAPH_INVALID",
            details={"errors": [e.model_dump() for e in report.errors]},
        )

    delta = compute_replan_delta(dict(parent_version.graph_json or {}), payload.proposed_graph)
    new_hash = compute_graph_content_hash(payload.proposed_graph)
    scores = score_candidate_workflows([payload.proposed_graph])
    score_dict = scores[0].model_dump() if scores else {}

    max_ver = await repository.get_max_version_number(
        session,
        organization_id=actor.organization_id,
        workflow_definition_id=run.workflow_definition_id,
    )
    new_ver_status = (
        WorkflowVersionStatus.AWAITING_APPROVAL.value
        if delta.risk_escalated
        else WorkflowVersionStatus.VALID.value
    )
    new_version = WorkflowVersion(
        organization_id=actor.organization_id,
        workflow_definition_id=run.workflow_definition_id,
        version_number=max_ver + 1,
        status=new_ver_status,
        graph_json=payload.proposed_graph,
        content_hash=new_hash,
        validation_report_json=report.model_dump(),
        score_summary_json=score_dict,
        created_by_user_id=actor.user_id,
    )
    session.add(new_version)
    await session.flush()

    proposal_status = "AWAITING_APPROVAL" if delta.risk_escalated else "PROPOSED"
    proposal = WorkflowReplanProposal(
        organization_id=actor.organization_id,
        workflow_run_id=run.id,
        parent_version_id=parent_version.id,
        proposed_version_id=new_version.id,
        reason=payload.reason,
        scope_delta_json=delta.to_dict(),
        risk_escalated=delta.risk_escalated,
        status=proposal_status,
        proposed_by_actor_id=actor.membership_id,
    )
    session.add(proposal)

    approval_id: str | None = None
    run.replan_count += 1
    if delta.risk_escalated:
        run.status = WorkflowRunStatus.WAITING_APPROVAL.value
        replan_params = {
            "proposal_reason": payload.reason,
            "new_version_id": new_version.id,
            "new_content_hash": new_hash,
            "reasons": delta.reasons,
        }
        replan_scope = (
            ", ".join(delta.new_scopes) if delta.new_scopes else f"workflow:run:{run.id}"
        )[:255]
        approval = ApprovalRequest(
            organization_id=actor.organization_id,
            request_id=run.request_id,
            workflow_run_id=run.id,
            workflow_version_id=new_version.id,
            node_id="replan_gate",
            action="workflow:replan",
            parameters_json=replan_params,
            parameter_hash=compute_parameter_hash(
                action="workflow:replan",
                parameters=replan_params,
                resource_scope=replan_scope,
            ),
            resource_scope=replan_scope,
            policy_version="v1",
            risk_level=delta.max_proposed_risk if delta.max_proposed_risk in {"HIGH", "CRITICAL"} else "HIGH",
            required_role="department_manager",
            status=ApprovalRequestStatus.PENDING.value,
            requested_by_actor_id=actor.membership_id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        session.add(approval)
        await session.flush()
        approval_id = approval.id

    await record_audit_log(
        session,
        organization_id=actor.organization_id,
        actor_type="USER",
        actor_id=actor.membership_id,
        action="workflow_run:replanned",
        resource=f"workflow_run:{run.id}",
        outcome=proposal_status,
        request_id=run.request_id,
        workflow_run_id=run.id,
        approval_id=approval_id,
        safe_metadata={"risk_escalated": delta.risk_escalated, "replan_count": run.replan_count},
    )
    await enqueue_outbox_event(
        session,
        organization_id=actor.organization_id,
        event_type="WORKFLOW_REPLAN_PROPOSED",
        aggregate_type="workflow_run",
        aggregate_id=run.id,
        actor_type="USER",
        actor_id=actor.membership_id,
        request_id=run.request_id,
        workflow_run_id=run.id,
        payload={
            "new_version_id": new_version.id,
            "risk_escalated": delta.risk_escalated,
            "approval_id": approval_id,
        },
    )
    await session.commit()
    await session.refresh(proposal)
    return ReplanWorkflowRunOut(
        workflow_run_id=run.id,
        run_status=run.status,
        replan_count=run.replan_count,
        proposal=_to_replan_proposal_out(proposal),
        new_version_id=new_version.id,
        new_version_number=new_version.version_number,
        new_version_status=new_version.status,
        approval_request_id=approval_id,
    )
