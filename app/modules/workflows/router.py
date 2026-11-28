"""Các tuyến API thiết kế, kiểm định 7 tầng và ban hành phiên bản quy trình bất biến."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.modules.identity.dependencies import get_current_actor
from app.modules.identity.service import AuthenticatedActor

from . import service
from .schemas import (
    CreateWorkflowIn,
    CreateWorkflowVersionIn,
    NodeRegistryResponse,
    PublishWorkflowIn,
    ValidateGraphIn,
    WorkflowDefinitionOut,
    WorkflowListResponse,
    WorkflowVersionOut,
)
from .validator import WorkflowValidationReport

router = APIRouter(prefix="/api/v1", tags=["Thiết kế & Kiểm định Quy trình"])


@router.get(
    "/workflows/node-registry",
    response_model=NodeRegistryResponse,
    summary="Danh mục 12 loại bước quy trình cho giao diện vẽ",
)
async def get_node_registry(
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> NodeRegistryResponse:
    """Xuất danh sách 12 loại bước chuẩn kèm cấu trúc JSON Schema cấu hình cho React Flow."""
    return service.get_node_registry_for_actor(actor)


@router.post(
    "/workflows/validate",
    response_model=WorkflowValidationReport,
    summary="Kiểm tra hợp lệ 7 tầng cho sơ đồ quy trình",
)
async def validate_workflow(
    payload: ValidateGraphIn,
    actor: AuthenticatedActor = Depends(get_current_actor),
) -> WorkflowValidationReport:
    """Chạy kiểm định 7 tầng trên một sơ đồ JSON và trả chi tiết lỗi/cảnh báo từng bước."""
    return service.validate_graph_for_actor(actor, graph_data=payload.graph)


@router.post(
    "/workflows",
    response_model=WorkflowDefinitionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo quy trình mới kèm phiên bản đầu tiên",
)
async def create_workflow(
    payload: CreateWorkflowIn,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowDefinitionOut:
    """Tạo định nghĩa quy trình và phiên bản đầu tiên v1 kèm báo cáo kiểm định."""
    return await service.create_workflow_for_actor(session, actor=actor, payload=payload)


@router.get("/workflows", response_model=WorkflowListResponse, summary="Danh sách quy trình")
async def list_workflows(
    page: int = Query(default=1, ge=1, description="Số trang cần lấy."),
    page_size: int = Query(default=20, ge=1, le=100, description="Số bản ghi tối đa mỗi trang."),
    request_type: str | None = Query(default=None, description="Lọc theo loại yêu cầu."),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowListResponse:
    """Liệt kê danh sách quy trình thuộc tổ chức của nhân viên gọi API."""
    return await service.list_workflows_for_actor(
        session,
        actor=actor,
        page=page,
        page_size=page_size,
        request_type=request_type,
    )


@router.get(
    "/workflows/{workflow_id}",
    response_model=WorkflowDefinitionOut,
    summary="Xem chi tiết quy trình và các phiên bản",
)
async def get_workflow_detail(
    workflow_id: str,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowDefinitionOut:
    """Xem thông tin định nghĩa quy trình và toàn bộ danh sách phiên bản."""
    return await service.get_workflow_detail_for_actor(
        session,
        actor=actor,
        workflow_id=workflow_id,
    )


@router.post(
    "/workflows/{workflow_id}/versions",
    response_model=WorkflowVersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo phiên bản sơ đồ quy trình mới",
)
async def create_workflow_version(
    workflow_id: str,
    payload: CreateWorkflowVersionIn,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowVersionOut:
    """Tạo phiên bản mới (`v+1`) mà không làm thay đổi các phiên bản đã ban hành trước đó."""
    return await service.create_workflow_version_for_actor(
        session,
        actor=actor,
        workflow_id=workflow_id,
        payload=payload,
    )


@router.get(
    "/workflows/{workflow_id}/versions/{version_id}",
    response_model=WorkflowVersionOut,
    summary="Xem chi tiết một phiên bản quy trình",
)
async def get_workflow_version(
    workflow_id: str,
    version_id: str,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowVersionOut:
    """Lấy sơ đồ JSON, mã băm `content_hash` và kết quả kiểm định của phiên bản cụ thể."""
    return await service.get_workflow_version_for_actor(
        session,
        actor=actor,
        workflow_id=workflow_id,
        version_id=version_id,
    )


@router.post(
    "/workflows/{workflow_id}/publish",
    response_model=WorkflowVersionOut,
    summary="Ban hành phiên bản quy trình bất biến",
)
async def publish_workflow_version(
    workflow_id: str,
    payload: PublishWorkflowIn = Body(default_factory=PublishWorkflowIn),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> WorkflowVersionOut:
    """Kiểm định lại 7 tầng và khóa cứng phiên bản thành `PUBLISHED` nếu hoàn toàn hợp lệ."""
    return await service.publish_workflow_version_for_actor(
        session,
        actor=actor,
        workflow_id=workflow_id,
        payload=payload,
    )
