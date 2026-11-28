"""Các tuyến API khởi chạy, theo dõi và điều khiển lượt chạy quy trình Temporal."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.modules.identity.dependencies import get_current_actor
from app.modules.identity.service import AuthenticatedActor

from . import service
from .schemas import (
    ReplanWorkflowRunIn,
    ReplanWorkflowRunOut,
    RunControlActionIn,
    StartWorkflowRunIn,
    WorkflowRunListResponse,
    WorkflowRunOut,
)
from .temporal_client import TemporalRuntimeGateway

router = APIRouter(prefix="/api/v1", tags=["Thực thi quy trình Temporal"])


def _get_runtime_gateway(request: Request) -> TemporalRuntimeGateway:
    gateway = getattr(request.app.state, "runtime_gateway", None)
    if gateway is None:
        gateway = TemporalRuntimeGateway(settings=request.app.state.settings)
        request.app.state.runtime_gateway = gateway
    return gateway


@router.post(
    "/workflow-runs",
    response_model=WorkflowRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Khởi phát lượt chạy quy trình mới",
)
async def start_workflow_run(
    payload: StartWorkflowRunIn,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowRunOut:
    """Khởi phát một lượt chạy từ phiên bản `PUBLISHED` kèm bảo vệ chống tạo trùng lặp."""
    gateway = _get_runtime_gateway(request)
    return await service.start_workflow_run_for_actor(
        session,
        actor=actor,
        payload=payload,
        gateway=gateway,
        header_idempotency_key=idempotency_key,
    )


@router.get(
    "/workflow-runs",
    response_model=WorkflowRunListResponse,
    summary="Danh sách lượt chạy quy trình",
)
async def list_workflow_runs(
    page: int = Query(default=1, ge=1, description="Số trang cần lấy."),
    page_size: int = Query(default=20, ge=1, le=100, description="Số bản ghi tối đa mỗi trang."),
    status_filter: str | None = Query(default=None, alias="status", description="Lọc theo trạng thái lượt chạy."),
    request_id: str | None = Query(default=None, description="Lọc theo mã yêu cầu."),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowRunListResponse:
    """Liệt kê các lượt chạy quy trình thuộc phạm vi tổ chức."""
    return await service.list_workflow_runs_for_actor(
        session,
        actor=actor,
        page=page,
        page_size=page_size,
        status=status_filter,
        request_id=request_id,
    )


@router.get(
    "/workflow-runs/{run_id}",
    response_model=WorkflowRunOut,
    summary="Xem chi tiết lượt chạy quy trình",
)
async def get_workflow_run_detail(
    run_id: str,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowRunOut:
    """Xem đầy đủ thông tin lượt chạy, lịch sử từng bước và các đề xuất lập lại."""
    return await service.get_workflow_run_detail_for_actor(
        session,
        actor=actor,
        run_id=run_id,
    )


@router.post(
    "/workflow-runs/{run_id}/pause",
    response_model=WorkflowRunOut,
    summary="Tạm dừng lượt chạy quy trình",
)
async def pause_workflow_run(
    run_id: str,
    request: Request,
    payload: RunControlActionIn | None = None,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowRunOut:
    """Tạm dừng lượt chạy đang hoạt động và gửi tín hiệu xuống Temporal."""
    gateway = _get_runtime_gateway(request)
    return await service.pause_workflow_run_for_actor(
        session,
        actor=actor,
        run_id=run_id,
        reason=(payload.reason if payload else ""),
        gateway=gateway,
    )


@router.post(
    "/workflow-runs/{run_id}/resume",
    response_model=WorkflowRunOut,
    summary="Tiếp tục lượt chạy quy trình đang tạm dừng",
)
async def resume_workflow_run(
    run_id: str,
    request: Request,
    payload: RunControlActionIn | None = None,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowRunOut:
    """Gửi tín hiệu cho phép lượt chạy đang tạm dừng tiếp tục thực thi."""
    gateway = _get_runtime_gateway(request)
    return await service.resume_workflow_run_for_actor(
        session,
        actor=actor,
        run_id=run_id,
        reason=(payload.reason if payload else ""),
        gateway=gateway,
    )


@router.post(
    "/workflow-runs/{run_id}/cancel",
    response_model=WorkflowRunOut,
    summary="Hủy bỏ lượt chạy quy trình",
)
async def cancel_workflow_run(
    run_id: str,
    request: Request,
    payload: RunControlActionIn | None = None,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowRunOut:
    """Hủy lượt chạy chưa kết thúc và dừng thực thi các bước còn lại."""
    gateway = _get_runtime_gateway(request)
    return await service.cancel_workflow_run_for_actor(
        session,
        actor=actor,
        run_id=run_id,
        reason=(payload.reason if payload else ""),
        gateway=gateway,
    )


@router.post(
    "/workflow-runs/{run_id}/replan",
    response_model=ReplanWorkflowRunOut,
    status_code=status.HTTP_201_CREATED,
    summary="Đề xuất lập lại sơ đồ quy trình an toàn",
)
async def replan_workflow_run(
    run_id: str,
    payload: ReplanWorkflowRunIn,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> ReplanWorkflowRunOut:
    """Tạo phiên bản sơ đồ mới có kiểm định và giữ nguyên bản cũ bất biến."""
    return await service.replan_workflow_run_for_actor(
        session,
        actor=actor,
        run_id=run_id,
        payload=payload,
    )
