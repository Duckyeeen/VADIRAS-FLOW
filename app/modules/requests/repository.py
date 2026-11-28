"""Tầng truy vấn cơ sở dữ liệu cho yêu cầu công việc, tin nhắn và tác vụ con người."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.identity.models import Department, Membership

from .models import (
    HumanTask,
    Request,
    RequestMessage,
    RequestParticipant,
    VisibilityLevel,
)


async def get_department_by_code(
    session: AsyncSession,
    *,
    organization_id: str,
    code: str,
) -> Department | None:
    """Tìm phòng ban theo mã phòng ban trong đúng phạm vi tổ chức."""
    stmt = sa.select(Department).where(
        Department.organization_id == organization_id,
        sa.func.upper(Department.code) == code.strip().upper(),
        Department.is_active.is_(True),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_membership_in_org(
    session: AsyncSession,
    *,
    organization_id: str,
    membership_id: str,
) -> Membership | None:
    """Kiểm tra một thành viên có thuộc đúng tổ chức hiện tại hay không."""
    stmt = sa.select(Membership).where(
        Membership.id == membership_id,
        Membership.organization_id == organization_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_request_by_idempotency_key(
    session: AsyncSession,
    *,
    organization_id: str,
    idempotency_key: str,
) -> Request | None:
    """Tìm yêu cầu đã tạo trước đó dựa trên mã chống trùng lặp trong phạm vi tổ chức."""
    stmt = (
        sa.select(Request)
        .options(selectinload(Request.messages), selectinload(Request.human_tasks))
        .where(
            Request.organization_id == organization_id,
            Request.idempotency_key == idempotency_key,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def generate_next_request_number(
    session: AsyncSession,
    *,
    organization_id: str,
) -> str:
    """Sinh mã yêu cầu tuần tự duy nhất trong một tổ chức (ví dụ `REQ-000001`)."""
    count_stmt = sa.select(sa.func.count()).select_from(Request).where(
        Request.organization_id == organization_id
    )
    current_count = int((await session.execute(count_stmt)).scalar_one())
    return f"REQ-{current_count + 1:06d}"


async def get_request_by_id(
    session: AsyncSession,
    *,
    organization_id: str,
    request_id: str,
) -> Request | None:
    """Lấy chi tiết một yêu cầu kèm tin nhắn và đầu việc trong phạm vi tổ chức."""
    stmt = (
        sa.select(Request)
        .options(selectinload(Request.messages), selectinload(Request.human_tasks))
        .execution_options(populate_existing=True)
        .where(
            Request.id == request_id,
            Request.organization_id == organization_id,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_requests(
    session: AsyncSession,
    *,
    organization_id: str,
    page: int,
    page_size: int,
    only_requester_membership_id: str | None = None,
    customer_account_ref: str | None = None,
    request_type: str | None = None,
    status: str | None = None,
    department_id: str | None = None,
    priority: str | None = None,
) -> tuple[list[Request], int]:
    """Truy vấn danh sách yêu cầu có lọc quyền sở hữu, lọc tiêu chí và phân trang."""
    filters: list[sa.ColumnElement[bool]] = [Request.organization_id == organization_id]

    if only_requester_membership_id is not None:
        if customer_account_ref:
            filters.append(
                sa.or_(
                    Request.requester_membership_id == only_requester_membership_id,
                    Request.customer_account_ref == customer_account_ref,
                )
            )
        else:
            filters.append(Request.requester_membership_id == only_requester_membership_id)

    if request_type:
        filters.append(Request.request_type == request_type.strip().upper())
    if status:
        filters.append(Request.status == status.strip().upper())
    if department_id:
        filters.append(Request.department_id == department_id)
    if priority:
        filters.append(Request.priority == priority.strip().upper())

    count_stmt = sa.select(sa.func.count()).select_from(Request).where(*filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = (
        sa.select(Request)
        .options(selectinload(Request.messages), selectinload(Request.human_tasks))
        .where(*filters)
        .order_by(Request.created_at.desc(), Request.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await session.execute(stmt)).scalars().all())
    return items, total


async def add_participant_if_missing(
    session: AsyncSession,
    *,
    organization_id: str,
    request_id: str,
    membership_id: str,
    participant_role: str,
) -> None:
    """Thêm thành viên tham gia vào yêu cầu nếu chưa tồn tại vai trò tương ứng."""
    exists_stmt = sa.select(RequestParticipant.id).where(
        RequestParticipant.request_id == request_id,
        RequestParticipant.membership_id == membership_id,
        RequestParticipant.participant_role == participant_role,
    )
    if (await session.execute(exists_stmt)).scalar_one_or_none() is None:
        session.add(
            RequestParticipant(
                organization_id=organization_id,
                request_id=request_id,
                membership_id=membership_id,
                participant_role=participant_role,
            )
        )


async def list_messages_for_request(
    session: AsyncSession,
    *,
    organization_id: str,
    request_id: str,
    customer_visible_only: bool,
) -> list[RequestMessage]:
    """Lấy danh sách tin nhắn của yêu cầu (lọc bỏ tin nội bộ nếu người xem là khách hàng)."""
    filters: list[sa.ColumnElement[bool]] = [
        RequestMessage.organization_id == organization_id,
        RequestMessage.request_id == request_id,
    ]
    if customer_visible_only:
        filters.append(RequestMessage.visibility == VisibilityLevel.CUSTOMER_VISIBLE.value)

    stmt = sa.select(RequestMessage).where(*filters).order_by(RequestMessage.created_at.asc())
    return list((await session.execute(stmt)).scalars().all())


async def get_human_task_by_id(
    session: AsyncSession,
    *,
    organization_id: str,
    task_id: str,
) -> HumanTask | None:
    """Tìm một đầu việc giao cho con người theo mã trong phạm vi tổ chức."""
    stmt = sa.select(HumanTask).where(
        HumanTask.id == task_id,
        HumanTask.organization_id == organization_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_human_tasks(
    session: AsyncSession,
    *,
    organization_id: str,
    page: int,
    page_size: int,
    status: str | None = None,
    department_id: str | None = None,
    assignee_membership_id: str | None = None,
    request_id: str | None = None,
) -> tuple[list[HumanTask], int]:
    """Lấy danh sách đầu việc con người có lọc và phân trang trong phạm vi tổ chức."""
    filters: list[sa.ColumnElement[bool]] = [HumanTask.organization_id == organization_id]
    if status:
        filters.append(HumanTask.status == status.strip().upper())
    if department_id:
        filters.append(HumanTask.department_id == department_id)
    if assignee_membership_id:
        filters.append(HumanTask.assignee_membership_id == assignee_membership_id)
    if request_id:
        filters.append(HumanTask.request_id == request_id)

    count_stmt = sa.select(sa.func.count()).select_from(HumanTask).where(*filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = (
        sa.select(HumanTask)
        .where(*filters)
        .order_by(HumanTask.created_at.desc(), HumanTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await session.execute(stmt)).scalars().all())
    return items, total
