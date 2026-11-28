"""Kiểm thử đơn vị cho `MockGitHubConnector`, `GitHubAppConnector` (JWT RS256 + Mock HTTP) và `app.ticket_connector`."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.modules.connectors.providers.base import (
    ConnectorExecutionContext,
    ConnectorPermanentError,
    ConnectorTransientError,
)
from app.modules.connectors.providers.github_app import GitHubAppConnector
from app.modules.connectors.providers.mock_github import MockGitHubConnector
from app.adapters.schemas import ProposedAction
from app.adapters.ticket_connector import create_ticket


def _generate_ephemeral_rsa_pem() -> tuple[str, str]:
    """Sinh cặp khóa RSA tạm thời trong RAM phục vụ kiểm thử chữ ký GitHub App (không lưu đĩa)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem


@pytest.mark.asyncio
async def test_mock_github_connector_lifecycle_errors_and_verification() -> None:
    """Kiểm tra 5 hành động giả lập, chặn kho ngoài phạm vi, lỗi tạm thời/vĩnh viễn và đối chiếu ngược."""
    mock = MockGitHubConnector(
        allowed_repos=["Duckyeeen/VADIRAS-FLOW"],
        fail_transient_times=1,
    )
    ctx = ConnectorExecutionContext(
        organization_id="org-1",
        repository="Duckyeeen/VADIRAS-FLOW",
        idempotency_key="idem-mock-001",
    )

    # Lần 1 gặp lỗi mạng tạm thời -> nâng ConnectorTransientError
    with pytest.raises(ConnectorTransientError):
        await mock.execute_action("create_issue", {"title": "Lỗi thử nghiệm"}, ctx)

    # Lần 2 thành công và lần 3 cùng idempotency_key trả về đúng số Issue cũ
    created = await mock.execute_action(
        "create_issue",
        {"title": "Sự cố kết nối", "body": "Chi tiết", "labels": ["incident"]},
        ctx,
    )
    assert created.external_number is not None
    replayed = await mock.execute_action(
        "create_issue",
        {"title": "Sự cố kết nối", "body": "Chi tiết"},
        ctx,
    )
    assert replayed.external_id == created.external_id

    # Cập nhật, bình luận và gán người phụ trách
    issue_num = created.external_number
    await mock.execute_action(
        "comment_issue",
        {"issue_number": issue_num, "body": "Đang xử lý sự cố."},
        ConnectorExecutionContext(organization_id="org-1", repository="Duckyeeen/VADIRAS-FLOW", idempotency_key="idem-cmt-1"),
    )
    await mock.execute_action(
        "assign_issue",
        {"issue_number": issue_num, "assignees": ["devops-lead"]},
        ConnectorExecutionContext(organization_id="org-1", repository="Duckyeeen/VADIRAS-FLOW", idempotency_key="idem-asg-1"),
    )
    await mock.execute_action(
        "update_issue",
        {"issue_number": issue_num, "state": "closed", "labels": ["incident", "resolved"]},
        ConnectorExecutionContext(organization_id="org-1", repository="Duckyeeen/VADIRAS-FLOW", idempotency_key="idem-upd-1"),
    )

    # Đối chiếu ngược khớp hoàn toàn và phát hiện thiếu khớp
    ok_ev = await mock.verify_result(
        "update_issue",
        {"state": "closed", "labels": ["resolved"], "assignees": ["devops-lead"]},
        {"repository": "Duckyeeen/VADIRAS-FLOW", "external_number": issue_num},
    )
    assert ok_ev.matched is True
    assert ok_ev.outcome == "VERIFIED"

    partial_ev = await mock.verify_result(
        "update_issue",
        {"state": "open"},
        {"repository": "Duckyeeen/VADIRAS-FLOW", "external_number": issue_num},
    )
    assert partial_ev.matched is False
    assert partial_ev.outcome == "PARTIALLY_VERIFIED"

    # Chặn kho mã ngoài danh sách cho phép
    with pytest.raises(ConnectorPermanentError) as exc_repo:
        await mock.execute_action(
            "create_issue",
            {"title": "Lậu"},
            ConnectorExecutionContext(organization_id="org-1", repository="attacker/secret-repo", idempotency_key="idem-bad"),
        )
    assert exc_repo.value.code == "REPO_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_github_app_connector_jwt_token_cache_and_http_error_classification() -> None:
    """Kiểm tra ký JWT RS256, lưu đệm thẻ cài đặt trên RAM và phân loại lỗi HTTP của GitHub App."""
    priv_pem, pub_pem = _generate_ephemeral_rsa_pem()
    calls: list[tuple[str, str]] = []
    mode = {"behavior": "ok"}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/app/installations/999/access_tokens":
            # Xác minh App JWT ký đúng bằng khóa RSA vừa sinh
            auth = request.headers.get("Authorization", "")
            assert auth.startswith("Bearer ")
            decoded = jwt.decode(auth.removeprefix("Bearer "), pub_pem, algorithms=["RS256"])
            assert decoded["iss"] == "12345"
            exp = (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat().replace("+00:00", "Z")
            return httpx.Response(201, json={"token": "ghs_ephemeral_ram_only_token", "expires_at": exp})

        if mode["behavior"] == "transient":
            return httpx.Response(503, json={"message": "Service Unavailable"})
        if mode["behavior"] == "forbidden":
            return httpx.Response(403, json={"message": "Forbidden"})

        if request.method == "POST" and request.url.path == "/repos/Duckyeeen/VADIRAS-FLOW/issues":
            payload = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                201,
                json={
                    "number": 77,
                    "title": payload["title"],
                    "state": "open",
                    "html_url": "https://github.com/Duckyeeen/VADIRAS-FLOW/issues/77",
                },
            )
        if request.method == "GET" and request.url.path == "/repos/Duckyeeen/VADIRAS-FLOW/issues/77":
            return httpx.Response(
                200,
                json={
                    "number": 77,
                    "title": "Issue qua GitHub App",
                    "state": "open",
                    "labels": [{"name": "change-request"}],
                    "assignees": [],
                    "comments": 0,
                    "html_url": "https://github.com/Duckyeeen/VADIRAS-FLOW/issues/77",
                },
            )
        return httpx.Response(404, json={"message": "Not Found"})

    gh = GitHubAppConnector(
        app_id="12345",
        installation_id="999",
        private_key_pem=priv_pem,
        allowed_repos=["Duckyeeen/VADIRAS-FLOW"],
        http_transport=httpx.MockTransport(handler),
    )

    ctx = ConnectorExecutionContext(
        organization_id="org-a",
        repository="Duckyeeen/VADIRAS-FLOW",
        idempotency_key="idem-gh-app-1",
    )
    created = await gh.execute_action(
        "create_issue",
        {"title": "Issue qua GitHub App", "labels": ["change-request"]},
        ctx,
    )
    assert created.external_id == "Duckyeeen/VADIRAS-FLOW#77"

    snap = await gh.get_resource(repository="Duckyeeen/VADIRAS-FLOW", resource_number=77)
    assert snap.title == "Issue qua GitHub App"
    assert snap.labels == ["change-request"]

    # Endpoint đổi thẻ cài đặt chỉ bị gọi đúng 1 lần nhờ bộ đệm trên RAM
    token_calls = [c for c in calls if c[1] == "/app/installations/999/access_tokens"]
    assert len(token_calls) == 1

    # Kiểm tra phân loại lỗi 503 -> Transient vs 403 -> Permanent
    mode["behavior"] = "transient"
    with pytest.raises(ConnectorTransientError):
        await gh.get_resource(repository="Duckyeeen/VADIRAS-FLOW", resource_number=77)

    mode["behavior"] = "forbidden"
    with pytest.raises(ConnectorPermanentError):
        await gh.get_resource(repository="Duckyeeen/VADIRAS-FLOW", resource_number=77)


def test_legacy_ticket_connector_creates_ticket_cleanly() -> None:
    """Xác nhận hàm tương thích `app.ticket_connector.create_ticket` không còn báo `NotImplementedError`."""
    refs = create_ticket(
        ProposedAction(
            action_type="CREATE_TICKET",
            target_system="github",
            ticket_title="Phiếu hỗ trợ tương thích ngược",
            labels=["support"],
            message_draft="Nội dung phiếu mẫu.",
        )
    )
    assert refs.ticket_id is not None and "#" in refs.ticket_id
    assert refs.ticket_url is not None and refs.ticket_url.startswith("https://github.com/")
