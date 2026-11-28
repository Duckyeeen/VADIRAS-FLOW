"""Định nghĩa quy trình bền vững Temporal — tuyệt đối tất định, không gọi I/O trực tiếp."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from app.modules.runtime.contracts import (
        ApprovalSignalPayload,
        ExternalEventSignalPayload,
        HumanTaskSignalPayload,
        NodeExecutionInput,
        NodeExecutionOutput,
        NodeStatusUpdateInput,
        RunStatusUpdateInput,
        WorkflowProgressSnapshot,
        WorkflowRunInput,
    )
    from app.modules.workflows.dsl.conditions import evaluate_condition_expr


def _resolve_node_inputs(
    input_mapping: dict[str, Any],
    eval_context: dict[str, Any],
) -> dict[str, Any]:
    """Ánh xạ dữ liệu đầu vào của một bước từ ngữ cảnh các bước trước một cách tất định."""
    resolved: dict[str, Any] = {}
    for target_key, source_expr in input_mapping.items():
        if not isinstance(source_expr, str) or "." not in source_expr:
            continue
        src_node, src_field = source_expr.split(".", 1)
        src_bucket = eval_context.get(src_node)
        if isinstance(src_bucket, dict) and src_field in src_bucket:
            resolved[target_key] = src_bucket[src_field]
    return resolved


@workflow.defn(name="RequestOrchestrationWorkflow")
class RequestOrchestrationWorkflow:
    """Bộ điều phối quy trình dạng đồ thị không chu trình có khả năng tạm dừng, chờ duyệt và phục hồi."""

    def __init__(self) -> None:
        self._run_id: str = ""
        self._status: str = "QUEUED"
        self._paused: bool = False
        self._cancelled: bool = False
        self._cancel_reason: str = ""
        self._waiting_node_id: str | None = None
        self._pending_approval_id: str | None = None
        self._latest_approval_id: str | None = None
        self._last_verification_outcome: str | None = None
        self._node_states: dict[str, str] = {}
        self._node_outputs: dict[str, dict[str, Any]] = {}
        self._approval_decisions: dict[str, ApprovalSignalPayload] = {}
        self._external_events: dict[str, ExternalEventSignalPayload] = {}
        self._human_task_results: dict[str, HumanTaskSignalPayload] = {}

    @workflow.signal(name="submit_approval_decision")
    async def submit_approval_decision(self, payload: ApprovalSignalPayload) -> None:
        """Nhận quyết định phê duyệt hoặc từ chối để đánh thức bước đang chờ duyệt."""
        self._approval_decisions[payload.node_id] = payload
        if (
            self._waiting_node_id is not None
            and self._waiting_node_id != payload.node_id
            and self._node_states.get(self._waiting_node_id) == "WAITING_APPROVAL"
            and (not self._pending_approval_id or self._pending_approval_id == payload.approval_id)
        ):
            self._approval_decisions[self._waiting_node_id] = payload

    @workflow.signal(name="receive_external_event")
    async def receive_external_event(self, payload: ExternalEventSignalPayload) -> None:
        """Nhận sự kiện từ hệ thống ngoài (như webhook GitHub) gửi vào bước đang chờ."""
        self._external_events[payload.node_id] = payload
        if (
            self._waiting_node_id is not None
            and self._waiting_node_id != payload.node_id
            and self._node_states.get(self._waiting_node_id) == "WAITING_EVENT"
        ):
            self._external_events[self._waiting_node_id] = payload

    @workflow.signal(name="complete_human_task")
    async def complete_human_task(self, payload: HumanTaskSignalPayload) -> None:
        """Nhận kết quả xử lý đầu việc từ nhân viên để đi tiếp quy trình."""
        self._human_task_results[payload.node_id] = payload

    @workflow.signal(name="pause_run")
    async def pause_run(self, reason: str = "") -> None:
        """Tạm dừng lượt chạy sau khi hoàn tất các bước đang chạy dở."""
        self._paused = True

    @workflow.signal(name="resume_run")
    async def resume_run(self, reason: str = "") -> None:
        """Cho phép lượt chạy đang tạm dừng tiếp tục điều phối các bước còn lại."""
        self._paused = False

    @workflow.signal(name="cancel_run")
    async def cancel_run(self, reason: str = "") -> None:
        """Yêu cầu hủy lượt chạy hiện tại và đánh dấu các bước còn lại là đã hủy."""
        self._cancelled = True
        self._cancel_reason = reason

    @workflow.query(name="get_progress")
    def get_progress(self) -> WorkflowProgressSnapshot:
        """Trả ảnh chụp tiến độ hiện tại mà không làm thay đổi trạng thái quy trình."""
        completed = [nid for nid, st in self._node_states.items() if st == "COMPLETED"]
        failed = [nid for nid, st in self._node_states.items() if st == "FAILED"]
        skipped = [nid for nid, st in self._node_states.items() if st == "SKIPPED"]
        return WorkflowProgressSnapshot(
            workflow_run_id=self._run_id,
            status=self._status,
            paused=self._paused,
            cancelled=self._cancelled,
            waiting_node_id=self._waiting_node_id,
            pending_approval_id=self._pending_approval_id,
            completed_nodes=completed,
            failed_nodes=failed,
            skipped_nodes=skipped,
            node_states=dict(self._node_states),
        )

    async def _update_run_status(
        self,
        inp: WorkflowRunInput,
        *,
        status: str,
        started_at_iso: str | None = None,
        finished_at_iso: str | None = None,
        result_summary: dict[str, Any] | None = None,
    ) -> None:
        self._status = status
        await workflow.execute_activity(
            "update_run_status_activity",
            RunStatusUpdateInput(
                organization_id=inp.organization_id,
                workflow_run_id=inp.workflow_run_id,
                status=status,
                started_at_iso=started_at_iso,
                finished_at_iso=finished_at_iso,
                result_summary=result_summary,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1)),
            result_type=dict,
        )

    async def _persist_node_state(
        self,
        inp: WorkflowRunInput,
        *,
        node_id: str,
        node_type: str,
        status: str,
        attempt: int = 1,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        error_class: str | None = None,
        error_message: str | None = None,
        started_at_iso: str | None = None,
        finished_at_iso: str | None = None,
    ) -> None:
        self._node_states[node_id] = status
        await workflow.execute_activity(
            "persist_node_state_activity",
            NodeStatusUpdateInput(
                organization_id=inp.organization_id,
                workflow_run_id=inp.workflow_run_id,
                node_id=node_id,
                node_type=node_type,
                status=status,
                attempt=attempt,
                idempotency_key=f"run:{inp.workflow_run_id}:node:{node_id}:att:{attempt}",
                input_summary=input_summary,
                output_summary=output_summary,
                error_class=error_class,
                error_message=error_message,
                started_at_iso=started_at_iso,
                finished_at_iso=finished_at_iso,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1)),
            result_type=dict,
        )

    def _mark_outgoing_edges(
        self,
        source_node_id: str,
        outgoing_edges: dict[str, list[dict[str, Any]]],
        edge_decisions: dict[str, bool],
        edge_context: dict[str, Any],
        *,
        force_not_taken: bool = False,
    ) -> None:
        for edge in outgoing_edges.get(source_node_id, []):
            eid = str(edge["id"])
            if force_not_taken:
                edge_decisions[eid] = False
                continue
            cond = edge.get("condition")
            if cond is None:
                edge_decisions[eid] = True
            elif isinstance(cond, dict):
                edge_decisions[eid] = bool(evaluate_condition_expr(cond, edge_context))
            else:
                edge_decisions[eid] = False

    async def _run_single_node(
        self,
        inp: WorkflowRunInput,
        node: dict[str, Any],
        eval_context: dict[str, Any],
        outgoing_edges: dict[str, list[dict[str, Any]]],
        edge_decisions: dict[str, bool],
    ) -> str:
        """Thực thi một bước (kể cả chờ tín hiệu nếu bước đó là cổng duyệt/sự kiện/nhân sự).

        Trả về kết quả điều hướng vòng lặp: `"OK"`, `"FAILED"`, `"TIMED_OUT"` hoặc `"CANCELLED"`.
        """
        node_id = str(node["id"])
        node_type = str(node["type"]).upper()
        node_name = str(node.get("name") or node_id)
        node_cfg = dict(node.get("config") or {})
        retry_cfg = dict(node.get("retry_policy") or {})

        resolved_inputs = _resolve_node_inputs(dict(node.get("input_mapping") or {}), eval_context)
        if node_type == "TRIGGER":
            resolved_inputs = {**dict(inp.trigger_input), **resolved_inputs}

        now_iso = workflow.now().isoformat()
        await self._persist_node_state(
            inp,
            node_id=node_id,
            node_type=node_type,
            status="RUNNING",
            attempt=1,
            input_summary=resolved_inputs,
            started_at_iso=now_iso,
        )

        max_attempts = min(max(1, int(retry_cfg.get("max_attempts", 3))), 3)
        init_sec = max(1, int(retry_cfg.get("initial_interval_seconds", 1)))
        backoff = max(1.0, float(retry_cfg.get("backoff_coefficient", 2.0)))
        node_timeout = max(5, int(node.get("timeout_seconds", 300)))

        # Nếu là bước APPROVAL chưa khai báo sẵn mục tiêu ràng buộc, tự liên kết với CONNECTOR_ACTION kế tiếp
        if node_type == "APPROVAL" and "target_node_id" not in node_cfg:
            for edge in outgoing_edges.get(node_id, []):
                tgt_id = str(edge.get("target") or "")
                tgt_node = nodes_by_id_map.get(tgt_id) if (nodes_by_id_map := getattr(self, "_nodes_by_id", None)) else None
                if tgt_node and str(tgt_node.get("type", "")).upper() == "CONNECTOR_ACTION":
                    tgt_cfg = dict(tgt_node.get("config") or {})
                    repo_name = str(tgt_cfg.get("target_repository") or "Duckyeeen/VADIRAS-FLOW")
                    node_cfg = {
                        **node_cfg,
                        "target_node_id": tgt_id,
                        "target_action": str(tgt_cfg.get("action") or "create_issue").strip().lower(),
                        "target_parameters": {
                            **dict(tgt_cfg.get("parameters") or {}),
                            "target_repository": repo_name,
                            "idempotency_key": f"run:{inp.workflow_run_id}:node:{tgt_id}:att:1",
                        },
                        "target_scope": str(tgt_node.get("resource_scope") or f"github:repo:{repo_name}"),
                    }
                    break

        try:
            exec_out = await workflow.execute_activity(
                "execute_node_activity",
                NodeExecutionInput(
                    organization_id=inp.organization_id,
                    workflow_run_id=inp.workflow_run_id,
                    request_id=inp.request_id,
                    workflow_version_id=inp.workflow_version_id,
                    node_id=node_id,
                    node_type=node_type,
                    node_name=node_name,
                    node_config=node_cfg,
                    resource_scope=node.get("resource_scope"),
                    risk_class=str(node.get("risk_class") or "LOW"),
                    estimated_cost_usd=float(node.get("estimated_cost_usd") or 0.01),
                    resolved_inputs=resolved_inputs,
                    idempotency_key=f"run:{inp.workflow_run_id}:node:{node_id}:att:1",
                    attempt=1,
                    started_by_user_id=inp.started_by_user_id,
                    started_by_membership_id=inp.started_by_membership_id,
                    approved_approval_id=self._latest_approval_id,
                ),
                start_to_close_timeout=timedelta(seconds=node_timeout),
                retry_policy=RetryPolicy(
                    maximum_attempts=max_attempts,
                    initial_interval=timedelta(seconds=init_sec),
                    backoff_coefficient=backoff,
                    non_retryable_error_types=["PERMISSION", "BUSINESS", "PERMANENT"],
                ),
                result_type=NodeExecutionOutput,
            )
        except ActivityError as exc:
            err_msg = str(exc.cause or exc)
            err_cls = getattr(exc.cause, "type", None) or "TRANSIENT"
            await self._persist_node_state(
                inp,
                node_id=node_id,
                node_type=node_type,
                status="FAILED",
                attempt=1,
                error_class=str(err_cls),
                error_message=err_msg,
                finished_at_iso=workflow.now().isoformat(),
            )
            self._mark_outgoing_edges(
                node_id, outgoing_edges, edge_decisions, eval_context, force_not_taken=True
            )
            return "FAILED"

        final_output = dict(exec_out.output or {})

        # Xử lý các bước cần tạm dừng chờ tín hiệu từ người duyệt, nhân viên hoặc webhook ngoài
        if exec_out.requires_wait:
            self._waiting_node_id = node_id
            if exec_out.wait_kind == "APPROVAL":
                self._pending_approval_id = exec_out.approval_id
                await self._persist_node_state(
                    inp,
                    node_id=node_id,
                    node_type=node_type,
                    status="WAITING_APPROVAL",
                    output_summary=final_output,
                )
                await self._update_run_status(inp, status="WAITING_APPROVAL")
                cfg_hours = int(node_cfg.get("approval_timeout_hours") or 24)
                wait_sec = min(inp.approval_timeout_seconds, max(5, cfg_hours * 3600))
                try:
                    await workflow.wait_condition(
                        lambda: self._cancelled or node_id in self._approval_decisions,
                        timeout=timedelta(seconds=wait_sec),
                    )
                except asyncio.TimeoutError:
                    await self._persist_node_state(
                        inp,
                        node_id=node_id,
                        node_type=node_type,
                        status="FAILED",
                        error_class="TIMEOUT",
                        error_message="Quá hạn thời gian chờ phê duyệt.",
                        finished_at_iso=workflow.now().isoformat(),
                    )
                    self._waiting_node_id = None
                    self._pending_approval_id = None
                    return "TIMED_OUT"

                self._waiting_node_id = None
                self._pending_approval_id = None
                if self._cancelled:
                    await self._persist_node_state(
                        inp,
                        node_id=node_id,
                        node_type=node_type,
                        status="CANCELLED",
                        finished_at_iso=workflow.now().isoformat(),
                    )
                    return "CANCELLED"

                decision_sig = self._approval_decisions[node_id]
                final_output = {
                    "approval_id": decision_sig.approval_id,
                    "approval_status": decision_sig.decision,
                    "approved_by": decision_sig.decided_by,
                    "rationale": decision_sig.rationale,
                }
                if decision_sig.decision != "APPROVED":
                    await self._persist_node_state(
                        inp,
                        node_id=node_id,
                        node_type=node_type,
                        status="FAILED",
                        output_summary=final_output,
                        error_class="BUSINESS",
                        error_message="Yêu cầu phê duyệt đã bị từ chối.",
                        finished_at_iso=workflow.now().isoformat(),
                    )
                    self._mark_outgoing_edges(
                        node_id, outgoing_edges, edge_decisions, eval_context, force_not_taken=True
                    )
                    return "FAILED"

                self._latest_approval_id = decision_sig.approval_id
                await self._update_run_status(inp, status="RUNNING")

            elif exec_out.wait_kind == "EVENT":
                await self._persist_node_state(
                    inp,
                    node_id=node_id,
                    node_type=node_type,
                    status="WAITING_EVENT",
                    output_summary=final_output,
                )
                await self._update_run_status(inp, status="WAITING_EVENT")
                try:
                    await workflow.wait_condition(
                        lambda: self._cancelled or node_id in self._external_events,
                        timeout=timedelta(seconds=inp.event_timeout_seconds),
                    )
                except asyncio.TimeoutError:
                    await self._persist_node_state(
                        inp,
                        node_id=node_id,
                        node_type=node_type,
                        status="FAILED",
                        error_class="TIMEOUT",
                        error_message="Quá hạn chờ sự kiện từ hệ thống ngoài.",
                        finished_at_iso=workflow.now().isoformat(),
                    )
                    self._waiting_node_id = None
                    return "TIMED_OUT"

                self._waiting_node_id = None
                if self._cancelled:
                    await self._persist_node_state(
                        inp,
                        node_id=node_id,
                        node_type=node_type,
                        status="CANCELLED",
                        finished_at_iso=workflow.now().isoformat(),
                    )
                    return "CANCELLED"

                ev = self._external_events[node_id]
                final_output = {
                    "event_id": f"{ev.event_source}:{ev.event_type}",
                    "event_payload": dict(ev.payload),
                }
                await self._update_run_status(inp, status="RUNNING")

            elif exec_out.wait_kind == "HUMAN_TASK":
                await self._persist_node_state(
                    inp,
                    node_id=node_id,
                    node_type=node_type,
                    status="WAITING_EVENT",
                    output_summary=final_output,
                )
                await self._update_run_status(inp, status="WAITING_EVENT")
                try:
                    await workflow.wait_condition(
                        lambda: self._cancelled or node_id in self._human_task_results,
                        timeout=timedelta(seconds=inp.event_timeout_seconds),
                    )
                except asyncio.TimeoutError:
                    await self._persist_node_state(
                        inp,
                        node_id=node_id,
                        node_type=node_type,
                        status="FAILED",
                        error_class="TIMEOUT",
                        error_message="Quá hạn hoàn thành đầu việc nhân sự.",
                        finished_at_iso=workflow.now().isoformat(),
                    )
                    self._waiting_node_id = None
                    return "TIMED_OUT"

                self._waiting_node_id = None
                if self._cancelled:
                    await self._persist_node_state(
                        inp,
                        node_id=node_id,
                        node_type=node_type,
                        status="CANCELLED",
                        finished_at_iso=workflow.now().isoformat(),
                    )
                    return "CANCELLED"

                task_sig = self._human_task_results[node_id]
                final_output = {
                    "task_id": task_sig.task_id,
                    "completion_note": task_sig.completion_note,
                    "evidence": dict(task_sig.evidence),
                    "status": task_sig.status,
                }
                if task_sig.status != "COMPLETED":
                    await self._persist_node_state(
                        inp,
                        node_id=node_id,
                        node_type=node_type,
                        status="FAILED",
                        output_summary=final_output,
                        error_class="BUSINESS",
                        error_message="Đầu việc nhân sự bị đánh dấu vướng mắc.",
                        finished_at_iso=workflow.now().isoformat(),
                    )
                    self._mark_outgoing_edges(
                        node_id, outgoing_edges, edge_decisions, eval_context, force_not_taken=True
                    )
                    return "FAILED"
                await self._update_run_status(inp, status="RUNNING")

        # Lưu kết quả bước đã hoàn tất và đánh giá các cạnh đi ra
        if node_type == "VERIFICATION":
            self._last_verification_outcome = str(final_output.get("verification_outcome") or "")
        self._node_outputs[node_id] = final_output
        eval_context[node_id] = final_output
        await self._persist_node_state(
            inp,
            node_id=node_id,
            node_type=node_type,
            status="COMPLETED",
            output_summary=final_output,
            finished_at_iso=workflow.now().isoformat(),
        )
        edge_eval_ctx = {**eval_context, **final_output}
        self._mark_outgoing_edges(node_id, outgoing_edges, edge_decisions, edge_eval_ctx)
        return "OK"

    @workflow.run
    async def run(self, inp: WorkflowRunInput) -> dict[str, Any]:
        """Điều phối trọn vẹn một lượt chạy theo đúng thứ tự phụ thuộc của sơ đồ đã kiểm định."""
        self._run_id = inp.workflow_run_id
        nodes_list: list[dict[str, Any]] = list(inp.graph_json.get("nodes") or [])
        edges_list: list[dict[str, Any]] = list(inp.graph_json.get("edges") or [])

        nodes_by_id: dict[str, dict[str, Any]] = {str(n["id"]): n for n in nodes_list}
        self._nodes_by_id = nodes_by_id
        for nid in nodes_by_id:
            self._node_states[nid] = "PENDING"

        incoming_edges: dict[str, list[dict[str, Any]]] = {nid: [] for nid in nodes_by_id}
        outgoing_edges: dict[str, list[dict[str, Any]]] = {nid: [] for nid in nodes_by_id}
        for edge in edges_list:
            src = str(edge["source"])
            tgt = str(edge["target"])
            if src in outgoing_edges and tgt in incoming_edges:
                outgoing_edges[src].append(edge)
                incoming_edges[tgt].append(edge)

        edge_decisions: dict[str, bool] = {}
        eval_context: dict[str, Any] = {"trigger": dict(inp.trigger_input)}

        await self._update_run_status(
            inp,
            status="RUNNING",
            started_at_iso=workflow.now().isoformat(),
        )

        max_parallel = min(max(1, inp.max_parallelism), 4)
        terminal_status = "COMPLETED"

        while True:
            # Kiểm tra lệnh hủy lượt chạy
            if self._cancelled:
                for nid, st in list(self._node_states.items()):
                    if st == "PENDING":
                        await self._persist_node_state(
                            inp,
                            node_id=nid,
                            node_type=str(nodes_by_id[nid]["type"]).upper(),
                            status="CANCELLED",
                            finished_at_iso=workflow.now().isoformat(),
                        )
                terminal_status = "CANCELLED"
                break

            # Kiểm tra lệnh tạm dừng lượt chạy
            if self._paused:
                await self._update_run_status(inp, status="PAUSED")
                await workflow.wait_condition(lambda: not self._paused or self._cancelled)
                if self._cancelled:
                    continue
                await self._update_run_status(inp, status="RUNNING")

            # Lan truyền bỏ qua các bước thuộc nhánh điều kiện không được chọn
            progressed_skip = True
            while progressed_skip:
                progressed_skip = False
                for nid in nodes_by_id:
                    if self._node_states[nid] != "PENDING":
                        continue
                    inc = incoming_edges[nid]
                    if inc and all(str(e["id"]) in edge_decisions for e in inc):
                        if not any(edge_decisions[str(e["id"])] for e in inc):
                            await self._persist_node_state(
                                inp,
                                node_id=nid,
                                node_type=str(nodes_by_id[nid]["type"]).upper(),
                                status="SKIPPED",
                                finished_at_iso=workflow.now().isoformat(),
                            )
                            self._mark_outgoing_edges(
                                nid,
                                outgoing_edges,
                                edge_decisions,
                                eval_context,
                                force_not_taken=True,
                            )
                            progressed_skip = True

            # Gom tối đa `max_parallel` bước đã đủ điều kiện phụ thuộc để chạy
            ready_nodes: list[dict[str, Any]] = []
            for nid, node in nodes_by_id.items():
                if self._node_states[nid] != "PENDING":
                    continue
                inc = incoming_edges[nid]
                if not inc:
                    ready_nodes.append(node)
                elif all(str(e["id"]) in edge_decisions for e in inc) and any(
                    edge_decisions[str(e["id"])] for e in inc
                ):
                    ready_nodes.append(node)

            if not ready_nodes:
                break

            batch = ready_nodes[:max_parallel]
            if len(batch) == 1:
                outcomes = [
                    await self._run_single_node(
                        inp, batch[0], eval_context, outgoing_edges, edge_decisions
                    )
                ]
            else:
                outcomes = list(
                    await asyncio.gather(
                        *[
                            self._run_single_node(
                                inp, n, eval_context, outgoing_edges, edge_decisions
                            )
                            for n in batch
                        ]
                    )
                )

            if "CANCELLED" in outcomes:
                terminal_status = "CANCELLED"
                break
            if "TIMED_OUT" in outcomes:
                terminal_status = "TIMED_OUT"
                break
            if "FAILED" in outcomes:
                terminal_status = "FAILED"
                break

        if terminal_status == "COMPLETED":
            if self._last_verification_outcome == "PARTIALLY_VERIFIED":
                terminal_status = "PARTIALLY_COMPLETED"
            elif self._last_verification_outcome in {"FAILED", "UNVERIFIED"}:
                terminal_status = "FAILED"

        summary = {
            "terminal_status": terminal_status,
            "verification_outcome": self._last_verification_outcome,
            "completed_nodes": [nid for nid, st in self._node_states.items() if st == "COMPLETED"],
            "failed_nodes": [nid for nid, st in self._node_states.items() if st == "FAILED"],
            "skipped_nodes": [nid for nid, st in self._node_states.items() if st == "SKIPPED"],
            "outputs": self._node_outputs,
        }
        await self._update_run_status(
            inp,
            status=terminal_status,
            finished_at_iso=workflow.now().isoformat(),
            result_summary=summary,
        )
        return summary
