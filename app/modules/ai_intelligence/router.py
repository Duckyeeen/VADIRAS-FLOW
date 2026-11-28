"""Các tuyến API kích hoạt phân tích AI, đề xuất sơ đồ quy trình và tra cứu trợ lý AI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_db_session
from app.modules.identity.dependencies import get_app_settings, get_current_actor
from app.modules.identity.service import AuthenticatedActor

from . import service
from .schemas import (
    AgentIdentityOut,
    AgentListResponse,
    ProposeWorkflowsOut,
    RequestAnalysisOut,
)

router = APIRouter(prefix="/api/v1", tags=["Trí tuệ AI & Trợ lý"])


@router.post(
    "/requests/{request_id}/analyze",
    response_model=RequestAnalysisOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Chạy nhóm 9 trợ lý AI phân tích yêu cầu",
)
async def analyze_request(
    request_id: str,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> RequestAnalysisOut:
    """Điều phối nhóm trợ lý AI phân tích bản sạch của yêu cầu và lưu phiên bản kết quả."""
    return await service.analyze_request_for_actor(
        session,
        actor=actor,
        request_id=request_id,
        settings=settings,
    )


@router.get(
    "/requests/{request_id}/analysis",
    response_model=RequestAnalysisOut,
    summary="Xem kết quả phân tích AI của yêu cầu",
)
async def get_request_analysis(
    request_id: str,
    version: int | None = Query(default=None, ge=1, description="Số phiên bản phân tích (mặc định bản mới nhất)."),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> RequestAnalysisOut:
    """Trả kết quả phân tích nội bộ có phiên bản (tài khoản khách hàng bị chặn xem)."""
    return await service.get_request_analysis_for_actor(
        session,
        actor=actor,
        request_id=request_id,
        version=version,
    )


@router.post(
    "/requests/{request_id}/propose-workflows",
    response_model=ProposeWorkflowsOut,
    summary="Đề xuất các phương án sơ đồ quy trình cho yêu cầu",
)
async def propose_workflows(
    request_id: str,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> ProposeWorkflowsOut:
    """Trả danh sách sơ đồ quy trình ứng viên lắp ghép từ 12 loại bước chuẩn."""
    return await service.propose_workflows_for_actor(
        session,
        actor=actor,
        request_id=request_id,
        settings=settings,
    )


@router.get("/agents", response_model=AgentListResponse, summary="Danh sách trợ lý AI")
async def list_agents(
    page: int = Query(default=1, ge=1, description="Số trang cần lấy."),
    page_size: int = Query(default=20, ge=1, le=100, description="Số bản ghi tối đa mỗi trang."),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> AgentListResponse:
    """Liệt kê các danh tính trợ lý AI và năng lực được cấp trong tổ chức."""
    return await service.list_agents_for_actor(
        session,
        actor=actor,
        page=page,
        page_size=page_size,
    )


@router.get("/agents/{agent_id}", response_model=AgentIdentityOut, summary="Chi tiết một trợ lý AI")
async def get_agent_detail(
    agent_id: str,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> AgentIdentityOut:
    """Xem chi tiết một vai trò trợ lý AI thuộc tổ chức hiện tại."""
    return await service.get_agent_detail_for_actor(
        session,
        actor=actor,
        agent_id=agent_id,
    )
