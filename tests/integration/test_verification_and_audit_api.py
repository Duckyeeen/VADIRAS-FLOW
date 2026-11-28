"""Kiểm thử tích hợp cho API `/verification`, `/evidence`, `/audit-logs` và lọc bằng chứng theo quyền."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.connectors.providers.base import ConnectorExecutionContext
from app.modules.connectors.idempotency import ConnectorOperationExecutor
from app.modules.connectors.providers.mock_github import MockGitHubConnector
from app.modules.verification.audit import record_audit_log
from app.modules.verification.engine import VerificationEngine
from app.modules.verification.models import VerificationOutcome


async def _login_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.asyncio
async def test_verification_customer_visibility_and_audit_log_scoping(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Khách hàng chỉ thấy bằng chứng `CUSTOMER_VISIBLE`; nhật ký kiểm toán tách biệt chặt theo tổ chức."""
    password = str(seeded_env["password"])
    org_a_id = str(seeded_env["org_a_id"])
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    app = seeded_env["app"]

    cust_headers = await _login_headers(api_client, "customer@client.local", password)
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)
    org_b_headers = await _login_headers(api_client, "admin@other.local", password)

    # Khách hàng gửi 1 yêu cầu
    req_res = await api_client.post(
        "/api/v1/requests",
        headers=cust_headers,
        json={
            "title": "Lỗi đăng nhập trang quản trị",
            "description": "Gặp mã lỗi 500 khi gửi biểu mẫu.",
            "request_type": "INCIDENT",
        },
    )
    assert req_res.status_code == 201
    request_id = req_res.json()["id"]

    # Tạo 1 Issue giả lập + chạy VerificationEngine với 2 nguồn: github_issue_readback (CUSTOMER_VISIBLE) và approval_record (INTERNAL_ONLY)
    mock_conn: MockGitHubConnector = app.state.github_connector  # type: ignore[attr-defined]
    executor = ConnectorOperationExecutor(mock_conn)
    async with session_factory() as session:
        op_out = await executor.execute_with_idempotency(
            session,
            organization_id=org_a_id,
            action="create_issue",
            repository="Duckyeeen/VADIRAS-FLOW",
            payload={"title": "Issue từ test xác minh", "labels": ["incident"]},
            idempotency_key="idem-ver-api-001",
            request_id=request_id,
        )
        ver_run = await VerificationEngine().run_verification(
            session,
            organization_id=org_a_id,
            request_id=request_id,
            postconditions=["issue_exists_in_allowlisted_repo"],
            evidence_sources=["github_issue_readback", "approval_record"],
            connector=mock_conn,
            external_id_hint=op_out.result.external_id,
        )
        # Ghi thêm 1 bản ghi kiểm toán chứa khóa nhạy cảm để kiểm tra cơ chế lọc sạch
        await record_audit_log(
            session,
            organization_id=org_a_id,
            actor_type="SYSTEM",
            actor_id="test_suite",
            action="manual:check",
            resource=f"request:{request_id}",
            outcome="OK",
            request_id=request_id,
            safe_metadata={"secret_token": "should_be_masked", "reasoning_trace": "must_be_dropped"},
            commit=True,
        )

    assert ver_run.outcome == VerificationOutcome.VERIFIED.value

    # Khách hàng xem kết quả xác minh của chính mình -> chỉ nhận bằng chứng CUSTOMER_VISIBLE
    cust_ver = await api_client.get(f"/api/v1/requests/{request_id}/verification", headers=cust_headers)
    assert cust_ver.status_code == 200, cust_ver.text
    cust_body = cust_ver.json()
    assert cust_body["business_outcome"] == "VERIFIED"
    assert cust_body["request_status"] == "RESOLVED"
    cust_evs = cust_body["verification_runs"][0]["evidences"]
    assert len(cust_evs) == 1
    assert cust_evs[0]["access_classification"] == "CUSTOMER_VISIBLE"

    # Quản lý xem đủ cả 2 bằng chứng (gồm cả INTERNAL_ONLY)
    mgr_ver = await api_client.get(f"/api/v1/requests/{request_id}/verification", headers=mgr_headers)
    assert mgr_ver.status_code == 200
    assert len(mgr_ver.json()["verification_runs"][0]["evidences"]) == 2

    # Khách hàng không được xem /audit-logs (403); Tổ chức B không thấy audit log của Tổ chức A
    assert (await api_client.get("/api/v1/audit-logs", headers=cust_headers)).status_code == 403
    audits_b = await api_client.get("/api/v1/audit-logs", headers=org_b_headers)
    assert audits_b.status_code == 200
    assert audits_b.json()["items"] == []

    audits_a = await api_client.get(
        f"/api/v1/audit-logs?request_id={request_id}", headers=mgr_headers
    )
    assert audits_a.status_code == 200
    items_a = audits_a.json()["items"]
    assert len(items_a) >= 2
    manual_entry = next(x for x in items_a if x["action"] == "manual:check")
    assert manual_entry["safe_metadata"]["secret_token"] == "[DA_AN]"
    assert "reasoning_trace" not in manual_entry["safe_metadata"]
