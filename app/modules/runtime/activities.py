"""Các tác vụ Temporal thực hiện toàn bộ thao tác CSDL, gọi AI, duyệt, nhân sự và bộ kết nối."""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.exceptions import ApplicationError

from app.core.errors import AuthorizationError, ConflictError, ValidationAppError
from app.modules.ai_intelligence.prompts.registry import PromptRegistry
from app.modules.ai_intelligence.providers.base import LLMProvider
from app.modules.ai_intelligence.providers.mock_provider import MockLLMProvider
from app.modules.ai_intelligence.swarm.schemas import SpecialistFinding
from app.modules.connectors.providers.base import (
    GITHUB_ACTION_SCHEMAS,
    BaseConnector,
    ConnectorPermanentError,
    ConnectorTransientError,
)
from app.modules.connectors.providers.factory import build_github_connector
from app.modules.connectors.idempotency import ConnectorOperationExecutor
from app.modules.governance.models import ApprovalRequest, ApprovalRequestStatus
from app.modules.governance.policy_engine import PolicyEvaluationContext, compute_parameter_hash
from app.modules.governance.tool_broker import ToolBroker
from app.modules.identity.models import Department
from app.modules.requests.models import HumanTask, HumanTaskStatus, Request, VisibilityLevel
from app.modules.verification.engine import VerificationEngine
from app.modules.verification.models import ExecutionEvidence
from app.modules.workflows.models import NodeRunStatus, WorkflowNodeRun, WorkflowRun

from .contracts import (
    NodeExecutionInput,
    NodeExecutionOutput,
    NodeStatusUpdateInput,
    RunStatusUpdateInput,
)
from .state_machine import ErrorClass

# Ngữ cảnh tạm thời truyền phiên CSDL và thông số nút vào hàm xử lý của ToolBroker mà không làm biến đổi parameter_hash
_ACTIVE_EXEC_CONTEXT: ContextVar[tuple[AsyncSession, NodeExecutionInput] | None] = ContextVar(
    "_ACTIVE_EXEC_CONTEXT", default=None
)


def _parse_iso_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def build_default_tool_broker(connector: BaseConnector | None = None) -> ToolBroker:
    """Tạo cổng điều phối công cụ mặc định nối với `BaseConnector` và lớp chống trùng lặp."""
    broker = ToolBroker()
    active_connector = connector or build_github_connector()
    executor = ConnectorOperationExecutor(active_connector)

    async def _connector_handler(action_name: str, params: dict[str, Any]) -> dict[str, Any]:
        ctx_pair = _ACTIVE_EXEC_CONTEXT.get()
        repo = str(params.get("target_repository") or "Duckyeeen/VADIRAS-FLOW")
        if ctx_pair is not None:
            session, inp = ctx_pair
            outcome = await executor.execute_with_idempotency(
                session,
                organization_id=inp.organization_id,
                action=action_name,
                repository=repo,
                payload={
                    **params,
                    "title": params.get("title") or inp.node_name,
                },
                idempotency_key=inp.idempotency_key,
                request_id=inp.request_id,
                workflow_run_id=inp.workflow_run_id,
                node_id=inp.node_id,
                actor_id=inp.started_by_user_id,
            )
            return dict(outcome.result.raw_summary)

        issue_number = int(params.get("issue_number") or 101)
        return {
            "external_id": f"{repo}#{issue_number}",
            "external_url": f"https://github.com/{repo}/issues/{issue_number}",
            "operation_id": f"sim-{action_name}-{issue_number}",
            "repository": repo,
            "applied_parameters": params,
        }

    for action_name in GITHUB_ACTION_SCHEMAS:
        for prefix in ("github", "mock_github"):
            broker.register_tool(
                f"{prefix}:{action_name}",
                lambda params, _act=action_name: _connector_handler(_act, params),
            )
    return broker


class RuntimeActivities:
    """Tập hợp các tác vụ I/O bất đồng bộ phục vụ quy trình điều phối Temporal."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        connector: BaseConnector | None = None,
        tool_broker: ToolBroker | None = None,
        llm_provider: LLMProvider | None = None,
        prompt_registry: PromptRegistry | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._connector = connector or build_github_connector()
        self._tool_broker = tool_broker or build_default_tool_broker(self._connector)
        self._llm_provider = llm_provider or MockLLMProvider()
        self._prompts = prompt_registry or PromptRegistry()

    @activity.defn(name="update_run_status_activity")
    async def update_run_status_activity(self, inp: RunStatusUpdateInput) -> dict[str, Any]:
        """Cập nhật trạng thái tổng thể và mốc thời gian của một lượt chạy trong CSDL."""
        async with self._session_factory() as session:
            run = (
                await session.execute(
                    sa.select(WorkflowRun).where(
                        WorkflowRun.id == inp.workflow_run_id,
                        WorkflowRun.organization_id == inp.organization_id,
                    )
                )
            ).scalar_one_or_none()
            if run is None:
                raise ApplicationError(
                    f"Không tìm thấy lượt chạy `{inp.workflow_run_id}` trong tổ chức.",
                    type=ErrorClass.PERMANENT.value,
                    non_retryable=True,
                )

            run.status = inp.status
            started_dt = _parse_iso_dt(inp.started_at_iso)
            if started_dt is not None and run.started_at is None:
                run.started_at = started_dt
            finished_dt = _parse_iso_dt(inp.finished_at_iso)
            if finished_dt is not None:
                run.finished_at = finished_dt
            if inp.result_summary is not None:
                run.result_summary_json = dict(inp.result_summary)

            await session.commit()
            return {"workflow_run_id": run.id, "status": run.status}

    @activity.defn(name="persist_node_state_activity")
    async def persist_node_state_activity(self, inp: NodeStatusUpdateInput) -> dict[str, Any]:
        """Lưu mới hoặc cập nhật trạng thái thực thi của một bước vào `workflow_node_runs`."""
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    sa.select(WorkflowNodeRun).where(
                        WorkflowNodeRun.organization_id == inp.organization_id,
                        WorkflowNodeRun.workflow_run_id == inp.workflow_run_id,
                        WorkflowNodeRun.node_id == inp.node_id,
                        WorkflowNodeRun.attempt == inp.attempt,
                    )
                )
            ).scalar_one_or_none()

            if row is None:
                row = WorkflowNodeRun(
                    organization_id=inp.organization_id,
                    workflow_run_id=inp.workflow_run_id,
                    node_id=inp.node_id,
                    node_type=inp.node_type,
                    status=inp.status,
                    attempt=inp.attempt,
                    idempotency_key=inp.idempotency_key
                    or f"run:{inp.workflow_run_id}:node:{inp.node_id}:att:{inp.attempt}",
                    input_summary_json=dict(inp.input_summary or {}),
                    output_summary_json=dict(inp.output_summary or {}),
                    error_class=inp.error_class,
                    error_message=inp.error_message,
                    started_at=_parse_iso_dt(inp.started_at_iso),
                    finished_at=_parse_iso_dt(inp.finished_at_iso),
                )
                session.add(row)
            else:
                row.status = inp.status
                if inp.input_summary is not None:
                    row.input_summary_json = dict(inp.input_summary)
                if inp.output_summary is not None:
                    row.output_summary_json = dict(inp.output_summary)
                if inp.error_class is not None:
                    row.error_class = inp.error_class
                if inp.error_message is not None:
                    row.error_message = inp.error_message
                started_dt = _parse_iso_dt(inp.started_at_iso)
                if started_dt is not None and row.started_at is None:
                    row.started_at = started_dt
                finished_dt = _parse_iso_dt(inp.finished_at_iso)
                if finished_dt is not None:
                    row.finished_at = finished_dt

            await session.commit()
            return {"node_run_id": row.id, "node_id": row.node_id, "status": row.status}

    @activity.defn(name="execute_node_activity")
    async def execute_node_activity(self, inp: NodeExecutionInput) -> NodeExecutionOutput:
        """Thực thi logic nghiệp vụ ứng với từng loại trong 12 loại bước quy trình."""
        ntype = inp.node_type.strip().upper()
        cfg = dict(inp.node_config or {})

        if ntype == "TRIGGER":
            return NodeExecutionOutput(
                node_id=inp.node_id,
                status=NodeRunStatus.COMPLETED.value,
                output=dict(inp.resolved_inputs),
            )

        if ntype == "CLASSIFY":
            return NodeExecutionOutput(
                node_id=inp.node_id,
                status=NodeRunStatus.COMPLETED.value,
                output={
                    "request_type": str(cfg.get("request_type") or inp.resolved_inputs.get("request_type") or "INTERNAL_TASK"),
                    "department_code": str(cfg.get("department_code") or "IT_OPS"),
                    "missing_information": [],
                },
            )

        if ntype in {"AI_ANALYSIS", "AGENT_TASK"}:
            role_code = (
                str(cfg.get("role_code") or "technical_analyst")
                if ntype == "AGENT_TASK"
                else str((cfg.get("roles") or ["technical_analyst"])[0])
            )
            prompt_spec = self._prompts.get_prompt(role_code)
            res = await self._llm_provider.generate_structured(
                role_code=role_code,
                system_prompt=prompt_spec.system_prompt,
                user_context={
                    "request_id": inp.request_id,
                    "node_id": inp.node_id,
                    "node_name": inp.node_name,
                    "inputs": inp.resolved_inputs,
                },
                output_model=SpecialistFinding,
                max_repair_attempts=2,
            )
            parsed = res.parsed
            if ntype == "AI_ANALYSIS":
                out = {
                    "risk_level": "HIGH" if inp.risk_class == "HIGH" else "MEDIUM",
                    "decision_summary": parsed.decision_summary,
                    "findings": parsed.findings,
                    "evidence_refs": parsed.evidence_refs,
                    "confidence": parsed.confidence,
                }
            else:
                out = {
                    "agent_output": parsed.decision_summary,
                    "findings": parsed.findings,
                    "confidence": parsed.confidence,
                }
            return NodeExecutionOutput(
                node_id=inp.node_id,
                status=NodeRunStatus.COMPLETED.value,
                output=out,
            )

        if ntype == "CONDITION":
            return NodeExecutionOutput(
                node_id=inp.node_id,
                status=NodeRunStatus.COMPLETED.value,
                output={"branch_taken": True, **inp.resolved_inputs},
            )

        if ntype == "HUMAN_TASK":
            dept_code = str(cfg.get("department_code") or "IT_OPS").strip()
            title = str(cfg.get("title") or inp.node_name)[:300]
            instructions = str(cfg.get("instructions") or "")
            async with self._session_factory() as session:
                dept = (
                    await session.execute(
                        sa.select(Department).where(
                            Department.organization_id == inp.organization_id,
                            Department.code == dept_code,
                        )
                    )
                ).scalar_one_or_none()
                task = HumanTask(
                    organization_id=inp.organization_id,
                    request_id=inp.request_id,
                    workflow_run_id=inp.workflow_run_id,
                    department_id=dept.id if dept is not None else None,
                    title=title,
                    instructions=instructions,
                    status=HumanTaskStatus.OPEN.value,
                    visibility=VisibilityLevel.INTERNAL_ONLY.value,
                )
                session.add(task)
                await session.commit()
                return NodeExecutionOutput(
                    node_id=inp.node_id,
                    status=NodeRunStatus.WAITING_EVENT.value,
                    output={"task_id": task.id},
                    requires_wait=True,
                    wait_kind="HUMAN_TASK",
                    human_task_id=task.id,
                )

        if ntype == "APPROVAL":
            required_role = str(cfg.get("required_role") or "department_manager").strip()
            timeout_hours = int(cfg.get("approval_timeout_hours") or 24)
            target_node_id = str(cfg.get("target_node_id") or inp.node_id)
            target_action = str(cfg.get("target_action") or "workflow:approve_step").strip().lower()
            target_params = dict(cfg.get("target_parameters") or {"approval_node_id": inp.node_id})
            target_scope = str(cfg.get("target_scope") or inp.resource_scope or f"workflow:run:{inp.workflow_run_id}")
            param_hash = compute_parameter_hash(
                action=target_action,
                parameters=target_params,
                resource_scope=target_scope,
            )
            async with self._session_factory() as session:
                approval = ApprovalRequest(
                    organization_id=inp.organization_id,
                    request_id=inp.request_id,
                    workflow_run_id=inp.workflow_run_id,
                    workflow_version_id=inp.workflow_version_id,
                    node_id=target_node_id,
                    action=target_action,
                    parameters_json=target_params,
                    parameter_hash=param_hash,
                    resource_scope=target_scope,
                    policy_version="v1",
                    risk_level=inp.risk_class or "HIGH",
                    required_role=required_role,
                    status=ApprovalRequestStatus.PENDING.value,
                    requested_by_actor_id=inp.started_by_membership_id,
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=timeout_hours),
                )
                session.add(approval)
                await session.commit()
                return NodeExecutionOutput(
                    node_id=inp.node_id,
                    status=NodeRunStatus.WAITING_APPROVAL.value,
                    output={"approval_id": approval.id},
                    requires_wait=True,
                    wait_kind="APPROVAL",
                    approval_id=approval.id,
                )

        if ntype == "CONNECTOR_ACTION":
            connector = str(cfg.get("connector") or "mock_github").strip().lower()
            action = str(cfg.get("action") or "create_issue").strip().lower()
            tool_name = f"{connector}:{action}"
            parameters = {
                **dict(cfg.get("parameters") or {}),
                "target_repository": str(cfg.get("target_repository") or "Duckyeeen/VADIRAS-FLOW"),
                "idempotency_key": inp.idempotency_key,
            }
            resource_scope = str(inp.resource_scope or f"github:repo:{parameters['target_repository']}")

            async with self._session_factory() as session:
                req = (
                    await session.execute(
                        sa.select(Request).where(
                            Request.id == inp.request_id,
                            Request.organization_id == inp.organization_id,
                        )
                    )
                ).scalar_one_or_none()
                req_type = req.request_type if req is not None else "CHANGE"
                inj_flags = tuple(req.injection_flags_json or []) if req is not None else ()

                actor_type = str(cfg.get("actor_type") or "EMPLOYEE").strip().upper()
                actor_id = str(cfg.get("actor_id") or inp.started_by_user_id)
                actor_perms = ("workflows:manage", "requests:update", "connectors:execute") if actor_type == "EMPLOYEE" else ()

                ctx = PolicyEvaluationContext(
                    organization_id=inp.organization_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    action=action,
                    resource_scope=resource_scope,
                    parameters=parameters,
                    request_type=req_type,
                    side_effect_class="WRITE",
                    actor_permissions=actor_perms,
                    estimated_cost_usd=inp.estimated_cost_usd,
                    injection_flags=inj_flags,
                )
                token = _ACTIVE_EXEC_CONTEXT.set((session, inp))
                try:
                    receipt = await self._tool_broker.execute(
                        session,
                        tool_name=tool_name,
                        context=ctx,
                        request_id=inp.request_id,
                        workflow_run_id=inp.workflow_run_id,
                        workflow_version_id=inp.workflow_version_id,
                        node_id=inp.node_id,
                        approval_id=inp.approved_approval_id,
                    )
                except AuthorizationError as exc:
                    raise ApplicationError(
                        exc.message,
                        type=ErrorClass.PERMISSION.value,
                        non_retryable=True,
                    ) from exc
                except (ConflictError, ValidationAppError) as exc:
                    raise ApplicationError(
                        exc.message,
                        type=ErrorClass.BUSINESS.value,
                        non_retryable=True,
                    ) from exc
                except ConnectorPermanentError as exc:
                    raise ApplicationError(
                        exc.message,
                        type=ErrorClass.PERMANENT.value,
                        non_retryable=True,
                    ) from exc
                except (ConnectorTransientError, TimeoutError, OSError) as exc:
                    raise ApplicationError(
                        f"Lỗi kết nối tạm thời tới bộ kết nối `{tool_name}`: {exc}",
                        type=ErrorClass.TRANSIENT.value,
                        non_retryable=False,
                    ) from exc
                finally:
                    _ACTIVE_EXEC_CONTEXT.reset(token)

                return NodeExecutionOutput(
                    node_id=inp.node_id,
                    status=NodeRunStatus.COMPLETED.value,
                    output={
                        **receipt.output,
                        "policy_decision_id": receipt.policy_decision_id,
                        "parameter_hash": receipt.parameter_hash,
                    },
                )

        if ntype == "WAIT_EVENT":
            return NodeExecutionOutput(
                node_id=inp.node_id,
                status=NodeRunStatus.WAITING_EVENT.value,
                output={},
                requires_wait=True,
                wait_kind="EVENT",
            )

        if ntype == "NOTIFICATION":
            return NodeExecutionOutput(
                node_id=inp.node_id,
                status=NodeRunStatus.COMPLETED.value,
                output={
                    "notification_sent": True,
                    "audience": str(cfg.get("audience") or "INTERNAL_ONLY"),
                    "channel": str(cfg.get("channel") or "in_app"),
                    "template_code": str(cfg.get("template_code") or "generic_update"),
                },
            )

        if ntype == "VERIFICATION":
            postconditions = [str(x) for x in (cfg.get("postconditions") or [])]
            evidence_sources = [str(x) for x in (cfg.get("evidence_sources") or [])]
            freshness_sec = int(cfg.get("freshness_seconds") or 300)
            evaluator_type = str(cfg.get("evaluator_type") or "DETERMINISTIC_FIRST")
            ext_hint = inp.resolved_inputs.get("external_id")

            async with self._session_factory() as session:
                engine = VerificationEngine()
                ver_run = await engine.run_verification(
                    session,
                    organization_id=inp.organization_id,
                    request_id=inp.request_id,
                    workflow_run_id=inp.workflow_run_id,
                    node_id=inp.node_id,
                    postconditions=postconditions,
                    evidence_sources=evidence_sources,
                    freshness_seconds=freshness_sec,
                    connector=self._connector,
                    external_id_hint=str(ext_hint) if ext_hint else None,
                    evaluator_type=evaluator_type,
                )
                ev_rows = (
                    await session.execute(
                        sa.select(ExecutionEvidence).where(
                            ExecutionEvidence.verification_run_id == ver_run.id
                        )
                    )
                ).scalars().all()
                return NodeExecutionOutput(
                    node_id=inp.node_id,
                    status=NodeRunStatus.COMPLETED.value,
                    output={
                        "verification_run_id": ver_run.id,
                        "verification_outcome": ver_run.outcome,
                        "rationale_summary": ver_run.rationale_summary,
                        "evidence_refs": [
                            {
                                "evidence_id": e.id,
                                "source_type": e.source_type,
                                "source_ref": e.source_ref,
                                "resource_identifier": e.resource_identifier,
                                "is_fresh": e.is_fresh,
                            }
                            for e in ev_rows
                        ],
                    },
                )

        if ntype == "END":
            return NodeExecutionOutput(
                node_id=inp.node_id,
                status=NodeRunStatus.COMPLETED.value,
                output={"final_outcome": str(cfg.get("expected_outcome") or "VERIFIED")},
            )

        raise ApplicationError(
            f"Loại bước `{inp.node_type}` chưa được hỗ trợ trong bộ thực thi.",
            type=ErrorClass.PERMANENT.value,
            non_retryable=True,
        )
