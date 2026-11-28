"""Cổng kiểm soát cuối cùng bắt buộc chạy ngay trước mọi thao tác có tác động ngoài."""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthorizationError
from app.modules.identity.models import AgentIdentity, AgentToolGrant

from .approvals import verify_approval_binding
from .models import (
    ApprovalRequest,
    PermissionGrant,
    PolicyDecision,
    PolicySet,
)
from .policy_engine import (
    PolicyEvaluationContext,
    PolicyRuleInput,
    evaluate_policy,
)


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class ExecutionGuard:
    """Cổng kiểm soát lại toàn bộ quyền, quy tắc và lệnh duyệt ngay trước khi thực thi."""

    async def authorize_side_effect(
        self,
        session: AsyncSession,
        *,
        context: PolicyEvaluationContext,
        request_id: str | None = None,
        workflow_run_id: str | None = None,
        workflow_version_id: str | None = None,
        node_id: str = "unknown_node",
        approval_id: str | None = None,
    ) -> PolicyDecision:
        """Đánh giá lại chính sách và ràng buộc phê duyệt trước một lệnh gọi công cụ ngoài.

        Các bước kiểm tra trực tiếp trên cơ sở dữ liệu:
        1. Nạp bộ quy tắc đang kích hoạt của tổ chức (nếu có).
        2. Nếu người thực thi là trợ lý AI (`AGENT`), tự động nạp các giấy phép hẹp còn hiệu lực
           từ `agent_tool_grants` và `permission_grants` (không tin vào danh sách cũ truyền từ ngoài).
        3. Chạy `evaluate_policy` và ghi lại bản ghi `PolicyDecision` để kiểm toán.
        4. Nếu quyết định là `DENY` -> chặn ngay với lỗi `403`.
        5. Nếu quyết định là `REQUIRE_APPROVAL` -> bắt buộc có `approval_id` hợp lệ và khớp đủ
           7 yếu tố ràng buộc qua `verify_approval_binding`.
        """
        # Bước 1: Nạp chính sách đang kích hoạt của tổ chức
        active_policy_stmt = (
            sa.select(PolicySet)
            .where(
                PolicySet.organization_id == context.organization_id,
                PolicySet.is_active.is_(True),
            )
            .order_by(PolicySet.created_at.desc())
            .limit(1)
        )
        policy_set = (await session.execute(active_policy_stmt)).scalar_one_or_none()
        effective_policy_version = policy_set.version if policy_set is not None else context.policy_version

        loaded_rules: list[PolicyRuleInput] = []
        if policy_set is not None:
            await session.refresh(policy_set, ["rules"])
            loaded_rules = [
                PolicyRuleInput(
                    code=r.code,
                    action_pattern=r.action_pattern,
                    risk_band=r.risk_band,
                    effect=r.effect,
                    required_approver_role=r.required_approver_role,
                    priority_order=r.priority_order,
                    is_enabled=r.is_enabled,
                )
                for r in policy_set.rules
            ]

        # Bước 2: Nạp giấy phép hẹp hiện hành của trợ lý AI từ CSDL
        effective_grants = context.agent_grants
        if context.actor_type.upper() == "AGENT":
            now = datetime.now(timezone.utc)
            agent = (
                await session.execute(
                    sa.select(AgentIdentity).where(
                        AgentIdentity.organization_id == context.organization_id,
                        AgentIdentity.role_code == context.actor_id,
                        AgentIdentity.status == "ACTIVE",
                    )
                )
            ).scalar_one_or_none()
            db_grants: list[tuple[str, str]] = []
            if agent is not None:
                tool_rows = (
                    await session.execute(
                        sa.select(AgentToolGrant).where(
                            AgentToolGrant.organization_id == context.organization_id,
                            AgentToolGrant.agent_identity_id == agent.id,
                            AgentToolGrant.is_active.is_(True),
                        )
                    )
                ).scalars().all()
                db_grants.extend((g.tool_name, g.resource_scope) for g in tool_rows)

                perm_rows = (
                    await session.execute(
                        sa.select(PermissionGrant).where(
                            PermissionGrant.organization_id == context.organization_id,
                            PermissionGrant.agent_identity_id == agent.id,
                            PermissionGrant.revoked_at.is_(None),
                        )
                    )
                ).scalars().all()
                for pg in perm_rows:
                    if _normalize_utc(pg.expires_at) > now:
                        db_grants.append((pg.action, pg.resource_scope))
            effective_grants = tuple(db_grants)

        effective_context = PolicyEvaluationContext(
            organization_id=context.organization_id,
            actor_type=context.actor_type,
            actor_id=context.actor_id,
            action=context.action,
            resource_scope=context.resource_scope,
            parameters=context.parameters,
            request_type=context.request_type,
            side_effect_class=context.side_effect_class,
            policy_version=effective_policy_version,
            actor_permissions=context.actor_permissions,
            agent_grants=effective_grants,
            estimated_cost_usd=context.estimated_cost_usd,
            max_cost_usd=context.max_cost_usd,
            impact_score=context.impact_score,
            likelihood_score=context.likelihood_score,
            data_sensitivity=context.data_sensitivity,
            scope_breadth=context.scope_breadth,
            privilege_level=context.privilege_level,
            external_customer_impact=context.external_customer_impact,
            irreversible=context.irreversible,
            injection_flags=context.injection_flags,
        )

        # Bước 3: Chạy bộ đánh giá quy tắc và lưu vết quyết định
        result = evaluate_policy(effective_context, rules=loaded_rules)
        decision_row = PolicyDecision(
            organization_id=context.organization_id,
            request_id=request_id,
            workflow_run_id=workflow_run_id,
            node_id=node_id,
            actor_type=context.actor_type,
            actor_id=context.actor_id,
            action=context.action,
            resource_scope=context.resource_scope,
            parameter_hash=result.parameter_hash,
            risk_level=result.risk_level,
            decision=result.decision,
            policy_version=result.policy_version,
            triggered_rules_json=result.triggered_rules,
            reason=result.reason,
        )
        session.add(decision_row)
        await session.flush()

        # Bước 4: Xử lý kết quả DENY
        if result.decision == "DENY":
            await session.commit()
            raise AuthorizationError(result.reason, code=result.triggered_rules[0] if result.triggered_rules else "POLICY_DENIED")

        # Bước 5: Xử lý kết quả REQUIRE_APPROVAL (kiểm tra đủ 7 yếu tố ràng buộc)
        if result.decision == "REQUIRE_APPROVAL":
            if not approval_id:
                await session.commit()
                raise AuthorizationError(
                    "Thao tác này bắt buộc phải có lệnh phê duyệt hợp lệ trước khi thực thi.",
                    code="APPROVAL_REQUIRED",
                )
            approval = (
                await session.execute(
                    sa.select(ApprovalRequest).where(
                        ApprovalRequest.id == approval_id,
                        ApprovalRequest.organization_id == context.organization_id,
                    )
                )
            ).scalar_one_or_none()
            if approval is None:
                await session.commit()
                raise AuthorizationError("Không tìm thấy lệnh phê duyệt trong tổ chức.", code="APPROVAL_NOT_FOUND")
            try:
                verify_approval_binding(
                    approval,
                    workflow_version_id=workflow_version_id,
                    node_id=node_id,
                    action=context.action,
                    parameter_hash=result.parameter_hash,
                    resource_scope=context.resource_scope,
                    policy_version=result.policy_version,
                )
            except AuthorizationError:
                await session.commit()
                raise

        await session.commit()
        return decision_row
