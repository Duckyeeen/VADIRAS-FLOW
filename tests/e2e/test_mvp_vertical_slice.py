"""Kiểm thử toàn trình đầu–cuối MVP cho 2 luồng chuẩn: Sự cố (`INCIDENT`) và Yêu cầu thay đổi (`CHANGE`)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.modules.connectors.providers.mock_github import MockGitHubConnector
from app.modules.runtime.activities import RuntimeActivities
from app.modules.runtime.workflows import RequestOrchestrationWorkflow

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
async def test_mvp_vertical_slice_incident_end_to_end(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Chạy thông suốt từ đầu tới cuối luồng Sự cố (`INCIDENT`): gửi -> phân tích AI -> Temporal -> Issue -> Webhook -> Xác minh."""
    password = str(seeded_env["password"])
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    settings = seeded_env["settings"]
    app = seeded_env["app"]

    cust_headers = await _login_headers(api_client, "customer@client.local", password)
    admin_headers = await _login_headers(api_client, "admin@vadiras.local", password)
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)

    # 1. Khách hàng gửi yêu cầu Sự cố (kèm đăng ký cài đặt GitHub kho được phép)
    await api_client.post(
        "/api/v1/connectors/github/installations",
        headers=mgr_headers,
        json={
            "installation_external_id": "inst-mvp-incident",
            "allowed_repos": ["Duckyeeen/VADIRAS-FLOW"],
        },
    )
    req_res = await api_client.post(
        "/api/v1/requests",
        headers={**cust_headers, "Idempotency-Key": f"mvp-inc-{uuid4().hex[:6]}"},
        json={
            "title": "Hệ thống xuất báo cáo bị lỗi HTTP 500",
            "description": "Khách hàng bấm xuất báo cáo PDF bị trả lỗi 500 trên môi trường thật.",
            "request_type": "INCIDENT",
            "priority": "P1_CRITICAL",
        },
    )
    assert req_res.status_code == 201, req_res.text
    request_id = req_res.json()["id"]

    # 2. Chạy nhóm trợ lý AI phân tích & tạo/ban hành quy trình incident_v1
    an_res = await api_client.post(f"/api/v1/requests/{request_id}/analyze", headers=mgr_headers)
    assert an_res.status_code == 202

    graph = _load_template("incident_v1.json")
    wf_res = await api_client.post(
        "/api/v1/workflows",
        headers=mgr_headers,
        json={"code": f"mvp-inc-wf-{uuid4().hex[:6]}", "name": "MVP Sự cố", "request_type": "INCIDENT", "graph": graph},
    )
    assert wf_res.status_code == 201
    wf_id = wf_res.json()["id"]
    ver_id = wf_res.json()["versions"][0]["id"]
    pub_res = await api_client.post(
        f"/api/v1/workflows/{wf_id}/publish", headers=mgr_headers, json={"version_id": ver_id}
    )
    assert pub_res.status_code == 200

    # 3. Kết nối API vào Temporal Test Server và chạy Worker thực tế dùng cùng MockGitHubConnector
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
            start_res = await api_client.post(
                "/api/v1/workflow-runs",
                headers={**admin_headers, "Idempotency-Key": f"run-inc-{uuid4().hex[:6]}"},
                json={"request_id": request_id, "workflow_version_id": ver_id},
            )
            assert start_res.status_code == 202, start_res.text
            run_id = start_res.json()["id"]
            temporal_wf_id = start_res.json()["temporal_workflow_id"]
            handle = env.client.get_workflow_handle(temporal_wf_id)

            # Đợi quy trình tạo xong Issue và dừng chờ sự kiện GitHub tại n5_wait_update
            for _ in range(50):
                snap = await handle.query(RequestOrchestrationWorkflow.get_progress)
                if snap.status == "WAITING_EVENT":
                    break
                await asyncio.sleep(0.1)
            assert snap.status == "WAITING_EVENT"

            # Gửi Webhook GitHub có chữ ký HMAC hợp lệ -> tự động đánh thức bước WAIT_EVENT
            status_res = await api_client.get("/api/v1/connectors/github/status", headers=mgr_headers)
            assert status_res.status_code == 200
            issues_in_mock = await mock_conn.list_issues(repository="Duckyeeen/VADIRAS-FLOW")
            issue_num = issues_in_mock[-1].external_number

            wh_body = json.dumps(
                {
                    "action": "labeled",
                    "installation": {"id": "inst-mvp-incident"},
                    "repository": {"full_name": "Duckyeeen/VADIRAS-FLOW"},
                    "issue": {"number": issue_num, "state": "open", "labels": [{"name": "incident"}, {"name": "triage"}]},
                }
            ).encode("utf-8")
            wh_res = await api_client.post(
                "/api/v1/webhooks/github",
                headers={
                    "X-Hub-Signature-256": _sign_webhook(wh_body, settings.github_webhook_secret),  # type: ignore[attr-defined]
                    "X-GitHub-Delivery": f"deliv-mvp-{uuid4().hex[:8]}",
                    "X-GitHub-Event": "issues",
                },
                content=wh_body,
            )
            assert wh_res.status_code == 202
            assert wh_res.json()["correlated_run_id"] == run_id

            result = await handle.result()
            assert result["terminal_status"] == "COMPLETED"
            assert result["verification_outcome"] == "VERIFIED"

    # 4. Xác minh trạng thái Request, bằng chứng và nhật ký kiểm toán qua REST API
    ver_res = await api_client.get(f"/api/v1/requests/{request_id}/verification", headers=cust_headers)
    assert ver_res.status_code == 200
    assert ver_res.json()["business_outcome"] == "VERIFIED"
    assert ver_res.json()["request_status"] == "RESOLVED"

    ev_res = await api_client.get(f"/api/v1/workflow-runs/{run_id}/evidence", headers=mgr_headers)
    assert ev_res.status_code == 200
    assert len(ev_res.json()["evidences"]) >= 1

    audit_res = await api_client.get(f"/api/v1/audit-logs?request_id={request_id}", headers=mgr_headers)
    assert audit_res.status_code == 200
    assert any(a["action"] == "verification:completed" and a["outcome"] == "VERIFIED" for a in audit_res.json()["items"])


@pytest.mark.asyncio
async def test_mvp_vertical_slice_change_request_with_approval_gate(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Chạy thông suốt luồng Yêu cầu Thay đổi (`CHANGE`): chặn ở cổng duyệt -> Quản lý duyệt qua API -> ExecutionGuard -> Xác minh."""
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
            "title": "Nâng giới hạn kết nối CSDL dịch vụ thanh toán",
            "description": "Tăng pool kết nối từ 20 lên 50 trên cụm dịch vụ thanh toán.",
            "request_type": "CHANGE",
            "priority": "P2_HIGH",
        },
    )
    assert req_res.status_code == 201
    request_id = req_res.json()["id"]

    graph = _load_template("change_request_v1.json")
    wf_res = await api_client.post(
        "/api/v1/workflows",
        headers=mgr_headers,
        json={"code": f"mvp-chg-wf-{uuid4().hex[:6]}", "name": "MVP Thay đổi", "request_type": "CHANGE", "graph": graph},
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
            # Admin khởi chạy lượt chạy -> quy trình phải dừng đúng ở cổng phê duyệt n4_approval
            start_res = await api_client.post(
                "/api/v1/workflow-runs",
                headers={**admin_headers, "Idempotency-Key": f"run-chg-{uuid4().hex[:6]}"},
                json={"request_id": request_id, "workflow_version_id": ver_id},
            )
            assert start_res.status_code == 202
            run_id = start_res.json()["id"]
            handle = env.client.get_workflow_handle(start_res.json()["temporal_workflow_id"])

            approval_id: str | None = None
            for _ in range(50):
                snap = await handle.query(RequestOrchestrationWorkflow.get_progress)
                if snap.status == "WAITING_APPROVAL" and snap.pending_approval_id:
                    approval_id = snap.pending_approval_id
                    break
                await asyncio.sleep(0.1)
            assert approval_id is not None

            # 1) Chặn Admin tự phê duyệt yêu cầu do chính mình khởi phát (403 SELF_APPROVAL_FORBIDDEN)
            self_app = await api_client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                headers=admin_headers,
                json={"decision": "APPROVED", "rationale": "Thử tự duyệt"},
            )
            assert self_app.status_code == 403
            assert self_app.json()["error"]["code"] == "SELF_APPROVAL_FORBIDDEN"

            # 2) Quản lý phê duyệt qua API -> tự động đánh thức Temporal -> chạy qua ExecutionGuard -> xác minh Issue + Approval
            mgr_app = await api_client.post(
                f"/api/v1/approvals/{approval_id}/decision",
                headers=mgr_headers,
                json={"decision": "APPROVED", "rationale": "Đã soát xét thay đổi an toàn."},
            )
            assert mgr_app.status_code == 200, mgr_app.text

            result = await handle.result()
            assert result["terminal_status"] == "COMPLETED"
            assert result["verification_outcome"] == "VERIFIED"

    ver_res = await api_client.get(f"/api/v1/requests/{request_id}/verification", headers=mgr_headers)
    assert ver_res.status_code == 200
    assert ver_res.json()["business_outcome"] == "VERIFIED"
    assert len(ver_res.json()["verification_runs"][0]["evidences"]) == 2

    audit_res = await api_client.get(f"/api/v1/audit-logs?workflow_run_id={run_id}", headers=mgr_headers)
    assert audit_res.status_code == 200
    actions = {item["action"] for item in audit_res.json()["items"]}
    assert "workflow_run:started" in actions
    assert "approval:decided" in actions
    assert "verification:completed" in actions
