"""Khuôn mẫu chuẩn, danh mục hành động cho phép và ngoại lệ cho mọi bộ kết nối hệ thống ngoài."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class ConnectorError(Exception):
    """Ngoại lệ gốc cho mọi lỗi phát sinh khi giao tiếp với hệ thống ngoài."""

    def __init__(self, message: str, *, code: str = "CONNECTOR_ERROR", retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable


class ConnectorTransientError(ConnectorError):
    """Lỗi tạm thời (mất mạng ngắn hạn, quá tải 429 hoặc 5xx) — có thể thử lại an toàn."""

    def __init__(self, message: str, *, code: str = "CONNECTOR_TRANSIENT_ERROR") -> None:
        super().__init__(message, code=code, retryable=True)


class ConnectorPermanentError(ConnectorError):
    """Lỗi vĩnh viễn (thiếu quyền, kho ngoài danh sách cho phép, dữ liệu sai) — không được thử lại."""

    def __init__(self, message: str, *, code: str = "CONNECTOR_PERMANENT_ERROR") -> None:
        super().__init__(message, code=code, retryable=False)


@dataclass(frozen=True, slots=True)
class ConnectorActionSchema:
    """Mô tả đầy đủ một hành động được phép của bộ kết nối kèm quyền và cách xác minh."""

    name: str
    description: str
    required_permission: str
    side_effect_class: str  # READ | WRITE
    supports_idempotency: bool
    required_fields: tuple[str, ...]
    verification_method: str


@dataclass(frozen=True, slots=True)
class ConnectorExecutionContext:
    """Ngữ cảnh thực thi được truyền xuống bộ kết nối cho mỗi thao tác cụ thể."""

    organization_id: str
    repository: str
    idempotency_key: str
    request_id: str | None = None
    workflow_run_id: str | None = None
    node_id: str | None = None
    actor_id: str = "system"


@dataclass(frozen=True, slots=True)
class ConnectorActionResult:
    """Kết quả trả về chuẩn hóa sau khi thực thi một hành động trên hệ thống ngoài."""

    connector_type: str
    action: str
    repository: str
    external_id: str
    external_number: int | None
    external_url: str
    status: str
    raw_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConnectorResourceSnapshot:
    """Ảnh chụp trạng thái hiện tại của một tài nguyên (ví dụ GitHub Issue) khi đọc ngược."""

    repository: str
    external_id: str
    external_number: int
    external_url: str
    title: str
    state: str
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    comments_count: int = 0
    updated_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConnectorVerificationEvidence:
    """Kết quả đối chiếu ngược giữa trạng thái kỳ vọng và dữ liệu thực tế tại hệ thống đích."""

    matched: bool
    outcome: str  # VERIFIED | PARTIALLY_VERIFIED | FAILED | UNVERIFIED
    reason: str
    snapshot: ConnectorResourceSnapshot | None = None
    mismatched_fields: list[str] = field(default_factory=list)


# Danh mục cố định 5 hành động GitHub được phép — tuyệt đối không gọi URL hay hành động tùy tiện ngoài danh mục
GITHUB_ACTION_SCHEMAS: dict[str, ConnectorActionSchema] = {
    "create_issue": ConnectorActionSchema(
        name="create_issue",
        description="Tạo phiếu công việc (Issue) mới trong kho mã nằm trong danh sách cho phép.",
        required_permission="issues:write",
        side_effect_class="WRITE",
        supports_idempotency=True,
        required_fields=("title",),
        verification_method="read_back_issue_and_compare_title_labels",
    ),
    "update_issue": ConnectorActionSchema(
        name="update_issue",
        description="Cập nhật tiêu đề, nội dung, trạng thái hoặc nhãn của một Issue có sẵn.",
        required_permission="issues:write",
        side_effect_class="WRITE",
        supports_idempotency=True,
        required_fields=("issue_number",),
        verification_method="read_back_issue_and_compare_state_labels",
    ),
    "comment_issue": ConnectorActionSchema(
        name="comment_issue",
        description="Thêm bình luận cập nhật tiến độ vào một Issue đã tồn tại.",
        required_permission="issues:write",
        side_effect_class="WRITE",
        supports_idempotency=True,
        required_fields=("issue_number", "body"),
        verification_method="read_back_issue_comments_count",
    ),
    "assign_issue": ConnectorActionSchema(
        name="assign_issue",
        description="Gán người phụ trách xử lý cho một Issue có sẵn.",
        required_permission="issues:write",
        side_effect_class="WRITE",
        supports_idempotency=True,
        required_fields=("issue_number", "assignees"),
        verification_method="read_back_issue_and_compare_assignees",
    ),
    "read_issue": ConnectorActionSchema(
        name="read_issue",
        description="Đọc ngược trạng thái hiện tại của một Issue phục vụ đối chiếu bằng chứng.",
        required_permission="issues:read",
        side_effect_class="READ",
        supports_idempotency=True,
        required_fields=("issue_number",),
        verification_method="direct_read",
    ),
}


class BaseConnector(ABC):
    """Giao diện chuẩn mà cả `GitHubAppConnector` lẫn `MockGitHubConnector` đều phải tuân thủ."""

    connector_type: str = "base"

    @abstractmethod
    def get_capabilities(self) -> list[ConnectorActionSchema]:
        """Trả về danh sách các hành động đã đăng ký mà bộ kết nối này hỗ trợ."""

    @abstractmethod
    async def validate_connection(self) -> bool:
        """Kiểm tra tính hợp lệ của thông tin xác thực và quyền truy cập tối thiểu."""

    @abstractmethod
    async def get_resource(self, *, repository: str, resource_number: int) -> ConnectorResourceSnapshot:
        """Đọc ngược trạng thái hiện tại của một tài nguyên theo số hiệu."""

    @abstractmethod
    async def execute_action(
        self,
        action: str,
        validated_payload: dict[str, Any],
        execution_context: ConnectorExecutionContext,
    ) -> ConnectorActionResult:
        """Thực thi một hành động hợp lệ ra hệ thống đích."""

    @abstractmethod
    async def verify_result(
        self,
        action: str,
        expected_state: dict[str, Any],
        evidence_context: dict[str, Any],
    ) -> ConnectorVerificationEvidence:
        """Đọc ngược lại tài nguyên đích và đối chiếu với trạng thái kỳ vọng."""

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Kiểm tra tình trạng sẵn sàng của bộ kết nối."""

    @abstractmethod
    async def list_issues(
        self,
        *,
        repository: str,
        since: datetime | None = None,
    ) -> list[ConnectorResourceSnapshot]:
        """Liệt kê các Issue gần đây của một kho để phục vụ quét đồng bộ dự phòng."""
