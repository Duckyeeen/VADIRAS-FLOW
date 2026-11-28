"""Bộ đánh giá quy tắc cố định (tách biệt hoàn toàn khỏi phân hệ AI)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.modules.workflows.registry import FORBIDDEN_DEMO_ACTIONS

from .risk import RiskInput, assess_risk


def compute_parameter_hash(
    *,
    action: str,
    parameters: dict[str, Any],
    resource_scope: str,
) -> str:
    """Tính mã băm SHA-256 cố định của hành động, tham số và phạm vi tài nguyên.

    Dùng để khóa chặt lệnh phê duyệt: chỉ cần một tham số thay đổi, mã băm sẽ khác
    và lệnh phê duyệt cũ lập tức bị vô hiệu hóa.
    """
    canonical = json.dumps(
        {
            "action": action.strip().lower(),
            "resource_scope": resource_scope.strip(),
            "parameters": parameters,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PolicyRuleInput:
    """Bản ghi quy tắc nhẹ đưa vào bộ đánh giá quy tắc."""

    code: str
    action_pattern: str
    risk_band: str
    effect: str  # ALLOW | REQUIRE_APPROVAL | DENY
    required_approver_role: str | None = None
    priority_order: int = 100
    is_enabled: bool = True


@dataclass(frozen=True, slots=True)
class PolicyEvaluationContext:
    """Toàn bộ ngữ cảnh cần thiết để Bộ kiểm soát quy tắc đưa ra quyết định độc lập."""

    organization_id: str
    actor_type: str  # USER | AGENT | SYSTEM
    actor_id: str
    action: str
    resource_scope: str
    parameters: dict[str, Any] = field(default_factory=dict)
    request_type: str = "SERVICE_REQUEST"
    side_effect_class: str = "WRITE"
    policy_version: str = "v1"
    actor_permissions: frozenset[str] = field(default_factory=frozenset)
    agent_grants: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (action, resource_scope)
    estimated_cost_usd: float = 0.0
    max_cost_usd: float = 5.0
    impact_score: int = 2
    likelihood_score: int = 2
    data_sensitivity: int = 1
    scope_breadth: int = 1
    privilege_level: int = 1
    external_customer_impact: bool = False
    irreversible: bool = False
    injection_flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class PolicyEvaluationResult:
    """Kết quả đánh giá cố định từ Bộ kiểm soát quy tắc."""

    decision: str  # ALLOW | REQUIRE_APPROVAL | DENY
    risk_level: str
    policy_version: str
    parameter_hash: str
    triggered_rules: list[str]
    required_role: str | None
    reason: str


def _action_matches(pattern: str, action: str) -> bool:
    """Kiểm tra tên hành động có khớp mẫu quy tắc (hỗ trợ khớp chính xác hoặc tiền tố `*`)."""
    p = pattern.strip().lower()
    a = action.strip().lower()
    if p == "*" or p == a:
        return True
    if p.endswith("*"):
        return a.startswith(p[:-1])
    return False


def evaluate_policy(
    context: PolicyEvaluationContext,
    *,
    rules: list[PolicyRuleInput] | None = None,
) -> PolicyEvaluationResult:
    """Đánh giá hành động đề xuất theo 7 bước cố định, không phụ thuộc kết luận của AI.

    Các bước quyết định theo thứ tự ưu tiên từ cao xuống thấp:
    1. Chặn ngay hành động nằm trong danh sách cấm của bản thử nghiệm.
    2. Chặn ngay nếu `resource_scope` rỗng hoặc chứa ký tự đại diện `*`.
    3. Nếu người thực thi là trợ lý AI (`AGENT`): bắt buộc phải có giấy phép hẹp khớp đúng
       `(action, resource_scope)` — trợ lý AI không bao giờ tự kế thừa toàn bộ quyền người gửi.
    4. Chặn nếu chi phí ước tính vượt trần ngân sách cho phép.
    5. Tính mức độ rủi ro qua `assess_risk`; mức `CRITICAL` bị chặn mặc định (`DENY`).
    6. Kiểm tra danh sách quy tắc tùy chỉnh `rules` theo thứ tự ưu tiên.
    7. Áp ánh xạ mặc định theo phân tầng rủi ro: `HIGH` -> bắt buộc phê duyệt;
       `MEDIUM` (có ghi ngoài) -> bắt buộc phê duyệt; `LOW` -> `ALLOW`.
    """
    action_lower = context.action.strip().lower()
    scope_clean = context.resource_scope.strip()
    param_hash = compute_parameter_hash(
        action=action_lower,
        parameters=context.parameters,
        resource_scope=scope_clean,
    )
    triggered: list[str] = []

    # Bước 1: Chặn hành động cấm
    if action_lower in FORBIDDEN_DEMO_ACTIONS:
        return PolicyEvaluationResult(
            decision="DENY",
            risk_level="CRITICAL",
            policy_version=context.policy_version,
            parameter_hash=param_hash,
            triggered_rules=["FORBIDDEN_DEMO_ACTION"],
            required_role=None,
            reason=f"Hành động `{action_lower}` bị cấm thực thi trong bản thử nghiệm.",
        )

    # Bước 2: Bắt buộc có phạm vi tài nguyên cụ thể
    if not scope_clean or "*" in scope_clean:
        return PolicyEvaluationResult(
            decision="DENY",
            risk_level="HIGH",
            policy_version=context.policy_version,
            parameter_hash=param_hash,
            triggered_rules=["INVALID_RESOURCE_SCOPE"],
            required_role=None,
            reason="Phạm vi tài nguyên (`resource_scope`) phải được chỉ định cụ thể, không được rỗng hoặc dùng `*`.",
        )

    # Bước 3: Kiểm tra giấy phép phạm vi hẹp cho trợ lý AI
    if context.actor_type.upper() == "AGENT":
        has_narrow_grant = any(
            grant_action.strip().lower() == action_lower and grant_scope.strip() == scope_clean
            for grant_action, grant_scope in context.agent_grants
        )
        if not has_narrow_grant:
            return PolicyEvaluationResult(
                decision="DENY",
                risk_level="HIGH",
                policy_version=context.policy_version,
                parameter_hash=param_hash,
                triggered_rules=["AGENT_GRANT_MISSING"],
                required_role=None,
                reason=f"Trợ lý AI `{context.actor_id}` chưa được cấp giấy phép hẹp cho `{action_lower}` trên `{scope_clean}`.",
            )

    # Bước 4: Kiểm tra giới hạn ngân sách
    if context.estimated_cost_usd > context.max_cost_usd:
        return PolicyEvaluationResult(
            decision="DENY",
            risk_level="MEDIUM",
            policy_version=context.policy_version,
            parameter_hash=param_hash,
            triggered_rules=["BUDGET_EXCEEDED"],
            required_role=None,
            reason="Chi phí ước tính vượt quá trần ngân sách cho phép của bước thực thi.",
        )

    # Bước 5: Chấm điểm rủi ro độc lập
    risk_result = assess_risk(
        RiskInput(
            action=action_lower,
            request_type=context.request_type,
            side_effect_class=context.side_effect_class,
            impact_score=context.impact_score,
            likelihood_score=context.likelihood_score,
            data_sensitivity=context.data_sensitivity,
            scope_breadth=context.scope_breadth,
            privilege_level=context.privilege_level,
            external_customer_impact=context.external_customer_impact,
            irreversible=context.irreversible,
            injection_flags=context.injection_flags,
        )
    )
    if risk_result.risk_level == "CRITICAL":
        return PolicyEvaluationResult(
            decision="DENY",
            risk_level="CRITICAL",
            policy_version=context.policy_version,
            parameter_hash=param_hash,
            triggered_rules=["CRITICAL_BLOCKED_IN_DEMO"],
            required_role=None,
            reason="; ".join(risk_result.reasons),
        )

    # Bước 6: Áp các quy tắc tùy chỉnh theo độ ưu tiên
    sorted_rules = sorted((r for r in (rules or []) if r.is_enabled), key=lambda r: r.priority_order)
    for rule in sorted_rules:
        if not _action_matches(rule.action_pattern, action_lower):
            continue
        if rule.risk_band not in {"ANY", risk_result.risk_level}:
            continue
        triggered.append(rule.code)
        if rule.effect == "DENY":
            return PolicyEvaluationResult(
                decision="DENY",
                risk_level=risk_result.risk_level,
                policy_version=context.policy_version,
                parameter_hash=param_hash,
                triggered_rules=triggered,
                required_role=None,
                reason=f"Bị chặn bởi quy tắc `{rule.code}`.",
            )
        if rule.effect == "REQUIRE_APPROVAL":
            return PolicyEvaluationResult(
                decision="REQUIRE_APPROVAL",
                risk_level=risk_result.risk_level,
                policy_version=context.policy_version,
                parameter_hash=param_hash,
                triggered_rules=triggered,
                required_role=rule.required_approver_role or "department_manager",
                reason=f"Cần phê duyệt theo quy tắc `{rule.code}`.",
            )

    # Bước 7: Quy tắc mặc định theo phân tầng rủi ro
    if risk_result.risk_level == "HIGH":
        triggered.append("DEFAULT_HIGH_RISK_APPROVAL")
        return PolicyEvaluationResult(
            decision="REQUIRE_APPROVAL",
            risk_level="HIGH",
            policy_version=context.policy_version,
            parameter_hash=param_hash,
            triggered_rules=triggered,
            required_role="department_manager",
            reason="; ".join(risk_result.reasons),
        )

    if risk_result.risk_level == "MEDIUM" and context.side_effect_class == "WRITE":
        triggered.append("DEFAULT_MEDIUM_WRITE_APPROVAL")
        return PolicyEvaluationResult(
            decision="REQUIRE_APPROVAL",
            risk_level="MEDIUM",
            policy_version=context.policy_version,
            parameter_hash=param_hash,
            triggered_rules=triggered,
            required_role="department_manager",
            reason="Thao tác ghi ở mức rủi ro trung bình cần quản lý phê duyệt.",
        )

    triggered.append("DEFAULT_LOW_RISK_ALLOW")
    return PolicyEvaluationResult(
        decision="ALLOW",
        risk_level=risk_result.risk_level,
        policy_version=context.policy_version,
        parameter_hash=param_hash,
        triggered_rules=triggered,
        required_role=None,
        reason="Đạt đầy đủ điều kiện chính sách, phạm vi tài nguyên và ngân sách.",
    )
