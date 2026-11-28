"""Tầng xử lý nghiệp vụ quản lý bộ kết nối, đăng ký cài đặt kho mã, webhook và đồng bộ dự phòng."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ValidationAppError
from app.modules.identity.service import AuthenticatedActor, require_employee, require_permission
from app.modules.runtime.temporal_client import TemporalRuntimeGateway

from . import repository
from .models import ConnectorInstallation, ConnectorResourceScope, InstallationStatus
from .providers.base import BaseConnector
from .providers.mock_github import MockGitHubConnector
from .reconciler import GitHubReconciler
from .schemas import (
    ConnectorCapabilityOut,
    ConnectorSummaryOut,
    GitHubConnectorStatusOut,
    GitHubInstallationOut,
    InstallationScopeOut,
    ReconcileReportOut,
    RegisterGitHubInstallationIn,
    WebhookEventSummaryOut,
)


def _to_installation_out(inst: ConnectorInstallation) -> GitHubInstallationOut:
    scopes = [
        InstallationScopeOut(
            id=s.id,
            resource_type=s.resource_type,
            resource_identifier=s.resource_identifier,
            allowed_actions=list(s.allowed_actions_json or []),
            is_active=s.is_active,
        )
        for s in inst.resource_scopes
    ]
    return GitHubInstallationOut(
        id=inst.id,
        organization_id=inst.organization_id,
        connector_type=inst.connector_type,
        installation_external_id=inst.installation_external_id,
        account_login=inst.account_login,
        app_id=inst.app_id,
        status=inst.status,
        permissions=dict(inst.permissions_json or {}),
        last_synced_at=inst.last_synced_at,
        sync_cursor=inst.sync_cursor,
        resource_scopes=scopes,
        created_at=inst.created_at,
    )


async def list_connectors_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    connector: BaseConnector,
    settings: Settings,
) -> list[ConnectorSummaryOut]:
    """Liệt kê danh sách bộ kết nối khả dụng kèm năng lực cho phép trong tổ chức."""
    require_employee(actor)
    installations = await repository.list_installations(session, organization_id=actor.organization_id)
    health = await connector.health_check()
    caps = [
        ConnectorCapabilityOut(
            name=c.name,
            description=c.description,
            required_permission=c.required_permission,
            side_effect_class=c.side_effect_class,
            supports_idempotency=c.supports_idempotency,
            required_fields=list(c.required_fields),
            verification_method=c.verification_method,
        )
        for c in connector.get_capabilities()
    ]
    allowed_repos = list(health.get("allowed_repos") or settings.get_github_allowed_repos_list())
    return [
        ConnectorSummaryOut(
            connector_type=connector.connector_type,
            display_name="GitHub App / Bộ giả lập GitHub",
            active_mode=settings.github_connector_mode,
            status=str(health.get("status") or "up"),
            allowed_repos=allowed_repos,
            capabilities=caps,
            installation_count=len(installations),
        )
    ]


async def register_github_installation_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    payload: RegisterGitHubInstallationIn,
    connector: BaseConnector,
    settings: Settings,
) -> GitHubInstallationOut:
    """Đăng ký hoặc cập nhật cài đặt GitHub App kèm danh sách kho cho phép (chặn ký tự `*`)."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:update")

    cleaned_repos: list[str] = []
    for raw_repo in payload.allowed_repos:
        repo = raw_repo.strip()
        if not repo or "*" in repo or "/" not in repo:
            raise ValidationAppError(
                f"Tên kho `{raw_repo}` không hợp lệ; bắt buộc có dạng `chu_so_huu/ten_kho` và không chứa `*`.",
                code="INVALID_REPOSITORY_SCOPE",
            )
        if repo not in cleaned_repos:
            cleaned_repos.append(repo)

    conn_type = (payload.connector_type or connector.connector_type).strip().lower()
    existing = await repository.get_installation_by_external_id(
        session,
        organization_id=actor.organization_id,
        connector_type=conn_type,
        installation_external_id=payload.installation_external_id,
    )

    minimal_permissions = {"metadata": "read", "issues": "write"}
    if existing is None:
        inst = ConnectorInstallation(
            organization_id=actor.organization_id,
            connector_type=conn_type,
            installation_external_id=payload.installation_external_id,
            account_login=payload.account_login,
            app_id=payload.app_id or settings.github_app_id or "demo-app",
            status=InstallationStatus.ACTIVE.value,
            permissions_json=minimal_permissions,
            config_json={"subscribed_events": ["issues", "issue_comment"]},
            created_by_user_id=actor.user_id,
        )
        session.add(inst)
        await session.flush()
    else:
        inst = existing
        inst.account_login = payload.account_login
        inst.app_id = payload.app_id or inst.app_id
        inst.status = InstallationStatus.ACTIVE.value
        inst.permissions_json = minimal_permissions

    # Cập nhật danh sách kho được phép cho bản cài đặt
    existing_scopes = {s.resource_identifier: s for s in (existing.resource_scopes if existing else [])}
    for repo in cleaned_repos:
        if repo in existing_scopes:
            existing_scopes[repo].is_active = True
        else:
            session.add(
                ConnectorResourceScope(
                    organization_id=actor.organization_id,
                    connector_installation_id=inst.id,
                    resource_type="repository",
                    resource_identifier=repo,
                    allowed_actions_json=[
                        "create_issue",
                        "update_issue",
                        "comment_issue",
                        "assign_issue",
                        "read_issue",
                    ],
                    is_active=True,
                )
            )
        if isinstance(connector, MockGitHubConnector):
            connector.add_allowed_repo(repo)

    await session.commit()
    refreshed = await repository.get_installation_by_external_id(
        session,
        organization_id=actor.organization_id,
        connector_type=conn_type,
        installation_external_id=payload.installation_external_id,
    )
    assert refreshed is not None
    return _to_installation_out(refreshed)


async def get_github_status_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    connector: BaseConnector,
    settings: Settings,
) -> GitHubConnectorStatusOut:
    """Trả báo cáo sức khỏe, phạm vi kho, thống kê giao dịch và webhook gần đây của tổ chức."""
    require_employee(actor)
    health = await connector.health_check()
    installations = await repository.list_installations(session, organization_id=actor.organization_id)
    total_ops, ok_ops = await repository.count_operations(session, organization_id=actor.organization_id)
    recent_wh = await repository.list_recent_webhooks(session, organization_id=actor.organization_id, limit=20)

    scoped_repos: set[str] = set()
    for inst in installations:
        for s in inst.resource_scopes:
            if s.is_active:
                scoped_repos.add(s.resource_identifier)
    if not scoped_repos:
        scoped_repos.update(settings.get_github_allowed_repos_list())

    return GitHubConnectorStatusOut(
        mode=settings.github_connector_mode,
        health=health,
        allowed_repos=sorted(scoped_repos),
        installations=[_to_installation_out(i) for i in installations],
        total_operations=total_ops,
        succeeded_operations=ok_ops,
        recent_webhooks=[
            WebhookEventSummaryOut(
                id=w.id,
                delivery_id=w.delivery_id,
                event_type=w.event_type,
                repository_full_name=w.repository_full_name,
                status=w.status,
                signature_verified=w.signature_verified,
                correlated_run_id=w.correlated_run_id,
                received_at=w.received_at,
                processed_at=w.processed_at,
            )
            for w in recent_wh
        ],
    )


async def trigger_github_reconcile_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    connector: BaseConnector,
    settings: Settings,
    runtime_gateway: TemporalRuntimeGateway | None = None,
) -> ReconcileReportOut:
    """Kích hoạt quét đồng bộ dự phòng cho các kho mã và giao dịch của tổ chức."""
    require_employee(actor)
    if "workflows:manage" not in actor.permissions:
        require_permission(actor, "requests:update")

    reconciler = GitHubReconciler()
    return await reconciler.reconcile_organization(
        session,
        organization_id=actor.organization_id,
        connector=connector,
        default_allowed_repos=settings.get_github_allowed_repos_list(),
        runtime_gateway=runtime_gateway,
    )
