"""Kiểm thử tích hợp cho API phân tích AI theo 5 loại yêu cầu, chi phí AI và bảo mật truy cập."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.ai_intelligence.models import AgentRun, AgentTask, LLMCallRecord


async def _login_token(client: AsyncClient, email: str, password: str) -> str:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return str(res.json()["access_token"])


@pytest.mark.asyncio
async def test_analyze_and_propose_workflows_for_five_categories(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kiểm tra chạy phân tích AI cho 5 loại yêu cầu, lưu vết chạy và chi phí ước tính."""
    password = str(seeded_env["password"])
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    mgr_token = await _login_token(api_client, "manager@vadiras.local", password)
    headers = {"Authorization": f"Bearer {mgr_token}"}

    categories = ["INCIDENT", "CHANGE", "SERVICE_REQUEST", "ONBOARDING", "INTERNAL_TASK"]
    change_req_id = ""

    for req_type in categories:
        create_res = await api_client.post(
            "/api/v1/requests",
            headers=headers,
            json={
                "title": f"Yêu cầu kiểm thử {req_type}",
                "description": f"Mô tả đầy đủ cho yêu cầu nhóm {req_type} cần phân tích quy trình.",
                "request_type": req_type,
            },
        )
        assert create_res.status_code == 201
        req_id = create_res.json()["id"]
        if req_type == "CHANGE":
            change_req_id = req_id

        analyze_res = await api_client.post(f"/api/v1/requests/{req_id}/analyze", headers=headers)
        assert analyze_res.status_code == 202, analyze_res.text
        body = analyze_res.json()
        assert body["version_number"] == 1
        assert body["provider"] == "mock"
        assert body["status"] == "COMPLETED"
        assert len(body["agent_runs"]) == 6
        assert "reasoning_trace" not in body["structured_output"]

    # Chạy phân tích lần 2 cho yêu cầu CHANGE -> tăng phiên bản phân tích lên 2
    reanalyze_res = await api_client.post(f"/api/v1/requests/{change_req_id}/analyze", headers=headers)
    assert reanalyze_res.status_code == 202
    assert reanalyze_res.json()["version_number"] == 2

    get_analysis_res = await api_client.get(f"/api/v1/requests/{change_req_id}/analysis", headers=headers)
    assert get_analysis_res.status_code == 200
    assert get_analysis_res.json()["version_number"] == 2

    # Đề xuất quy trình cho CHANGE phải có bước APPROVAL và bước VERIFICATION
    propose_res = await api_client.post(f"/api/v1/requests/{change_req_id}/propose-workflows", headers=headers)
    assert propose_res.status_code == 200
    proposals = propose_res.json()["proposals"]
    assert len(proposals) >= 1
    node_types = {node["type"] for node in proposals[0]["nodes"]}
    assert "APPROVAL" in node_types
    assert "VERIFICATION" in node_types

    # Kiểm tra các bảng agent_tasks, agent_runs và llm_call_records đã được ghi nhận chuẩn xác
    async with session_factory() as session:
        task_count = int((await session.execute(sa.select(sa.func.count()).select_from(AgentTask))).scalar_one())
        run_count = int((await session.execute(sa.select(sa.func.count()).select_from(AgentRun))).scalar_one())
        llm_rows = (await session.execute(sa.select(LLMCallRecord))).scalars().all()
        assert task_count == 36  # 6 lần chạy phân tích x 6 vai trò
        assert run_count == 36
        assert len(llm_rows) == 36
        assert all(row.cost_source == "ESTIMATED" for row in llm_rows)


@pytest.mark.asyncio
async def test_agents_listing_and_customer_isolation_on_ai_endpoints(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kiểm tra liệt kê 9 trợ lý AI, cô lập tổ chức và chặn khách hàng xem phân tích AI nội bộ."""
    password = str(seeded_env["password"])
    org_a_id = str(seeded_env["org_a_id"])
    admin_a_token = await _login_token(api_client, "admin@vadiras.local", password)
    cust_a_token = await _login_token(api_client, "customer@client.local", password)
    admin_b_token = await _login_token(api_client, "admin@other.local", password)

    # 1. Khách hàng tạo yêu cầu rồi cố gắng xem phân tích AI nội bộ -> phải bị chặn 403
    cust_req = await api_client.post(
        "/api/v1/requests",
        headers={"Authorization": f"Bearer {cust_a_token}"},
        json={
            "title": "Sự cố từ khách hàng",
            "description": "Không đăng nhập được vào trang báo cáo từ 8 giờ sáng.",
            "request_type": "INCIDENT",
        },
    )
    assert cust_req.status_code == 201
    req_id = cust_req.json()["id"]

    # Admin A phân tích yêu cầu này bình thường
    admin_analyze = await api_client.post(
        f"/api/v1/requests/{req_id}/analyze",
        headers={"Authorization": f"Bearer {admin_a_token}"},
    )
    assert admin_analyze.status_code == 202

    # Khách hàng gọi analyze, analysis, propose-workflows và agents đều bị chặn 403
    for method, path in (
        ("POST", f"/api/v1/requests/{req_id}/analyze"),
        ("GET", f"/api/v1/requests/{req_id}/analysis"),
        ("POST", f"/api/v1/requests/{req_id}/propose-workflows"),
        ("GET", "/api/v1/agents"),
    ):
        res = await api_client.request(
            method,
            path,
            headers={"Authorization": f"Bearer {cust_a_token}"},
        )
        assert res.status_code == 403, f"Kỳ vọng 403 cho {method} {path}, nhận {res.status_code}"

    # 2. Admin A xem danh sách 9 trợ lý AI của tổ chức A
    agents_res = await api_client.get(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {admin_a_token}"},
    )
    assert agents_res.status_code == 200
    items = agents_res.json()["items"]
    assert len(items) == 9
    assert all(item["organization_id"] == org_a_id for item in items)

    first_agent_id = items[0]["id"]
    detail_res = await api_client.get(
        f"/api/v1/agents/{first_agent_id}",
        headers={"Authorization": f"Bearer {admin_a_token}"},
    )
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == first_agent_id

    # 3. Admin tổ chức B không thể xem trợ lý AI hoặc phân tích của tổ chức A
    cross_agents = await api_client.get(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {admin_b_token}"},
    )
    assert cross_agents.status_code == 200
    assert cross_agents.json()["pagination"]["total"] == 0

    cross_agent_detail = await api_client.get(
        f"/api/v1/agents/{first_agent_id}",
        headers={"Authorization": f"Bearer {admin_b_token}"},
    )
    assert cross_agent_detail.status_code == 404

    cross_analysis = await api_client.get(
        f"/api/v1/requests/{req_id}/analysis",
        headers={"Authorization": f"Bearer {admin_b_token}"},
    )
    assert cross_analysis.status_code == 404
