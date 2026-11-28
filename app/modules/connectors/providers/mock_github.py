"""Bộ giả lập GitHub tương thích hoàn toàn phục vụ phát triển và kiểm thử không cần khóa thật."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

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


@dataclass
class _MockIssueRecord:
    """Bản ghi Issue nội bộ lưu trên bộ nhớ RAM cho môi trường giả lập."""

    repository: str
    number: int
    title: str
    body: str
    state: str
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_snapshot(self) -> ConnectorResourceSnapshot:
        """Chuyển bản ghi nội bộ sang cấu trúc ảnh chụp chuẩn."""
        return ConnectorResourceSnapshot(
            repository=self.repository,
            external_id=f"{self.repository}#{self.number}",
            external_number=self.number,
            external_url=f"https://github.com/{self.repository}/issues/{self.number}",
            title=self.title,
            state=self.state,
            labels=list(self.labels),
            assignees=list(self.assignees),
            comments_count=len(self.comments),
            updated_at=self.updated_at,
            extra={"comments": list(self.comments)},
        )


class MockGitHubConnector(BaseConnector):
    """Bộ giả lập GitHub giữ trạng thái nhất quán và hỗ trợ các kịch bản lỗi giả lập."""

    connector_type = "mock_github"

    def __init__(
        self,
        *,
        allowed_repos: list[str] | None = None,
        fail_transient_times: int = 0,
        force_permanent_error: bool = False,
        simulate_verification_mismatch: bool = False,
    ) -> None:
        self._allowed_repos: set[str] = {
            r.strip() for r in (allowed_repos or ["Duckyeeen/VADIRAS-FLOW"]) if r.strip()
        }
        self._fail_transient_remaining = max(0, fail_transient_times)
        self._force_permanent_error = force_permanent_error
        self._simulate_verification_mismatch = simulate_verification_mismatch
        self._issues_by_repo: dict[str, dict[int, _MockIssueRecord]] = {}
        self._counters: dict[str, int] = {}
        self._idempotency_cache: dict[str, ConnectorActionResult] = {}

    def _assert_repo_allowed(self, repository: str) -> str:
        repo = repository.strip()
        if not repo or "*" in repo or repo not in self._allowed_repos:
            raise ConnectorPermanentError(
                f"Kho mã `{repository}` không nằm trong danh sách kho được phép truy cập.",
                code="REPO_NOT_ALLOWED",
            )
        return repo

    def add_allowed_repo(self, repository: str) -> None:
        """Bổ sung một kho mã hợp lệ vào danh sách được phép khi đăng ký cài đặt mới."""
        cleaned = repository.strip()
        if cleaned and "*" not in cleaned:
            self._allowed_repos.add(cleaned)

    def get_allowed_repos(self) -> list[str]:
        """Trả danh sách các kho mã đang được bộ kết nối cho phép thao tác."""
        return sorted(self._allowed_repos)

    def get_capabilities(self) -> list[ConnectorActionSchema]:
        """Trả về 5 hành động GitHub chuẩn hỗ trợ trong hệ thống."""
        return list(GITHUB_ACTION_SCHEMAS.values())

    async def validate_connection(self) -> bool:
        """Kiểm tra bộ giả lập luôn sẵn sàng trừ khi đang bật chế độ lỗi vĩnh viễn."""
        return not self._force_permanent_error

    async def health_check(self) -> dict[str, Any]:
        """Báo cáo trạng thái bộ giả lập GitHub."""
        return {
            "connector": self.connector_type,
            "mode": "mock",
            "status": "up" if not self._force_permanent_error else "error",
            "allowed_repos": self.get_allowed_repos(),
        }

    async def get_resource(self, *, repository: str, resource_number: int) -> ConnectorResourceSnapshot:
        """Đọc ngược thông tin một Issue đang lưu trong kho giả lập."""
        repo = self._assert_repo_allowed(repository)
        issue = self._issues_by_repo.get(repo, {}).get(resource_number)
        if issue is None:
            raise ConnectorPermanentError(
                f"Không tìm thấy Issue #{resource_number} trong kho `{repo}`.",
                code="ISSUE_NOT_FOUND",
            )
        return issue.to_snapshot()

    async def list_issues(
        self,
        *,
        repository: str,
        since: datetime | None = None,
    ) -> list[ConnectorResourceSnapshot]:
        """Lấy danh sách các Issue trong kho giả lập để phục vụ quét đồng bộ dự phòng."""
        repo = self._assert_repo_allowed(repository)
        records = list(self._issues_by_repo.get(repo, {}).values())
        if since is not None:
            records = [r for r in records if r.updated_at >= since]
        records.sort(key=lambda item: item.number)
        return [r.to_snapshot() for r in records]

    async def execute_action(
        self,
        action: str,
        validated_payload: dict[str, Any],
        execution_context: ConnectorExecutionContext,
    ) -> ConnectorActionResult:
        """Thực thi hành động trên kho giả lập kèm chống trùng và kịch bản lỗi kiểm thử."""
        normalized_action = action.strip().lower()
        if normalized_action not in GITHUB_ACTION_SCHEMAS:
            raise ConnectorPermanentError(
                f"Hành động `{action}` không nằm trong danh mục cho phép.",
                code="UNSUPPORTED_CONNECTOR_ACTION",
            )

        repo = self._assert_repo_allowed(execution_context.repository)

        if self._force_permanent_error:
            raise ConnectorPermanentError(
                "Bộ giả lập được cấu hình mô phỏng lỗi phân quyền vĩnh viễn.",
                code="SIMULATED_PERMANENT_ERROR",
            )

        if self._fail_transient_remaining > 0:
            self._fail_transient_remaining -= 1
            raise ConnectorTransientError(
                "Bộ giả lập mô phỏng sự cố mạng tạm thời với GitHub API.",
                code="SIMULATED_TRANSIENT_ERROR",
            )

        cache_key = f"{execution_context.organization_id}:{normalized_action}:{execution_context.idempotency_key}"
        if execution_context.idempotency_key and cache_key in self._idempotency_cache:
            return self._idempotency_cache[cache_key]

        repo_issues = self._issues_by_repo.setdefault(repo, {})
        now = datetime.now(timezone.utc)

        if normalized_action == "create_issue":
            next_num = self._counters.get(repo, 100) + 1
            self._counters[repo] = next_num
            title = str(validated_payload.get("title") or f"Yêu cầu #{next_num}")
            body = str(validated_payload.get("body") or "")
            labels = [str(x) for x in (validated_payload.get("labels") or [])]
            assignees = [str(x) for x in (validated_payload.get("assignees") or [])]
            issue = _MockIssueRecord(
                repository=repo,
                number=next_num,
                title=title,
                body=body,
                state="open",
                labels=labels,
                assignees=assignees,
                updated_at=now,
            )
            repo_issues[next_num] = issue
            result = ConnectorActionResult(
                connector_type=self.connector_type,
                action=normalized_action,
                repository=repo,
                external_id=f"{repo}#{next_num}",
                external_number=next_num,
                external_url=f"https://github.com/{repo}/issues/{next_num}",
                status="SUCCEEDED",
                raw_summary={
                    "external_id": f"{repo}#{next_num}",
                    "external_number": next_num,
                    "external_url": f"https://github.com/{repo}/issues/{next_num}",
                    "operation_id": f"mock-op-{repo.replace('/', '-')}-{next_num}",
                    "title": title,
                    "state": issue.state,
                    "labels": list(labels),
                    "assignees": list(assignees),
                },
            )
        elif normalized_action == "update_issue":
            issue_num = int(validated_payload["issue_number"])
            issue = repo_issues.get(issue_num)
            if issue is None:
                raise ConnectorPermanentError(
                    f"Không tìm thấy Issue #{issue_num} trong kho `{repo}`.",
                    code="ISSUE_NOT_FOUND",
                )
            if "title" in validated_payload and validated_payload["title"] is not None:
                issue.title = str(validated_payload["title"])
            if "body" in validated_payload and validated_payload["body"] is not None:
                issue.body = str(validated_payload["body"])
            if "state" in validated_payload and validated_payload["state"] in {"open", "closed"}:
                issue.state = str(validated_payload["state"])
            if "labels" in validated_payload and validated_payload["labels"] is not None:
                issue.labels = [str(x) for x in validated_payload["labels"]]
            issue.updated_at = now
            result = ConnectorActionResult(
                connector_type=self.connector_type,
                action=normalized_action,
                repository=repo,
                external_id=f"{repo}#{issue_num}",
                external_number=issue_num,
                external_url=f"https://github.com/{repo}/issues/{issue_num}",
                status="SUCCEEDED",
                raw_summary={
                    "external_id": f"{repo}#{issue_num}",
                    "external_number": issue_num,
                    "external_url": f"https://github.com/{repo}/issues/{issue_num}",
                    "operation_id": f"mock-upd-{issue_num}",
                    "title": issue.title,
                    "state": issue.state,
                    "labels": list(issue.labels),
                },
            )
        elif normalized_action == "comment_issue":
            issue_num = int(validated_payload["issue_number"])
            issue = repo_issues.get(issue_num)
            if issue is None:
                raise ConnectorPermanentError(
                    f"Không tìm thấy Issue #{issue_num} trong kho `{repo}`.",
                    code="ISSUE_NOT_FOUND",
                )
            comment_id = len(issue.comments) + 1
            issue.comments.append(
                {
                    "id": comment_id,
                    "body": str(validated_payload.get("body") or ""),
                    "created_at": now.isoformat(),
                }
            )
            issue.updated_at = now
            result = ConnectorActionResult(
                connector_type=self.connector_type,
                action=normalized_action,
                repository=repo,
                external_id=f"{repo}#{issue_num}",
                external_number=issue_num,
                external_url=f"https://github.com/{repo}/issues/{issue_num}#issuecomment-{comment_id}",
                status="SUCCEEDED",
                raw_summary={
                    "external_id": f"{repo}#{issue_num}",
                    "external_number": issue_num,
                    "external_url": f"https://github.com/{repo}/issues/{issue_num}#issuecomment-{comment_id}",
                    "operation_id": f"mock-cmt-{issue_num}-{comment_id}",
                    "comment_id": comment_id,
                    "comments_count": len(issue.comments),
                },
            )
        elif normalized_action == "assign_issue":
            issue_num = int(validated_payload["issue_number"])
            issue = repo_issues.get(issue_num)
            if issue is None:
                raise ConnectorPermanentError(
                    f"Không tìm thấy Issue #{issue_num} trong kho `{repo}`.",
                    code="ISSUE_NOT_FOUND",
                )
            issue.assignees = [str(x) for x in (validated_payload.get("assignees") or [])]
            issue.updated_at = now
            result = ConnectorActionResult(
                connector_type=self.connector_type,
                action=normalized_action,
                repository=repo,
                external_id=f"{repo}#{issue_num}",
                external_number=issue_num,
                external_url=f"https://github.com/{repo}/issues/{issue_num}",
                status="SUCCEEDED",
                raw_summary={
                    "external_id": f"{repo}#{issue_num}",
                    "external_number": issue_num,
                    "external_url": f"https://github.com/{repo}/issues/{issue_num}",
                    "operation_id": f"mock-asg-{issue_num}",
                    "assignees": list(issue.assignees),
                },
            )
        else:  # read_issue
            issue_num = int(validated_payload["issue_number"])
            snap = await self.get_resource(repository=repo, resource_number=issue_num)
            result = ConnectorActionResult(
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
                    "assignees": list(snap.assignees),
                    "comments_count": snap.comments_count,
                },
            )

        if execution_context.idempotency_key:
            self._idempotency_cache[cache_key] = result
        return result

    async def verify_result(
        self,
        action: str,
        expected_state: dict[str, Any],
        evidence_context: dict[str, Any],
    ) -> ConnectorVerificationEvidence:
        """Đọc ngược lại Issue trong bộ giả lập và đối chiếu từng trường kỳ vọng."""
        if self._simulate_verification_mismatch:
            return ConnectorVerificationEvidence(
                matched=False,
                outcome="FAILED",
                reason="Bộ giả lập mô phỏng tình huống sai lệch trạng thái khi đọc ngược tài nguyên đích.",
                mismatched_fields=["simulated_mismatch"],
            )

        repo = str(evidence_context.get("repository") or "")
        resource_number = evidence_context.get("external_number")
        if not repo or resource_number is None:
            return ConnectorVerificationEvidence(
                matched=False,
                outcome="UNVERIFIED",
                reason="Thiếu thông tin kho mã hoặc số hiệu Issue để đọc ngược kiểm chứng.",
            )

        try:
            snapshot = await self.get_resource(repository=repo, resource_number=int(resource_number))
        except ConnectorError as exc:
            return ConnectorVerificationEvidence(
                matched=False,
                outcome="UNVERIFIED",
                reason=exc.message,
            )

        mismatches: list[str] = []
        if "state" in expected_state and expected_state["state"] != snapshot.state:
            mismatches.append("state")
        if "title" in expected_state and expected_state["title"] != snapshot.title:
            mismatches.append("title")
        if "labels" in expected_state:
            expected_labels = set(str(x) for x in expected_state["labels"])
            if not expected_labels.issubset(set(snapshot.labels)):
                mismatches.append("labels")
        if "assignees" in expected_state:
            expected_assignees = set(str(x) for x in expected_state["assignees"])
            if not expected_assignees.issubset(set(snapshot.assignees)):
                mismatches.append("assignees")

        if mismatches:
            return ConnectorVerificationEvidence(
                matched=False,
                outcome="PARTIALLY_VERIFIED",
                reason=f"Một số trường không khớp khi đọc ngược: {', '.join(mismatches)}.",
                snapshot=snapshot,
                mismatched_fields=mismatches,
            )

        return ConnectorVerificationEvidence(
            matched=True,
            outcome="VERIFIED",
            reason="Dữ liệu đọc ngược khớp hoàn toàn với trạng thái kỳ vọng.",
            snapshot=snapshot,
        )
