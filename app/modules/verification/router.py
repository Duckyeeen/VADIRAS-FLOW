"""Các tuyến API tra cứu kết quả xác minh, bằng chứng đối chiếu ngược và nhật ký kiểm toán."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.modules.identity.dependencies import get_current_actor
from app.modules.identity.service import AuthenticatedActor

from . import service
from .schemas import (
    AuditLogListResponse,
    RequestVerificationResponse,
    RunEvidenceResponse,
)

router = APIRouter(prefix="/api/v1", tags=["Xác minh & Kiểm toán"])


@router.get(
    "/requests/{request_id}/verification",
    response_model=RequestVerificationResponse,
    summary="Xem kết quả xác minh và bằng chứng của yêu cầu",
)
async def get_request_verification(
    request_id: str,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> RequestVerificationResponse:
    """Trả về trạng thái xác minh và bằng chứng (lọc bỏ bằng chứng nội bộ nếu là khách hàng)."""
    return await service.get_request_verification_for_actor(
        session, actor=actor, request_id=request_id
    )


@router.get(
    "/workflow-runs/{run_id}/evidence",
    response_model=RunEvidenceResponse,
    summary="Xem toàn bộ bằng chứng của một lượt chạy quy trình",
)
async def get_workflow_run_evidence(
    run_id: str,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> RunEvidenceResponse:
    """Liệt kê toàn bộ bằng chứng đọc ngược thu thập trong một lượt chạy cho nhân viên nội bộ."""
    return await service.get_run_evidence_for_actor(
        session, actor=actor, run_id=run_id
    )


@router.get(
    "/audit-logs",
    response_model=AuditLogListResponse,
    summary="Tra cứu nhật ký kiểm toán hệ thống",
)
async def list_audit_logs(
    page: int = Query(default=1, ge=1, description="Số trang cần lấy."),
    page_size: int = Query(default=20, ge=1, le=100, description="Số bản ghi tối đa mỗi trang."),
    request_id: str | None = Query(default=None, description="Lọc theo mã yêu cầu."),
    workflow_run_id: str | None = Query(default=None, description="Lọc theo mã lượt chạy."),
    actor_type: str | None = Query(default=None, description="Lọc theo loại chủ thể (`USER`, `SYSTEM`, `AGENT`)."),
    action: str | None = Query(default=None, description="Lọc theo tên hành động."),
    outcome: str | None = Query(default=None, description="Lọc theo kết quả."),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> AuditLogListResponse:
    """Đọc nhật ký kiểm toán chỉ thêm mới trong phạm vi tổ chức."""
    return await service.list_audit_logs_for_actor(
        session,
        actor=actor,
        page=page,
        page_size=page_size,
        request_id=request_id,
        workflow_run_id=workflow_run_id,
        actor_type=actor_type,
        action=action,
        outcome=outcome,
    )
