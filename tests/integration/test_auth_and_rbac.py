"""Kiểm thử tích hợp và bảo mật cho xác thực JWT, xoay vòng thẻ, phân quyền và cô lập tổ chức."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.identity.models import Membership, MembershipRole, MembershipStatus


async def _login_and_get_tokens(client: AsyncClient, email: str, password: str) -> dict[str, object]:
    """Hàm hỗ trợ đăng nhập và trả về cặp thẻ JWT."""
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.asyncio
async def test_login_success_wrong_password_and_suspended_membership(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kiểm tra đăng nhập thành công, sai mật khẩu bị 401 và tài khoản bị khóa bị từ chối."""
    password = str(seeded_env["password"])

    tokens = await _login_and_get_tokens(api_client, "admin@vadiras.local", password)
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    bad_pw = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@vadiras.local", "password": "SaiMatKhau"},
    )
    assert bad_pw.status_code == 401
    assert bad_pw.json()["error"]["code"] == "INVALID_CREDENTIALS"

    locked = await api_client.post(
        "/api/v1/auth/login",
        json={"email": "locked@vadiras.local", "password": password},
    )
    assert locked.status_code == 401
    assert locked.json()["error"]["code"] == "MEMBERSHIP_INACTIVE"


@pytest.mark.asyncio
async def test_auth_me_does_not_leak_password_and_enforces_fresh_db_state(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Đảm bảo `/auth/me` nạp quyền mới nhất từ CSDL và chặn ngay nếu vừa bị khóa hoặc thu hồi vai trò."""
    password = str(seeded_env["password"])
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    mgr_membership_id = str(seeded_env["mgr_membership_id"])
    role_mgr_a_id = str(seeded_env["role_mgr_a_id"])

    tokens = await _login_and_get_tokens(api_client, "manager@vadiras.local", password)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    me_res = await api_client.get("/api/v1/auth/me", headers=headers)
    assert me_res.status_code == 200
    me_body = me_res.json()
    assert me_body["email"] == "manager@vadiras.local"
    assert me_body["user_kind"] == "EMPLOYEE"
    assert "department_manager" in me_body["roles"]
    assert "users:read" in me_body["permissions"]
    assert "password_hash" not in me_body

    # Thu hồi vai trò quản lý trong CSDL khi thẻ JWT vẫn còn hạn -> gọi /users phải bị chặn 403 ngay
    async with session_factory() as session:
        await session.execute(
            sa.delete(MembershipRole).where(
                MembershipRole.membership_id == mgr_membership_id,
                MembershipRole.role_id == role_mgr_a_id,
            )
        )
        await session.commit()

    denied_after_revoke = await api_client.get("/api/v1/users", headers=headers)
    assert denied_after_revoke.status_code == 403
    assert denied_after_revoke.json()["error"]["code"] == "PERMISSION_DENIED"

    # Khóa tư cách thành viên trong CSDL -> gọi /auth/me bị chặn 401 ngay lập tức
    async with session_factory() as session:
        await session.execute(
            sa.update(Membership)
            .where(Membership.id == mgr_membership_id)
            .values(status=MembershipStatus.SUSPENDED.value)
        )
        await session.commit()

    denied_after_suspend = await api_client.get("/api/v1/auth/me", headers=headers)
    assert denied_after_suspend.status_code == 401
    assert denied_after_suspend.json()["error"]["code"] == "ACTOR_INACTIVE"


@pytest.mark.asyncio
async def test_refresh_rotation_reuse_detection_and_logout(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kiểm tra xoay vòng thẻ làm mới, phát hiện dùng lại thẻ cũ và thu hồi khi đăng xuất."""
    password = str(seeded_env["password"])
    initial = await _login_and_get_tokens(api_client, "employee@vadiras.local", password)
    old_refresh = str(initial["refresh_token"])

    # Xoay vòng lần 1 -> nhận cặp thẻ mới
    rotated_res = await api_client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert rotated_res.status_code == 200
    rotated = rotated_res.json()
    new_refresh = str(rotated["refresh_token"])
    assert new_refresh != old_refresh

    # Cố tình dùng lại thẻ cũ -> bị từ chối 401 VÀ thu hồi cả thẻ mới vừa cấp
    reused_res = await api_client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert reused_res.status_code == 401
    assert reused_res.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"

    compromised_new_res = await api_client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert compromised_new_res.status_code == 401

    # Đăng nhập lại và kiểm tra đăng xuất
    fresh = await _login_and_get_tokens(api_client, "employee@vadiras.local", password)
    logout_res = await api_client.post("/api/v1/auth/logout", json={"refresh_token": fresh["refresh_token"]})
    assert logout_res.status_code == 204

    after_logout = await api_client.post("/api/v1/auth/refresh", json={"refresh_token": fresh["refresh_token"]})
    assert after_logout.status_code == 401


@pytest.mark.asyncio
async def test_rbac_customer_isolation_and_organization_scoping(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kiểm tra phân quyền RBAC, chặn khách hàng xem dữ liệu nội bộ và cô lập tuyệt đối giữa 2 tổ chức."""
    password = str(seeded_env["password"])
    org_a_id = str(seeded_env["org_a_id"])
    org_b_id = str(seeded_env["org_b_id"])

    admin_a_tokens = await _login_and_get_tokens(api_client, "admin@vadiras.local", password)
    emp_a_tokens = await _login_and_get_tokens(api_client, "employee@vadiras.local", password)
    cust_a_tokens = await _login_and_get_tokens(api_client, "customer@client.local", password)
    admin_b_tokens = await _login_and_get_tokens(api_client, "admin@other.local", password)

    # 1. Admin tổ chức A chỉ thấy 6 phòng ban và 5 thành viên thuộc tổ chức A (không thấy dữ liệu tổ chức B)
    depts_a_res = await api_client.get(
        "/api/v1/departments",
        headers={"Authorization": f"Bearer {admin_a_tokens['access_token']}"},
    )
    assert depts_a_res.status_code == 200
    depts_a_items = depts_a_res.json()["items"]
    assert len(depts_a_items) == 6
    assert all(item["organization_id"] == org_a_id for item in depts_a_items)

    users_a_res = await api_client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_a_tokens['access_token']}"},
    )
    assert users_a_res.status_code == 200
    users_a_items = users_a_res.json()["items"]
    assert len(users_a_items) == 5
    assert all(item["organization_id"] == org_a_id for item in users_a_items)
    assert all(item["email"] != "admin@other.local" for item in users_a_items)

    # 2. Admin tổ chức B chỉ thấy dữ liệu của tổ chức B
    users_b_res = await api_client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_b_tokens['access_token']}"},
    )
    assert users_b_res.status_code == 200
    users_b_items = users_b_res.json()["items"]
    assert len(users_b_items) == 1
    assert users_b_items[0]["organization_id"] == org_b_id
    assert users_b_items[0]["email"] == "admin@other.local"

    # 3. Nhân viên thường không có quyền users:read -> bị chặn 403 khi xem danh sách thành viên
    emp_users_res = await api_client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {emp_a_tokens['access_token']}"},
    )
    assert emp_users_res.status_code == 403
    assert emp_users_res.json()["error"]["code"] == "PERMISSION_DENIED"

    # 4. Khách hàng (CUSTOMER_CONTACT) bị chặn xem cả phòng ban lẫn danh sách thành viên nội bộ
    cust_depts_res = await api_client.get(
        "/api/v1/departments",
        headers={"Authorization": f"Bearer {cust_a_tokens['access_token']}"},
    )
    assert cust_depts_res.status_code == 403
    assert cust_depts_res.json()["error"]["code"] == "INTERNAL_ONLY_RESOURCE"

    cust_users_res = await api_client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {cust_a_tokens['access_token']}"},
    )
    assert cust_users_res.status_code == 403

    # 5. Kiểm tra giới hạn phân trang page_size tối đa 100 -> trả về khuôn mẫu lỗi 422 chuẩn
    invalid_page_res = await api_client.get(
        "/api/v1/users?page_size=500",
        headers={"Authorization": f"Bearer {admin_a_tokens['access_token']}"},
    )
    assert invalid_page_res.status_code == 422
    assert invalid_page_res.json()["error"]["code"] == "VALIDATION_ERROR"
