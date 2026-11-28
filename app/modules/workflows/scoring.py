"""Thuật toán chấm điểm xếp hạng các phương án sơ đồ quy trình sau khi qua kiểm định cứng."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.core.schemas import ContractModel

from .dsl.schemas import WorkflowGraphSpec
from .validator import WorkflowValidationReport, validate_workflow_graph


class ScoringWeights(ContractModel):
    """Trọng số đánh giá các phương án quy trình (có thể tùy chỉnh theo tổ chức)."""

    coverage: float = Field(default=0.30, ge=0.0)
    feasibility: float = Field(default=0.25, ge=0.0)
    efficiency: float = Field(default=0.20, ge=0.0)
    risk_penalty: float = Field(default=0.10, ge=0.0)
    cost_penalty: float = Field(default=0.08, ge=0.0)
    time_penalty: float = Field(default=0.07, ge=0.0)


class CandidateScoreSummary(ContractModel):
    """Kết quả kiểm định và điểm xếp hạng của một phương án sơ đồ ứng viên."""

    workflow_id: str
    name: str
    eligible: bool
    rank: int | None = None
    total_score: float | None = None
    validation_report: WorkflowValidationReport
    metrics_breakdown: dict[str, float] = Field(default_factory=dict)


_RISK_WEIGHT_MAP: dict[str, float] = {
    "LOW": 0.1,
    "MEDIUM": 0.35,
    "HIGH": 0.7,
    "CRITICAL": 1.0,
}


def score_candidate_workflows(
    candidates: list[dict[str, Any]],
    *,
    weights: ScoringWeights | None = None,
) -> list[CandidateScoreSummary]:
    """Kiểm định 7 tầng và xếp hạng các phương án sơ đồ theo công thức chuẩn hóa.

    Thuật toán gồm 3 bước:
    1. Chạy `validate_workflow_graph` cho từng ứng viên; bất kỳ ứng viên nào không hợp lệ
       sẽ bị đánh dấu `eligible=False`, `rank=None` (ràng buộc cứng không bao giờ bị đánh đổi).
    2. Với các ứng viên hợp lệ, tính các thành phần chuẩn hóa trong khoảng [0, 1] và áp công thức:
       `Score = wC*Coverage + wF*Feasibility + wE*Efficiency - wR*Risk - wK*Cost - wT*ExpectedTime`.
    3. Sắp xếp giảm dần theo điểm và gán thứ hạng `rank = 1, 2, ...` cho nhóm hợp lệ.
    """
    active_weights = weights or ScoringWeights()
    weight_sum = (
        active_weights.coverage
        + active_weights.feasibility
        + active_weights.efficiency
        + active_weights.risk_penalty
        + active_weights.cost_penalty
        + active_weights.time_penalty
    ) or 1.0

    w_c = active_weights.coverage / weight_sum
    w_f = active_weights.feasibility / weight_sum
    w_e = active_weights.efficiency / weight_sum
    w_r = active_weights.risk_penalty / weight_sum
    w_k = active_weights.cost_penalty / weight_sum
    w_t = active_weights.time_penalty / weight_sum

    eligible_items: list[CandidateScoreSummary] = []
    ineligible_items: list[CandidateScoreSummary] = []

    for idx, raw_graph in enumerate(candidates, start=1):
        report = validate_workflow_graph(raw_graph)
        wf_id = str(raw_graph.get("workflow_id") or f"candidate-{idx}")
        wf_name = str(raw_graph.get("name") or wf_id)

        if not report.valid:
            ineligible_items.append(
                CandidateScoreSummary(
                    workflow_id=wf_id,
                    name=wf_name,
                    eligible=False,
                    rank=None,
                    total_score=None,
                    validation_report=report,
                )
            )
            continue

        spec = WorkflowGraphSpec.model_validate(raw_graph)
        node_types = {n.type.upper() for n in spec.nodes}
        coverage = 1.0 if {"CLASSIFY", "VERIFICATION"}.issubset(node_types) else 0.85
        feasibility = 1.0
        efficiency = max(0.2, 1.0 - (len(spec.nodes) / 30.0) * 0.5)
        max_risk = max((_RISK_WEIGHT_MAP[n.risk_class] for n in spec.nodes), default=0.1)
        total_cost = sum(n.estimated_cost_usd for n in spec.nodes)
        norm_cost = min(1.0, total_cost / max(spec.limits.max_estimated_cost_usd, 0.01))
        total_timeout = sum(n.timeout_seconds for n in spec.nodes)
        norm_time = min(1.0, total_timeout / max(spec.limits.max_duration_seconds, 60))

        raw_score = (
            w_c * coverage
            + w_f * feasibility
            + w_e * efficiency
            - w_r * max_risk
            - w_k * norm_cost
            - w_t * norm_time
        )
        eligible_items.append(
            CandidateScoreSummary(
                workflow_id=wf_id,
                name=wf_name,
                eligible=True,
                total_score=round(raw_score, 4),
                validation_report=report,
                metrics_breakdown={
                    "coverage": round(coverage, 3),
                    "feasibility": round(feasibility, 3),
                    "efficiency": round(efficiency, 3),
                    "risk_penalty": round(max_risk, 3),
                    "cost_penalty": round(norm_cost, 3),
                    "time_penalty": round(norm_time, 3),
                },
            )
        )

    eligible_items.sort(key=lambda item: float(item.total_score or 0.0), reverse=True)
    ranked_eligible = [
        item.model_copy(update={"rank": rank_idx})
        for rank_idx, item in enumerate(eligible_items, start=1)
    ]
    return ranked_eligible + ineligible_items
