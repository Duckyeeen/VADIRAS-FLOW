"""Các tuyến API quản lý yêu cầu phê duyệt và đánh giá quy tắc kiểm soát."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.modules.identity.dependencies import get_current_actor
from app.modules.identity.service import AuthenticatedActor
from app.modules.runtime import repository as runtime_repo
from app.modules.runtime.contracts import ApprovalSignalPayload
from app.modules.runtime.temporal_client import TemporalRuntimeGateway

from . import service
from .schemas import (
    ApprovalDecisionIn,
    ApprovalListResponse,
    ApprovalRequestOut,
    CreateApprovalIn,
    GovernanceEvaluateIn,
    GovernanceEvaluateOut,
)

router = APIRouter(prefix="/api/v1", tags=["Kiểm soát & Phê duyệt"])


@router.get("/approvals", response_model=ApprovalListResponse, summary="Danh sách yêu cầu phê duyệt")
async def list_approvals(
    page: int = Query(default=1, ge=1, description="Số trang cần lấy."),
    page_size: int = Query(default=20, ge=1, le=100, description="Số bản ghi tối đa mỗi trang."),
    status_filter: str | None = Query(default=None, alias="status", description="Lọc theo trạng thái duyệt."),
    request_id: str | None = Query(default=None, description="Lọc theo mã yêu cầu."),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalListResponse:
    """Liệt kê các yêu cầu phê duyệt thuộc phạm vi tổ chức của nhân viên gọi API."""
    return await service.list_approvals_for_actor(
        session,
        actor=actor,
        page=page,
        page_size=page_size,
        status=status_filter,
        request_id=request_id,
    )


@router.get(
    "/approvals/{approval_id}",
    response_model=ApprovalRequestOut,
    summary="Xem chi tiết yêu cầu phê duyệt",
)
async def get_approval_detail(
    approval_id: str,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalRequestOut:
    """Hiển thị chính xác hành động, tham số, mã băm, phạm vi, mức rủi ro và phiên bản quy trình."""
    return await service.get_approval_detail_for_actor(
        session,
        actor=actor,
        approval_id=approval_id,
    )


@router.post(
    "/approvals",
    response_model=ApprovalRequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo yêu cầu phê duyệt mới",
)
async def create_approval(
    payload: CreateApprovalIn,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalRequestOut:
    """Khởi tạo yêu cầu phê duyệt gắn chặt 7 yếu tố cho bước nhạy cảm."""
    return await service.create_approval_request_for_actor(
        session,
        actor=actor,
        payload=payload,
    )


@router.post(
    "/approvals/{approval_id}/decision",
    response_model=ApprovalRequestOut,
    summary="Phê duyệt hoặc từ chối yêu cầu",
)
async def decide_approval(
    approval_id: str,
    payload: ApprovalDecisionIn,
    request: Request,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> ApprovalRequestOut:
    """Ghi nhận quyết định duyệt/từ chối, đồng thời đánh thức lượt chạy Temporal nếu đang chờ."""
    result = await service.decide_approval_for_actor(
        session,
        actor=actor,
        approval_id=approval_id,
        payload=payload,
    )
    if result.workflow_run_id:
        run = await runtime_repo.get_run_by_id(
            session,
            organization_id=actor.organization_id,
            run_id=result.workflow_run_id,
        )
        gateway: TemporalRuntimeGateway | None = getattr(request.app.state, "runtime_gateway", None)
        if run is not None and gateway is not None:
            await gateway.signal_approval(
                run.temporal_workflow_id,
                ApprovalSignalPayload(
                    approval_id=result.id,
                    node_id=result.node_id or "",
                    decision=result.status,
                    decided_by=actor.membership_id,
                    rationale=payload.rationale,
                ),
            )
    return result


@router.post(
    "/governance/evaluate",
    response_model=GovernanceEvaluateOut,
    summary="Đánh giá thử quy tắc kiểm soát và rủi ro",
)
async def evaluate_governance_preview(
    payload: GovernanceEvaluateIn,
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> GovernanceEvaluateOut:
    """Kiểm tra trước quyết định của Bộ quy tắc cố định đối với một hành động dự kiến."""
    return service.evaluate_policy_preview_for_actor(actor, payload=payload)
