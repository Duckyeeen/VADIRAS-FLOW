"""Tầng truy vấn cơ sở dữ liệu cho kết quả phân tích AI, tác vụ trợ lý và danh tính AI."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import AgentCapability, AgentIdentity
from app.modules.requests.models import RequestAnalysis

from .models import AgentRun


async def get_next_analysis_version(
    session: AsyncSession,
    *,
    organization_id: str,
    request_id: str,
) -> int:
    """Tính số thứ tự phiên bản phân tích tiếp theo cho một yêu cầu."""
    stmt = sa.select(sa.func.max(RequestAnalysis.version_number)).where(
        RequestAnalysis.organization_id == organization_id,
        RequestAnalysis.request_id == request_id,
    )
    current_max = (await session.execute(stmt)).scalar_one_or_none()
    return int(current_max or 0) + 1


async def get_analysis_by_version(
    session: AsyncSession,
    *,
    organization_id: str,
    request_id: str,
    version_number: int | None = None,
) -> RequestAnalysis | None:
    """Lấy bản phân tích mới nhất hoặc theo đúng số phiên bản của một yêu cầu."""
    filters = [
        RequestAnalysis.organization_id == organization_id,
        RequestAnalysis.request_id == request_id,
    ]
    if version_number is not None:
        filters.append(RequestAnalysis.version_number == version_number)

    stmt = (
        sa.select(RequestAnalysis)
        .where(*filters)
        .order_by(RequestAnalysis.version_number.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_agent_runs_for_job(
    session: AsyncSession,
    *,
    organization_id: str,
    analysis_job_id: str,
) -> list[AgentRun]:
    """Lấy toàn bộ kết quả chạy của các trợ lý AI thuộc một phiên phân tích."""
    stmt = (
        sa.select(AgentRun)
        .where(
            AgentRun.organization_id == organization_id,
            AgentRun.analysis_job_id == analysis_job_id,
        )
        .order_by(AgentRun.round_number.asc(), AgentRun.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_agent_identities_map(
    session: AsyncSession,
    *,
    organization_id: str,
) -> dict[str, AgentIdentity]:
    """Nạp bảng ánh xạ từ mã vai trò sang bản ghi danh tính AI trong tổ chức."""
    stmt = sa.select(AgentIdentity).where(AgentIdentity.organization_id == organization_id)
    rows = (await session.execute(stmt)).scalars().all()
    return {row.role_code: row for row in rows}


async def list_agents_with_capabilities(
    session: AsyncSession,
    *,
    organization_id: str,
    page: int,
    page_size: int,
) -> tuple[list[tuple[AgentIdentity, list[str]]], int]:
    """Liệt kê các trợ lý AI kèm danh sách năng lực được cấp trong phạm vi tổ chức."""
    count_stmt = (
        sa.select(sa.func.count())
        .select_from(AgentIdentity)
        .where(AgentIdentity.organization_id == organization_id)
    )
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = (
        sa.select(AgentIdentity)
        .where(AgentIdentity.organization_id == organization_id)
        .order_by(AgentIdentity.role_code.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    agents = list((await session.execute(stmt)).scalars().all())
    if not agents:
        return [], total

    agent_ids = [a.id for a in agents]
    cap_rows = (
        await session.execute(
            sa.select(AgentCapability.agent_identity_id, AgentCapability.capability_code).where(
                AgentCapability.organization_id == organization_id,
                AgentCapability.agent_identity_id.in_(agent_ids),
                AgentCapability.is_enabled.is_(True),
            )
        )
    ).all()
    cap_map: dict[str, list[str]] = {aid: [] for aid in agent_ids}
    for aid, cap_code in cap_rows:
        cap_map[aid].append(cap_code)

    return [(a, sorted(cap_map.get(a.id, []))) for a in agents], total


async def get_agent_with_capabilities(
    session: AsyncSession,
    *,
    organization_id: str,
    agent_id: str,
) -> tuple[AgentIdentity, list[str]] | None:
    """Lấy chi tiết một danh tính trợ lý AI trong đúng phạm vi tổ chức."""
    stmt = sa.select(AgentIdentity).where(
        AgentIdentity.id == agent_id,
        AgentIdentity.organization_id == organization_id,
    )
    agent = (await session.execute(stmt)).scalar_one_or_none()
    if agent is None:
        return None

    cap_rows = (
        await session.execute(
            sa.select(AgentCapability.capability_code)
            .where(
                AgentCapability.organization_id == organization_id,
                AgentCapability.agent_identity_id == agent.id,
                AgentCapability.is_enabled.is_(True),
            )
            .order_by(AgentCapability.capability_code.asc())
        )
    ).scalars().all()
    return agent, list(cap_rows)
