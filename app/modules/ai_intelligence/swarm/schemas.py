"""Khuôn mẫu dữ liệu trao đổi giữa các trợ lý AI (cấm chứa suy nghĩ ẩn nội bộ)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.core.schemas import ContractModel


class SpecialistFinding(ContractModel):
    """Kết quả phân tích có cấu trúc từ một chuyên viên AI chuyên trách."""

    role_code: str = Field(min_length=2, max_length=64)
    recommended_request_type: str = Field(min_length=2, max_length=64)
    recommended_department: str = Field(min_length=2, max_length=64)
    recommended_priority: Literal["P1_CRITICAL", "P2_HIGH", "P3_MEDIUM", "P4_LOW"] = "P3_MEDIUM"
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"
    findings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    hard_blockers: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    decision_summary: str = Field(min_length=1, max_length=2_000)


class CandidateWorkflowNode(ContractModel):
    """Mô tả một bước trong sơ đồ quy trình ứng viên do Trợ lý Thiết kế đề xuất."""

    id: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)


class CandidateWorkflowEdge(ContractModel):
    """Mô tả một đường nối có điều kiện an toàn giữa hai bước trong sơ đồ quy trình."""

    id: str = Field(min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=64)
    condition: str | None = Field(default=None, max_length=500)
    label: str | None = Field(default=None, max_length=120)


class CandidateWorkflowProposal(ContractModel):
    """Một phương án sơ đồ quy trình ứng viên lắp ghép từ 12 loại bước chuẩn."""

    template_code: str = Field(min_length=2, max_length=128)
    name: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3, max_length=1_000)
    nodes: list[CandidateWorkflowNode] = Field(min_length=2, max_length=30)
    edges: list[CandidateWorkflowEdge] = Field(min_length=1, max_length=60)
    requires_approval: bool = False
    verification_criteria: list[str] = Field(default_factory=list)


class PlannerProposalOutput(ContractModel):
    """Đầu ra có cấu trúc của Trợ lý Thiết kế Quy trình (1–3 phương án ứng viên)."""

    proposals: list[CandidateWorkflowProposal] = Field(default_factory=list, max_length=3)
    decision_summary: str = Field(min_length=1, max_length=2_000)
    assumptions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class CriticReview(ContractModel):
    """Đầu ra có cấu trúc của Trợ lý Phản biện sau khi rà soát sơ đồ ứng viên."""

    approved: bool
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
    decision_summary: str = Field(min_length=1, max_length=2_000)
    assumptions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class AgentExecutionLog(ContractModel):
    """Vết chạy rút gọn của từng trợ lý AI trong một phiên phân tích."""

    role_code: str
    round_number: int
    status: str
    repair_attempts: int
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    cost_source: str
    decision_summary: str
    structured_output: dict[str, Any]
    assumptions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class SwarmAnalysisResult(ContractModel):
    """Kết quả tổng hợp cuối cùng của Điều phối viên trưởng sau các vòng phân tích có giới hạn."""

    analysis_job_id: str
    status: Literal["COMPLETED", "NEEDS_INFORMATION", "NO_SAFE_PLAN"]
    provider: str
    model: str
    prompt_version: str
    recommended_request_type: str
    recommended_department: str
    recommended_priority: Literal["P1_CRITICAL", "P2_HIGH", "P3_MEDIUM", "P4_LOW"]
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    missing_information: list[str] = Field(default_factory=list)
    hard_blockers: list[str] = Field(default_factory=list)
    candidate_workflows: list[CandidateWorkflowProposal] = Field(default_factory=list)
    decision_summary: str
    assumptions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    rounds_executed: int = Field(ge=1)
    agent_logs: list[AgentExecutionLog] = Field(default_factory=list)
