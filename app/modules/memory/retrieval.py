"""Bộ truy xuất kết hợp lọc quyền SQL + hiệu lực thời gian + tương đồng vector/từ khóa."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from .embeddings import DeterministicEmbeddingProvider, cosine_similarity, keyword_overlap_score
from .models import MemoryItem
from .repository import list_promoted_candidates


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class RankedMemoryHit:
    """Một kết quả tri thức được xếp hạng kèm cờ đánh dấu dữ liệu tham khảo chưa tin cậy."""

    item: MemoryItem
    score: float
    untrusted_reference: bool = True


async def search_memory_items(
    session: AsyncSession,
    *,
    organization_id: str,
    query: str,
    customer_only: bool,
    memory_class: str | None = None,
    department_id: str | None = None,
    request_type: str | None = None,
    top_k: int = 5,
    embedder: DeterministicEmbeddingProvider | None = None,
) -> list[RankedMemoryHit]:
    """Tìm kiếm tri thức theo đúng trình tự: lọc tổ chức & quyền -> lọc hiệu lực -> chấm điểm tương đồng."""
    candidates = await list_promoted_candidates(
        session,
        organization_id=organization_id,
        customer_only=customer_only,
        memory_class=memory_class,
        department_id=department_id,
        request_type=request_type,
    )
    now = datetime.now(timezone.utc)
    active_items: list[MemoryItem] = []
    for item in candidates:
        if _normalize_utc(item.valid_from) > now:
            continue
        if item.valid_until is not None and _normalize_utc(item.valid_until) <= now:
            continue
        active_items.append(item)

    if not active_items:
        return []

    provider = embedder or DeterministicEmbeddingProvider()
    q_vec = provider.embed_text(query)

    scored: list[RankedMemoryHit] = []
    for item in active_items:
        item_vec = [float(x) for x in (item.embedding_vector or [])]
        vec_sim = cosine_similarity(q_vec, item_vec)
        kw_sim = keyword_overlap_score(query, f"{item.title} {item.content}")
        combined = round(0.65 * vec_sim + 0.35 * kw_sim, 4)
        scored.append(RankedMemoryHit(item=item, score=combined, untrusted_reference=True))

    scored.sort(key=lambda h: (h.score, h.item.confidence_score), reverse=True)
    return scored[:top_k]
