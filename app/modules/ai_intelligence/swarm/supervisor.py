"""Điều phối viên trưởng quản lý nhóm chuyên viên AI chạy song song và phản biện có giới hạn."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from app.modules.ai_intelligence.prompts.registry import PromptRegistry
from app.modules.ai_intelligence.providers.base import LLMProvider

from .aggregator import aggregate_swarm_outputs
from .schemas import (
    AgentExecutionLog,
    CriticReview,
    PlannerProposalOutput,
    SpecialistFinding,
    SwarmAnalysisResult,
)

# 4 vai trò chuyên viên phân tích độc lập có thể chạy song song ngay từ đầu
PARALLEL_ANALYST_ROLES: tuple[str, ...] = (
    "request_analyst",
    "technical_analyst",
    "operations_analyst",
    "security_risk_analyst",
)


class SwarmSupervisor:
    """Điều phối viên trưởng điều hành nhóm trợ lý AI trong ranh giới tài nguyên và bảo mật.

    Giới hạn mặc định:
    - Chạy song song tối đa `max_concurrent` (mặc định 4) chuyên viên cùng lúc.
    - Tối đa `max_review_rounds` (mặc định 2) vòng lập sơ đồ và phản biện.
    - Toàn bộ thông điệp giữa các trợ lý phải đi qua Điều phối viên và đúng khuôn mẫu JSON.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        prompt_registry: PromptRegistry,
        max_concurrent: int = 4,
        max_review_rounds: int = 2,
        max_repair_attempts: int = 2,
    ) -> None:
        self._provider = provider
        self._prompts = prompt_registry
        self._max_concurrent = max(1, max_concurrent)
        self._max_review_rounds = max(1, max_review_rounds)
        self._max_repair_attempts = max(0, max_repair_attempts)

    async def run_analysis(self, *, context_snapshot: dict[str, Any]) -> SwarmAnalysisResult:
        """Điều phối trọn vẹn một phiên phân tích cho yêu cầu công việc từ bản chụp dữ liệu sạch.

        Các bước thực hiện:
        1. Tạo mã phiên `analysis_job_id` bất biến và gắn phiên bản câu lệnh hiện hành.
        2. Dùng `asyncio.Semaphore` giới hạn số lượng chuyên viên chạy đồng thời để chạy song song
           4 vai trò: Phân tích yêu cầu, Kỹ thuật, Vận hành và Bảo mật/Rủi ro.
        3. Gọi Trợ lý Thiết kế Quy trình sinh 1–3 sơ đồ ứng viên và đưa cho Trợ lý Phản biện
           rà soát; lặp tối đa `max_review_rounds` vòng nếu còn yêu cầu chỉnh sửa.
        4. Tổng hợp kết quả theo quy tắc giải quyết mâu thuẫn cố định và trả về `SwarmAnalysisResult`.
        """
        analysis_job_id = str(uuid4())
        snapshot = {
            **context_snapshot,
            "analysis_job_id": analysis_job_id,
            "prompt_version": self._prompts.version,
        }
        semaphore = asyncio.Semaphore(self._max_concurrent)
        agent_logs: list[AgentExecutionLog] = []

        async def _run_specialist(role_code: str) -> tuple[SpecialistFinding, AgentExecutionLog]:
            async with semaphore:
                prompt_spec = self._prompts.get_prompt(role_code)
                result = await self._provider.generate_structured(
                    role_code=role_code,
                    system_prompt=prompt_spec.system_prompt,
                    user_context=snapshot,
                    output_model=SpecialistFinding,
                    max_repair_attempts=self._max_repair_attempts,
                )
                parsed = result.parsed
                log_entry = AgentExecutionLog(
                    role_code=role_code,
                    round_number=1,
                    status=result.status,
                    repair_attempts=result.repair_attempts,
                    latency_ms=result.latency_ms,
                    prompt_tokens=result.usage.prompt_tokens,
                    completion_tokens=result.usage.completion_tokens,
                    cost_usd=result.usage.cost_usd,
                    cost_source=result.usage.cost_source,
                    decision_summary=parsed.decision_summary,
                    structured_output=parsed.model_dump(),
                    assumptions=parsed.assumptions,
                    evidence_refs=parsed.evidence_refs,
                    confidence=parsed.confidence,
                )
                return parsed, log_entry

        # Bước 2: Chạy song song các chuyên viên phân tích có giới hạn đồng thời
        specialist_results = await asyncio.gather(
            *[_run_specialist(role) for role in PARALLEL_ANALYST_ROLES]
        )
        findings = [item[0] for item in specialist_results]
        agent_logs.extend(item[1] for item in specialist_results)

        # Bước 3: Lập sơ đồ ứng viên và phản biện trong tối đa `max_review_rounds` vòng
        planner_prompt = self._prompts.get_prompt("workflow_planner")
        critic_prompt = self._prompts.get_prompt("critic_reviewer")

        latest_proposals = []
        latest_critic = CriticReview(
            approved=False,
            blocking_issues=["Chưa hoàn tất phản biện."],
            decision_summary="Chưa có phản biện.",
            confidence=0.0,
        )
        rounds_executed = 0
        critic_feedback: list[str] = []

        for round_num in range(1, self._max_review_rounds + 1):
            rounds_executed = round_num
            planner_ctx = {
                **snapshot,
                "round_number": round_num,
                "specialist_findings": [f.model_dump() for f in findings],
                "critic_feedback": critic_feedback,
            }
            planner_res = await self._provider.generate_structured(
                role_code="workflow_planner",
                system_prompt=planner_prompt.system_prompt,
                user_context=planner_ctx,
                output_model=PlannerProposalOutput,
                max_repair_attempts=self._max_repair_attempts,
            )
            latest_proposals = planner_res.parsed.proposals
            agent_logs.append(
                AgentExecutionLog(
                    role_code="workflow_planner",
                    round_number=round_num,
                    status=planner_res.status,
                    repair_attempts=planner_res.repair_attempts,
                    latency_ms=planner_res.latency_ms,
                    prompt_tokens=planner_res.usage.prompt_tokens,
                    completion_tokens=planner_res.usage.completion_tokens,
                    cost_usd=planner_res.usage.cost_usd,
                    cost_source=planner_res.usage.cost_source,
                    decision_summary=planner_res.parsed.decision_summary,
                    structured_output=planner_res.parsed.model_dump(),
                    assumptions=planner_res.parsed.assumptions,
                    evidence_refs=planner_res.parsed.evidence_refs,
                    confidence=planner_res.parsed.confidence,
                )
            )

            critic_ctx = {
                **snapshot,
                "round_number": round_num,
                "specialist_findings": [f.model_dump() for f in findings],
                "candidate_workflows": [p.model_dump() for p in latest_proposals],
            }
            critic_res = await self._provider.generate_structured(
                role_code="critic_reviewer",
                system_prompt=critic_prompt.system_prompt,
                user_context=critic_ctx,
                output_model=CriticReview,
                max_repair_attempts=self._max_repair_attempts,
            )
            latest_critic = critic_res.parsed
            agent_logs.append(
                AgentExecutionLog(
                    role_code="critic_reviewer",
                    round_number=round_num,
                    status=critic_res.status,
                    repair_attempts=critic_res.repair_attempts,
                    latency_ms=critic_res.latency_ms,
                    prompt_tokens=critic_res.usage.prompt_tokens,
                    completion_tokens=critic_res.usage.completion_tokens,
                    cost_usd=critic_res.usage.cost_usd,
                    cost_source=critic_res.usage.cost_source,
                    decision_summary=latest_critic.decision_summary,
                    structured_output=latest_critic.model_dump(),
                    assumptions=latest_critic.assumptions,
                    evidence_refs=latest_critic.evidence_refs,
                    confidence=latest_critic.confidence,
                )
            )

            if latest_critic.approved:
                break
            critic_feedback = list(latest_critic.required_changes) + list(latest_critic.blocking_issues)

        # Bước 4: Tổng hợp theo quy tắc cố định (không dùng biểu quyết số đông)
        return aggregate_swarm_outputs(
            analysis_job_id=analysis_job_id,
            provider_name=self._provider.provider_name,
            model_name=self._provider.model_name,
            prompt_version=self._prompts.version,
            specialist_findings=findings,
            candidate_workflows=latest_proposals,
            critic_review=latest_critic,
            rounds_executed=rounds_executed,
            agent_logs=agent_logs,
        )
