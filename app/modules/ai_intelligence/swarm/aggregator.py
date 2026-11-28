"""Thuật toán tổng hợp kết quả và giải quyết mâu thuẫn cố định giữa các trợ lý AI."""

from __future__ import annotations

from .schemas import (
    AgentExecutionLog,
    CandidateWorkflowProposal,
    CriticReview,
    SpecialistFinding,
    SwarmAnalysisResult,
)

# Thứ tự ưu tiên độ rủi ro và độ khẩn cấp (luôn lấy mức cao nhất khi có bất đồng)
_RISK_RANK: dict[str, int] = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
_PRIORITY_RANK: dict[str, int] = {"P4_LOW": 1, "P3_MEDIUM": 2, "P2_HIGH": 3, "P1_CRITICAL": 4}


def _deduplicate_keep_order(items: list[str]) -> list[str]:
    """Loại bỏ phần tử trùng lặp nhưng vẫn giữ nguyên thứ tự ban đầu."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def aggregate_swarm_outputs(
    *,
    analysis_job_id: str,
    provider_name: str,
    model_name: str,
    prompt_version: str,
    specialist_findings: list[SpecialistFinding],
    candidate_workflows: list[CandidateWorkflowProposal],
    critic_review: CriticReview,
    rounds_executed: int,
    agent_logs: list[AgentExecutionLog],
) -> SwarmAnalysisResult:
    """Giải quyết mâu thuẫn giữa các chuyên viên AI theo quy tắc cứng (không dùng biểu quyết số đông).

    Thuật toán gồm 5 bước:
    1. Lấy mức độ rủi ro cao nhất và mức ưu tiên cao nhất trong toàn bộ chuyên viên
       (đảm bảo 1 cảnh báo `CRITICAL` của Chuyên viên Bảo mật không bị 3 phiếu `LOW` lấn át).
    2. Gom toàn bộ yếu tố chặn cứng (`hard_blockers`) từ Bảo mật và Phản biện.
    3. Nếu thiếu thông tin bắt buộc -> chốt trạng thái `NEEDS_INFORMATION`.
    4. Nếu có yếu tố chặn cứng mức `CRITICAL`, hoặc Phản biện không duyệt sau số vòng tối đa,
       hoặc không có sơ đồ ứng viên hợp lệ -> chốt trạng thái `NO_SAFE_PLAN` để con người can thiệp.
    5. Tổng hợp tóm tắt quyết định, giả định và dẫn chứng (tuyệt đối không lưu suy nghĩ ẩn).
    """
    # Bước 1: Xác định mức rủi ro cao nhất và mức ưu tiên cao nhất
    highest_risk = max(
        (f.risk_level for f in specialist_findings),
        key=lambda level: _RISK_RANK[level],
        default="LOW",
    )
    highest_priority = max(
        (f.recommended_priority for f in specialist_findings),
        key=lambda p: _PRIORITY_RANK[p],
        default="P3_MEDIUM",
    )

    # Ưu tiên khuyến nghị phân loại từ Request Analyst và phòng ban từ Operations Analyst
    by_role = {f.role_code: f for f in specialist_findings}
    req_analyst = by_role.get("request_analyst")
    ops_analyst = by_role.get("operations_analyst")
    recommended_type = (
        req_analyst.recommended_request_type
        if req_analyst is not None
        else specialist_findings[0].recommended_request_type
    )
    recommended_dept = (
        ops_analyst.recommended_department
        if ops_analyst is not None
        else specialist_findings[0].recommended_department
    )

    # Bước 2: Thu thập thông tin thiếu, chặn cứng, giả định và dẫn chứng
    missing_info = _deduplicate_keep_order(
        [item for f in specialist_findings for item in f.missing_information]
    )
    hard_blockers = _deduplicate_keep_order(
        [item for f in specialist_findings for item in f.hard_blockers]
        + list(critic_review.blocking_issues)
    )
    assumptions = _deduplicate_keep_order(
        [item for f in specialist_findings for item in f.assumptions]
        + list(critic_review.assumptions)
    )
    evidence_refs = _deduplicate_keep_order(
        [item for f in specialist_findings for item in f.evidence_refs]
        + list(critic_review.evidence_refs)
    )

    # Bước 3 & 4: Quyết định trạng thái kết luận an toàn
    if missing_info:
        final_status = "NEEDS_INFORMATION"
    elif (hard_blockers and highest_risk == "CRITICAL") or not critic_review.approved or not candidate_workflows:
        final_status = "NO_SAFE_PLAN"
    else:
        final_status = "COMPLETED"

    # Bước 5: Tạo tóm tắt quyết định súc tích và điểm tin cậy trung bình có trọng số
    avg_confidence = round(
        sum(f.confidence for f in specialist_findings) / max(len(specialist_findings), 1),
        3,
    )
    summary_parts = [
        f"Trạng thái phân tích: {final_status}",
        f"Loại đề xuất: {recommended_type}",
        f"Phòng ban đề xuất: {recommended_dept}",
        f"Mức rủi ro cao nhất: {highest_risk}",
    ]
    if hard_blockers:
        summary_parts.append(f"Cảnh báo chặn cứng: {'; '.join(hard_blockers)}")
    if missing_info:
        summary_parts.append(f"Thông tin cần bổ sung: {'; '.join(missing_info)}")

    return SwarmAnalysisResult(
        analysis_job_id=analysis_job_id,
        status=final_status,
        provider=provider_name,
        model=model_name,
        prompt_version=prompt_version,
        recommended_request_type=recommended_type,
        recommended_department=recommended_dept,
        recommended_priority=highest_priority,
        risk_level=highest_risk,
        missing_information=missing_info,
        hard_blockers=hard_blockers,
        candidate_workflows=[] if final_status == "NEEDS_INFORMATION" else candidate_workflows,
        decision_summary=" | ".join(summary_parts),
        assumptions=assumptions,
        evidence_refs=evidence_refs,
        confidence_score=avg_confidence,
        rounds_executed=rounds_executed,
        agent_logs=agent_logs,
    )
