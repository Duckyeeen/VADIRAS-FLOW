"""Tầng xử lý nghiệp vụ tạo, thăng hạng có kiểm soát và tìm kiếm bộ nhớ 5 nhóm."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.modules.identity.models import UserKind
from app.modules.identity.service import AuthenticatedActor, require_employee, require_permission

from . import repository
from .embeddings import DeterministicEmbeddingProvider
from .models import (
    MemoryItem,
    MemoryReviewStatus,
    MemoryVerificationStatus,
)
from .retrieval import search_memory_items
from .schemas import (
    CreateMemoryItemIn,
    MemoryItemOut,
    MemorySearchHitOut,
    MemorySearchResponse,
    PromoteMemoryItemIn,
)


def _to_memory_out(item: MemoryItem) -> MemoryItemOut:
    return MemoryItemOut(
        id=item.id,
        organization_id=item.organization_id,
        department_id=item.department_id,
        memory_class=item.memory_class,
        access_classification=item.access_classification,
        request_type=item.request_type,
        title=item.title,
        content=item.content,
        provenance_source=item.provenance_source,
        provenance_ref=item.provenance_ref,
        verification_status=item.verification_status,
        review_status=item.review_status,
        confidence_score=item.confidence_score,
        embedding_model=item.embedding_model,
        embedding_provider=item.embedding_provider,
        embedding_dimensions=item.embedding_dimensions,
        valid_from=item.valid_from,
        valid_until=item.valid_until,
        created_at=item.created_at,
    )


async def create_memory_item_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    payload: CreateMemoryItemIn,
) -> MemoryItemOut:
    """Lưu mới một mục tri thức vào bộ nhớ; chặn tự động thăng hạng nếu chưa được xác minh."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:update")

    is_verified = payload.verification_status in {
        MemoryVerificationStatus.VERIFIED.value,
        MemoryVerificationStatus.HUMAN_APPROVED.value,
    }
    if payload.promote_immediately and not is_verified:
        raise ConflictError(
            "Không thể thăng hạng tri thức chưa được xác minh (`VERIFIED` hoặc `HUMAN_APPROVED`).",
            code="MEMORY_PROMOTION_REQUIRES_VERIFICATION",
        )

    embedder = DeterministicEmbeddingProvider()
    vector = embedder.embed_text(f"{payload.title}\n{payload.content}")
    now = datetime.now(timezone.utc)

    item = MemoryItem(
        organization_id=actor.organization_id,
        department_id=payload.department_id,
        memory_class=payload.memory_class,
        access_classification=payload.access_classification,
        request_type=payload.request_type.strip().upper() if payload.request_type else None,
        title=payload.title,
        content=payload.content,
        provenance_source=payload.provenance_source,
        provenance_ref=payload.provenance_ref,
        verification_status=payload.verification_status,
        review_status=(
            MemoryReviewStatus.PROMOTED.value
            if payload.promote_immediately and is_verified
            else MemoryReviewStatus.DRAFT.value
        ),
        confidence_score=payload.confidence_score,
        valid_from=now,
        embedding_model=embedder.model_name,
        embedding_provider=embedder.provider_name,
        embedding_dimensions=embedder.dimensions,
        embedding_vector=vector,
        created_by_user_id=actor.user_id,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return _to_memory_out(item)


async def promote_memory_item_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    item_id: str,
    payload: PromoteMemoryItemIn,
) -> MemoryItemOut:
    """Thăng hạng một mục tri thức sang `PROMOTED` — bắt buộc đã `VERIFIED` hoặc có duyệt con người."""
    require_employee(actor)
    if "approvals:decide" not in actor.permissions:
        require_permission(actor, "workflows:manage")

    item = await repository.get_memory_item_by_id(
        session,
        organization_id=actor.organization_id,
        item_id=item_id,
    )
    if item is None:
        raise NotFoundError("Không tìm thấy mục tri thức trong tổ chức.", code="MEMORY_ITEM_NOT_FOUND")

    already_verified = item.verification_status in {
        MemoryVerificationStatus.VERIFIED.value,
        MemoryVerificationStatus.HUMAN_APPROVED.value,
    }
    if not already_verified and not payload.human_approved:
        raise ConflictError(
            "Chỉ được phép thăng hạng tri thức sau khi đã `VERIFIED` hoặc có phê duyệt tường minh từ nhân viên có thẩm quyền.",
            code="MEMORY_PROMOTION_REQUIRES_VERIFICATION",
        )

    if payload.human_approved and item.verification_status == MemoryVerificationStatus.UNVERIFIED.value:
        item.verification_status = MemoryVerificationStatus.HUMAN_APPROVED.value
    if payload.provenance_ref:
        item.provenance_ref = payload.provenance_ref
    item.review_status = MemoryReviewStatus.PROMOTED.value

    await session.commit()
    await session.refresh(item)
    return _to_memory_out(item)


async def search_memory_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    query: str,
    memory_class: str | None = None,
    department_id: str | None = None,
    request_type: str | None = None,
    top_k: int = 5,
) -> MemorySearchResponse:
    """Tìm kiếm bộ nhớ có lọc chặt `organization_id` và nhãn hiển thị của người dùng."""
    is_customer = actor.user_kind == UserKind.CUSTOMER_CONTACT.value
    hits = await search_memory_items(
        session,
        organization_id=actor.organization_id,
        query=query,
        customer_only=is_customer,
        memory_class=memory_class,
        department_id=department_id,
        request_type=request_type,
        top_k=top_k,
    )
    return MemorySearchResponse(
        query=query,
        total_hits=len(hits),
        hits=[
            MemorySearchHitOut(
                item=_to_memory_out(h.item),
                score=h.score,
                untrusted_reference=h.untrusted_reference,
            )
            for h in hits
        ],
    )
