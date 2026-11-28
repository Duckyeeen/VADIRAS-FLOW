"""Kiểm thử tích hợp cho API `/api/v1/workflow-runs`: chống trùng lặp, tạm dừng/hủy, lập lại an toàn và cô lập tổ chức."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient

REPO_ROOT = Path(__file__).resolve().parents[2]


async def _login_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _load_template(name: str) -> dict:
    return json.loads((REPO_ROOT / "data" / "workflow_templates" / name).read_text(encoding="utf-8"))


async def _create_request_and_published_workflow(
    api_client: AsyncClient,
    mgr_headers: dict[str, str],
) -> tuple[str, str, str, dict]:
    req_res = await api_client.post(
        "/api/v1/requests",
        headers=mgr_headers,
        json={
            "title": "Yêu cầu thay đổi cấu hình kiểm thử Temporal",
            "description": "Cập nhật tham số bộ đệm dịch vụ cổng thanh toán.",
            "request_type": "CHANGE",
            "priority": "P2_HIGH",
        },
    )
    assert req_res.status_code == 201, req_res.text
    request_id = req_res.json()["id"]

    graph = _load_template("change_request_v1.json")
    wf_res = await api_client.post(
        "/api/v1/workflows",
        headers=mgr_headers,
        json={
            "code": f"wf-run-api-{uuid4().hex[:6]}",
            "name": "Quy trình thay đổi kiểm thử",
            "request_type": "CHANGE",
            "graph": graph,
        },
    )
    assert wf_res.status_code == 201, wf_res.text
    wf_data = wf_res.json()
    workflow_id = wf_data["id"]
    draft_version_id = wf_data["versions"][0]["id"]

    pub_res = await api_client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers=mgr_headers,
        json={"version_id": draft_version_id},
    )
    assert pub_res.status_code == 200, pub_res.text
    return request_id, workflow_id, draft_version_id, graph


@pytest.mark.asyncio
async def test_workflow_run_requires_published_version_and_deduplicates_idempotency_key(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Chặn chạy phiên bản chưa ban hành và chống tạo trùng lượt chạy khi gửi lặp `Idempotency-Key`."""
    password = str(seeded_env["password"])
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)

    req_res = await api_client.post(
        "/api/v1/requests",
        headers=mgr_headers,
        json={
            "title": "Kiểm thử chạy nháp",
            "description": "Không cho phép chạy bản nháp.",
            "request_type": "CHANGE",
        },
    )
    assert req_res.status_code == 201
    request_id = req_res.json()["id"]

    graph = _load_template("change_request_v1.json")
    wf_res = await api_client.post(
        "/api/v1/workflows",
        headers=mgr_headers,
        json={"code": "wf-draft-only", "name": "Bản nháp", "request_type": "CHANGE", "graph": graph},
    )
    assert wf_res.status_code == 201
    workflow_id = wf_res.json()["id"]
    version_id = wf_res.json()["versions"][0]["id"]

    # Thử chạy khi mới VALID (chưa PUBLISHED) -> bị chặn 409
    bad_start = await api_client.post(
        "/api/v1/workflow-runs",
        headers={**mgr_headers, "Idempotency-Key": "idem-bad-1"},
        json={"request_id": request_id, "workflow_version_id": version_id},
    )
    assert bad_start.status_code == 409
    assert bad_start.json()["error"]["code"] == "WORKFLOW_VERSION_NOT_PUBLISHED"

    # Ban hành rồi chạy 2 lần cùng Idempotency-Key
    pub_res = await api_client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers=mgr_headers,
        json={"version_id": version_id},
    )
    assert pub_res.status_code == 200
    published_hash = pub_res.json()["content_hash"]

    first_start = await api_client.post(
        "/api/v1/workflow-runs",
        headers={**mgr_headers, "Idempotency-Key": "idem-run-unique-01"},
        json={"request_id": request_id, "workflow_version_id": version_id},
    )
    assert first_start.status_code == 202, first_start.text
    first_body = first_start.json()
    assert first_body["workflow_version_id"] == version_id
    assert first_body["workflow_content_hash"] == published_hash
    assert first_body["idempotent_replay"] is False

    replay_start = await api_client.post(
        "/api/v1/workflow-runs",
        headers={**mgr_headers, "Idempotency-Key": "idem-run-unique-01"},
        json={"request_id": request_id, "workflow_version_id": version_id},
    )
    assert replay_start.status_code == 202, replay_start.text
    replay_body = replay_start.json()
    assert replay_body["id"] == first_body["id"]
    assert replay_body["idempotent_replay"] is True


@pytest.mark.asyncio
async def test_workflow_run_controls_replan_safety_and_tenant_isolation(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kiểm tra tạm dừng/tiếp tục/hủy, lập lại giữ nguyên bản cũ, tự dừng chờ duyệt khi tăng rủi ro và cô lập quyền."""
    password = str(seeded_env["password"])
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)
    cust_headers = await _login_headers(api_client, "customer@client.local", password)
    org_b_headers = await _login_headers(api_client, "admin@other.local", password)

    request_id, workflow_id, version_id, base_graph = await _create_request_and_published_workflow(
        api_client, mgr_headers
    )

    start_res = await api_client.post(
        "/api/v1/workflow-runs",
        headers=mgr_headers,
        json={"request_id": request_id, "workflow_version_id": version_id},
    )
    assert start_res.status_code == 202, start_res.text
    run_id = start_res.json()["id"]
    original_hash = start_res.json()["workflow_content_hash"]

    # Khách hàng không được xem hay điều khiển lượt chạy (403); tổ chức khác bị chặn 404
    assert (await api_client.get(f"/api/v1/workflow-runs/{run_id}", headers=cust_headers)).status_code == 403
    assert (await api_client.get(f"/api/v1/workflow-runs/{run_id}", headers=org_b_headers)).status_code == 404

    # Tạm dừng và tiếp tục lượt chạy
    pause_res = await api_client.post(
        f"/api/v1/workflow-runs/{run_id}/pause",
        headers=mgr_headers,
        json={"reason": "Kiểm tra cấu hình trước khi chạy"},
    )
    assert pause_res.status_code == 200
    assert pause_res.json()["status"] == "PAUSED"

    # Không thể tạm dừng tiếp khi đã PAUSED
    assert (await api_client.post(f"/api/v1/workflow-runs/{run_id}/pause", headers=mgr_headers)).status_code == 409

    resume_res = await api_client.post(
        f"/api/v1/workflow-runs/{run_id}/resume",
        headers=mgr_headers,
        json={"reason": "Tiếp tục chạy"},
    )
    assert resume_res.status_code == 200
    assert resume_res.json()["status"] == "RUNNING"

    # Lập lại lần 1: không làm tăng phạm vi hay rủi ro -> giữ nguyên bản cũ, không cần phê duyệt mới
    safe_graph = json.loads(json.dumps(base_graph))
    safe_graph["description"] = "Bổ sung mô tả chi tiết cho lần lập lại an toàn"
    replan_1 = await api_client.post(
        f"/api/v1/workflow-runs/{run_id}/replan",
        headers=mgr_headers,
        json={"reason": "Làm rõ mô tả các bước kiểm tra.", "proposed_graph": safe_graph},
    )
    assert replan_1.status_code == 201, replan_1.text
    r1_body = replan_1.json()
    assert r1_body["replan_count"] == 1
    assert r1_body["proposal"]["risk_escalated"] is False
    assert r1_body["approval_request_id"] is None

    # Đảm bảo phiên bản đang chạy gốc vẫn hoàn toàn bất biến
    old_ver_res = await api_client.get(
        f"/api/v1/workflows/{workflow_id}/versions/{version_id}",
        headers=mgr_headers,
    )
    assert old_ver_res.status_code == 200
    assert old_ver_res.json()["content_hash"] == original_hash

    # Lập lại lần 2: đổi resource_scope sang kho khác -> risk_escalated=True, dừng WAITING_APPROVAL + tạo ApprovalRequest
    escalated_graph = json.loads(json.dumps(base_graph))
    escalated_graph["nodes"][4]["resource_scope"] = "github:repo:Duckyeeen/OTHER-CRITICAL-REPO"
    replan_2 = await api_client.post(
        f"/api/v1/workflow-runs/{run_id}/replan",
        headers=mgr_headers,
        json={"reason": "Chuyển sang xử lý trên kho mã phụ.", "proposed_graph": escalated_graph},
    )
    assert replan_2.status_code == 201, replan_2.text
    r2_body = replan_2.json()
    assert r2_body["replan_count"] == 2
    assert r2_body["run_status"] == "WAITING_APPROVAL"
    assert r2_body["proposal"]["risk_escalated"] is True
    assert r2_body["approval_request_id"] is not None

    # Lập lại lần 3 -> bị chặn vì vượt trần tối đa 2 lần
    replan_3 = await api_client.post(
        f"/api/v1/workflow-runs/{run_id}/replan",
        headers=mgr_headers,
        json={"reason": "Thử lập lại lần thứ 3.", "proposed_graph": safe_graph},
    )
    assert replan_3.status_code == 409
    assert replan_3.json()["error"]["code"] == "REPLAN_LIMIT_EXCEEDED"

    # Hủy lượt chạy và kiểm tra trạng thái cuối
    cancel_res = await api_client.post(
        f"/api/v1/workflow-runs/{run_id}/cancel",
        headers=mgr_headers,
        json={"reason": "Đóng lượt chạy sau kiểm thử"},
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"
