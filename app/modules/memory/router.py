"""Các tuyến API tìm kiếm, lưu trữ và thăng hạng tri thức trong bộ nhớ `pgvector`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.modules.identity.dependencies import get_current_actor
from app.modules.identity.service import AuthenticatedActor

from . import service
from .schemas import (
    CreateMemoryItemIn,
    MemoryItemOut,
    MemorySearchResponse,
    PromoteMemoryItemIn,
)

router = APIRouter(prefix="/api/v1", tags=["Bộ nhớ Ngữ nghĩa"])


@router.get(
    "/memory/search",
    response_model=MemorySearchResponse,
    summary="Tìm kiếm tri thức ngữ nghĩa có lọc quyền",
)
async def search_memory(
    q: str = Query(min_length=1, max_length=500, description="Từ khóa hoặc câu truy vấn cần tìm."),
    memory_class: str | None = Query(default=None, description="Lọc theo 1 trong 5 nhóm bộ nhớ."),
    department_id: str | None = Query(default=None, description="Lọc theo phòng ban."),
    request_type: str | None = Query(default=None, description="Lọc theo loại yêu cầu."),
    top_k: int = Query(default=5, ge=1, le=20, description="Số kết quả tối đa trả về."),
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> MemorySearchResponse:
    """Truy xuất bộ nhớ có lọc tổ chức, phân loại quyền xem, hiệu lực và điểm tương đồng."""
    return await service.search_memory_for_actor(
        session,
        actor=actor,
        query=q,
        memory_class=memory_class,
        department_id=department_id,
        request_type=request_type,
        top_k=top_k,
    )


@router.post(
    "/memory/items",
    response_model=MemoryItemOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo mới một mục tri thức trong bộ nhớ",
)
async def create_memory_item(
    payload: CreateMemoryItemIn,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> MemoryItemOut:
    """Thêm mới một mục tri thức vào bộ nhớ kèm nguồn gốc và mức xác thực."""
    return await service.create_memory_item_for_actor(
        session, actor=actor, payload=payload
    )


@router.post(
    "/memory/items/{item_id}/promote",
    response_model=MemoryItemOut,
    summary="Thăng hạng mục tri thức sau khi đã xác minh",
)
async def promote_memory_item(
    item_id: str,
    payload: PromoteMemoryItemIn,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> MemoryItemOut:
    """Chuyển trạng thái sang `PROMOTED` nếu mục tri thức đã `VERIFIED` hoặc được người duyệt xác nhận."""
    return await service.promote_memory_item_for_actor(
        session, actor=actor, item_id=item_id, payload=payload
    )
