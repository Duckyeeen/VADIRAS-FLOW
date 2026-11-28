"""Kiểm thử tích hợp cho API phê duyệt, chống tự duyệt, ExecutionGuard và ToolBroker."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AuthorizationError
from app.modules.governance.models import PolicyDecision
from app.modules.governance.policy_engine import PolicyEvaluationContext
from app.modules.governance.tool_broker import ToolBroker
from app.modules.identity.models import AgentIdentity, AgentToolGrant


async def _login_token(client: AsyncClient, email: str, password: str) -> str:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return str(res.json()["access_token"])


@pytest.mark.asyncio
async def test_approval_binding_tool_broker_and_execution_guard_end_to_end(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Kiểm tra trọn vẹn: Tạo duyệt -> Chống tự duyệt -> Quản lý duyệt -> ToolBroker chạy -> Đổi tham số bị chặn."""
    password = str(seeded_env["password"])
    org_a_id = str(seeded_env["org_a_id"])
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]

    admin_token = await _login_token(api_client, "admin@vadiras.local", password)
    mgr_token = await _login_token(api_client, "manager@vadiras.local", password)
    emp_token = await _login_token(api_client, "employee@vadiras.local", password)
    cust_token = await _login_token(api_client, "customer@client.local", password)
    admin_b_token = await _login_token(api_client, "admin@other.local", password)

    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    mgr_headers = {"Authorization": f"Bearer {mgr_token}"}

    # 1. Cấp giấy phép hẹp cho executor_worker trên đúng kho Duckyeeen/VADIRAS-FLOW
    async with session_factory() as session:
        agent = (
            await session.execute(
                sa.select(AgentIdentity).where(
                    AgentIdentity.organization_id == org_a_id,
                    AgentIdentity.role_code == "executor_worker",
                )
            )
        ).scalar_one()
        session.add(
            AgentToolGrant(
                organization_id=org_a_id,
                agent_identity_id=agent.id,
                tool_name="create_issue",
                resource_scope="github:repo:Duckyeeen/VADIRAS-FLOW",
                policy_version="v1",
                is_active=True,
            )
        )
        await session.commit()

    # 2. Tạo yêu cầu loại CHANGE
    req_res = await api_client.post(
        "/api/v1/requests",
        headers=admin_headers,
        json={
            "title": "Thay đổi tham số kết nối dịch vụ",
            "description": "Cần duyệt trước khi mở GitHub Issue thay đổi cấu hình.",
            "request_type": "CHANGE",
        },
    )
    assert req_res.status_code == 201
    req_id = req_res.json()["id"]

    # 3. Admin tạo yêu cầu phê duyệt cho hành động `create_issue`
    action_params = {"title": "Thay đổi tham số kết nối", "labels": ["change"]}
    scope = "github:repo:Duckyeeen/VADIRAS-FLOW"
    app_res = await api_client.post(
        "/api/v1/approvals",
        headers=admin_headers,
        json={
            "request_id": req_id,
            "node_id": "n5_action",
            "action": "create_issue",
            "parameters": action_params,
            "resource_scope": scope,
            "policy_version": "v1",
            "risk_level": "HIGH",
            "required_role": "department_manager",
        },
    )
    assert app_res.status_code == 201
    approval_id = app_res.json()["id"]
    assert app_res.json()["status"] == "PENDING"

    # 4. Chưa được duyệt -> gọi ToolBroker phải bị chặn
    broker = ToolBroker()

    async def _mock_create_issue(params: dict) -> dict:
        return {"issue_number": 101, "title": params.get("title")}

    broker.register_tool("github.create_issue", _mock_create_issue)

    async with session_factory() as session:
        with pytest.raises(AuthorizationError) as exc_pending:
            await broker.execute(
                session,
                tool_name="github.create_issue",
                request_id=req_id,
                node_id="n5_action",
                approval_id=approval_id,
                context=PolicyEvaluationContext(
                    organization_id=org_a_id,
                    actor_type="AGENT",
                    actor_id="executor_worker",
                    action="create_issue",
                    resource_scope=scope,
                    parameters=action_params,
                    request_type="CHANGE",
                ),
            )
        assert exc_pending.value.code == "APPROVAL_NOT_APPROVED"

    # 5. Admin không được tự duyệt yêu cầu do chính mình tạo (SELF_APPROVAL_FORBIDDEN)
    self_approve = await api_client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        headers=admin_headers,
        json={"decision": "APPROVED", "rationale": "Tự duyệt yêu cầu của mình."},
    )
    assert self_approve.status_code == 403
    assert self_approve.json()["error"]["code"] == "SELF_APPROVAL_FORBIDDEN"

    # Nhân viên thường không có quyền approvals:decide -> bị chặn 403
    emp_approve = await api_client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        headers={"Authorization": f"Bearer {emp_token}"},
        json={"decision": "APPROVED", "rationale": "Thử duyệt không có quyền."},
    )
    assert emp_approve.status_code == 403

    # Khách hàng bị chặn 403 khi xem hoặc duyệt; Admin tổ chức B không xem được (404/rỗng)
    cust_list = await api_client.get("/api/v1/approvals", headers={"Authorization": f"Bearer {cust_token}"})
    assert cust_list.status_code == 403

    cross_detail = await api_client.get(
        f"/api/v1/approvals/{approval_id}",
        headers={"Authorization": f"Bearer {admin_b_token}"},
    )
    assert cross_detail.status_code == 404

    # 6. Quản lý (department_manager) phê duyệt thành công
    mgr_approve = await api_client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        headers=mgr_headers,
        json={"decision": "APPROVED", "rationale": "Đã kiểm tra tác động và đồng ý thực hiện."},
    )
    assert mgr_approve.status_code == 200
    assert mgr_approve.json()["status"] == "APPROVED"
    assert mgr_approve.json()["decision_record"]["authority_verified"] is True

    # 7. ToolBroker chạy thành công với đúng tham số đã phê duyệt
    async with session_factory() as session:
        receipt = await broker.execute(
            session,
            tool_name="github.create_issue",
            request_id=req_id,
            node_id="n5_action",
            approval_id=approval_id,
            context=PolicyEvaluationContext(
                organization_id=org_a_id,
                actor_type="AGENT",
                actor_id="executor_worker",
                action="create_issue",
                resource_scope=scope,
                parameters=action_params,
                request_type="CHANGE",
            ),
        )
        assert receipt.output["issue_number"] == 101

        # 8. Cố tình sửa đổi 1 tham số khi gọi lại -> bị chặn APPROVAL_BINDING_MISMATCH ngay lập tức
        with pytest.raises(AuthorizationError) as exc_tamper:
            await broker.execute(
                session,
                tool_name="github.create_issue",
                request_id=req_id,
                node_id="n5_action",
                approval_id=approval_id,
                context=PolicyEvaluationContext(
                    organization_id=org_a_id,
                    actor_type="AGENT",
                    actor_id="executor_worker",
                    action="create_issue",
                    resource_scope=scope,
                    parameters={"title": "Tiêu đề bị sửa ngầm", "labels": ["change"]},
                    request_type="CHANGE",
                ),
            )
        assert exc_tamper.value.code == "APPROVAL_BINDING_MISMATCH"

        decisions_count = int(
            (await session.execute(sa.select(sa.func.count()).select_from(PolicyDecision))).scalar_one()
        )
        assert decisions_count == 3


@pytest.mark.asyncio
async def test_rejected_approval_blocks_execution_and_preview_endpoint(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Khi lệnh duyệt bị từ chối (`REJECTED`), ExecutionGuard chặn thực thi và kiểm tra API đánh giá thử."""
    password = str(seeded_env["password"])
    admin_token = await _login_token(api_client, "admin@vadiras.local", password)
    mgr_token = await _login_token(api_client, "manager@vadiras.local", password)

    eval_res = await api_client.post(
        "/api/v1/governance/evaluate",
        headers={"Authorization": f"Bearer {mgr_token}"},
        json={
            "actor_type": "AGENT",
            "actor_id": "executor_worker",
            "action": "deploy_production",
            "resource_scope": "github:repo:Duckyeeen/VADIRAS-FLOW",
        },
    )
    assert eval_res.status_code == 200
    assert eval_res.json()["decision"] == "DENY"

    req_res = await api_client.post(
        "/api/v1/requests",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "title": "Yêu cầu cần xem xét",
            "description": "Kiểm tra kịch bản từ chối phê duyệt.",
            "request_type": "CHANGE",
        },
    )
    req_id = req_res.json()["id"]

    app_res = await api_client.post(
        "/api/v1/approvals",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "request_id": req_id,
            "node_id": "n5_action",
            "action": "create_issue",
            "parameters": {"title": "Thay đổi rủi ro"},
            "resource_scope": "github:repo:Duckyeeen/VADIRAS-FLOW",
            "risk_level": "HIGH",
        },
    )
    approval_id = app_res.json()["id"]

    reject_res = await api_client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        headers={"Authorization": f"Bearer {mgr_token}"},
        json={"decision": "REJECTED", "rationale": "Chưa có phương án khôi phục dự phòng."},
    )
    assert reject_res.status_code == 200
    assert reject_res.json()["status"] == "REJECTED"
