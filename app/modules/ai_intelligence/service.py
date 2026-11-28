"""Tầng xử lý nghiệp vụ điều phối phân tích AI, lưu vết chi phí và tra cứu trợ lý AI."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.modules.identity.schemas import PaginationMeta
from app.modules.identity.service import AuthenticatedActor, require_employee, require_permission
from app.modules.requests import repository as request_repo
from app.modules.requests.models import Request, RequestAnalysis, RequestStatus

from . import repository
from .models import AgentRun, AgentTask, LLMCallRecord
from .prompts.registry import PromptRegistry
from .providers.base import LLMProvider
from .providers.factory import build_llm_provider
from .schemas import (
    AgentIdentityOut,
    AgentListResponse,
    AgentRunOut,
    ProposeWorkflowsOut,
    RequestAnalysisOut,
)
from .swarm.supervisor import SwarmSupervisor


def _to_agent_run_out(run: AgentRun) -> AgentRunOut:
    """Chuyển bản ghi lượt chạy trợ lý AI sang khuôn mẫu phản hồi API."""
    return AgentRunOut(
        id=run.id,
        role_code=run.role_code,
        round_number=run.round_number,
        status=run.status,
        decision_summary=run.decision_summary,
        assumptions=list(run.assumptions_json or []),
        evidence_refs=list(run.evidence_refs_json or []),
        confidence_score=run.confidence_score,
        latency_ms=run.latency_ms,
    )


def _to_analysis_out(analysis: RequestAnalysis, runs: list[AgentRun]) -> RequestAnalysisOut:
    """Chuyển bản ghi phân tích yêu cầu kèm các lượt chạy chuyên viên sang khuôn mẫu API."""
    return RequestAnalysisOut(
        id=analysis.id,
        organization_id=analysis.organization_id,
        request_id=analysis.request_id,
        version_number=analysis.version_number,
        analysis_job_id=analysis.analysis_job_id,
        provider=analysis.provider,
        model=analysis.model,
        prompt_version=analysis.prompt_version,
        status=analysis.status,
        decision_summary=analysis.decision_summary,
        assumptions=list(analysis.assumptions_json or []),
        evidence_refs=list(analysis.evidence_refs_json or []),
        confidence_score=analysis.confidence_score,
        structured_output=dict(analysis.structured_output_json or {}),
        agent_runs=[_to_agent_run_out(run) for run in runs],
        created_at=analysis.created_at,
    )


def _build_context_snapshot(req: Request) -> dict[str, object]:
    """Tạo bản chụp dữ liệu sạch để gửi cho AI (chỉ dùng mô tả đã che thông tin cá nhân)."""
    return {
        "organization_id": req.organization_id,
        "request_id": req.id,
        "request_number": req.request_number,
        "request_type": req.request_type,
        "title": req.title,
        "sanitized_description": req.sanitized_description,
        "priority": req.priority,
        "impact": req.impact,
        "urgency": req.urgency,
        "requester_kind": req.requester_kind,
        "injection_flags": list(req.injection_flags_json or []),
    }


async def analyze_request_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    request_id: str,
    settings: Settings,
    provider_override: LLMProvider | None = None,
) -> RequestAnalysisOut:
    """Chạy nhóm 9 trợ lý AI phân tích yêu cầu và lưu bản phân tích có phiên bản vào CSDL.

    Các bước xử lý:
    1. Chỉ nhân viên nội bộ có quyền đọc/cập nhật yêu cầu mới được kích hoạt phân tích
       (tuyệt đối không để lộ kết quả phân tích nội bộ cho khách hàng).
    2. Lấy bản chụp dữ liệu sạch (`sanitized_description`) để chạy `SwarmSupervisor`.
    3. Lưu đầy đủ `RequestAnalysis` (tăng `version_number`), `AgentTask`, `AgentRun` và
       `LLMCallRecord` với nguồn chi phí trung thực (`ESTIMATED` / `ACTUAL` / `UNKNOWN`).
    4. Cập nhật trạng thái yêu cầu sang `NEEDS_INFORMATION` nếu thiếu dữ liệu, hoặc `TRIAGED`
       nếu đang ở trạng thái `OPEN`.
    """
    require_employee(actor)
    if "requests:update" not in actor.permissions:
        require_permission(actor, "requests:read_all")

    req = await request_repo.get_request_by_id(
        session,
        organization_id=actor.organization_id,
        request_id=request_id,
    )
    if req is None:
        raise NotFoundError("Không tìm thấy yêu cầu cần phân tích.", code="REQUEST_NOT_FOUND")

    provider = provider_override or build_llm_provider(settings)
    prompt_registry = PromptRegistry()
    supervisor = SwarmSupervisor(
        provider=provider,
        prompt_registry=prompt_registry,
        max_concurrent=settings.swarm_max_concurrent,
        max_review_rounds=settings.swarm_max_rounds,
        max_repair_attempts=settings.llm_max_repair_attempts,
    )
    swarm_result = await supervisor.run_analysis(context_snapshot=_build_context_snapshot(req))

    next_version = await repository.get_next_analysis_version(
        session,
        organization_id=actor.organization_id,
        request_id=req.id,
    )
    structured_payload = {
        "recommended_request_type": swarm_result.recommended_request_type,
        "recommended_department": swarm_result.recommended_department,
        "recommended_priority": swarm_result.recommended_priority,
        "risk_level": swarm_result.risk_level,
        "missing_information": swarm_result.missing_information,
        "hard_blockers": swarm_result.hard_blockers,
        "candidate_workflows": [p.model_dump() for p in swarm_result.candidate_workflows],
        "rounds_executed": swarm_result.rounds_executed,
    }
    analysis = RequestAnalysis(
        organization_id=actor.organization_id,
        request_id=req.id,
        version_number=next_version,
        analysis_job_id=swarm_result.analysis_job_id,
        provider=swarm_result.provider,
        model=swarm_result.model,
        prompt_version=swarm_result.prompt_version,
        status=swarm_result.status,
        structured_output_json=structured_payload,
        decision_summary=swarm_result.decision_summary,
        assumptions_json=swarm_result.assumptions,
        evidence_refs_json=swarm_result.evidence_refs,
        confidence_score=swarm_result.confidence_score,
    )
    session.add(analysis)

    identities_map = await repository.get_agent_identities_map(
        session,
        organization_id=actor.organization_id,
    )
    now = datetime.now(timezone.utc)
    saved_runs: list[AgentRun] = []

    for log_item in swarm_result.agent_logs:
        identity = identities_map.get(log_item.role_code)
        agent_task = AgentTask(
            organization_id=actor.organization_id,
            request_id=req.id,
            analysis_job_id=swarm_result.analysis_job_id,
            agent_identity_id=identity.id if identity is not None else None,
            role_code=log_item.role_code,
            round_number=log_item.round_number,
            status="COMPLETED",
            input_snapshot_json={"request_number": req.request_number, "round_number": log_item.round_number},
            started_at=now,
            finished_at=now,
        )
        session.add(agent_task)
        await session.flush()

        agent_run = AgentRun(
            organization_id=actor.organization_id,
            agent_task_id=agent_task.id,
            request_id=req.id,
            analysis_job_id=swarm_result.analysis_job_id,
            role_code=log_item.role_code,
            round_number=log_item.round_number,
            status=log_item.status,
            structured_output_json=log_item.structured_output,
            decision_summary=log_item.decision_summary,
            assumptions_json=log_item.assumptions,
            evidence_refs_json=log_item.evidence_refs,
            confidence_score=log_item.confidence,
            latency_ms=log_item.latency_ms,
        )
        session.add(agent_run)
        await session.flush()
        saved_runs.append(agent_run)

        llm_record = LLMCallRecord(
            organization_id=actor.organization_id,
            request_id=req.id,
            agent_run_id=agent_run.id,
            analysis_job_id=swarm_result.analysis_job_id,
            provider=swarm_result.provider,
            model=swarm_result.model,
            purpose=f"swarm:{log_item.role_code}",
            prompt_version=swarm_result.prompt_version,
            status=log_item.status,
            repair_attempts=log_item.repair_attempts,
            latency_ms=log_item.latency_ms,
            prompt_tokens=log_item.prompt_tokens,
            completion_tokens=log_item.completion_tokens,
            cost_usd=log_item.cost_usd,
            cost_source=log_item.cost_source,
        )
        session.add(llm_record)

    if swarm_result.status == "NEEDS_INFORMATION":
        req.status = RequestStatus.NEEDS_INFORMATION.value
    elif req.status == RequestStatus.OPEN.value:
        req.status = RequestStatus.TRIAGED.value

    if swarm_result.recommended_department not in list(req.proposed_departments_json or []):
        req.proposed_departments_json = [*list(req.proposed_departments_json or []), swarm_result.recommended_department]
    req.updated_by_user_id = actor.user_id

    await session.commit()
    await session.refresh(analysis)
    return _to_analysis_out(analysis, saved_runs)


async def get_request_analysis_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    request_id: str,
    version: int | None = None,
) -> RequestAnalysisOut:
    """Xem kết quả phân tích AI nội bộ của một yêu cầu (chặn tài khoản khách hàng)."""
    require_employee(actor)
    require_permission(actor, "requests:read_all")

    analysis = await repository.get_analysis_by_version(
        session,
        organization_id=actor.organization_id,
        request_id=request_id,
        version_number=version,
    )
    if analysis is None:
        raise NotFoundError("Chưa có kết quả phân tích nào cho yêu cầu này.", code="ANALYSIS_NOT_FOUND")

    runs = await repository.list_agent_runs_for_job(
        session,
        organization_id=actor.organization_id,
        analysis_job_id=analysis.analysis_job_id,
    )
    return _to_analysis_out(analysis, runs)


async def propose_workflows_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    request_id: str,
    settings: Settings,
) -> ProposeWorkflowsOut:
    """Lấy danh sách phương án sơ đồ quy trình ứng viên cho yêu cầu (tự phân tích nếu chưa có)."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:read_all")

    latest = await repository.get_analysis_by_version(
        session,
        organization_id=actor.organization_id,
        request_id=request_id,
    )
    if latest is None:
        analysis_out = await analyze_request_for_actor(
            session,
            actor=actor,
            request_id=request_id,
            settings=settings,
        )
        proposals = list(analysis_out.structured_output.get("candidate_workflows", []))
        return ProposeWorkflowsOut(
            request_id=request_id,
            analysis_id=analysis_out.id,
            analysis_version=analysis_out.version_number,
            status=analysis_out.status,
            proposals=proposals,
        )

    proposals = list((latest.structured_output_json or {}).get("candidate_workflows", []))
    return ProposeWorkflowsOut(
        request_id=request_id,
        analysis_id=latest.id,
        analysis_version=latest.version_number,
        status=latest.status,
        proposals=proposals,
    )


async def list_agents_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    page: int,
    page_size: int,
) -> AgentListResponse:
    """Liệt kê các danh tính trợ lý AI thuộc tổ chức của nhân viên gọi API."""
    require_employee(actor)
    require_permission(actor, "agents:read")

    rows, total = await repository.list_agents_with_capabilities(
        session,
        organization_id=actor.organization_id,
        page=page,
        page_size=page_size,
    )
    items = [
        AgentIdentityOut(
            id=agent.id,
            organization_id=agent.organization_id,
            role_code=agent.role_code,
            display_name=agent.display_name,
            status=agent.status,
            limits=dict(agent.limits_json or {}),
            capabilities=caps,
        )
        for agent, caps in rows
    ]
    return AgentListResponse(
        items=items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total),
    )


async def get_agent_detail_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    agent_id: str,
) -> AgentIdentityOut:
    """Xem chi tiết một trợ lý AI và các năng lực được đăng ký trong tổ chức."""
    require_employee(actor)
    require_permission(actor, "agents:read")

    found = await repository.get_agent_with_capabilities(
        session,
        organization_id=actor.organization_id,
        agent_id=agent_id,
    )
    if found is None:
        raise NotFoundError("Không tìm thấy trợ lý AI trong tổ chức của bạn.", code="AGENT_NOT_FOUND")
    agent, caps = found
    return AgentIdentityOut(
        id=agent.id,
        organization_id=agent.organization_id,
        role_code=agent.role_code,
        display_name=agent.display_name,
        status=agent.status,
        limits=dict(agent.limits_json or {}),
        capabilities=caps,
    )
