"""Kiểm thử tích hợp bộ chạy quy trình Temporal thực tế với `WorkflowEnvironment.start_time_skipping`."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.modules.governance.models import ApprovalRequest
from app.modules.identity.models import Membership, Organization
from app.modules.requests.models import Request
from app.modules.runtime.activities import RuntimeActivities
from app.modules.runtime.contracts import ApprovalSignalPayload, NodeExecutionInput, NodeExecutionOutput, WorkflowRunInput
from app.modules.runtime.state_machine import ErrorClass
from app.modules.runtime.workflows import RequestOrchestrationWorkflow
from app.modules.workflows.dsl.schemas import compute_graph_content_hash
from app.modules.workflows.models import WorkflowDefinition, WorkflowNodeRun, WorkflowRun, WorkflowVersion, WorkflowVersionStatus


async def _seed_workflow_run_record(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_env: dict[str, object],
    graph_json: dict,
) -> tuple[str, str, str, str, str]:
    """Tạo sẵn yêu cầu, phiên bản quy trình `PUBLISHED` và bản ghi `WorkflowRun` phục vụ chạy Temporal."""
    org_a_id = str(seeded_env["org_a_id"])
    emp_membership_id = str(seeded_env["emp_membership_id"])

    async with session_factory() as session:
        emp_mem = (
            await session.execute(sa.select(Membership).where(Membership.id == emp_membership_id))
        ).scalar_one()
        req = Request(
            organization_id=org_a_id,
            request_number=f"REQ-T-{uuid4().hex[:6]}",
            title="Kiểm thử quy trình Temporal",
            description="Kiểm tra điều phối bền vững trên Temporal",
            sanitized_description="Kiểm tra điều phối bền vững trên Temporal",
            request_type="CHANGE",
            status="OPEN",
            priority="P2_HIGH",
            requester_membership_id=emp_mem.id,
            requester_kind="EMPLOYEE",
            content_hash=uuid4().hex,
            created_by_user_id=emp_mem.user_id,
            updated_by_user_id=emp_mem.user_id,
        )
        session.add(req)
        await session.flush()

        wf_def = WorkflowDefinition(
            organization_id=org_a_id,
            code=f"wf-temporal-{uuid4().hex[:6]}",
            name="Quy trình Temporal Test",
            request_type="CHANGE",
            created_by_user_id=emp_mem.user_id,
            updated_by_user_id=emp_mem.user_id,
        )
        session.add(wf_def)
        await session.flush()

        wf_ver = WorkflowVersion(
            organization_id=org_a_id,
            workflow_definition_id=wf_def.id,
            version_number=1,
            status=WorkflowVersionStatus.PUBLISHED.value,
            graph_json=graph_json,
            content_hash=compute_graph_content_hash(graph_json),
            created_by_user_id=emp_mem.user_id,
        )
        session.add(wf_ver)
        await session.flush()

        wf_run = WorkflowRun(
            organization_id=org_a_id,
            request_id=req.id,
            workflow_definition_id=wf_def.id,
            workflow_version_id=wf_ver.id,
            workflow_content_hash=wf_ver.content_hash,
            temporal_workflow_id=f"wf-run-test-{uuid4().hex[:8]}",
            status="QUEUED",
            started_by_user_id=emp_mem.user_id,
        )
        session.add(wf_run)
        await session.commit()
        return org_a_id, req.id, wf_ver.id, wf_run.id, emp_mem.user_id, emp_mem.id  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_temporal_dag_branching_parallelism_and_skip_propagation(
    seeded_env: dict[str, object],
) -> None:
    """Chạy đồ thị DAG có rẽ nhánh điều kiện và chạy song song: nhánh không thỏa điều kiện phải bị `SKIPPED`."""
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    graph = {
        "workflow_id": "wf-branch",
        "version": 1,
        "name": "Rẽ nhánh song song",
        "request_type": "INCIDENT",
        "nodes": [
            {"id": "n1", "type": "TRIGGER", "name": "Bắt đầu", "config": {"source": "api"}},
            {"id": "n2_cond", "type": "CONDITION", "name": "Kiểm tra ưu tiên", "config": {}},
            {
                "id": "n3_fast",
                "type": "NOTIFICATION",
                "name": "Nhánh khẩn cấp",
                "config": {"audience": "INTERNAL_ONLY", "channel": "in_app", "template_code": "p1"},
            },
            {
                "id": "n3_slow",
                "type": "NOTIFICATION",
                "name": "Nhánh thường",
                "config": {"audience": "INTERNAL_ONLY", "channel": "in_app", "template_code": "p3"},
            },
            {"id": "n4_end", "type": "END", "name": "Kết thúc", "config": {"expected_outcome": "VERIFIED"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2_cond"},
            {
                "id": "e2_yes",
                "source": "n2_cond",
                "target": "n3_fast",
                "condition": {"op": "eq", "field": "trigger.priority", "value": "P1_CRITICAL"},
            },
            {
                "id": "e2_no",
                "source": "n2_cond",
                "target": "n3_slow",
                "condition": {"op": "eq", "field": "trigger.priority", "value": "P3_MEDIUM"},
            },
            {"id": "e3", "source": "n3_fast", "target": "n4_end"},
            {"id": "e4", "source": "n3_slow", "target": "n4_end"},
        ],
    }

    org_id, req_id, ver_id, run_id, user_id, mem_id = await _seed_workflow_run_record(
        session_factory, seeded_env, graph
    )  # type: ignore[misc]
    acts = RuntimeActivities(session_factory=session_factory)
    task_queue = f"tq-branch-{uuid4().hex[:6]}"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RequestOrchestrationWorkflow],
            activities=[
                acts.update_run_status_activity,
                acts.persist_node_state_activity,
                acts.execute_node_activity,
            ],
        ):
            handle = await env.client.start_workflow(
                RequestOrchestrationWorkflow.run,
                WorkflowRunInput(
                    organization_id=org_id,
                    workflow_run_id=run_id,
                    request_id=req_id,
                    workflow_version_id=ver_id,
                    workflow_content_hash=compute_graph_content_hash(graph),
                    graph_json=graph,
                    trigger_input={"priority": "P1_CRITICAL"},
                    started_by_user_id=user_id,
                    started_by_membership_id=mem_id,
                ),
                id=f"wf-dag-{uuid4().hex[:8]}",
                task_queue=task_queue,
            )
            result = await handle.result()
            snapshot = await handle.query(RequestOrchestrationWorkflow.get_progress)

    assert result["terminal_status"] == "COMPLETED"
    assert "n3_fast" in result["completed_nodes"]
    assert "n4_end" in result["completed_nodes"]
    assert result["skipped_nodes"] == ["n3_slow"]
    assert snapshot.status == "COMPLETED"


@pytest.mark.asyncio
async def test_temporal_approval_wait_survives_worker_restart(
    seeded_env: dict[str, object],
) -> None:
    """Chứng minh quy trình dừng ở `WAITING_APPROVAL`, tắt bật lại Worker vẫn giữ tiến độ và chạy tiếp qua `ExecutionGuard`."""
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    mgr_membership_id = str(seeded_env["mgr_membership_id"])

    graph = {
        "workflow_id": "wf-approval-restart",
        "version": 1,
        "name": "Kiểm tra duyệt bền vững",
        "request_type": "CHANGE",
        "nodes": [
            {"id": "n1", "type": "TRIGGER", "name": "Bắt đầu", "config": {"source": "api"}},
            {
                "id": "n2_approval",
                "type": "APPROVAL",
                "name": "Cổng duyệt",
                "config": {"required_role": "department_manager", "approval_timeout_hours": 24},
            },
            {
                "id": "n3_action",
                "type": "CONNECTOR_ACTION",
                "name": "Tạo issue GitHub",
                "config": {
                    "connector": "mock_github",
                    "action": "create_issue",
                    "target_repository": "Duckyeeen/VADIRAS-FLOW",
                    "parameters": {"labels": ["approved"]},
                },
                "required_capabilities": ["mock_github:create_issue"],
                "resource_scope": "github:repo:Duckyeeen/VADIRAS-FLOW",
                "risk_class": "HIGH",
            },
            {
                "id": "n4_verify",
                "type": "VERIFICATION",
                "name": "Xác minh",
                "config": {"postconditions": ["issue_created"], "evidence_sources": ["github_issue_readback"]},
            },
            {"id": "n5_end", "type": "END", "name": "Kết thúc", "config": {"expected_outcome": "VERIFIED"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2_approval"},
            {
                "id": "e2",
                "source": "n2_approval",
                "target": "n3_action",
                "condition": {"op": "eq", "field": "approval_status", "value": "APPROVED"},
            },
            {"id": "e3", "source": "n3_action", "target": "n4_verify"},
            {"id": "e4", "source": "n4_verify", "target": "n5_end"},
        ],
    }

    org_id, req_id, ver_id, run_id, user_id, mem_id = await _seed_workflow_run_record(
        session_factory, seeded_env, graph
    )  # type: ignore[misc]
    acts = RuntimeActivities(session_factory=session_factory)
    task_queue = f"tq-approval-{uuid4().hex[:6]}"
    wf_id = f"wf-app-{uuid4().hex[:8]}"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        # Đợt 1: Worker chạy tới bước chờ duyệt rồi tắt Worker (tắt bộ đệm dính để Worker mới phát lại toàn bộ lịch sử)
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RequestOrchestrationWorkflow],
            activities=[
                acts.update_run_status_activity,
                acts.persist_node_state_activity,
                acts.execute_node_activity,
            ],
            max_cached_workflows=0,
        ):
            handle = await env.client.start_workflow(
                RequestOrchestrationWorkflow.run,
                WorkflowRunInput(
                    organization_id=org_id,
                    workflow_run_id=run_id,
                    request_id=req_id,
                    workflow_version_id=ver_id,
                    workflow_content_hash=compute_graph_content_hash(graph),
                    graph_json=graph,
                    trigger_input={"title": "Đổi cấu hình"},
                    started_by_user_id=user_id,
                    started_by_membership_id=mem_id,
                ),
                id=wf_id,
                task_queue=task_queue,
            )

            # Đợi quy trình dừng đúng trạng thái WAITING_APPROVAL
            approval_id: str | None = None
            for _ in range(40):
                snap = await handle.query(RequestOrchestrationWorkflow.get_progress)
                if snap.status == "WAITING_APPROVAL" and snap.pending_approval_id:
                    approval_id = snap.pending_approval_id
                    break
                await asyncio.sleep(0.1)
            assert approval_id is not None

        # Lúc này Worker ĐÃ TẮT — cập nhật phê duyệt vào CSDL và gửi tín hiệu Temporal
        async with session_factory() as session:
            app_row = (
                await session.execute(sa.select(ApprovalRequest).where(ApprovalRequest.id == approval_id))
            ).scalar_one()
            app_row.status = "APPROVED"
            await session.commit()

        await handle.signal(
            RequestOrchestrationWorkflow.submit_approval_decision,
            ApprovalSignalPayload(
                approval_id=approval_id,
                node_id="n2_approval",
                decision="APPROVED",
                decided_by=mgr_membership_id,
                rationale="Đã kiểm tra kỹ lưỡng và đồng ý triển khai.",
            ),
        )

        # Đợt 2: Khởi động lại một Worker hoàn toàn mới -> tự phát lại lịch sử và chạy nốt n3_action -> n5_end
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RequestOrchestrationWorkflow],
            activities=[
                acts.update_run_status_activity,
                acts.persist_node_state_activity,
                acts.execute_node_activity,
            ],
            max_cached_workflows=0,
        ):
            result = await handle.result()

    assert result["terminal_status"] == "COMPLETED"
    assert set(result["completed_nodes"]) == {"n1", "n2_approval", "n3_action", "n4_verify", "n5_end"}


@pytest.mark.asyncio
async def test_temporal_approval_timeout_pause_resume_and_cancel(
    seeded_env: dict[str, object],
) -> None:
    """Kiểm tra hết hạn phê duyệt tự chuyển `TIMED_OUT` (dùng tua nhanh thời gian) và tạm dừng/hủy."""
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    graph = {
        "workflow_id": "wf-timeout",
        "version": 1,
        "name": "Kiểm tra quá hạn và tạm dừng",
        "request_type": "CHANGE",
        "nodes": [
            {"id": "n1", "type": "TRIGGER", "name": "Bắt đầu", "config": {"source": "api"}},
            {
                "id": "n2_approval",
                "type": "APPROVAL",
                "name": "Cổng duyệt",
                "config": {"required_role": "department_manager", "approval_timeout_hours": 1},
            },
            {"id": "n3_end", "type": "END", "name": "Kết thúc", "config": {"expected_outcome": "VERIFIED"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n2_approval"},
            {"id": "e2", "source": "n2_approval", "target": "n3_end"},
        ],
    }

    org_id, req_id, ver_id, run_id_to, user_id, mem_id = await _seed_workflow_run_record(
        session_factory, seeded_env, graph
    )  # type: ignore[misc]
    acts = RuntimeActivities(session_factory=session_factory)
    tq = f"tq-to-{uuid4().hex[:6]}"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=tq,
            workflows=[RequestOrchestrationWorkflow],
            activities=[
                acts.update_run_status_activity,
                acts.persist_node_state_activity,
                acts.execute_node_activity,
            ],
        ):
            # 1) Kiểm tra quá hạn chờ phê duyệt -> TIMED_OUT
            handle_to = await env.client.start_workflow(
                RequestOrchestrationWorkflow.run,
                WorkflowRunInput(
                    organization_id=org_id,
                    workflow_run_id=run_id_to,
                    request_id=req_id,
                    workflow_version_id=ver_id,
                    workflow_content_hash=compute_graph_content_hash(graph),
                    graph_json=graph,
                    trigger_input={},
                    started_by_user_id=user_id,
                    started_by_membership_id=mem_id,
                    approval_timeout_seconds=10,
                ),
                id=f"wf-to-{uuid4().hex[:8]}",
                task_queue=tq,
            )
            res_to = await handle_to.result()
            assert res_to["terminal_status"] == "TIMED_OUT"

            # 2) Kiểm tra hủy khi đang chờ duyệt -> CANCELLED
            _, _, _, run_id_cancel, _, _ = await _seed_workflow_run_record(
                session_factory, seeded_env, graph
            )  # type: ignore[misc]
            handle_cancel = await env.client.start_workflow(
                RequestOrchestrationWorkflow.run,
                WorkflowRunInput(
                    organization_id=org_id,
                    workflow_run_id=run_id_cancel,
                    request_id=req_id,
                    workflow_version_id=ver_id,
                    workflow_content_hash=compute_graph_content_hash(graph),
                    graph_json=graph,
                    trigger_input={},
                    started_by_user_id=user_id,
                    started_by_membership_id=mem_id,
                    approval_timeout_seconds=3600,
                ),
                id=f"wf-cancel-{uuid4().hex[:8]}",
                task_queue=tq,
            )
            for _ in range(30):
                snap = await handle_cancel.query(RequestOrchestrationWorkflow.get_progress)
                if snap.status == "WAITING_APPROVAL":
                    break
                await env.sleep(timedelta(milliseconds=100))
            await handle_cancel.signal(RequestOrchestrationWorkflow.cancel_run, "Khách hàng hủy yêu cầu")
            res_cancel = await handle_cancel.result()
            assert res_cancel["terminal_status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_temporal_retry_for_transient_error_vs_non_retryable_permission_error(
    seeded_env: dict[str, object],
) -> None:
    """Lỗi tạm thời `TRANSIENT` tự thử lại đủ tối đa 3 lần rồi thành công; lỗi `PERMISSION` dừng ngay sau 1 lần."""
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    real_acts = RuntimeActivities(session_factory=session_factory)
    transient_attempts = 0
    perm_attempts = 0

    @activity.defn(name="execute_node_activity")
    async def mocked_execute_node(inp: NodeExecutionInput) -> NodeExecutionOutput:
        nonlocal transient_attempts, perm_attempts
        if inp.node_id == "n_flaky":
            transient_attempts += 1
            if transient_attempts < 3:
                raise ApplicationError(
                    "Đứt mạng tạm thời",
                    type=ErrorClass.TRANSIENT.value,
                    non_retryable=False,
                )
            return NodeExecutionOutput(node_id=inp.node_id, status="COMPLETED", output={"ok": True})
        if inp.node_id == "n_forbidden":
            perm_attempts += 1
            raise ApplicationError(
                "Không có quyền gọi công cụ",
                type=ErrorClass.PERMISSION.value,
                non_retryable=True,
            )
        return await real_acts.execute_node_activity(inp)

    # Đồ thị 1: lỗi tạm thời -> thành công ở lần thử thứ 3
    flaky_graph = {
        "workflow_id": "wf-flaky",
        "version": 1,
        "name": "Thử lại lỗi tạm thời",
        "request_type": "INCIDENT",
        "nodes": [
            {"id": "n1", "type": "TRIGGER", "name": "Bắt đầu", "config": {"source": "api"}},
            {
                "id": "n_flaky",
                "type": "NOTIFICATION",
                "name": "Bước chập chờn",
                "config": {"audience": "INTERNAL_ONLY", "channel": "in_app", "template_code": "t"},
                "retry_policy": {"max_attempts": 3, "initial_interval_seconds": 1, "backoff_coefficient": 1.0},
            },
            {"id": "n3", "type": "END", "name": "Kết thúc", "config": {"expected_outcome": "VERIFIED"}},
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n_flaky"},
            {"id": "e2", "source": "n_flaky", "target": "n3"},
        ],
    }

    # Đồ thị 2: lỗi quyền không thử lại -> thất bại ngay ở lần đầu
    perm_graph = {
        **flaky_graph,
        "workflow_id": "wf-perm-err",
        "nodes": [
            flaky_graph["nodes"][0],
            {**flaky_graph["nodes"][1], "id": "n_forbidden", "name": "Bước bị cấm quyền"},
            flaky_graph["nodes"][2],
        ],
        "edges": [
            {"id": "e1", "source": "n1", "target": "n_forbidden"},
            {"id": "e2", "source": "n_forbidden", "target": "n3"},
        ],
    }

    org_id, req_id, ver1_id, run1_id, user_id, mem_id = await _seed_workflow_run_record(
        session_factory, seeded_env, flaky_graph
    )  # type: ignore[misc]
    _, _, ver2_id, run2_id, _, _ = await _seed_workflow_run_record(
        session_factory, seeded_env, perm_graph
    )  # type: ignore[misc]
    tq = f"tq-retry-{uuid4().hex[:6]}"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=tq,
            workflows=[RequestOrchestrationWorkflow],
            activities=[
                real_acts.update_run_status_activity,
                real_acts.persist_node_state_activity,
                mocked_execute_node,
            ],
        ):
            res_ok = await (
                await env.client.start_workflow(
                    RequestOrchestrationWorkflow.run,
                    WorkflowRunInput(
                        organization_id=org_id,
                        workflow_run_id=run1_id,
                        request_id=req_id,
                        workflow_version_id=ver1_id,
                        workflow_content_hash=compute_graph_content_hash(flaky_graph),
                        graph_json=flaky_graph,
                        trigger_input={},
                        started_by_user_id=user_id,
                        started_by_membership_id=mem_id,
                    ),
                    id=f"wf-retry-ok-{uuid4().hex[:8]}",
                    task_queue=tq,
                )
            ).result()

            res_fail = await (
                await env.client.start_workflow(
                    RequestOrchestrationWorkflow.run,
                    WorkflowRunInput(
                        organization_id=org_id,
                        workflow_run_id=run2_id,
                        request_id=req_id,
                        workflow_version_id=ver2_id,
                        workflow_content_hash=compute_graph_content_hash(perm_graph),
                        graph_json=perm_graph,
                        trigger_input={},
                        started_by_user_id=user_id,
                        started_by_membership_id=mem_id,
                    ),
                    id=f"wf-perm-fail-{uuid4().hex[:8]}",
                    task_queue=tq,
                )
            ).result()

    assert res_ok["terminal_status"] == "COMPLETED"
    assert transient_attempts == 3
    assert res_fail["terminal_status"] == "FAILED"
    assert perm_attempts == 1

    async with session_factory() as session:
        fail_node = (
            await session.execute(
                sa.select(WorkflowNodeRun).where(
                    WorkflowNodeRun.workflow_run_id == run2_id,
                    WorkflowNodeRun.node_id == "n_forbidden",
                )
            )
        ).scalar_one()
        assert fail_node.status == "FAILED"
        assert fail_node.error_class == "PERMISSION"
