"""Các tuyến API luồng sự kiện SSE và 7 nhóm thống kê hiệu suất, SLA, chi phí."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.session import get_db_session
from app.modules.identity.dependencies import get_current_actor
from app.modules.identity.service import AuthenticatedActor, require_employee, require_permission
from app.modules.runtime import repository as runtime_repo

from .analytics import (
    AnalyticsFilter,
    compute_agent_metrics,
    compute_automation_metrics,
    compute_cost_metrics,
    compute_department_metrics,
    compute_industry_metrics,
    compute_overview_metrics,
    compute_sla_metrics,
)
from .sse import stream_workflow_run_events

router = APIRouter(prefix="/api/v1", tags=["Giám sát, SSE & Thống kê"])


def _build_filter(
    actor: AuthenticatedActor,
    *,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    department_id: str | None = None,
    request_type: str | None = None,
    workflow_id: str | None = None,
    domain_pack: str | None = None,
) -> AnalyticsFilter:
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:read_all")
    return AnalyticsFilter(
        organization_id=actor.organization_id,
        from_date=from_date,
        to_date=to_date,
        department_id=department_id,
        request_type=request_type,
        workflow_id=workflow_id,
        domain_pack=domain_pack,
    )


@router.get(
    "/workflow-runs/{run_id}/events",
    summary="Luồng sự kiện tiến độ trực tiếp (SSE) của lượt chạy quy trình",
)
async def stream_run_events_sse(
    run_id: str,
    once: bool = Query(default=False, description="Đặt `true` để nhận snapshot + sự kiện hiện có rồi đóng luồng."),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Phát luồng sự kiện SSE có kiểm tra quyền và cô lập tổ chức giống hoàn toàn API REST."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:read_all")

    run = await runtime_repo.get_run_by_id(
        session, organization_id=actor.organization_id, run_id=run_id
    )
    if run is None:
        raise NotFoundError("Không tìm thấy lượt chạy quy trình.", code="WORKFLOW_RUN_NOT_FOUND")

    generator = stream_workflow_run_events(
        session,
        organization_id=actor.organization_id,
        run_id=run_id,
        once=once,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/metrics/overview", summary="Thống kê tổng quan yêu cầu và lượt chạy")
async def metrics_overview(
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    department_id: str | None = Query(default=None),
    request_type: str | None = Query(default=None),
    workflow_id: str | None = Query(default=None),
    domain_pack: str | None = Query(default=None),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    flt = _build_filter(
        actor,
        from_date=from_date,
        to_date=to_date,
        department_id=department_id,
        request_type=request_type,
        workflow_id=workflow_id,
        domain_pack=domain_pack,
    )
    return await compute_overview_metrics(session, flt)


@router.get("/metrics/sla", summary="Thống kê tuân thủ thời hạn cam kết (SLA)")
async def metrics_sla(
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    department_id: str | None = Query(default=None),
    request_type: str | None = Query(default=None),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    flt = _build_filter(
        actor,
        from_date=from_date,
        to_date=to_date,
        department_id=department_id,
        request_type=request_type,
    )
    return await compute_sla_metrics(session, flt)


@router.get("/metrics/automation", summary="Thống kê tỷ lệ tự động hóa và thời gian duyệt")
async def metrics_automation(
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    department_id: str | None = Query(default=None),
    request_type: str | None = Query(default=None),
    workflow_id: str | None = Query(default=None),
    domain_pack: str | None = Query(default=None),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    flt = _build_filter(
        actor,
        from_date=from_date,
        to_date=to_date,
        department_id=department_id,
        request_type=request_type,
        workflow_id=workflow_id,
        domain_pack=domain_pack,
    )
    return await compute_automation_metrics(session, flt)


@router.get("/metrics/cost", summary="Thống kê chi phí AI tách bạch nguồn thực và ước tính")
async def metrics_cost(
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    department_id: str | None = Query(default=None),
    request_type: str | None = Query(default=None),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    flt = _build_filter(
        actor,
        from_date=from_date,
        to_date=to_date,
        department_id=department_id,
        request_type=request_type,
    )
    return await compute_cost_metrics(session, flt)


@router.get("/metrics/agents", summary="Thống kê hiệu suất nhóm 9 trợ lý AI")
async def metrics_agents(
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    flt = _build_filter(actor)
    return await compute_agent_metrics(session, flt)


@router.get("/metrics/departments", summary="Thống kê khối lượng và SLA theo 6 phòng ban")
async def metrics_departments(
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    request_type: str | None = Query(default=None),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    flt = _build_filter(actor, from_date=from_date, to_date=to_date, request_type=request_type)
    return await compute_department_metrics(session, flt)


@router.get("/metrics/industries", summary="Thống kê theo gói miền nghiệp vụ và loại yêu cầu")
async def metrics_industries(
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    domain_pack: str | None = Query(default=None),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    flt = _build_filter(actor, from_date=from_date, to_date=to_date, domain_pack=domain_pack)
    return await compute_industry_metrics(session, flt)
