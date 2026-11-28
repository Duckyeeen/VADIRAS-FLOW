"""Khuôn mẫu dữ liệu vào và ra cho API quản lý và tìm kiếm bộ nhớ ngữ nghĩa."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.core.schemas import ContractModel


class CreateMemoryItemIn(ContractModel):
    """Dữ liệu tạo mới một mục tri thức trong bộ nhớ 5 nhóm."""

    memory_class: Literal[
        "REQUEST_MEMORY",
        "WORKFLOW_MEMORY",
        "EXECUTION_MEMORY",
        "KNOWLEDGE_MEMORY",
        "FEEDBACK_MEMORY",
    ]
    title: str = Field(min_length=3, max_length=300)
    content: str = Field(min_length=5, max_length=20_000)
    access_classification: Literal["INTERNAL_ONLY", "CUSTOMER_VISIBLE"] = "INTERNAL_ONLY"
    department_id: str | None = Field(default=None, max_length=36)
    request_type: str | None = Field(default=None, max_length=64)
    provenance_source: str = Field(default="manual_curated", min_length=2, max_length=128)
    provenance_ref: str | None = Field(default=None, max_length=255)
    verification_status: Literal["UNVERIFIED", "VERIFIED", "HUMAN_APPROVED"] = "UNVERIFIED"
    confidence_score: float = Field(default=0.7, ge=0.0, le=1.0)
    promote_immediately: bool = False


class PromoteMemoryItemIn(ContractModel):
    """Yêu cầu thăng hạng một mục tri thức thành mẫu chính thức được phép tìm kiếm lại."""

    human_approved: bool = False
    provenance_ref: str | None = Field(default=None, max_length=255)


class MemoryItemOut(ContractModel):
    """Thông tin một mục tri thức kèm nguồn gốc, mức xác thực và phân loại quyền xem."""

    id: str
    organization_id: str
    department_id: str | None = None
    memory_class: str
    access_classification: str
    request_type: str | None = None
    title: str
    content: str
    provenance_source: str
    provenance_ref: str | None = None
    verification_status: str
    review_status: str
    confidence_score: float
    embedding_model: str
    embedding_provider: str
    embedding_dimensions: int
    valid_from: datetime
    valid_until: datetime | None = None
    created_at: datetime


class MemorySearchHitOut(ContractModel):
    """Một kết quả tìm kiếm tri thức kèm điểm tương đồng và cảnh báo dữ liệu tham khảo."""

    item: MemoryItemOut
    score: float
    untrusted_reference: bool = True
    advisory_notice: str = "Dữ liệu tham khảo chỉ mang tính gợi ý; không được tự cấp quyền thực thi."


class MemorySearchResponse(ContractModel):
    """Kết quả trả về của API tìm kiếm bộ nhớ có lọc chặt quyền xem và tổ chức."""

    query: str
    total_hits: int
    hits: list[MemorySearchHitOut]
