"""Kiểm thử tích hợp cho API danh mục 12 bước, kiểm định 7 tầng, ban hành bất biến và cô lập tổ chức."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from httpx import AsyncClient

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "data" / "workflow_templates"


async def _login_token(client: AsyncClient, email: str, password: str) -> str:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return str(res.json()["access_token"])


@pytest.mark.asyncio
async def test_node_registry_and_validate_endpoint(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Xác nhận API xuất đủ 12 loại bước chuẩn và trả lỗi kiểm định chính xác."""
    password = str(seeded_env["password"])
    mgr_token = await _login_token(api_client, "manager@vadiras.local", password)
    headers = {"Authorization": f"Bearer {mgr_token}"}

    reg_res = await api_client.get("/api/v1/workflows/node-registry", headers=headers)
    assert reg_res.status_code == 200
    node_types = reg_res.json()["node_types"]
    assert len(node_types) == 12
    assert {item["type"] for item in node_types} == {
        "TRIGGER",
        "CLASSIFY",
        "AI_ANALYSIS",
        "CONDITION",
        "AGENT_TASK",
        "HUMAN_TASK",
        "APPROVAL",
        "CONNECTOR_ACTION",
        "WAIT_EVENT",
        "NOTIFICATION",
        "VERIFICATION",
        "END",
    }

    change_graph = json.loads((TEMPLATES_DIR / "change_request_v1.json").read_text(encoding="utf-8"))
    ok_val = await api_client.post("/api/v1/workflows/validate", headers=headers, json={"graph": change_graph})
    assert ok_val.status_code == 200
    assert ok_val.json()["valid"] is True

    bad_graph = copy.deepcopy(change_graph)
    bad_graph["nodes"][4]["config"]["action"] = "deploy_production"
    bad_val = await api_client.post("/api/v1/workflows/validate", headers=headers, json={"graph": bad_graph})
    assert bad_val.status_code == 200
    assert bad_val.json()["valid"] is False
    assert any(err["code"] == "FORBIDDEN_DEMO_ACTION" for err in bad_val.json()["errors"])


@pytest.mark.asyncio
async def test_workflow_versioning_immutability_and_isolation(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kiểm tra tạo, phiên bản hóa, từ chối ban hành bản lỗi, khóa bất biến và cô lập tổ chức/khách hàng."""
    password = str(seeded_env["password"])
    mgr_token = await _login_token(api_client, "manager@vadiras.local", password)
    cust_token = await _login_token(api_client, "customer@client.local", password)
    admin_b_token = await _login_token(api_client, "admin@other.local", password)
    mgr_headers = {"Authorization": f"Bearer {mgr_token}"}

    incident_graph = json.loads((TEMPLATES_DIR / "incident_v1.json").read_text(encoding="utf-8"))

    # 1. Tạo quy trình mới với phiên bản 1 hợp lệ
    create_res = await api_client.post(
        "/api/v1/workflows",
        headers=mgr_headers,
        json={
            "code": "wf-incident-core",
            "name": "Quy trình Sự cố Lõi",
            "request_type": "INCIDENT",
            "graph": incident_graph,
        },
    )
    assert create_res.status_code == 201, create_res.text
    wf_body = create_res.json()
    wf_id = wf_body["id"]
    v1_id = wf_body["versions"][0]["id"]
    assert wf_body["versions"][0]["status"] == "VALID"

    # 2. Tạo phiên bản 2 bị lỗi -> ban hành v2 phải bị từ chối 422
    broken_graph = copy.deepcopy(incident_graph)
    broken_graph["nodes"][3]["risk_class"] = "CRITICAL"
    v2_res = await api_client.post(
        f"/api/v1/workflows/{wf_id}/versions",
        headers=mgr_headers,
        json={"graph": broken_graph},
    )
    assert v2_res.status_code == 201
    v2_id = v2_res.json()["id"]
    assert v2_res.json()["version_number"] == 2
    assert v2_res.json()["status"] == "INVALID"

    pub_v2_fail = await api_client.post(
        f"/api/v1/workflows/{wf_id}/publish",
        headers=mgr_headers,
        json={"version_id": v2_id},
    )
    assert pub_v2_fail.status_code == 422
    assert pub_v2_fail.json()["error"]["code"] == "WORKFLOW_VALIDATION_FAILED"

    # 3. Ban hành phiên bản 1 hợp lệ -> PUBLISHED; ban hành lại v1 bị chặn 409 bất biến
    pub_v1_ok = await api_client.post(
        f"/api/v1/workflows/{wf_id}/publish",
        headers=mgr_headers,
        json={"version_id": v1_id},
    )
    assert pub_v1_ok.status_code == 200
    assert pub_v1_ok.json()["status"] == "PUBLISHED"
    assert len(pub_v1_ok.json()["content_hash"]) == 64

    repub_v1 = await api_client.post(
        f"/api/v1/workflows/{wf_id}/publish",
        headers=mgr_headers,
        json={"version_id": v1_id},
    )
    assert repub_v1.status_code == 409
    assert repub_v1.json()["error"]["code"] == "IMMUTABLE_WORKFLOW_VERSION"

    # 4. Khách hàng bị chặn 403; Admin tổ chức B không xem được quy trình của tổ chức A
    for method, path in (
        ("GET", "/api/v1/workflows/node-registry"),
        ("GET", "/api/v1/workflows"),
        ("GET", f"/api/v1/workflows/{wf_id}"),
    ):
        cust_res = await api_client.request(
            method,
            path,
            headers={"Authorization": f"Bearer {cust_token}"},
        )
        assert cust_res.status_code == 403

    cross_list = await api_client.get(
        "/api/v1/workflows",
        headers={"Authorization": f"Bearer {admin_b_token}"},
    )
    assert cross_list.status_code == 200
    assert cross_list.json()["pagination"]["total"] == 0

    cross_detail = await api_client.get(
        f"/api/v1/workflows/{wf_id}",
        headers={"Authorization": f"Bearer {admin_b_token}"},
    )
    assert cross_detail.status_code == 404
