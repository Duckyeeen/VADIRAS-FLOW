"""Giao diện tìm kiếm tài liệu hướng dẫn và các phiếu xử lý tương tự trong quá khứ."""

from __future__ import annotations

from app.modules.memory.embeddings import (
    DeterministicEmbeddingProvider,
    cosine_similarity,
    keyword_overlap_score,
)

from .schemas import PreprocessedContext, RetrievedDocument, SimilarTicket

_ADVISORY_KB_DOCS: tuple[tuple[str, str, str, str], ...] = (
    (
        "KB-001",
        "Xử lý lỗi HTTP 500 khi xuất báo cáo PDF",
        "Kiểm tra kết nối hàng đợi xuất tệp, giới hạn bộ nhớ và quyền ghi kho lưu trữ tạm.",
        "docs/runbooks/pdf_export_500.md",
    ),
    (
        "KB-002",
        "Quy trình nâng giới hạn kết nối cơ sở dữ liệu",
        "Yêu cầu thay đổi phải qua quản lý kỹ thuật phê duyệt trước khi điều chỉnh cấu hình.",
        "docs/runbooks/db_pool_change.md",
    ),
    (
        "KB-003",
        "Hướng dẫn cấp quyền và thiết lập tài khoản nhân viên mới",
        "Tạo tài khoản, gán vai trò tối thiểu và kiểm tra hoàn tất checklist nhân sự.",
        "docs/runbooks/onboarding_checklist.md",
    ),
)

_ADVISORY_PAST_TICKETS: tuple[tuple[str, str, str], ...] = (
    (
        "REQ-HIST-101",
        "Lỗi timeout cổng xuất báo cáo cuối tháng",
        "Đã tăng thời gian chờ và kiểm chứng xuất báo cáo thành công (VERIFIED).",
    ),
    (
        "REQ-HIST-102",
        "Yêu cầu tăng kết nối cơ sở dữ liệu cho cụm thanh toán",
        "Quản lý đã phê duyệt tăng giới hạn an toàn và kiểm chứng đối chiếu xong.",
    ),
)


def retrieve_context(context: PreprocessedContext) -> PreprocessedContext:
    """Bổ sung tài liệu tham khảo và phiếu xử lý tương tự vào `PreprocessedContext`."""
    query = context.sanitized_text or ""
    embedder = DeterministicEmbeddingProvider()
    q_vec = embedder.embed_text(query)

    kb_hits: list[RetrievedDocument] = []
    for doc_id, title, content, source in _ADVISORY_KB_DOCS:
        d_vec = embedder.embed_text(f"{title} {content}")
        score = round(0.65 * cosine_similarity(q_vec, d_vec) + 0.35 * keyword_overlap_score(query, f"{title} {content}"), 4)
        kb_hits.append(
            RetrievedDocument(
                document_id=doc_id,
                title=title,
                content=content,
                score=score,
                source=source,
            )
        )
    kb_hits.sort(key=lambda d: d.score, reverse=True)

    ticket_hits: list[SimilarTicket] = []
    for t_id, title, resolution in _ADVISORY_PAST_TICKETS:
        t_vec = embedder.embed_text(f"{title} {resolution}")
        score = round(0.65 * cosine_similarity(q_vec, t_vec) + 0.35 * keyword_overlap_score(query, f"{title} {resolution}"), 4)
        ticket_hits.append(
            SimilarTicket(
                ticket_id=t_id,
                title=title,
                resolution=resolution,
                score=score,
            )
        )
    ticket_hits.sort(key=lambda t: t.score, reverse=True)

    return context.model_copy(
        update={
            "retrieved_kb": kb_hits[:3],
            "similar_tickets": ticket_hits[:2],
        }
    )
