"""Tầng truy vấn cơ sở dữ liệu cho định nghĩa và phiên bản sơ đồ quy trình."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import WorkflowDefinition, WorkflowVersion


async def get_definition_by_code(
    session: AsyncSession,
    *,
    organization_id: str,
    code: str,
) -> WorkflowDefinition | None:
    """Tìm định nghĩa quy trình theo mã `code` trong phạm vi tổ chức."""
    stmt = sa.select(WorkflowDefinition).where(
        WorkflowDefinition.organization_id == organization_id,
        WorkflowDefinition.code == code,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_definition_by_id(
    session: AsyncSession,
    *,
    organization_id: str,
    workflow_id: str,
) -> WorkflowDefinition | None:
    """Lấy định nghĩa quy trình kèm toàn bộ danh sách phiên bản trong tổ chức."""
    stmt = (
        sa.select(WorkflowDefinition)
        .options(selectinload(WorkflowDefinition.versions))
        .execution_options(populate_existing=True)
        .where(
            WorkflowDefinition.id == workflow_id,
            WorkflowDefinition.organization_id == organization_id,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_definitions(
    session: AsyncSession,
    *,
    organization_id: str,
    page: int,
    page_size: int,
    request_type: str | None = None,
) -> tuple[list[WorkflowDefinition], int]:
    """Lấy danh sách quy trình có phân trang thuộc một tổ chức."""
    filters: list[sa.ColumnElement[bool]] = [WorkflowDefinition.organization_id == organization_id]
    if request_type:
        filters.append(WorkflowDefinition.request_type == request_type.strip().upper())

    count_stmt = sa.select(sa.func.count()).select_from(WorkflowDefinition).where(*filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = (
        sa.select(WorkflowDefinition)
        .options(selectinload(WorkflowDefinition.versions))
        .where(*filters)
        .order_by(WorkflowDefinition.created_at.desc(), WorkflowDefinition.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await session.execute(stmt)).scalars().all())
    return items, total


async def get_version_by_id(
    session: AsyncSession,
    *,
    organization_id: str,
    workflow_id: str,
    version_id: str,
) -> WorkflowVersion | None:
    """Lấy một phiên bản quy trình cụ thể trong phạm vi tổ chức."""
    stmt = sa.select(WorkflowVersion).where(
        WorkflowVersion.id == version_id,
        WorkflowVersion.workflow_definition_id == workflow_id,
        WorkflowVersion.organization_id == organization_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_latest_version(
    session: AsyncSession,
    *,
    organization_id: str,
    workflow_id: str,
) -> WorkflowVersion | None:
    """Lấy phiên bản mới nhất của một quy trình trong phạm vi tổ chức."""
    stmt = (
        sa.select(WorkflowVersion)
        .where(
            WorkflowVersion.workflow_definition_id == workflow_id,
            WorkflowVersion.organization_id == organization_id,
        )
        .order_by(WorkflowVersion.version_number.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
