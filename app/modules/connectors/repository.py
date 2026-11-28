"""Tầng truy vấn cơ sở dữ liệu cho cài đặt bộ kết nối, phạm vi kho, giao dịch và webhook."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import (
    ConnectorInstallation,
    ConnectorOperationRecord,
    WebhookInbox,
)


async def list_installations(
    session: AsyncSession,
    *,
    organization_id: str,
) -> list[ConnectorInstallation]:
    """Lấy toàn bộ bản cài đặt bộ kết nối kèm danh sách kho cho phép của một tổ chức."""
    stmt = (
        sa.select(ConnectorInstallation)
        .options(selectinload(ConnectorInstallation.resource_scopes))
        .execution_options(populate_existing=True)
        .where(ConnectorInstallation.organization_id == organization_id)
        .order_by(ConnectorInstallation.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_installation_by_external_id(
    session: AsyncSession,
    *,
    organization_id: str,
    connector_type: str,
    installation_external_id: str,
) -> ConnectorInstallation | None:
    """Tìm cài đặt theo tổ chức, loại bộ kết nối và mã cài đặt ngoài."""
    stmt = (
        sa.select(ConnectorInstallation)
        .options(selectinload(ConnectorInstallation.resource_scopes))
        .execution_options(populate_existing=True)
        .where(
            ConnectorInstallation.organization_id == organization_id,
            ConnectorInstallation.connector_type == connector_type,
            ConnectorInstallation.installation_external_id == installation_external_id,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def find_installation_by_external_id_any_org(
    session: AsyncSession,
    *,
    installation_external_id: str,
) -> ConnectorInstallation | None:
    """Tìm cài đặt khớp mã `installation.id` khi nhận webhook từ GitHub gửi vào."""
    stmt = (
        sa.select(ConnectorInstallation)
        .options(selectinload(ConnectorInstallation.resource_scopes))
        .where(ConnectorInstallation.installation_external_id == installation_external_id)
        .order_by(ConnectorInstallation.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_webhook_by_delivery_id(
    session: AsyncSession,
    *,
    delivery_id: str,
) -> WebhookInbox | None:
    """Kiểm tra sự kiện webhook đã từng được ghi nhận theo `X-GitHub-Delivery` hay chưa."""
    stmt = sa.select(WebhookInbox).where(WebhookInbox.delivery_id == delivery_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_recent_webhooks(
    session: AsyncSession,
    *,
    organization_id: str,
    limit: int = 20,
) -> list[WebhookInbox]:
    """Lấy danh sách các sự kiện webhook gần nhất thuộc phạm vi tổ chức."""
    stmt = (
        sa.select(WebhookInbox)
        .where(WebhookInbox.organization_id == organization_id)
        .order_by(WebhookInbox.received_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_operations(
    session: AsyncSession,
    *,
    organization_id: str,
) -> tuple[int, int]:
    """Đếm tổng số giao dịch ngoài và số giao dịch đã thành công/đối soát trong tổ chức."""
    total_stmt = (
        sa.select(sa.func.count())
        .select_from(ConnectorOperationRecord)
        .where(ConnectorOperationRecord.organization_id == organization_id)
    )
    ok_stmt = (
        sa.select(sa.func.count())
        .select_from(ConnectorOperationRecord)
        .where(
            ConnectorOperationRecord.organization_id == organization_id,
            ConnectorOperationRecord.status.in_(["SUCCEEDED", "RECONCILED"]),
        )
    )
    total = int((await session.execute(total_stmt)).scalar_one())
    succeeded = int((await session.execute(ok_stmt)).scalar_one())
    return total, succeeded
