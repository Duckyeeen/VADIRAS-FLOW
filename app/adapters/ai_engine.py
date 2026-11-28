"""Giao diện phân tích yêu cầu bằng AI (tương thích ngược với hợp đồng khởi tạo ban đầu)."""

from __future__ import annotations

import asyncio

from app.modules.ai_intelligence.prompts.registry import PromptRegistry
from app.modules.ai_intelligence.providers.mock_provider import MockLLMProvider
from app.modules.ai_intelligence.swarm.supervisor import SwarmSupervisor

from .schemas import (
    AIAnalysisOutput,
    InboundRequest,
    PreprocessedContext,
    Priority,
    ProposedAction,
    RecommendedTeam,
    RequestCategory,
    RiskLevel,
    WorkflowTemplate,
)

_DEPT_TO_LEGACY_TEAM: dict[str, RecommendedTeam] = {
    "ENGINEERING": RecommendedTeam.BACKEND_CORE,
    "DEVOPS": RecommendedTeam.BACKEND_CORE,
    "SECURITY": RecommendedTeam.IAM_SECURITY,
    "SUPPORT": RecommendedTeam.CUSTOMER_SUCCESS,
    "PRODUCT": RecommendedTeam.FRONTEND_WEB,
    "MANAGEMENT": RecommendedTeam.TRIAGE_HUMAN,
}


def analyze_request(
    request: InboundRequest,
    context: PreprocessedContext,
) -> AIAnalysisOutput:
    """Phân tích đồng bộ một `InboundRequest` thông qua bộ điều phối nhóm trợ lý AI."""
    supervisor = SwarmSupervisor(
        provider=MockLLMProvider(),
        prompt_registry=PromptRegistry(),
    )
    snapshot = {
        "request_id": request.request_id,
        "request_type": "INCIDENT",
        "title": request.subject,
        "sanitized_description": context.sanitized_text or request.description,
        "injection_flags": [flag.split(":", 1)[1] for flag in context.pii_redactions if flag.startswith("INJECTION:")],
    }
    result = asyncio.run(supervisor.run_analysis(context_snapshot=snapshot))

    risk = RiskLevel(result.risk_level)
    priority = Priority(result.recommended_priority)
    team = _DEPT_TO_LEGACY_TEAM.get(result.recommended_department, RecommendedTeam.TRIAGE_HUMAN)
    template = (
        WorkflowTemplate.REQUEST_MORE_INFO
        if result.status == "NEEDS_INFORMATION"
        else (
            WorkflowTemplate.HIGH_RISK_HUMAN_APPROVAL
            if risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}
            else WorkflowTemplate.STANDARD_BUG_TRIAGE
        )
    )
    return AIAnalysisOutput(
        request_id=request.request_id,
        is_valid_support_request=True,
        category=RequestCategory.BUG_BACKEND,
        priority=priority,
        risk_level=risk,
        summary=result.decision_summary,
        root_cause_hypothesis="",
        missing_information=result.missing_information,
        recommended_team=team,
        recommended_workflow_template=template,
        proposed_actions=[
            ProposedAction(
                action_type="create_ticket",
                target_system="github",
                ticket_title=request.subject,
                labels=[result.recommended_request_type.lower()],
            )
        ],
        policy_flags=result.hard_blockers,
        confidence_score=result.confidence_score,
        reasoning_trace="",
    )
