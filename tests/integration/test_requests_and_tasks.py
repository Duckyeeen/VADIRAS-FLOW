"""Kiểm thử tích hợp cho 5 loại yêu cầu, chống tạo trùng, làm rõ thông tin, tác vụ con người và nạp dữ liệu mẫu."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from data.seeds.demo_seed import seed_demo_data


async def _login_token(client: AsyncClient, email: str, password: str) -> str:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return str(res.json()["access_token"])


@pytest.mark.asyncio
async def test_create_all_five_request_types_and_idempotency(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Xác nhận có thể gửi cả 5 loại yêu cầu và mã `Idempotency-Key` ngăn tạo trùng bản ghi."""
    password = str(seeded_env["password"])
    mgr_token = await _login_token(api_client, "manager@vadiras.local", password)
    headers = {"Authorization": f"Bearer {mgr_token}"}

    categories = ["INCIDENT", "CHANGE", "SERVICE_REQUEST", "ONBOARDING", "INTERNAL_TASK"]
    created_ids: list[str] = []

    for idx, req_type in enumerate(categories, start=1):
        res = await api_client.post(
            "/api/v1/requests",
            headers={**headers, "Idempotency-Key": f"idem-cat-{idx}"},
            json={
                "title": f"Yêu cầu mẫu loại {req_type}",
                "description": f"Mô tả chi tiết cho {req_type} kèm email test{idx}@vadiras.local",
                "request_type": req_type,
                "priority": "P2_HIGH",
            },
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["request_type"] == req_type
        assert f"test{idx}@vadiras.local" not in body["sanitized_description"]
        assert "EMAIL" in body["pii_redactions"]
        created_ids.append(body["id"])

    # Gửi lại cùng Idempotency-Key -> trả 200 và đúng mã bản ghi cũ, không sinh yêu cầu thứ 6
    dup_res = await api_client.post(
        "/api/v1/requests",
        headers={**headers, "Idempotency-Key": "idem-cat-1"},
        json={
            "title": "Yêu cầu mẫu loại INCIDENT",
            "description": "Nội dung gửi trùng lần 2",
            "request_type": "INCIDENT",
        },
    )
    assert dup_res.status_code == 200
    assert dup_res.json()["id"] == created_ids[0]

    list_res = await api_client.get("/api/v1/requests", headers=headers)
    assert list_res.status_code == 200
    assert list_res.json()["pagination"]["total"] == 5


@pytest.mark.asyncio
async def test_clarification_flow_and_human_task_lifecycle(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kiểm tra luồng cập nhật trạng thái `NEEDS_INFORMATION -> OPEN` và vòng đời đầu việc con người."""
    password = str(seeded_env["password"])
    mgr_token = await _login_token(api_client, "manager@vadiras.local", password)
    emp_token = await _login_token(api_client, "employee@vadiras.local", password)
    mgr_headers = {"Authorization": f"Bearer {mgr_token}"}
    emp_headers = {"Authorization": f"Bearer {emp_token}"}

    # 1. Tạo yêu cầu và chuyển sang trạng thái chờ bổ sung thông tin
    req_res = await api_client.post(
        "/api/v1/requests",
        headers=emp_headers,
        json={
            "title": "Máy chủ API phản hồi chậm",
            "description": "Phát sinh chậm từ 10 giờ sáng nay.",
            "request_type": "INCIDENT",
        },
    )
    assert req_res.status_code == 201
    request_id = req_res.json()["id"]

    patch_res = await api_client.patch(
        f"/api/v1/requests/{request_id}",
        headers=mgr_headers,
        json={"status": "NEEDS_INFORMATION"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "NEEDS_INFORMATION"

    # 2. Người gửi trả lời làm rõ -> tự mở lại trạng thái OPEN
    clar_res = await api_client.post(
        f"/api/v1/requests/{request_id}/clarifications",
        headers=emp_headers,
        json={"answer": "Lỗi xảy ra ở cụm máy chủ báo cáo v2.1."},
    )
    assert clar_res.status_code == 200
    assert clar_res.json()["status"] == "OPEN"
    assert len(clar_res.json()["messages"]) == 1

    # 3. Quản lý tạo đầu việc -> Nhân viên nhận việc -> báo vướng -> nhận lại -> hoàn tất kèm bằng chứng
    task_res = await api_client.post(
        f"/api/v1/requests/{request_id}/tasks",
        headers=mgr_headers,
        json={
            "title": "Kiểm tra nhật ký cụm báo cáo",
            "instructions": "Đối chiếu thời gian phản hồi từ 10:00 đến 10:30.",
            "department_code": "ENGINEERING",
        },
    )
    assert task_res.status_code == 201
    task_id = task_res.json()["id"]
    assert task_res.json()["status"] == "OPEN"

    claim_res = await api_client.post(f"/api/v1/tasks/{task_id}/claim", headers=emp_headers)
    assert claim_res.status_code == 200
    assert claim_res.json()["status"] == "CLAIMED"

    block_res = await api_client.post(
        f"/api/v1/tasks/{task_id}/block",
        headers=emp_headers,
        json={"blocked_reason": "Đang chờ cấp quyền đọc kho lưu trữ log."},
    )
    assert block_res.status_code == 200
    assert block_res.json()["status"] == "BLOCKED"

    reclaim_res = await api_client.post(f"/api/v1/tasks/{task_id}/claim", headers=emp_headers)
    assert reclaim_res.status_code == 200
    assert reclaim_res.json()["status"] == "CLAIMED"

    complete_res = await api_client.post(
        f"/api/v1/tasks/{task_id}/complete",
        headers=emp_headers,
        json={
            "completion_note": "Đã tìm ra truy vấn chậm và ghi nhận số liệu.",
            "evidence": {"query_duration_ms": 4200},
        },
    )
    assert complete_res.status_code == 200
    assert complete_res.json()["status"] == "COMPLETED"
    assert complete_res.json()["evidence"]["query_duration_ms"] == 4200


@pytest.mark.asyncio
async def test_demo_seed_is_idempotent_across_repeated_runs(
    db_and_session_factory: tuple[str, async_sessionmaker[AsyncSession]],
) -> None:
    """Chạy hàm nạp dữ liệu mẫu 2 lần liên tiếp trên cùng CSDL không tạo bản ghi trùng lặp."""
    _, session_factory = db_and_session_factory

    async with session_factory() as session:
        summary_1 = await seed_demo_data(session)
    async with session_factory() as session:
        summary_2 = await seed_demo_data(session)

    assert summary_1.organization_id == summary_2.organization_id
    assert summary_1.departments_count == 6
    assert summary_1.users_count == 7
    assert summary_1.agents_count == 9
    assert summary_1.requests_count == 5
    assert summary_2 == summary_1
