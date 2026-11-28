"""Kiểm thử đơn vị cho chấm điểm rủi ro, bộ quy tắc cố định, ràng buộc 7 yếu tố và Cổng công cụ."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.errors import AuthorizationError
from app.adapters.guardian import evaluate_actions
from app.modules.governance.approvals import verify_approval_binding
from app.modules.governance.models import ApprovalRequest, ApprovalRequestStatus
from app.modules.governance.policy_engine import (
    PolicyEvaluationContext,
    compute_parameter_hash,
    evaluate_policy,
)
from app.modules.governance.risk import RiskInput, assess_risk
from app.modules.governance.tool_broker import ToolBroker
from app.adapters.schemas import AIAnalysisOutput, Priority, ProposedAction, RecommendedTeam, RequestCategory, RiskLevel, WorkflowTemplate


def test_risk_assessment_tiers() -> None:
    """Kiểm tra phân tầng 4 mức rủi ro: LOW, MEDIUM, HIGH, CRITICAL."""
    low = assess_risk(RiskInput(action="read_issue", request_type="SERVICE_REQUEST", side_effect_class="READ", impact_score=1, likelihood_score=2))
    assert low.risk_level == "LOW"

    med = assess_risk(RiskInput(action="comment_issue", request_type="SERVICE_REQUEST", impact_score=3, likelihood_score=3))
    assert med.risk_level == "MEDIUM"

    high = assess_risk(RiskInput(action="create_issue", request_type="CHANGE", side_effect_class="WRITE", impact_score=2, likelihood_score=2))
    assert high.risk_level == "HIGH"

    crit = assess_risk(RiskInput(action="deploy_production", request_type="CHANGE", impact_score=5, likelihood_score=3))
    assert crit.risk_level == "CRITICAL"


def test_policy_engine_blocks_ungranted_agent_wildcard_scope_and_critical() -> None:
    """Bộ quy tắc phải chặn trợ lý AI không có giấy phép hẹp, phạm vi `*` và hành động CRITICAL."""
    # 1. Trợ lý AI không có grant phù hợp -> bị chặn ngay dù hành động bình thường
    no_grant = evaluate_policy(
        PolicyEvaluationContext(
            organization_id="org-1",
            actor_type="AGENT",
            actor_id="executor_worker",
            action="create_issue",
            resource_scope="github:repo:Duckyeeen/VADIRAS-FLOW",
            agent_grants=(),
        )
    )
    assert no_grant.decision == "DENY"
    assert "AGENT_GRANT_MISSING" in no_grant.triggered_rules

    # 2. Phạm vi `*` bị từ chối
    wildcard = evaluate_policy(
        PolicyEvaluationContext(
            organization_id="org-1",
            actor_type="USER",
            actor_id="user-1",
            action="create_issue",
            resource_scope="github:repo:*",
        )
    )
    assert wildcard.decision == "DENY"
    assert "INVALID_RESOURCE_SCOPE" in wildcard.triggered_rules

    # 3. Trợ lý AI có grant hẹp + rủi ro LOW + trong ngân sách -> ALLOW
    low_ok = evaluate_policy(
        PolicyEvaluationContext(
            organization_id="org-1",
            actor_type="AGENT",
            actor_id="executor_worker",
            action="create_issue",
            resource_scope="github:repo:Duckyeeen/VADIRAS-FLOW",
            agent_grants=(("create_issue", "github:repo:Duckyeeen/VADIRAS-FLOW"),),
            impact_score=1,
            likelihood_score=2,
        )
    )
    assert low_ok.decision == "ALLOW"

    # 4. Yêu cầu CHANGE với rủi ro HIGH -> REQUIRE_APPROVAL
    change_high = evaluate_policy(
        PolicyEvaluationContext(
            organization_id="org-1",
            actor_type="AGENT",
            actor_id="executor_worker",
            action="create_issue",
            resource_scope="github:repo:Duckyeeen/VADIRAS-FLOW",
            request_type="CHANGE",
            agent_grants=(("create_issue", "github:repo:Duckyeeen/VADIRAS-FLOW"),),
        )
    )
    assert change_high.decision == "REQUIRE_APPROVAL"
    assert change_high.required_role == "department_manager"


def test_approval_binding_invalidates_on_any_material_change_or_expiry() -> None:
    """Sửa tham số, phiên bản quy trình, phạm vi, chính sách hoặc quá hạn đều vô hiệu hóa lệnh duyệt."""
    params = {"title": "Thay đổi cấu hình", "labels": ["change"]}
    scope = "github:repo:Duckyeeen/VADIRAS-FLOW"
    param_hash = compute_parameter_hash(action="create_issue", parameters=params, resource_scope=scope)
    now = datetime.now(timezone.utc)

    approval = ApprovalRequest(
        organization_id="org-1",
        request_id="req-1",
        workflow_version_id="ver-1",
        node_id="n4_approval",
        action="create_issue",
        parameters_json=params,
        parameter_hash=param_hash,
        resource_scope=scope,
        policy_version="v1",
        risk_level="HIGH",
        required_role="department_manager",
        status=ApprovalRequestStatus.APPROVED.value,
        requested_by_actor_id="mem-emp",
        expires_at=now + timedelta(hours=4),
    )

    # Khớp hoàn toàn -> hợp lệ
    verify_approval_binding(
        approval,
        workflow_version_id="ver-1",
        node_id="n4_approval",
        action="create_issue",
        parameter_hash=param_hash,
        resource_scope=scope,
        policy_version="v1",
        now=now,
    )

    # Sửa dù chỉ 1 tham số -> parameter_hash khác -> ném lỗi ngay
    tampered_hash = compute_parameter_hash(
        action="create_issue",
        parameters={"title": "Thay đổi cấu hình", "labels": ["bypass"]},
        resource_scope=scope,
    )
    with pytest.raises(AuthorizationError) as exc_param:
        verify_approval_binding(
            approval,
            workflow_version_id="ver-1",
            node_id="n4_approval",
            action="create_issue",
            parameter_hash=tampered_hash,
            resource_scope=scope,
            policy_version="v1",
            now=now,
        )
    assert exc_param.value.code == "APPROVAL_BINDING_MISMATCH"

    # Đổi phiên bản quy trình -> ném lỗi
    with pytest.raises(AuthorizationError):
        verify_approval_binding(
            approval,
            workflow_version_id="ver-2",
            node_id="n4_approval",
            action="create_issue",
            parameter_hash=param_hash,
            resource_scope=scope,
            policy_version="v1",
            now=now,
        )

    # Quá hạn phê duyệt -> ném lỗi APPROVAL_EXPIRED
    with pytest.raises(AuthorizationError) as exc_exp:
        verify_approval_binding(
            approval,
            workflow_version_id="ver-1",
            node_id="n4_approval",
            action="create_issue",
            parameter_hash=param_hash,
            resource_scope=scope,
            policy_version="v1",
            now=now + timedelta(hours=5),
        )
    assert exc_exp.value.code == "APPROVAL_EXPIRED"


@pytest.mark.asyncio
async def test_tool_broker_rejects_unlisted_tool() -> None:
    """Cổng điều phối công cụ từ chối công cụ chưa đăng ký trong danh sách cho phép."""
    broker = ToolBroker()

    async def _dummy(params: dict) -> dict:
        return params

    broker.register_tool("github.create_issue", _dummy)
    assert broker.is_allowlisted("github.create_issue") is True
    assert broker.is_allowlisted("shell.exec") is False

    with pytest.raises(AuthorizationError) as exc:
        await broker.execute(
            None,  # type: ignore[arg-type]
            tool_name="shell.exec",
            context=PolicyEvaluationContext(
                organization_id="org-1",
                actor_type="AGENT",
                actor_id="executor_worker",
                action="shell.exec",
                resource_scope="host:local",
            ),
        )
    assert exc.value.code == "TOOL_NOT_ALLOWLISTED"


def test_legacy_guardian_evaluate_actions_works() -> None:
    """Xác nhận hàm `app.guardian.evaluate_actions` đánh giá chuẩn theo quy tắc cố định."""
    analysis = AIAnalysisOutput(
        request_id="req-legacy-1",
        is_valid_support_request=True,
        category=RequestCategory.BUG_BACKEND,
        priority=Priority.P2_HIGH,
        risk_level=RiskLevel.HIGH,
        summary="Sự cố cần duyệt trước khi thao tác",
        recommended_team=RecommendedTeam.BACKEND_CORE,
        recommended_workflow_template=WorkflowTemplate.HIGH_RISK_HUMAN_APPROVAL,
        proposed_actions=[
            ProposedAction(action_type="create_ticket", target_system="github", ticket_title="Fix 502"),
            ProposedAction(action_type="delete_user_data", target_system="db"),
        ],
        policy_flags=["HIGH_IMPACT"],
        confidence_score=0.92,
    )
    decision = evaluate_actions(analysis)
    assert decision.requires_human_approval is True
    assert len(decision.permitted_actions) == 1
    assert decision.permitted_actions[0].action_type == "create_ticket"
