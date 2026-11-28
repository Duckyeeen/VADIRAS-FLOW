"""Kiểm thử tích hợp cho Bộ nhớ 5 nhóm, Outbox + SSE phân quyền và 7 tuyến API Thống kê."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.observability.outbox import OutboxDispatcher

REPO_ROOT = Path(__file__).resolve().parents[2]


async def _login_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _load_template(name: str) -> dict:
    return json.loads((REPO_ROOT / "data" / "workflow_templates" / name).read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_memory_promotion_gating_and_permission_filtered_search(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Chặn thăng hạng tri thức chưa xác minh; tìm kiếm chỉ trả tri thức đã duyệt đúng tổ chức & quyền xem."""
    password = str(seeded_env["password"])
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)
    cust_headers = await _login_headers(api_client, "customer@client.local", password)
    org_b_headers = await _login_headers(api_client, "admin@other.local", password)

    # 1) Tạo mục EXECUTION_MEMORY chưa xác minh và đòi thăng hạng ngay -> bị chặn 409
    bad_create = await api_client.post(
        "/api/v1/memory/items",
        headers=mgr_headers,
        json={
            "memory_class": "EXECUTION_MEMORY",
            "title": "Kinh nghiệm xử lý lỗi cổng thanh toán",
            "content": "Khởi động lại dịch vụ cổng thanh toán khi nghẽn kết nối.",
            "access_classification": "INTERNAL_ONLY",
            "verification_status": "UNVERIFIED",
            "promote_immediately": True,
        },
    )
    assert bad_create.status_code == 409
    assert bad_create.json()["error"]["code"] == "MEMORY_PROMOTION_REQUIRES_VERIFICATION"

    # 2) Tạo ở trạng thái DRAFT -> thử promote không kèm human_approved -> vẫn bị chặn 409
    draft_res = await api_client.post(
        "/api/v1/memory/items",
        headers=mgr_headers,
        json={
            "memory_class": "EXECUTION_MEMORY",
            "title": "Hướng dẫn nội bộ mở rộng pool kết nối",
            "content": "Tăng giới hạn pool kết nối nội bộ từ 20 lên 50.",
            "access_classification": "INTERNAL_ONLY",
            "verification_status": "UNVERIFIED",
            "promote_immediately": False,
        },
    )
    assert draft_res.status_code == 201
    internal_id = draft_res.json()["id"]

    reject_promote = await api_client.post(
        f"/api/v1/memory/items/{internal_id}/promote",
        headers=mgr_headers,
        json={"human_approved": False},
    )
    assert reject_promote.status_code == 409

    # Thăng hạng có human_approved=True -> thành công (PROMOTED)
    ok_promote = await api_client.post(
        f"/api/v1/memory/items/{internal_id}/promote",
        headers=mgr_headers,
        json={"human_approved": True, "provenance_ref": "verification-run-001"},
    )
    assert ok_promote.status_code == 200
    assert ok_promote.json()["review_status"] == "PROMOTED"

    # 3) Tạo thêm 1 mục KNOWLEDGE_MEMORY có VERIFIED + CUSTOMER_VISIBLE + promote_immediately=True
    public_res = await api_client.post(
        "/api/v1/memory/items",
        headers=mgr_headers,
        json={
            "memory_class": "KNOWLEDGE_MEMORY",
            "title": "Hướng dẫn khắc phục lỗi xuất PDF cho khách hàng",
            "content": "Vui lòng kiểm tra kích thước dữ liệu báo cáo và thử xuất lại theo từng tuần.",
            "access_classification": "CUSTOMER_VISIBLE",
            "verification_status": "VERIFIED",
            "promote_immediately": True,
        },
    )
    assert public_res.status_code == 201
    assert public_res.json()["review_status"] == "PROMOTED"

    # Khách hàng tìm kiếm -> CHỈ được thấy mục CUSTOMER_VISIBLE, tuyệt đối không thấy INTERNAL_ONLY
    cust_search = await api_client.get(
        "/api/v1/memory/search?q=kết nối PDF",
        headers=cust_headers,
    )
    assert cust_search.status_code == 200
    cust_hits = cust_search.json()["hits"]
    assert len(cust_hits) == 1
    assert cust_hits[0]["item"]["access_classification"] == "CUSTOMER_VISIBLE"
    assert cust_hits[0]["untrusted_reference"] is True

    # Quản lý nội bộ tìm kiếm -> thấy đủ cả 2 mục
    mgr_search = await api_client.get(
        "/api/v1/memory/search?q=kết nối PDF",
        headers=mgr_headers,
    )
    assert mgr_search.status_code == 200
    assert mgr_search.json()["total_hits"] == 2

    # Tổ chức B tìm kiếm -> 0 kết quả (cô lập triệt để)
    org_b_search = await api_client.get(
        "/api/v1/memory/search?q=kết nối PDF",
        headers=org_b_headers,
    )
    assert org_b_search.status_code == 200
    assert org_b_search.json()["total_hits"] == 0


@pytest.mark.asyncio
async def test_outbox_sse_stream_and_all_seven_metrics_endpoints(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kiểm tra phát Outbox, luồng SSE phân quyền và toàn bộ 7 API `/api/v1/metrics/*`."""
    password = str(seeded_env["password"])
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)
    cust_headers = await _login_headers(api_client, "customer@client.local", password)
    org_b_headers = await _login_headers(api_client, "admin@other.local", password)

    # Tạo 1 yêu cầu + phân tích AI + ban hành quy trình + khởi chạy lượt chạy (tự ghi Outbox WORKFLOW_STARTED)
    req_res = await api_client.post(
        "/api/v1/requests",
        headers=mgr_headers,
        json={
            "title": "Yêu cầu kiểm thử thống kê và SSE",
            "description": "Kiểm tra số liệu, chi phí AI và luồng sự kiện trực tiếp.",
            "request_type": "INCIDENT",
            "priority": "P2_HIGH",
        },
    )
    assert req_res.status_code == 201
    request_id = req_res.json()["id"]

    assert (await api_client.post(f"/api/v1/requests/{request_id}/analyze", headers=mgr_headers)).status_code == 202

    graph = _load_template("incident_v1.json")
    wf_res = await api_client.post(
        "/api/v1/workflows",
        headers=mgr_headers,
        json={"code": f"wf-sse-{uuid4().hex[:6]}", "name": "SSE Metrics WF", "request_type": "INCIDENT", "graph": graph},
    )
    assert wf_res.status_code == 201
    wf_id = wf_res.json()["id"]
    ver_id = wf_res.json()["versions"][0]["id"]
    assert (
        await api_client.post(f"/api/v1/workflows/{wf_id}/publish", headers=mgr_headers, json={"version_id": ver_id})
    ).status_code == 200

    run_res = await api_client.post(
        "/api/v1/workflow-runs",
        headers=mgr_headers,
        json={"request_id": request_id, "workflow_version_id": ver_id},
    )
    assert run_res.status_code == 202
    run_id = run_res.json()["id"]

    # Chạy OutboxDispatcher đẩy sự kiện chờ sang trạng thái PUBLISHED
    async with session_factory() as session:
        published = await OutboxDispatcher().publish_pending_batch(session, limit=20)
        assert published >= 1

    # Kiểm tra bảo mật SSE: khách hàng 403, tổ chức B 404, quản lý nhận text/event-stream chuẩn
    assert (await api_client.get(f"/api/v1/workflow-runs/{run_id}/events?once=true", headers=cust_headers)).status_code == 403
    assert (await api_client.get(f"/api/v1/workflow-runs/{run_id}/events?once=true", headers=org_b_headers)).status_code == 404

    sse_res = await api_client.get(f"/api/v1/workflow-runs/{run_id}/events?once=true", headers=mgr_headers)
    assert sse_res.status_code == 200
    assert sse_res.headers["content-type"].startswith("text/event-stream")
    assert "event: snapshot" in sse_res.text
    assert "event: WORKFLOW_STARTED" in sse_res.text

    # Kiểm tra đủ 7 tuyến /api/v1/metrics/* (chặn khách hàng 403; nhân viên nhận đủ cấu trúc)
    metric_paths = (
        "/api/v1/metrics/overview",
        "/api/v1/metrics/sla",
        "/api/v1/metrics/automation",
        "/api/v1/metrics/cost",
        "/api/v1/metrics/agents",
        "/api/v1/metrics/departments",
        "/api/v1/metrics/industries",
    )
    for path in metric_paths:
        assert (await api_client.get(path, headers=cust_headers)).status_code == 403

    overview = (await api_client.get("/api/v1/metrics/overview", headers=mgr_headers)).json()
    assert overview["request_volume"] >= 1
    assert "numerator" in overview["verified_resolution_rate"]

    sla = (await api_client.get("/api/v1/metrics/sla", headers=mgr_headers)).json()
    assert sla["total_requests"] >= 1
    assert "p95_resolution_minutes" in sla

    automation = (await api_client.get("/api/v1/metrics/automation", headers=mgr_headers)).json()
    assert "automation_rate" in automation and "approval_latency_seconds" in automation

    cost = (await api_client.get("/api/v1/metrics/cost", headers=mgr_headers)).json()
    assert set(cost["cost_by_source"].keys()) == {"ACTUAL", "ESTIMATED", "UNKNOWN"}
    assert cost["cost_by_source"]["ESTIMATED"]["calls"] >= 1

    agents = (await api_client.get("/api/v1/metrics/agents", headers=mgr_headers)).json()
    assert agents["total_agent_runs"] >= 1

    depts = (await api_client.get("/api/v1/metrics/departments", headers=mgr_headers)).json()
    assert len(depts["departments"]) == 6

    industries = (await api_client.get("/api/v1/metrics/industries", headers=mgr_headers)).json()
    assert len(industries["by_request_type"]) >= 1
