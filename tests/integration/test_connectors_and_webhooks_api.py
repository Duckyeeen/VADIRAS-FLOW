"""Kiểm thử tích hợp API bộ kết nối, chống trùng thao tác ngoài, chữ ký webhook HMAC và quét dự phòng."""

from __future__ import annotations

import hashlib
import hmac
import json
from uuid import uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.connectors.idempotency import ConnectorOperationExecutor
from app.modules.connectors.providers.mock_github import MockGitHubConnector
from app.modules.connectors.models import ConnectorOperationRecord, WebhookInbox


async def _login_headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _sign_github_payload(raw_body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_connector_installation_status_and_tenant_isolation(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Đăng ký cài đặt GitHub, chặn phạm vi `*`, xem trạng thái và cô lập theo tổ chức/khách hàng."""
    password = str(seeded_env["password"])
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)
    cust_headers = await _login_headers(api_client, "customer@client.local", password)
    org_b_headers = await _login_headers(api_client, "admin@other.local", password)

    # Khách hàng không được xem danh sách hay cài đặt bộ kết nối
    assert (await api_client.get("/api/v1/connectors", headers=cust_headers)).status_code == 403
    assert (await api_client.get("/api/v1/connectors/github/status", headers=cust_headers)).status_code == 403

    # Từ chối ký tự đại diện `*` trong danh sách kho
    bad_inst = await api_client.post(
        "/api/v1/connectors/github/installations",
        headers=mgr_headers,
        json={
            "installation_external_id": "inst-wild",
            "allowed_repos": ["Duckyeeen/*"],
        },
    )
    assert bad_inst.status_code == 422
    assert bad_inst.json()["error"]["code"] == "INVALID_REPOSITORY_SCOPE"

    # Đăng ký cài đặt hợp lệ cho Tổ chức A
    ok_inst = await api_client.post(
        "/api/v1/connectors/github/installations",
        headers=mgr_headers,
        json={
            "installation_external_id": "inst-demo-001",
            "account_login": "Duckyeeen",
            "app_id": "app-demo-01",
            "allowed_repos": ["Duckyeeen/VADIRAS-FLOW"],
        },
    )
    assert ok_inst.status_code == 201, ok_inst.text
    body = ok_inst.json()
    assert body["permissions"] == {"metadata": "read", "issues": "write"}
    assert body["resource_scopes"][0]["resource_identifier"] == "Duckyeeen/VADIRAS-FLOW"

    # Tổ chức B xem trạng thái không thấy bản cài đặt của Tổ chức A
    status_b = await api_client.get("/api/v1/connectors/github/status", headers=org_b_headers)
    assert status_b.status_code == 200
    assert status_b.json()["installations"] == []

    list_a = await api_client.get("/api/v1/connectors", headers=mgr_headers)
    assert list_a.status_code == 200
    assert list_a.json()[0]["installation_count"] == 1


@pytest.mark.asyncio
async def test_idempotent_operation_webhook_hmac_dedup_and_reconciler(
    api_client: AsyncClient,
    seeded_env: dict[str, object],
) -> None:
    """Thử lại không tạo 2 Issue trùng; Webhook xác thực chữ ký thô + chống nhận trùng; đối soát cập nhật CSDL."""
    password = str(seeded_env["password"])
    org_a_id = str(seeded_env["org_a_id"])
    session_factory: async_sessionmaker[AsyncSession] = seeded_env["session_factory"]  # type: ignore[assignment]
    settings = seeded_env["settings"]
    app = seeded_env["app"]
    mgr_headers = await _login_headers(api_client, "manager@vadiras.local", password)

    # Đăng ký cài đặt trước để liên kết webhook vào đúng tổ chức A
    reg_res = await api_client.post(
        "/api/v1/connectors/github/installations",
        headers=mgr_headers,
        json={
            "installation_external_id": "778899",
            "account_login": "Duckyeeen",
            "allowed_repos": ["Duckyeeen/VADIRAS-FLOW"],
        },
    )
    assert reg_res.status_code == 201

    # Chạy thao tác tạo Issue qua ConnectorOperationExecutor 2 lần liên tiếp cùng một khóa chống trùng lặp
    mock_conn: MockGitHubConnector = app.state.github_connector  # type: ignore[attr-defined]
    executor = ConnectorOperationExecutor(mock_conn)
    async with session_factory() as session:
        first_out = await executor.execute_with_idempotency(
            session,
            organization_id=org_a_id,
            action="create_issue",
            repository="Duckyeeen/VADIRAS-FLOW",
            payload={"title": "Sự cố cổng thanh toán", "labels": ["incident"]},
            idempotency_key="op-idem-incident-001",
            node_id="n_create_issue",
        )
        second_out = await executor.execute_with_idempotency(
            session,
            organization_id=org_a_id,
            action="create_issue",
            repository="Duckyeeen/VADIRAS-FLOW",
            payload={"title": "Sự cố cổng thanh toán", "labels": ["incident"]},
            idempotency_key="op-idem-incident-001",
            node_id="n_create_issue",
        )
        all_ops = (
            await session.execute(
                sa.select(ConnectorOperationRecord).where(ConnectorOperationRecord.organization_id == org_a_id)
            )
        ).scalars().all()

    assert first_out.replayed is False
    assert second_out.replayed is True
    assert first_out.result.external_id == second_out.result.external_id
    assert len(all_ops) == 1
    issue_num = first_out.result.external_number
    assert issue_num is not None

    # 1) Webhook thiếu X-GitHub-Delivery -> 422
    secret = settings.github_webhook_secret  # type: ignore[attr-defined]
    payload_bytes = json.dumps(
        {
            "action": "labeled",
            "installation": {"id": 778899},
            "repository": {"full_name": "Duckyeeen/VADIRAS-FLOW"},
            "issue": {"number": issue_num, "state": "open", "labels": [{"name": "incident"}, {"name": "triaged"}]},
        }
    ).encode("utf-8")
    valid_sig = _sign_github_payload(payload_bytes, secret)

    no_delivery = await api_client.post(
        "/api/v1/webhooks/github",
        headers={"X-Hub-Signature-256": valid_sig, "X-GitHub-Event": "issues"},
        content=payload_bytes,
    )
    assert no_delivery.status_code == 422

    # 2) Webhook sai chữ ký -> 401
    bad_sig_res = await api_client.post(
        "/api/v1/webhooks/github",
        headers={
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
            "X-GitHub-Delivery": "deliv-bad-1",
            "X-GitHub-Event": "issues",
        },
        content=payload_bytes,
    )
    assert bad_sig_res.status_code == 401
    assert bad_sig_res.json()["error"]["code"] == "INVALID_WEBHOOK_SIGNATURE"

    # 3) Webhook hợp lệ -> PROCESSED; gửi trùng cùng X-GitHub-Delivery -> duplicate=True
    delivery_id = f"deliv-{uuid4().hex[:8]}"
    ok_wh = await api_client.post(
        "/api/v1/webhooks/github",
        headers={
            "X-Hub-Signature-256": valid_sig,
            "X-GitHub-Delivery": delivery_id,
            "X-GitHub-Event": "issues",
        },
        content=payload_bytes,
    )
    assert ok_wh.status_code == 202, ok_wh.text
    assert ok_wh.json()["duplicate"] is False
    assert ok_wh.json()["status"] == "PROCESSED"

    dup_wh = await api_client.post(
        "/api/v1/webhooks/github",
        headers={
            "X-Hub-Signature-256": valid_sig,
            "X-GitHub-Delivery": delivery_id,
            "X-GitHub-Event": "issues",
        },
        content=payload_bytes,
    )
    assert dup_wh.status_code == 202
    assert dup_wh.json()["duplicate"] is True

    # 4) Webhook hợp lệ chữ ký nhưng từ kho ngoài phạm vi cho phép -> IGNORED
    untrusted_bytes = json.dumps(
        {
            "action": "opened",
            "installation": {"id": 778899},
            "repository": {"full_name": "other/untrusted-repo"},
            "issue": {"number": 999, "state": "open", "labels": []},
        }
    ).encode("utf-8")
    ignored_wh = await api_client.post(
        "/api/v1/webhooks/github",
        headers={
            "X-Hub-Signature-256": _sign_github_payload(untrusted_bytes, secret),
            "X-GitHub-Delivery": f"deliv-untrusted-{uuid4().hex[:6]}",
            "X-GitHub-Event": "issues",
        },
        content=untrusted_bytes,
    )
    assert ignored_wh.status_code == 202
    assert ignored_wh.json()["status"] == "IGNORED"

    # Đảm bảo chỉ có đúng 1 bản ghi WebhookInbox cho delivery_id đã gửi lặp
    async with session_factory() as session:
        wh_rows = (
            await session.execute(sa.select(WebhookInbox).where(WebhookInbox.delivery_id == delivery_id))
        ).scalars().all()
        assert len(wh_rows) == 1

    # 5) Cập nhật trạng thái Issue trực tiếp trên bộ giả lập rồi chạy /reconcile -> phát hiện & cập nhật
    from app.modules.connectors.providers.base import ConnectorExecutionContext

    await mock_conn.execute_action(
        "update_issue",
        {"issue_number": issue_num, "state": "closed", "labels": ["incident", "resolved"]},
        ConnectorExecutionContext(
            organization_id=org_a_id,
            repository="Duckyeeen/VADIRAS-FLOW",
            idempotency_key="direct-close-for-reconcile",
        ),
    )

    rec_res = await api_client.post("/api/v1/connectors/github/reconcile", headers=mgr_headers)
    assert rec_res.status_code == 200, rec_res.text
    rec_body = rec_res.json()
    assert rec_body["scanned_installations"] == 1
    assert rec_body["checked_operations"] == 1
    assert rec_body["updated_operations"] == 1
    assert rec_body["issues_seen"] >= 1
