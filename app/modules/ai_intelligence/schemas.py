"""Khuôn mẫu dữ liệu API cho phân tích AI, đề xuất sơ đồ quy trình và danh sách trợ lý AI."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.modules.identity.schemas import PaginationMeta
from app.core.schemas import ContractModel


class AgentRunOut(ContractModel):
    """Thông tin rút gọn của một lượt chạy trợ lý AI (chỉ hiển thị cho nhân viên nội bộ)."""

    id: str
    role_code: str
    round_number: int
    status: str
    decision_summary: str
    assumptions: list[str]
    evidence_refs: list[str]
    confidence_score: float
    latency_ms: float


class RequestAnalysisOut(ContractModel):
    """Kết quả phân tích có phiên bản của một yêu cầu công việc."""

    id: str
    organization_id: str
    request_id: str
    version_number: int
    analysis_job_id: str
    provider: str
    model: str
    prompt_version: str
    status: str
    decision_summary: str
    assumptions: list[str]
    evidence_refs: list[str]
    confidence_score: float
    structured_output: dict[str, Any]
    agent_runs: list[AgentRunOut]
    created_at: datetime


class ProposeWorkflowsOut(ContractModel):
    """Danh sách sơ đồ quy trình ứng viên được đề xuất từ kết quả phân tích AI."""

    request_id: str
    analysis_id: str
    analysis_version: int
    status: str
    proposals: list[dict[str, Any]]


class AgentIdentityOut(ContractModel):
    """Thông tin danh tính dịch vụ và năng lực đã đăng ký của một trợ lý AI."""

    id: str
    organization_id: str
    role_code: str
    display_name: str
    status: str
    limits: dict[str, Any]
    capabilities: list[str]


class AgentListResponse(ContractModel):
    """Phản hồi danh sách các trợ lý AI thuộc tổ chức hiện tại."""

    items: list[AgentIdentityOut]
    pagination: PaginationMeta
