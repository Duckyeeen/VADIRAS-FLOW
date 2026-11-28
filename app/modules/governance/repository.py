"""Tầng truy vấn cơ sở dữ liệu cho yêu cầu phê duyệt và quyết định kiểm soát."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import ApprovalRequest


async def get_approval_by_id(
    session: AsyncSession,
    *,
    organization_id: str,
    approval_id: str,
) -> ApprovalRequest | None:
    """Lấy chi tiết yêu cầu phê duyệt kèm kết quả quyết định trong phạm vi tổ chức."""
    stmt = (
        sa.select(ApprovalRequest)
        .options(selectinload(ApprovalRequest.decision_record))
        .execution_options(populate_existing=True)
        .where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.organization_id == organization_id,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_approvals(
    session: AsyncSession,
    *,
    organization_id: str,
    page: int,
    page_size: int,
    status: str | None = None,
    request_id: str | None = None,
) -> tuple[list[ApprovalRequest], int]:
    """Liệt kê danh sách yêu cầu phê duyệt có lọc và phân trang trong tổ chức."""
    filters: list[sa.ColumnElement[bool]] = [ApprovalRequest.organization_id == organization_id]
    if status:
        filters.append(ApprovalRequest.status == status.strip().upper())
    if request_id:
        filters.append(ApprovalRequest.request_id == request_id)

    count_stmt = sa.select(sa.func.count()).select_from(ApprovalRequest).where(*filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = (
        sa.select(ApprovalRequest)
        .options(selectinload(ApprovalRequest.decision_record))
        .where(*filters)
        .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await session.execute(stmt)).scalars().all())
    return items, total
