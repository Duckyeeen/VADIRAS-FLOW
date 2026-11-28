"""Tầng truy vấn cơ sở dữ liệu cho lượt chạy quy trình, từng bước chạy và đề xuất lập lại."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.workflows.models import (
    WorkflowDefinition,
    WorkflowNodeRun,
    WorkflowReplanProposal,
    WorkflowRun,
    WorkflowVersion,
)


async def get_run_by_id(
    session: AsyncSession,
    *,
    organization_id: str,
    run_id: str,
) -> WorkflowRun | None:
    """Lấy bản ghi lượt chạy theo mã `run_id` trong đúng phạm vi tổ chức."""
    stmt = (
        sa.select(WorkflowRun)
        .execution_options(populate_existing=True)
        .where(
            WorkflowRun.id == run_id,
            WorkflowRun.organization_id == organization_id,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_run_by_idempotency_key(
    session: AsyncSession,
    *,
    organization_id: str,
    idempotency_key: str,
) -> WorkflowRun | None:
    """Tìm lượt chạy đã khởi tạo trước đó trùng `idempotency_key` trong cùng tổ chức."""
    stmt = sa.select(WorkflowRun).where(
        WorkflowRun.organization_id == organization_id,
        WorkflowRun.idempotency_key == idempotency_key,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_runs(
    session: AsyncSession,
    *,
    organization_id: str,
    page: int,
    page_size: int,
    status: str | None = None,
    request_id: str | None = None,
) -> tuple[list[WorkflowRun], int]:
    """Liệt kê các lượt chạy quy trình trong tổ chức kèm lọc và phân trang."""
    filters: list[sa.ColumnElement[bool]] = [WorkflowRun.organization_id == organization_id]
    if status:
        filters.append(WorkflowRun.status == status.strip().upper())
    if request_id:
        filters.append(WorkflowRun.request_id == request_id.strip())

    count_stmt = sa.select(sa.func.count()).select_from(WorkflowRun).where(*filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = (
        sa.select(WorkflowRun)
        .where(*filters)
        .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return rows, total


async def list_node_runs(
    session: AsyncSession,
    *,
    organization_id: str,
    workflow_run_id: str,
) -> list[WorkflowNodeRun]:
    """Lấy toàn bộ lịch sử thực thi từng bước của một lượt chạy theo thứ tự tạo."""
    stmt = (
        sa.select(WorkflowNodeRun)
        .where(
            WorkflowNodeRun.organization_id == organization_id,
            WorkflowNodeRun.workflow_run_id == workflow_run_id,
        )
        .order_by(WorkflowNodeRun.created_at.asc(), WorkflowNodeRun.attempt.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_replan_proposals(
    session: AsyncSession,
    *,
    organization_id: str,
    workflow_run_id: str,
) -> list[WorkflowReplanProposal]:
    """Lấy danh sách các đề xuất lập lại sơ đồ gắn với một lượt chạy."""
    stmt = (
        sa.select(WorkflowReplanProposal)
        .where(
            WorkflowReplanProposal.organization_id == organization_id,
            WorkflowReplanProposal.workflow_run_id == workflow_run_id,
        )
        .order_by(WorkflowReplanProposal.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_version_by_id_in_org(
    session: AsyncSession,
    *,
    organization_id: str,
    version_id: str,
) -> WorkflowVersion | None:
    """Lấy một phiên bản quy trình theo `version_id` trong phạm vi tổ chức."""
    stmt = (
        sa.select(WorkflowVersion)
        .execution_options(populate_existing=True)
        .where(
            WorkflowVersion.id == version_id,
            WorkflowVersion.organization_id == organization_id,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_definition_by_id_in_org(
    session: AsyncSession,
    *,
    organization_id: str,
    definition_id: str,
) -> WorkflowDefinition | None:
    """Lấy định nghĩa quy trình theo `definition_id` trong phạm vi tổ chức."""
    stmt = sa.select(WorkflowDefinition).where(
        WorkflowDefinition.id == definition_id,
        WorkflowDefinition.organization_id == organization_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_max_version_number(
    session: AsyncSession,
    *,
    organization_id: str,
    workflow_definition_id: str,
) -> int:
    """Tìm số thứ tự phiên bản cao nhất hiện tại của một định nghĩa quy trình."""
    stmt = sa.select(sa.func.coalesce(sa.func.max(WorkflowVersion.version_number), 0)).where(
        WorkflowVersion.organization_id == organization_id,
        WorkflowVersion.workflow_definition_id == workflow_definition_id,
    )
    return int((await session.execute(stmt)).scalar_one())
