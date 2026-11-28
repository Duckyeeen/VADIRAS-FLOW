"""Giao diện kiểm soát quy tắc cố định và phê duyệt (tương thích ngược với hợp đồng cũ)."""

from __future__ import annotations

from app.modules.governance.policy_engine import PolicyEvaluationContext, evaluate_policy
from app.modules.workflows.registry import FORBIDDEN_DEMO_ACTIONS

from .schemas import (
    AIAnalysisOutput,
    ApprovalStatus,
    GuardianChoice,
    GuardianDecision,
    ProposedAction,
    RiskLevel,
)


def evaluate_actions(analysis: AIAnalysisOutput) -> GuardianDecision:
    """Đánh giá một `AIAnalysisOutput` theo quy tắc cố định, không phụ thuộc gợi ý của AI."""
    if not analysis.is_valid_support_request:
        return GuardianDecision(
            request_id=analysis.request_id,
            decision=GuardianChoice.REJECT_SAFE,
            triggered_rules=["INVALID_SUPPORT_REQUEST"],
            requires_human_approval=False,
            approval_status=ApprovalStatus.NOT_REQUIRED,
            block_reason="Yêu cầu nằm ngoài phạm vi hỗ trợ hợp lệ.",
            permitted_actions=[],
        )

    if analysis.missing_information:
        return GuardianDecision(
            request_id=analysis.request_id,
            decision=GuardianChoice.REQUEST_MORE_INFO,
            triggered_rules=["MISSING_INFORMATION"],
            requires_human_approval=False,
            approval_status=ApprovalStatus.NOT_REQUIRED,
            permitted_actions=[],
        )

    triggered_rules: list[str] = list(analysis.policy_flags)
    permitted: list[ProposedAction] = []
    requires_approval = (
        analysis.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
        or analysis.confidence_score < 0.80
        or bool(analysis.policy_flags)
    )

    for action in analysis.proposed_actions:
        action_name = action.action_type.strip().lower()
        if action_name in FORBIDDEN_DEMO_ACTIONS:
            triggered_rules.append(f"BLOCKED:{action_name}")
            requires_approval = True
            continue

        eval_res = evaluate_policy(
            PolicyEvaluationContext(
                organization_id="legacy-compat",
                actor_type="USER",
                actor_id="legacy-user",
                action=action_name,
                resource_scope=f"{action.target_system}:default",
                parameters=action.model_dump(),
                impact_score=4 if analysis.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL} else 2,
                likelihood_score=2,
            )
        )
        triggered_rules.extend(eval_res.triggered_rules)
        if eval_res.decision == "DENY":
            requires_approval = True
            continue
        if eval_res.decision == "REQUIRE_APPROVAL":
            requires_approval = True
        permitted.append(action)

    if any(rule.startswith("BLOCKED:") for rule in triggered_rules) and not permitted:
        return GuardianDecision(
            request_id=analysis.request_id,
            decision=GuardianChoice.REJECT_SAFE,
            triggered_rules=triggered_rules,
            requires_human_approval=False,
            approval_status=ApprovalStatus.NOT_REQUIRED,
            block_reason="Toàn bộ hành động đề xuất nằm trong danh sách bị chặn.",
            permitted_actions=[],
        )

    if requires_approval:
        return GuardianDecision(
            request_id=analysis.request_id,
            decision=GuardianChoice.REQUIRE_HUMAN_APPROVAL,
            triggered_rules=triggered_rules or ["RISK_OR_CONFIDENCE_GATE"],
            requires_human_approval=True,
            approval_status=ApprovalStatus.PENDING,
            permitted_actions=permitted,
        )

    return GuardianDecision(
        request_id=analysis.request_id,
        decision=GuardianChoice.AUTO_EXECUTE,
        triggered_rules=triggered_rules or ["LOW_RISK_AUTO_ALLOW"],
        requires_human_approval=False,
        approval_status=ApprovalStatus.NOT_REQUIRED,
        permitted_actions=permitted,
    )
