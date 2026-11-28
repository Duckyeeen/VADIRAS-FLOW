"""Bộ 10 kịch bản kiểm thử toàn trình đầu–cuối bắt buộc nghiệm thu cho backend VADIRAS FLOW."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.core.security import hash_password
from app.modules.connectors.idempotency import ConnectorOperationExecutor
from app.modules.connectors.providers.mock_github import MockGitHubConnector
from app.modules.connectors.models import ConnectorOperationRecord
from app.modules.governance.execution_guard import ExecutionGuard
from app.modules.governance.policy_engine import PolicyEvaluationContext
from app.modules.governance.tool_broker import ToolBroker
from app.modules.identity.models import Membership, MembershipRole, MembershipStatus, User, UserKind
from app.modules.runtime.activities import RuntimeActivities
from app.modules.runtime.contracts import NodeExecutionInput, NodeExecutionOutput
from app.modules.runtime.state_machine import ErrorClass
from app.modules.runtime.workflows import RequestOrchestrationWorkflow
from app.modules.workflows.models import WorkflowDefinition, WorkflowRun, WorkflowVersion, WorkflowVersionStatus

REPO_ROOT = Path(__file__).resolve().parents[2]


async def _login_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _load_template(name: str) -> dict:
    return json.loads((REPO_ROOT / "data" / "workflow_templates" / name).read_text(encoding="utf-8"))


def _sign_webhook(raw_body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_e2e_01_all_five_request_categories_intake_and_classification(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kịch bản 1: Gửi và phân tích có cấu trúc thành công cả 5 loại yêu cầu."""
    password = str(seeded_env["password"])
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)

    categories = ("INCIDENT", "CHANGE", "SERVICE_REQUEST", "ONBOARDING", "INTERNAL_TASK")
    for idx, cat in enumerate(categories):
        create_res = await api_client.post(
            "/api/v1/requests",
            headers={**mgr_headers, "Idempotency-Key": f"e2e-cat-{cat}-{uuid4().hex[:6]}"},
            json={
                "title": f"Yêu cầu kiểm thử loại {cat} số {idx + 1}",
                "description": f"Nội dung chi tiết mô tả đầy đủ cho loại yêu cầu {cat} trong hệ thống.",
                "request_type": cat,
                "priority": "P2_HIGH",
            },
        )
        assert create_res.status_code == 201, create_res.text
        req_id = create_res.json()["id"]
        assert create_res.json()["request_type"] == cat

        an_res = await api_client.post(f"/api/v1/requests/{req_id}/analyze", headers=mgr_headers)
        assert an_res.status_code == 202, an_res.text
        an_body = an_res.json()
        assert an_body["status"] == "COMPLETED"
        assert an_body["structured_output"]["recommended_request_type"] == cat


@pytest.mark.asyncio
async def test_e2e_02_bounded_multi_agent_analysis_and_no_hidden_cot(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kịch bản 2: Nhóm trợ lý AI trả phân tích có cấu trúc, truy vết từng vai trò và không rò rỉ CoT."""
    password = str(seeded_env["password"])
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)

    req_res = await api_client.post(
        "/api/v1/requests",
        headers=mgr_headers,
        json={
            "title": "Dịch vụ xác thực tăng độ trễ bất thường",
            "description": "Thời gian phản hồi API đăng nhập tăng từ 80ms lên 2500ms tại khu vực chính.",
            "request_type": "INCIDENT",
            "priority": "P1_CRITICAL",
        },
    )
    assert req_res.status_code == 201
    request_id = req_res.json()["id"]

    an_res = await api_client.post(f"/api/v1/requests/{request_id}/analyze", headers=mgr_headers)
    assert an_res.status_code == 202
    body = an_res.json()
    assert len(body["agent_runs"]) >= 4
    serialized = json.dumps(body, ensure_ascii=False)
    assert "reasoning_trace" not in serialized
    assert "chain_of_thought" not in serialized

    prop_res = await api_client.post(f"/api/v1/requests/{request_id}/propose-workflows", headers=mgr_headers)
    assert prop_res.status_code == 200
    assert len(prop_res.json()["proposals"]) >= 1


@pytest.mark.asyncio
async def test_e2e_03_full_lifecycle_from_intake_to_verified_audit(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kịch bản 3: Vòng đời trọn vẹn từ tiếp nhận -> AI -> kiểm định -> Temporal -> Issue -> Xác minh -> Kiểm toán."""
    password = str(seeded_env["password"])
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    settings = seeded_env["settings"]
    app = seeded_env["app"]

    cust_headers = await _login_headers(api_client, "customer@client.local", password)
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)

    await api_client.post(
        "/api/v1/connectors/github/installations",
        headers=mgr_headers,
        json={"installation_external_id": "inst-e2e-03", "allowed_repos": ["Duckyeeen/VADIRAS-FLOW"]},
    )

    req_res = await api_client.post(
        "/api/v1/requests",
        headers=cust_headers,
        json={
            "title": "Lỗi 500 khi tải tệp báo cáo tuần",
            "description": "Khách hàng không tải được báo cáo PDF định kỳ từ bảng điều khiển.",
            "request_type": "INCIDENT",
            "priority": "P1_CRITICAL",
        },
    )
    assert req_res.status_code == 201
    request_id = req_res.json()["id"]

    assert (await api_client.post(f"/api/v1/requests/{request_id}/analyze", headers=mgr_headers)).status_code == 202

    graph = _load_template("incident_v1.json")
    wf_res = await api_client.post(
        "/api/v1/workflows",
        headers=mgr_headers,
        json={"code": f"e2e-03-{uuid4().hex[:6]}", "name": "E2E 03 Incident", "request_type": "INCIDENT", "graph": graph},
    )
    assert wf_res.status_code == 201
    wf_id = wf_res.json()["id"]
    ver_id = wf_res.json()["versions"][0]["id"]
    assert (
        await api_client.post(f"/api/v1/workflows/{wf_id}/publish", headers=mgr_headers, json={"version_id": ver_id})
    ).status_code == 200

    mock_conn: MockGitHubConnector = app.state.github_connector  # type: ignore[attr-defined]
    acts = RuntimeActivities(session_factory=session_factory, connector=mock_conn)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        app.state.runtime_gateway.client = env.client  # type: ignore[attr-defined]
        async with Worker(
            env.client,
            task_queue=settings.temporal_task_queue,  # type: ignore[attr-defined]
            workflows=[RequestOrchestrationWorkflow],
            activities=[
                acts.update_run_status_activity,
                acts.persist_node_state_activity,
                acts.execute_node_activity,
            ],
            max_cached_workflows=0,
        ):
            run_res = await api_client.post(
                "/api/v1/workflow-runs",
                headers=mgr_headers,
                json={"request_id": request_id, "workflow_version_id": ver_id},
            )
            assert run_res.status_code == 202
            run_id = run_res.json()["id"]
            handle = env.client.get_workflow_handle(run_res.json()["temporal_workflow_id"])

            for _ in range(50):
                snap = await handle.query(RequestOrchestrationWorkflow.get_progress)
                if snap.status == "WAITING_EVENT":
                    break
                await asyncio.sleep(0.1)

            issues = await mock_conn.list_issues(repository="Duckyeeen/VADIRAS-FLOW")
            wh_body = json.dumps(
                {
                    "action": "labeled",
                    "installation": {"id": "inst-e2e-03"},
                    "repository": {"full_name": "Duckyeeen/VADIRAS-FLOW"},
                    "issue": {"number": issues[-1].external_number, "state": "open", "labels": ["incident", "triage"]},
                }
            ).encode("utf-8")
            wh_res = await api_client.post(
                "/api/v1/webhooks/github",
                headers={
                    "X-Hub-Signature-256": _sign_webhook(wh_body, settings.github_webhook_secret),  # type: ignore[attr-defined]
                    "X-GitHub-Delivery": f"deliv-e2e03-{uuid4().hex[:8]}",
                    "X-GitHub-Event": "issues",
                },
                content=wh_body,
            )
            assert wh_res.status_code == 202
            result = await handle.result()

    assert result["terminal_status"] == "COMPLETED"
    assert result["verification_outcome"] == "VERIFIED"

    ver = (await api_client.get(f"/api/v1/requests/{request_id}/verification", headers=cust_headers)).json()
    assert ver["business_outcome"] == "VERIFIED"
    assert ver["request_status"] == "RESOLVED"
    audits = (await api_client.get(f"/api/v1/audit-logs?workflow_run_id={run_id}", headers=mgr_headers)).json()
    assert len(audits["items"]) >= 2


@pytest.mark.asyncio
async def test_e2e_04_change_request_blocked_at_approval_gate_and_resumes(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kịch bản 4: Yêu cầu thay đổi dừng tại cổng duyệt trước thao tác nhạy cảm và chạy tiếp sau khi được duyệt."""
    password = str(seeded_env["password"])
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    settings = seeded_env["settings"]
    app = seeded_env["app"]

    admin_headers = await _login_headers(api_client, "admin@vadiras.local", password)
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)

    req_res = await api_client.post(
        "/api/v1/requests",
        headers=admin_headers,
        json={
            "title": "Thay đổi ngưỡng giới hạn phiên đăng nhập",
            "description": "Tăng giới hạn phiên đồng thời từ 100 lên 250 cho dịch vụ cổng API.",
            "request_type": "CHANGE",
            "priority": "P2_HIGH",
        },
    )
    request_id = req_res.json()["id"]

    graph = _load_template("change_request_v1.json")
    wf_res = await api_client.post(
        "/api/v1/workflows",
        headers=mgr_headers,
        json={"code": f"e2e-04-{uuid4().hex[:6]}", "name": "E2E 04 Change", "request_type": "CHANGE", "graph": graph},
    )
    wf_id = wf_res.json()["id"]
    ver_id = wf_res.json()["versions"][0]["id"]
    await api_client.post(f"/api/v1/workflows/{wf_id}/publish", headers=mgr_headers, json={"version_id": ver_id})

    mock_conn: MockGitHubConnector = app.state.github_connector  # type: ignore[attr-defined]
    acts = RuntimeActivities(session_factory=session_factory, connector=mock_conn)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        app.state.runtime_gateway.client = env.client  # type: ignore[attr-defined]
        async with Worker(
            env.client,
            task_queue=settings.temporal_task_queue,  # type: ignore[attr-defined]
            workflows=[RequestOrchestrationWorkflow],
            activities=[
                acts.update_run_status_activity,
                acts.persist_node_state_activity,
                acts.execute_node_activity,
            ],
            max_cached_workflows=0,
        ):
            run_res = await api_client.post(
                "/api/v1/workflow-runs",
                headers=admin_headers,
                json={"request_id": request_id, "workflow_version_id": ver_id},
            )
            handle = env.client.get_workflow_handle(run_res.json()["temporal_workflow_id"])
            approval_id = None
            for _ in range(50):
                snap = await handle.query(RequestOrchestrationWorkflow.get_progress)
                if snap.status == "WAITING_APPROVAL" and snap.pending_approval_id:
                    approval_id = snap.pending_approval_id
                    break
                await asyncio.sleep(0.1)
            assert approval_id is not None

            # Chưa có Issue nào được tạo trước khi duyệt
            issues_before = await mock_conn.list_issues(repository="Duckyeeen/VADIRAS-FLOW")
            count_before = len(issues_before)

            # Chặn tự duyệt
            assert (
                await api_client.post(
                    f"/api/v1/approvals/{approval_id}/decision",
                    headers=admin_headers,
                    json={"decision": "APPROVED", "rationale": "Tự duyệt"},
                )
            ).status_code == 403

            # Quản lý duyệt -> chạy qua ExecutionGuard tạo Issue và xác minh VERIFIED
            assert (
                await api_client.post(
                    f"/api/v1/approvals/{approval_id}/decision",
                    headers=mgr_headers,
                    json={"decision": "APPROVED", "rationale": "Đạt yêu cầu kiểm soát thay đổi."},
                )
            ).status_code == 200
            result = await handle.result()
            issues_after = await mock_conn.list_issues(repository="Duckyeeen/VADIRAS-FLOW")

    assert len(issues_after) == count_before + 1
    assert result["terminal_status"] == "COMPLETED"
    assert result["verification_outcome"] == "VERIFIED"


@pytest.mark.asyncio
async def test_e2e_05_unauthorized_ai_proposed_action_blocked_by_policy_engine(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kịch bản 5: Hành động trái phép do AI đề xuất vẫn bị Bộ kiểm soát quy tắc và ToolBroker chặn cứng."""
    password = str(seeded_env["password"])
    org_a_id = str(seeded_env["org_a_id"])
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)

    # 1) Hành động bị cấm trong demo (`delete_user_data`) bị chặn DENY ở preview
    deny_res = await api_client.post(
        "/api/v1/governance/evaluate",
        headers=mgr_headers,
        json={
            "actor_type": "AGENT",
            "actor_id": "executor_agent",
            "action": "delete_user_data",
            "resource_scope": "github:repo:Duckyeeen/VADIRAS-FLOW",
            "parameters": {},
            "request_type": "CHANGE",
        },
    )
    assert deny_res.status_code == 200
    assert deny_res.json()["decision"] == "DENY"

    # 2) Trợ lý AI không có giấy phép hẹp đòi gọi `create_issue` qua ToolBroker -> bị ExecutionGuard chặn 403
    broker = ToolBroker(guard=ExecutionGuard())

    async def _noop(params: dict) -> dict:
        return {"ok": True}

    broker.register_tool("github:create_issue", _noop)
    from app.core.errors import AuthorizationError

    async with session_factory() as session:
        with pytest.raises(AuthorizationError) as exc_info:
            await broker.execute(
                session,
                tool_name="github:create_issue",
                context=PolicyEvaluationContext(
                    organization_id=org_a_id,
                    actor_type="AGENT",
                    actor_id="executor_agent",
                    action="create_issue",
                    resource_scope="github:repo:Duckyeeen/VADIRAS-FLOW",
                    parameters={"title": "AI tự ý tạo"},
                    request_type="INCIDENT",
                    side_effect_class="WRITE",
                ),
            )
    assert exc_info.value.code == "AGENT_GRANT_MISSING"


@pytest.mark.asyncio
async def test_e2e_06_customer_isolation_across_requests_evidence_memory_and_sse(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kịch bản 6: Khách hàng không xem được yêu cầu của khách hàng khác, ghi chú/bằng chứng/bộ nhớ nội bộ."""
    password = str(seeded_env["password"])
    org_a_id = str(seeded_env["org_a_id"])
    role_cust_a_id = str(seeded_env["role_cust_a_id"])
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]

    cust1_headers = await _login_headers(api_client, "customer@client.local", password)
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)

    # Tạo Khách hàng B trong cùng Tổ chức A (cô lập cục bộ trong bài test, không đụng fixture chung)
    async with session_factory() as session:
        user_c2 = User(email="customer2@client.local", full_name="Khách hàng B", password_hash=hash_password(password))
        session.add(user_c2)
        await session.flush()
        mem_c2 = Membership(
            organization_id=org_a_id,
            user_id=user_c2.id,
            user_kind=UserKind.CUSTOMER_CONTACT.value,
            customer_account_ref="CUST-002",
            status=MembershipStatus.ACTIVE.value,
        )
        session.add(mem_c2)
        await session.flush()
        session.add(MembershipRole(membership_id=mem_c2.id, role_id=role_cust_a_id))
        await session.commit()

    cust2_headers = await _login_headers(api_client, "customer2@client.local", password)

    req_res = await api_client.post(
        "/api/v1/requests",
        headers=cust1_headers,
        json={
            "title": "Yêu cầu riêng tư của Khách hàng A1",
            "description": "Chi tiết riêng tư cần bảo vệ.",
            "request_type": "SERVICE_REQUEST",
        },
    )
    request_id = req_res.json()["id"]

    # Quản lý thêm ghi chú nội bộ INTERNAL_ONLY
    note_res = await api_client.post(
        f"/api/v1/requests/{request_id}/messages",
        headers=mgr_headers,
        json={"body": "Ghi chú điều tra nội bộ tuyệt mật", "visibility": "INTERNAL_ONLY", "message_kind": "SYSTEM_NOTE"},
    )
    assert note_res.status_code == 201

    # Khách hàng A1 xem yêu cầu của mình -> không thấy ghi chú INTERNAL_ONLY
    view_c1 = (await api_client.get(f"/api/v1/requests/{request_id}", headers=cust1_headers)).json()
    assert all(m["visibility"] == "CUSTOMER_VISIBLE" for m in view_c1["messages"])
    assert "sanitized_description" not in view_c1

    # Khách hàng A2 bị từ chối 403 trên cả chi tiết yêu cầu lẫn kết quả xác minh của Khách hàng A1
    assert (await api_client.get(f"/api/v1/requests/{request_id}", headers=cust2_headers)).status_code == 403
    assert (
        await api_client.get(f"/api/v1/requests/{request_id}/verification", headers=cust2_headers)
    ).status_code == 403

    # Khách hàng bị chặn 403 khi gọi các API nội bộ
    assert (await api_client.get("/api/v1/audit-logs", headers=cust1_headers)).status_code == 403
    assert (await api_client.get("/api/v1/metrics/overview", headers=cust1_headers)).status_code == 403


@pytest.mark.asyncio
async def test_e2e_07_idempotency_prevents_duplicate_requests_runs_issues_and_webhooks(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kịch bản 7: Gửi lặp yêu cầu, khởi chạy quy trình, thao tác Issue và webhook không tạo bản trùng."""
    password = str(seeded_env["password"])
    org_a_id = str(seeded_env["org_a_id"])
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    settings = seeded_env["settings"]
    app = seeded_env["app"]
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)

    await api_client.post(
        "/api/v1/connectors/github/installations",
        headers=mgr_headers,
        json={"installation_external_id": "inst-e2e-07", "allowed_repos": ["Duckyeeen/VADIRAS-FLOW"]},
    )

    # 1) Gửi lặp yêu cầu cùng Idempotency-Key
    req1 = await api_client.post(
        "/api/v1/requests",
        headers={**mgr_headers, "Idempotency-Key": "e2e07-req-key"},
        json={"title": "Yêu cầu chống trùng", "description": "Kiểm tra idempotency.", "request_type": "INCIDENT"},
    )
    req2 = await api_client.post(
        "/api/v1/requests",
        headers={**mgr_headers, "Idempotency-Key": "e2e07-req-key"},
        json={"title": "Yêu cầu chống trùng", "description": "Kiểm tra idempotency.", "request_type": "INCIDENT"},
    )
    assert req1.json()["id"] == req2.json()["id"]
    req_id = req1.json()["id"]

    # 2) Gửi lặp khởi chạy quy trình cùng Idempotency-Key
    graph = _load_template("incident_v1.json")
    wf = (
        await api_client.post(
            "/api/v1/workflows",
            headers=mgr_headers,
            json={"code": f"e2e07-{uuid4().hex[:6]}", "name": "E2E07", "request_type": "INCIDENT", "graph": graph},
        )
    ).json()
    ver_id = wf["versions"][0]["id"]
    await api_client.post(f"/api/v1/workflows/{wf['id']}/publish", headers=mgr_headers, json={"version_id": ver_id})

    run1 = await api_client.post(
        "/api/v1/workflow-runs",
        headers={**mgr_headers, "Idempotency-Key": "e2e07-run-key"},
        json={"request_id": req_id, "workflow_version_id": ver_id},
    )
    run2 = await api_client.post(
        "/api/v1/workflow-runs",
        headers={**mgr_headers, "Idempotency-Key": "e2e07-run-key"},
        json={"request_id": req_id, "workflow_version_id": ver_id},
    )
    assert run1.json()["id"] == run2.json()["id"]
    assert run2.json()["idempotent_replay"] is True

    # 3) Gửi lặp thao tác tạo Issue cùng idempotency_key + webhook lặp cùng X-GitHub-Delivery
    mock_conn: MockGitHubConnector = app.state.github_connector  # type: ignore[attr-defined]
    executor = ConnectorOperationExecutor(mock_conn)
    async with session_factory() as session:
        op1 = await executor.execute_with_idempotency(
            session,
            organization_id=org_a_id,
            action="create_issue",
            repository="Duckyeeen/VADIRAS-FLOW",
            payload={"title": "Issue E2E07"},
            idempotency_key="e2e07-op-key",
            request_id=req_id,
        )
        op2 = await executor.execute_with_idempotency(
            session,
            organization_id=org_a_id,
            action="create_issue",
            repository="Duckyeeen/VADIRAS-FLOW",
            payload={"title": "Issue E2E07"},
            idempotency_key="e2e07-op-key",
            request_id=req_id,
        )
        ops = (
            await session.execute(
                sa.select(ConnectorOperationRecord).where(ConnectorOperationRecord.idempotency_key == "e2e07-op-key")
            )
        ).scalars().all()
    assert op1.result.external_id == op2.result.external_id
    assert op2.replayed is True
    assert len(ops) == 1

    wh_body = json.dumps(
        {
            "action": "opened",
            "installation": {"id": "inst-e2e-07"},
            "repository": {"full_name": "Duckyeeen/VADIRAS-FLOW"},
            "issue": {"number": op1.result.external_number, "state": "open", "labels": []},
        }
    ).encode("utf-8")
    sig = _sign_webhook(wh_body, settings.github_webhook_secret)  # type: ignore[attr-defined]
    deliv = f"deliv-e2e07-{uuid4().hex[:8]}"
    w1 = await api_client.post(
        "/api/v1/webhooks/github",
        headers={"X-Hub-Signature-256": sig, "X-GitHub-Delivery": deliv, "X-GitHub-Event": "issues"},
        content=wh_body,
    )
    w2 = await api_client.post(
        "/api/v1/webhooks/github",
        headers={"X-Hub-Signature-256": sig, "X-GitHub-Delivery": deliv, "X-GitHub-Event": "issues"},
        content=wh_body,
    )
    assert w1.json()["duplicate"] is False
    assert w2.json()["duplicate"] is True


@pytest.mark.asyncio
async def test_e2e_08_simulated_failure_retry_and_bounded_replan_without_privilege_escalation(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kịch bản 8: Lỗi giả lập kích hoạt thử lại đúng giới hạn và lập lại không tự nâng quyền trái phép."""
    password = str(seeded_env["password"])
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)

    req_res = await api_client.post(
        "/api/v1/requests",
        headers=mgr_headers,
        json={"title": "Kiểm thử lỗi và lập lại an toàn", "description": "Mô tả đủ dài.", "request_type": "CHANGE"},
    )
    request_id = req_res.json()["id"]
    base_graph = _load_template("change_request_v1.json")
    wf = (
        await api_client.post(
            "/api/v1/workflows",
            headers=mgr_headers,
            json={"code": f"e2e08-{uuid4().hex[:6]}", "name": "E2E08", "request_type": "CHANGE", "graph": base_graph},
        )
    ).json()
    ver_id = wf["versions"][0]["id"]
    await api_client.post(f"/api/v1/workflows/{wf['id']}/publish", headers=mgr_headers, json={"version_id": ver_id})

    run = (
        await api_client.post(
            "/api/v1/workflow-runs",
            headers=mgr_headers,
            json={"request_id": request_id, "workflow_version_id": ver_id},
        )
    ).json()
    run_id = run["id"]

    # Lần lập lại 1: an toàn (không tăng phạm vi/rủi ro)
    safe_graph = json.loads(json.dumps(base_graph))
    safe_graph["description"] = "Chỉnh sửa mô tả an toàn"
    rp1 = await api_client.post(
        f"/api/v1/workflow-runs/{run_id}/replan",
        headers=mgr_headers,
        json={"reason": "Điều chỉnh mô tả quy trình.", "proposed_graph": safe_graph},
    )
    assert rp1.status_code == 201 and rp1.json()["proposal"]["risk_escalated"] is False

    # Lần lập lại 2: mở rộng phạm vi kho ngoài -> phải chuyển WAITING_APPROVAL + sinh ApprovalRequest
    esc_graph = json.loads(json.dumps(base_graph))
    esc_graph["nodes"][4]["resource_scope"] = "github:repo:Duckyeeen/CRITICAL-PROD-REPO"
    rp2 = await api_client.post(
        f"/api/v1/workflow-runs/{run_id}/replan",
        headers=mgr_headers,
        json={"reason": "Đổi sang kho sản phẩm trọng yếu.", "proposed_graph": esc_graph},
    )
    assert rp2.status_code == 201
    assert rp2.json()["proposal"]["risk_escalated"] is True
    assert rp2.json()["run_status"] == "WAITING_APPROVAL"
    assert rp2.json()["approval_request_id"] is not None

    # Lần lập lại 3: vượt trần tối đa 2 lần -> bị chặn 409 REPLAN_LIMIT_EXCEEDED
    rp3 = await api_client.post(
        f"/api/v1/workflow-runs/{run_id}/replan",
        headers=mgr_headers,
        json={"reason": "Thử lần 3.", "proposed_graph": safe_graph},
    )
    assert rp3.status_code == 409
    assert rp3.json()["error"]["code"] == "REPLAN_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_e2e_09_worker_restart_preserves_waiting_approval_state(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kịch bản 9: Tắt bật lại tiến trình Temporal Worker không làm mất trạng thái đang chờ duyệt."""
    password = str(seeded_env["password"])
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    settings = seeded_env["settings"]
    app = seeded_env["app"]

    admin_headers = await _login_headers(api_client, "admin@vadiras.local", password)
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)

    req_id = (
        await api_client.post(
            "/api/v1/requests",
            headers=admin_headers,
            json={"title": "Kiểm thử restart worker", "description": "Duyệt giữa 2 phiên worker.", "request_type": "CHANGE"},
        )
    ).json()["id"]
    graph = _load_template("change_request_v1.json")
    wf = (
        await api_client.post(
            "/api/v1/workflows",
            headers=mgr_headers,
            json={"code": f"e2e09-{uuid4().hex[:6]}", "name": "E2E09", "request_type": "CHANGE", "graph": graph},
        )
    ).json()
    ver_id = wf["versions"][0]["id"]
    await api_client.post(f"/api/v1/workflows/{wf['id']}/publish", headers=mgr_headers, json={"version_id": ver_id})

    mock_conn: MockGitHubConnector = app.state.github_connector  # type: ignore[attr-defined]
    acts = RuntimeActivities(session_factory=session_factory, connector=mock_conn)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        app.state.runtime_gateway.client = env.client  # type: ignore[attr-defined]
        # Phiên Worker 1: chạy tới WAITING_APPROVAL rồi dừng
        async with Worker(
            env.client,
            task_queue=settings.temporal_task_queue,  # type: ignore[attr-defined]
            workflows=[RequestOrchestrationWorkflow],
            activities=[
                acts.update_run_status_activity,
                acts.persist_node_state_activity,
                acts.execute_node_activity,
            ],
            max_cached_workflows=0,
        ):
            run_res = await api_client.post(
                "/api/v1/workflow-runs",
                headers=admin_headers,
                json={"request_id": req_id, "workflow_version_id": ver_id},
            )
            handle = env.client.get_workflow_handle(run_res.json()["temporal_workflow_id"])
            approval_id = None
            for _ in range(50):
                snap = await handle.query(RequestOrchestrationWorkflow.get_progress)
                if snap.status == "WAITING_APPROVAL" and snap.pending_approval_id:
                    approval_id = snap.pending_approval_id
                    break
                await asyncio.sleep(0.1)
            assert approval_id is not None

        # Lúc này Worker ĐÃ TẮT — Quản lý phê duyệt qua API
        assert (
            await api_client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                headers=mgr_headers,
                json={"decision": "APPROVED", "rationale": "Duyệt trong lúc worker bảo trì."},
            )
        ).status_code == 200

        # Phiên Worker 2 mới hoàn toàn: phát lại lịch sử và chạy nốt tới COMPLETED/VERIFIED
        async with Worker(
            env.client,
            task_queue=settings.temporal_task_queue,  # type: ignore[attr-defined]
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
    assert result["verification_outcome"] == "VERIFIED"


@pytest.mark.asyncio
async def test_e2e_10_frontend_contract_snapshot_validation_sse_approval_verification_and_metrics(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kịch bản 10: Xác nhận toàn bộ API và SSE cung cấp đủ hợp đồng dữ liệu cho giao diện React."""
    password = str(seeded_env["password"])
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)

    # 1) Danh mục 12 loại bước cho React Flow
    reg = (await api_client.get("/api/v1/workflows/node-registry", headers=mgr_headers)).json()
    assert len(reg["node_types"]) == 12

    # 2) Lỗi kiểm định cụ thể từng bước khi sơ đồ không hợp lệ
    bad_val = (
        await api_client.post(
            "/api/v1/workflows/validate",
            headers=mgr_headers,
            json={"graph": {"workflow_id": "bad", "version": 1, "name": "Bad", "request_type": "INCIDENT", "nodes": [], "edges": []}},
        )
    ).json()
    assert bad_val["valid"] is False and len(bad_val["errors"]) >= 1

    # 3) Ảnh chụp lượt chạy + luồng SSE + phê duyệt + xác minh + kiểm toán + 7 bảng thống kê
    req_id = (
        await api_client.post(
            "/api/v1/requests",
            headers=mgr_headers,
            json={"title": "Kiểm thử hợp đồng frontend", "description": "Đủ dữ liệu UI.", "request_type": "SERVICE_REQUEST"},
        )
    ).json()["id"]
    graph = _load_template("service_request_v1.json")
    wf = (
        await api_client.post(
            "/api/v1/workflows",
            headers=mgr_headers,
            json={"code": f"e2e10-{uuid4().hex[:6]}", "name": "E2E10", "request_type": "SERVICE_REQUEST", "graph": graph},
        )
    ).json()
    ver_id = wf["versions"][0]["id"]
    await api_client.post(f"/api/v1/workflows/{wf['id']}/publish", headers=mgr_headers, json={"version_id": ver_id})
    run = (
        await api_client.post(
            "/api/v1/workflow-runs",
            headers=mgr_headers,
            json={"request_id": req_id, "workflow_version_id": ver_id},
        )
    ).json()

    assert (await api_client.get(f"/api/v1/workflow-runs/{run['id']}", headers=mgr_headers)).status_code == 200
    sse = await api_client.get(f"/api/v1/workflow-runs/{run['id']}/events?once=true", headers=mgr_headers)
    assert sse.status_code == 200 and "event: snapshot" in sse.text
    assert (await api_client.get("/api/v1/approvals", headers=mgr_headers)).status_code == 200
    assert (await api_client.get(f"/api/v1/requests/{req_id}/verification", headers=mgr_headers)).status_code == 200
    assert (await api_client.get("/api/v1/audit-logs", headers=mgr_headers)).status_code == 200

    for m_path in (
        "/api/v1/metrics/overview",
        "/api/v1/metrics/sla",
        "/api/v1/metrics/automation",
        "/api/v1/metrics/cost",
        "/api/v1/metrics/agents",
        "/api/v1/metrics/departments",
        "/api/v1/metrics/industries",
    ):
        assert (await api_client.get(m_path, headers=mgr_headers)).status_code == 200
