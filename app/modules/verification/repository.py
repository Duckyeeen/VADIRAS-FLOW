"""Tầng truy vấn cơ sở dữ liệu cho kết quả xác minh, bằng chứng và nhật ký kiểm toán."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import AuditLog, ExecutionEvidence, VerificationRun


async def list_verification_runs_for_request(
    session: AsyncSession,
    *,
    organization_id: str,
    request_id: str,
) -> list[VerificationRun]:
    """Lấy toàn bộ lịch sử các lượt xác minh gắn với một yêu cầu trong tổ chức."""
    stmt = (
        sa.select(VerificationRun)
        .options(selectinload(VerificationRun.evidences))
        .execution_options(populate_existing=True)
        .where(
            VerificationRun.organization_id == organization_id,
            VerificationRun.request_id == request_id,
        )
        .order_by(VerificationRun.verified_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_evidence_for_run(
    session: AsyncSession,
    *,
    organization_id: str,
    workflow_run_id: str,
) -> list[ExecutionEvidence]:
    """Lấy toàn bộ bằng chứng thu thập được của một lượt chạy quy trình trong tổ chức."""
    stmt = (
        sa.select(ExecutionEvidence)
        .where(
            ExecutionEvidence.organization_id == organization_id,
            ExecutionEvidence.workflow_run_id == workflow_run_id,
        )
        .order_by(ExecutionEvidence.captured_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_audit_logs(
    session: AsyncSession,
    *,
    organization_id: str,
    page: int,
    page_size: int,
    request_id: str | None = None,
    workflow_run_id: str | None = None,
    actor_type: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
) -> tuple[list[AuditLog], int]:
    """Truy vấn nhật ký kiểm toán chỉ đọc có lọc chặt theo `organization_id` và phân trang."""
    filters: list[sa.ColumnElement[bool]] = [AuditLog.organization_id == organization_id]
    if request_id:
        filters.append(AuditLog.request_id == request_id.strip())
    if workflow_run_id:
        filters.append(AuditLog.workflow_run_id == workflow_run_id.strip())
    if actor_type:
        filters.append(AuditLog.actor_type == actor_type.strip().upper())
    if action:
        filters.append(AuditLog.action == action.strip())
    if outcome:
        filters.append(AuditLog.outcome == outcome.strip().upper())

    count_stmt = sa.select(sa.func.count()).select_from(AuditLog).where(*filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = (
        sa.select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return rows, total
