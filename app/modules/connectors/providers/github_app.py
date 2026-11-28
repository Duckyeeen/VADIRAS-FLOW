"""Bộ kết nối GitHub App chính thức dùng thẻ cài đặt ngắn hạn chỉ giữ trên bộ nhớ RAM."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import jwt

from .base import (
    GITHUB_ACTION_SCHEMAS,
    BaseConnector,
    ConnectorActionResult,
    ConnectorActionSchema,
    ConnectorExecutionContext,
    ConnectorPermanentError,
    ConnectorResourceSnapshot,
    ConnectorTransientError,
    ConnectorVerificationEvidence,
)


def _parse_gh_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


class GitHubAppConnector(BaseConnector):
    """Giao tiếp với GitHub REST API bằng khóa riêng RSA và thẻ cài đặt ngắn hạn theo từng kho."""

    connector_type = "github"

    def __init__(
        self,
        *,
        app_id: str,
        installation_id: str,
        private_key_pem: str | None = None,
        private_key_path: str | None = None,
        allowed_repos: list[str] | None = None,
        api_base_url: str = "https://api.github.com",
        timeout_seconds: float = 15.0,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._app_id = app_id.strip()
        self._installation_id = installation_id.strip()
        self._private_key_pem = private_key_pem
        self._private_key_path = private_key_path
        self._allowed_repos: set[str] = {r.strip() for r in (allowed_repos or []) if r.strip()}
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._http_transport = http_transport

        # Thẻ cài đặt chỉ lưu tạm trong bộ nhớ RAM và tự làm mới trước khi hết hạn
        self._cached_token: str | None = None
        self._token_expires_at: datetime | None = None

    def _load_private_key(self) -> str:
        if self._private_key_pem:
            return self._private_key_pem
        if self._private_key_path:
            path = Path(self._private_key_path)
            if path.is_file():
                return path.read_text(encoding="utf-8")
        raise ConnectorPermanentError(
            "Chưa cấu hình khóa riêng RSA của GitHub App.",
            code="GITHUB_PRIVATE_KEY_MISSING",
        )

    def _assert_repo_allowed(self, repository: str) -> str:
        repo = repository.strip()
        if not repo or "*" in repo or repo not in self._allowed_repos:
            raise ConnectorPermanentError(
                f"Kho mã `{repository}` không nằm trong danh sách được phép của GitHub App.",
                code="REPO_NOT_ALLOWED",
            )
        return repo

    def get_allowed_repos(self) -> list[str]:
        """Trả danh sách các kho mã được phép thao tác."""
        return sorted(self._allowed_repos)

    def generate_app_jwt(self) -> str:
        """Ký thẻ JWT ngắn hạn (tối đa 9 phút) đại diện cho chính GitHub App để xin thẻ cài đặt."""
        if not self._app_id:
            raise ConnectorPermanentError("Thiếu `GITHUB_APP_ID` khi khởi tạo GitHub App.", code="GITHUB_APP_ID_MISSING")
        now = datetime.now(timezone.utc)
        payload = {
            "iat": int((now - timedelta(seconds=60)).timestamp()),
            "exp": int((now + timedelta(seconds=540)).timestamp()),
            "iss": self._app_id,
        }
        return jwt.encode(payload, self._load_private_key(), algorithm="RS256")

    def _build_client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "base_url": self._api_base_url,
            "timeout": self._timeout_seconds,
        }
        if self._http_transport is not None:
            kwargs["transport"] = self._http_transport
        return httpx.AsyncClient(**kwargs)

    async def _get_installation_token(self) -> str:
        """Lấy hoặc làm mới thẻ truy cập ngắn hạn của cài đặt GitHub App (chỉ giữ trên RAM)."""
        now = datetime.now(timezone.utc)
        if (
            self._cached_token is not None
            and self._token_expires_at is not None
            and self._token_expires_at - timedelta(seconds=60) > now
        ):
            return self._cached_token

        if not self._installation_id:
            raise ConnectorPermanentError(
                "Thiếu `GITHUB_INSTALLATION_ID` để đổi thẻ truy cập.",
                code="GITHUB_INSTALLATION_ID_MISSING",
            )

        app_jwt = self.generate_app_jwt()
        headers = {
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with self._build_client() as client:
            try:
                resp = await client.post(
                    f"/app/installations/{self._installation_id}/access_tokens",
                    headers=headers,
                )
            except httpx.RequestError as exc:
                raise ConnectorTransientError(
                    f"Lỗi kết nối tạm thời khi xin thẻ cài đặt GitHub App: {exc}",
                    code="GITHUB_NETWORK_ERROR",
                ) from exc

        if resp.status_code in {429, 500, 502, 503, 504}:
            raise ConnectorTransientError(
                f"GitHub API tạm thời không phản hồi ({resp.status_code}) khi đổi thẻ cài đặt.",
                code="GITHUB_UPSTREAM_TRANSIENT",
            )
        if resp.status_code >= 400:
            raise ConnectorPermanentError(
                f"Không thể lấy thẻ cài đặt GitHub App (HTTP {resp.status_code}).",
                code="GITHUB_AUTH_FAILED",
            )

        body = resp.json()
        token = str(body.get("token") or "")
        if not token:
            raise ConnectorPermanentError("Phản hồi đổi thẻ GitHub App không chứa token hợp lệ.", code="GITHUB_AUTH_FAILED")

        expires_at = _parse_gh_datetime(body.get("expires_at")) or (now + timedelta(minutes=50))
        self._cached_token = token
        self._token_expires_at = expires_at
        return token

    async def _request_github(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        token = await self._get_installation_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with self._build_client() as client:
            try:
                resp = await client.request(
                    method,
                    path,
                    headers=headers,
                    json=json_body,
                    params=params,
                )
            except httpx.RequestError as exc:
                raise ConnectorTransientError(
                    f"Mất kết nối tạm thời tới GitHub API: {exc}",
                    code="GITHUB_NETWORK_ERROR",
                ) from exc

        if resp.status_code == 401:
            # Xóa bộ đệm thẻ để lần gọi hợp lệ sau có thể xin lại thẻ mới nếu vừa hết hạn
            self._cached_token = None
            self._token_expires_at = None
            raise ConnectorPermanentError("Thẻ truy cập GitHub App không được chấp nhận (HTTP 401).", code="GITHUB_UNAUTHORIZED")
        if resp.status_code in {429, 500, 502, 503, 504}:
            raise ConnectorTransientError(
                f"GitHub API gặp sự cố tạm thời (HTTP {resp.status_code}).",
                code="GITHUB_UPSTREAM_TRANSIENT",
            )
        if resp.status_code >= 400:
            raise ConnectorPermanentError(
                f"GitHub API từ chối yêu cầu (HTTP {resp.status_code}).",
                code=f"GITHUB_HTTP_{resp.status_code}",
            )
        return resp.json()

    def get_capabilities(self) -> list[ConnectorActionSchema]:
        """Trả danh sách 5 hành động GitHub được hỗ trợ."""
        return list(GITHUB_ACTION_SCHEMAS.values())

    async def validate_connection(self) -> bool:
        """Xác thực khả năng sinh App JWT và lấy thẻ cài đặt thành công."""
        try:
            await self._get_installation_token()
            return True
        except ConnectorErrorLike:  # pragma: no cover
            return False

    async def health_check(self) -> dict[str, Any]:
        """Kiểm tra tình trạng cấu hình và thẻ truy cập GitHub App."""
        try:
            await self._get_installation_token()
            status_val = "up"
            detail = "Kết nối GitHub App sẵn sàng."
        except Exception as exc:
            status_val = "degraded"
            detail = str(exc)
        return {
            "connector": self.connector_type,
            "mode": "github_app",
            "status": status_val,
            "detail": detail,
            "allowed_repos": self.get_allowed_repos(),
        }

    def _to_snapshot(self, repository: str, data: dict[str, Any]) -> ConnectorResourceSnapshot:
        num = int(data["number"])
        labels = [str(lbl["name"] if isinstance(lbl, dict) else lbl) for lbl in (data.get("labels") or [])]
        assignees = [str(u["login"] if isinstance(u, dict) else u) for u in (data.get("assignees") or [])]
        return ConnectorResourceSnapshot(
            repository=repository,
            external_id=f"{repository}#{num}",
            external_number=num,
            external_url=str(data.get("html_url") or f"https://github.com/{repository}/issues/{num}"),
            title=str(data.get("title") or ""),
            state=str(data.get("state") or "open"),
            labels=labels,
            assignees=assignees,
            comments_count=int(data.get("comments") or 0),
            updated_at=_parse_gh_datetime(data.get("updated_at")),
        )

    async def get_resource(self, *, repository: str, resource_number: int) -> ConnectorResourceSnapshot:
        """Đọc ngược thông tin một GitHub Issue trực tiếp từ GitHub REST API."""
        repo = self._assert_repo_allowed(repository)
        data = await self._request_github("GET", f"/repos/{repo}/issues/{resource_number}")
        return self._to_snapshot(repo, data)

    async def list_issues(
        self,
        *,
        repository: str,
        since: datetime | None = None,
    ) -> list[ConnectorResourceSnapshot]:
        """Lấy danh sách Issue gần đây từ kho mã để quét đồng bộ dự phòng."""
        repo = self._assert_repo_allowed(repository)
        params: dict[str, Any] = {"state": "all", "per_page": 30, "sort": "updated", "direction": "desc"}
        if since is not None:
            params["since"] = since.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        items = await self._request_github("GET", f"/repos/{repo}/issues", params=params)
        return [self._to_snapshot(repo, item) for item in items if isinstance(item, dict) and "pull_request" not in item]

    async def execute_action(
        self,
        action: str,
        validated_payload: dict[str, Any],
        execution_context: ConnectorExecutionContext,
    ) -> ConnectorActionResult:
        """Thực thi một trong 5 hành động cho phép tới GitHub REST API."""
        normalized_action = action.strip().lower()
        if normalized_action not in GITHUB_ACTION_SCHEMAS:
            raise ConnectorPermanentError(
                f"Hành động `{action}` không nằm trong danh sách cho phép.",
                code="UNSUPPORTED_CONNECTOR_ACTION",
            )
        repo = self._assert_repo_allowed(execution_context.repository)

        if normalized_action == "create_issue":
            body_json = {
                "title": str(validated_payload.get("title") or "VADIRAS FLOW Issue"),
                "body": str(validated_payload.get("body") or ""),
                "labels": [str(x) for x in (validated_payload.get("labels") or [])],
                "assignees": [str(x) for x in (validated_payload.get("assignees") or [])],
            }
            data = await self._request_github("POST", f"/repos/{repo}/issues", json_body=body_json)
            num = int(data["number"])
            url = str(data.get("html_url") or f"https://github.com/{repo}/issues/{num}")
            return ConnectorActionResult(
                connector_type=self.connector_type,
                action=normalized_action,
                repository=repo,
                external_id=f"{repo}#{num}",
                external_number=num,
                external_url=url,
                status="SUCCEEDED",
                raw_summary={
                    "external_id": f"{repo}#{num}",
                    "external_number": num,
                    "external_url": url,
                    "operation_id": f"gh-create-{num}",
                    "title": data.get("title"),
                    "state": data.get("state"),
                },
            )

        if normalized_action == "update_issue":
            num = int(validated_payload["issue_number"])
            patch_body = {
                k: validated_payload[k]
                for k in ("title", "body", "state", "labels")
                if k in validated_payload and validated_payload[k] is not None
            }
            data = await self._request_github("PATCH", f"/repos/{repo}/issues/{num}", json_body=patch_body)
            url = str(data.get("html_url") or f"https://github.com/{repo}/issues/{num}")
            return ConnectorActionResult(
                connector_type=self.connector_type,
                action=normalized_action,
                repository=repo,
                external_id=f"{repo}#{num}",
                external_number=num,
                external_url=url,
                status="SUCCEEDED",
                raw_summary={
                    "external_id": f"{repo}#{num}",
                    "external_number": num,
                    "external_url": url,
                    "operation_id": f"gh-update-{num}",
                    "state": data.get("state"),
                },
            )

        if normalized_action == "comment_issue":
            num = int(validated_payload["issue_number"])
            data = await self._request_github(
                "POST",
                f"/repos/{repo}/issues/{num}/comments",
                json_body={"body": str(validated_payload.get("body") or "")},
            )
            url = str(data.get("html_url") or f"https://github.com/{repo}/issues/{num}")
            return ConnectorActionResult(
                connector_type=self.connector_type,
                action=normalized_action,
                repository=repo,
                external_id=f"{repo}#{num}",
                external_number=num,
                external_url=url,
                status="SUCCEEDED",
                raw_summary={
                    "external_id": f"{repo}#{num}",
                    "external_number": num,
                    "external_url": url,
                    "operation_id": f"gh-comment-{data.get('id')}",
                    "comment_id": data.get("id"),
                },
            )

        if normalized_action == "assign_issue":
            num = int(validated_payload["issue_number"])
            assignees = [str(x) for x in (validated_payload.get("assignees") or [])]
            data = await self._request_github(
                "POST",
                f"/repos/{repo}/issues/{num}/assignees",
                json_body={"assignees": assignees},
            )
            url = str(data.get("html_url") or f"https://github.com/{repo}/issues/{num}")
            return ConnectorActionResult(
                connector_type=self.connector_type,
                action=normalized_action,
                repository=repo,
                external_id=f"{repo}#{num}",
                external_number=num,
                external_url=url,
                status="SUCCEEDED",
                raw_summary={
                    "external_id": f"{repo}#{num}",
                    "external_number": num,
                    "external_url": url,
                    "operation_id": f"gh-assign-{num}",
                    "assignees": assignees,
                },
            )

        num = int(validated_payload["issue_number"])
        snap = await self.get_resource(repository=repo, resource_number=num)
        return ConnectorActionResult(
            connector_type=self.connector_type,
            action=normalized_action,
            repository=repo,
            external_id=snap.external_id,
            external_number=snap.external_number,
            external_url=snap.external_url,
            status="SUCCEEDED",
            raw_summary={
                "external_id": snap.external_id,
                "external_number": snap.external_number,
                "external_url": snap.external_url,
                "title": snap.title,
                "state": snap.state,
                "labels": list(snap.labels),
            },
        )

    async def verify_result(
        self,
        action: str,
        expected_state: dict[str, Any],
        evidence_context: dict[str, Any],
    ) -> ConnectorVerificationEvidence:
        """Đọc ngược GitHub Issue thực tế và đối chiếu với trạng thái kỳ vọng."""
        repo = str(evidence_context.get("repository") or "")
        resource_number = evidence_context.get("external_number")
        if not repo or resource_number is None:
            return ConnectorVerificationEvidence(
                matched=False,
                outcome="UNVERIFIED",
                reason="Thiếu thông tin kho mã hoặc số hiệu Issue để đọc ngược.",
            )
        snap = await self.get_resource(repository=repo, resource_number=int(resource_number))
        mismatches: list[str] = []
        if "state" in expected_state and expected_state["state"] != snap.state:
            mismatches.append("state")
        if "title" in expected_state and expected_state["title"] != snap.title:
            mismatches.append("title")
        if "labels" in expected_state:
            if not set(str(x) for x in expected_state["labels"]).issubset(set(snap.labels)):
                mismatches.append("labels")
        if mismatches:
            return ConnectorVerificationEvidence(
                matched=False,
                outcome="PARTIALLY_VERIFIED",
                reason=f"Các trường chưa khớp trên GitHub: {', '.join(mismatches)}.",
                snapshot=snap,
                mismatched_fields=mismatches,
            )
        return ConnectorVerificationEvidence(
            matched=True,
            outcome="VERIFIED",
            reason="Đã đối chiếu ngược thành công trên GitHub.",
            snapshot=snap,
        )


ConnectorErrorLike = (ConnectorPermanentError, ConnectorTransientError)
