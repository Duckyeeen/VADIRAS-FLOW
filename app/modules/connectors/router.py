"""Các tuyến API quản lý bộ kết nối, tiếp nhận webhook GitHub có chữ ký và quét đồng bộ dự phòng."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_db_session
from app.modules.identity.dependencies import get_current_actor
from app.modules.identity.service import AuthenticatedActor
from app.modules.runtime.temporal_client import TemporalRuntimeGateway

from . import service
from .providers.base import BaseConnector
from .providers.factory import build_github_connector
from .schemas import (
    ConnectorSummaryOut,
    GitHubConnectorStatusOut,
    GitHubInstallationOut,
    ReconcileReportOut,
    RegisterGitHubInstallationIn,
    WebhookReceiptOut,
)
from .webhook_inbox import ingest_github_webhook

router = APIRouter(prefix="/api/v1", tags=["Bộ kết nối & Webhook"])


def _get_github_connector(request: Request) -> BaseConnector:
    connector = getattr(request.app.state, "github_connector", None)
    if connector is None:
        connector = build_github_connector(request.app.state.settings)
        request.app.state.github_connector = connector
    return connector


@router.get(
    "/connectors",
    response_model=list[ConnectorSummaryOut],
    summary="Danh sách bộ kết nối và năng lực hỗ trợ",
)
async def list_connectors(
    request: Request,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> list[ConnectorSummaryOut]:
    """Liệt kê các bộ kết nối khả dụng cùng danh sách hành động cho phép của tổ chức."""
    settings: Settings = request.app.state.settings
    connector = _get_github_connector(request)
    return await service.list_connectors_for_actor(
        session, actor=actor, connector=connector, settings=settings
    )


@router.post(
    "/connectors/github/installations",
    response_model=GitHubInstallationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Đăng ký hoặc cập nhật cài đặt GitHub App",
)
async def register_github_installation(
    payload: RegisterGitHubInstallationIn,
    request: Request,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> GitHubInstallationOut:
    """Lưu cấu hình cài đặt GitHub App / giả lập kèm danh sách kho cho phép."""
    settings: Settings = request.app.state.settings
    connector = _get_github_connector(request)
    return await service.register_github_installation_for_actor(
        session,
        actor=actor,
        payload=payload,
        connector=connector,
        settings=settings,
    )


@router.get(
    "/connectors/github/status",
    response_model=GitHubConnectorStatusOut,
    summary="Kiểm tra trạng thái kết nối GitHub và lịch sử webhook",
)
async def get_github_status(
    request: Request,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> GitHubConnectorStatusOut:
    """Xem tình trạng kết nối GitHub, danh sách kho cho phép, số giao dịch và webhook gần nhất."""
    settings: Settings = request.app.state.settings
    connector = _get_github_connector(request)
    return await service.get_github_status_for_actor(
        session, actor=actor, connector=connector, settings=settings
    )


@router.post(
    "/webhooks/github",
    response_model=WebhookReceiptOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Tiếp nhận sự kiện webhook từ GitHub",
)
async def receive_github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    session: AsyncSession = Depends(get_db_session),
) -> WebhookReceiptOut:
    """Xác thực chữ ký thô HMAC-SHA256, chống trùng theo mã giao nhận và đối soát lượt chạy."""
    raw_body = await request.body()
    settings: Settings = request.app.state.settings
    gateway: TemporalRuntimeGateway | None = getattr(request.app.state, "runtime_gateway", None)
    return await ingest_github_webhook(
        session,
        raw_body=raw_body,
        signature_header=x_hub_signature_256,
        delivery_id=x_github_delivery,
        event_type=x_github_event,
        webhook_secret=settings.github_webhook_secret,
        default_allowed_repos=settings.get_github_allowed_repos_list(),
        runtime_gateway=gateway,
    )


@router.post(
    "/connectors/github/reconcile",
    response_model=ReconcileReportOut,
    summary="Chạy quét đồng bộ dự phòng từ GitHub",
)
async def reconcile_github_state(
    request: Request,
    actor: AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> ReconcileReportOut:
    """Chủ động đọc ngược trạng thái các Issue đang theo dõi để bù sự kiện webhook bị trễ."""
    settings: Settings = request.app.state.settings
    connector = _get_github_connector(request)
    gateway: TemporalRuntimeGateway | None = getattr(request.app.state, "runtime_gateway", None)
    return await service.trigger_github_reconcile_for_actor(
        session,
        actor=actor,
        connector=connector,
        settings=settings,
        runtime_gateway=gateway,
    )
