"""Khuôn mẫu dữ liệu API cho thiết kế, kiểm định, chấm điểm và ban hành quy trình."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.modules.identity.schemas import PaginationMeta
from app.core.schemas import ContractModel


class ValidateGraphIn(ContractModel):
    """Dữ liệu đầu vào khi kiểm tra hợp lệ 7 tầng cho một sơ đồ quy trình."""

    graph: dict[str, Any]


class CreateWorkflowIn(ContractModel):
    """Dữ liệu đầu vào khi tạo định nghĩa quy trình kèm phiên bản đầu tiên."""

    code: str = Field(min_length=2, max_length=128)
    name: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=2_000)
    domain_pack: str = Field(default="enterprise_core", min_length=2, max_length=64)
    request_type: str = Field(min_length=2, max_length=64)
    graph: dict[str, Any]
    created_from_analysis_id: str | None = Field(default=None, min_length=36, max_length=36)


class CreateWorkflowVersionIn(ContractModel):
    """Dữ liệu đầu vào khi tạo phiên bản mới cho quy trình đã tồn tại."""

    graph: dict[str, Any]
    created_from_analysis_id: str | None = Field(default=None, min_length=36, max_length=36)


class PublishWorkflowIn(ContractModel):
    """Dữ liệu đầu vào khi ban hành một phiên bản quy trình (mặc định ban hành bản mới nhất)."""

    version_id: str | None = Field(default=None, min_length=36, max_length=36)


class WorkflowVersionOut(ContractModel):
    """Thông tin chi tiết một phiên bản sơ đồ quy trình kèm mã băm và báo cáo kiểm định."""

    id: str
    organization_id: str
    workflow_definition_id: str
    version_number: int
    status: str
    graph: dict[str, Any]
    content_hash: str
    validation_report: dict[str, Any]
    score_summary: dict[str, Any]
    created_from_analysis_id: str | None
    published_at: datetime | None
    created_at: datetime


class WorkflowDefinitionOut(ContractModel):
    """Thông tin định nghĩa quy trình kèm danh sách các phiên bản hiện có."""

    id: str
    organization_id: str
    code: str
    name: str
    description: str
    domain_pack: str
    request_type: str
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    versions: list[WorkflowVersionOut] = Field(default_factory=list)


class WorkflowListResponse(ContractModel):
    """Danh sách quy trình có phân trang thuộc tổ chức hiện tại."""

    items: list[WorkflowDefinitionOut]
    pagination: PaginationMeta


class NodeRegistryResponse(ContractModel):
    """Danh mục 12 loại bước chuẩn kèm JSON Schema cấu hình cho bảng vẽ giao diện."""

    node_types: list[dict[str, Any]]
