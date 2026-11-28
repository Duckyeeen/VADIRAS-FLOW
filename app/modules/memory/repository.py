"""Tầng truy vấn cơ sở dữ liệu cho bộ nhớ tri thức 5 nhóm với bộ lọc tổ chức và quyền xem."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from .models import MemoryItem, MemoryReviewStatus


async def get_memory_item_by_id(
    session: AsyncSession,
    *,
    organization_id: str,
    item_id: str,
) -> MemoryItem | None:
    """Lấy một mục tri thức theo mã `item_id` trong đúng phạm vi tổ chức."""
    stmt = (
        sa.select(MemoryItem)
        .execution_options(populate_existing=True)
        .where(
            MemoryItem.id == item_id,
            MemoryItem.organization_id == organization_id,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_promoted_candidates(
    session: AsyncSession,
    *,
    organization_id: str,
    customer_only: bool,
    memory_class: str | None = None,
    department_id: str | None = None,
    request_type: str | None = None,
    limit: int = 200,
) -> list[MemoryItem]:
    """Lọc các mục tri thức đủ điều kiện truy xuất ngay từ SQL trước khi chấm điểm tương đồng.

    Tuyệt đối chỉ lấy bản ghi cùng `organization_id` và đã ở trạng thái `PROMOTED`;
    nếu người tìm là khách hàng chỉ trả về bản ghi `CUSTOMER_VISIBLE`.
    """
    filters: list[sa.ColumnElement[bool]] = [
        MemoryItem.organization_id == organization_id,
        MemoryItem.review_status == MemoryReviewStatus.PROMOTED.value,
    ]
    if customer_only:
        filters.append(MemoryItem.access_classification == "CUSTOMER_VISIBLE")
    if memory_class:
        filters.append(MemoryItem.memory_class == memory_class.strip().upper())
    if department_id:
        filters.append(MemoryItem.department_id == department_id.strip())
    if request_type:
        filters.append(MemoryItem.request_type == request_type.strip().upper())

    stmt = (
        sa.select(MemoryItem)
        .where(*filters)
        .order_by(MemoryItem.updated_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())
