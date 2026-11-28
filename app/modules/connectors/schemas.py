"""Khuôn mẫu dữ liệu vào và ra cho các API quản lý bộ kết nối, cài đặt kho mã, webhook và đối soát."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.core.schemas import ContractModel


class ConnectorCapabilityOut(ContractModel):
    """Mô tả một hành động đã đăng ký của bộ kết nối kèm quyền tối thiểu."""

    name: str
    description: str
    required_permission: str
    side_effect_class: str
    supports_idempotency: bool
    required_fields: list[str]
    verification_method: str


class ConnectorSummaryOut(ContractModel):
    """Thông tin tổng quan về một bộ kết nối khả dụng trong hệ thống."""

    connector_type: str
    display_name: str
    active_mode: str
    status: str
    allowed_repos: list[str]
    capabilities: list[ConnectorCapabilityOut]
    installation_count: int


class RegisterGitHubInstallationIn(ContractModel):
    """Thông tin đăng ký hoặc cập nhật một cài đặt GitHub App / Mock GitHub cho tổ chức."""

    installation_external_id: str = Field(min_length=1, max_length=128)
    account_login: str = Field(default="vadiras-demo", min_length=1, max_length=128)
    app_id: str = Field(default="demo-app", max_length=64)
    allowed_repos: list[str] = Field(min_length=1, max_length=50)
    connector_type: str | None = Field(default=None, max_length=64)


class InstallationScopeOut(ContractModel):
    """Một kho mã nguồn nằm trong danh sách cho phép của cài đặt bộ kết nối."""

    id: str
    resource_type: str
    resource_identifier: str
    allowed_actions: list[str]
    is_active: bool


class GitHubInstallationOut(ContractModel):
    """Thông tin chi tiết một cài đặt bộ kết nối gắn với tổ chức."""

    id: str
    organization_id: str
    connector_type: str
    installation_external_id: str
    account_login: str
    app_id: str
    status: str
    permissions: dict[str, Any]
    last_synced_at: datetime | None = None
    sync_cursor: str | None = None
    resource_scopes: list[InstallationScopeOut] = Field(default_factory=list)
    created_at: datetime


class WebhookEventSummaryOut(ContractModel):
    """Tóm tắt một bản ghi webhook đã tiếp nhận vào hộp thư (không lộ khóa hay dữ liệu thừa)."""

    id: str
    delivery_id: str
    event_type: str
    repository_full_name: str | None = None
    status: str
    signature_verified: bool
    correlated_run_id: str | None = None
    received_at: datetime
    processed_at: datetime | None = None


class GitHubConnectorStatusOut(ContractModel):
    """Báo cáo trạng thái sức khỏe, phạm vi kho, giao dịch và webhook gần đây của GitHub."""

    mode: str
    health: dict[str, Any]
    allowed_repos: list[str]
    installations: list[GitHubInstallationOut]
    total_operations: int
    succeeded_operations: int
    recent_webhooks: list[WebhookEventSummaryOut]


class WebhookReceiptOut(ContractModel):
    """Phản hồi nhanh sau khi tiếp nhận và xác thực chữ ký một sự kiện webhook."""

    accepted: bool
    duplicate: bool
    delivery_id: str
    event_type: str
    status: str
    inbox_id: str
    correlated_run_id: str | None = None
    reason: str = ""


class ReconcileReportOut(ContractModel):
    """Kết quả chạy bộ quét đồng bộ dự phòng cho một tổ chức."""

    organization_id: str
    scanned_installations: int
    checked_operations: int
    updated_operations: int
    issues_seen: int
    synced_at: datetime
    details: list[dict[str, Any]] = Field(default_factory=list)
