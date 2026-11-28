"""Tầng truy vấn cơ sở dữ liệu cho phân hệ Định danh, Tổ chức và Phân quyền."""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import (
    Department,
    Membership,
    MembershipRole,
    MembershipStatus,
    Organization,
    Permission,
    RefreshTokenSession,
    Role,
    RolePermission,
    User,
)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Tìm tài khoản người dùng theo địa chỉ email (chuẩn hóa chữ thường).

    Đầu vào: phiên làm việc CSDL và địa chỉ email.
    Đầu ra: đối tượng `User` hoặc `None` nếu không tồn tại.
    """
    normalized_email = email.strip().lower()
    stmt = sa.select(User).where(sa.func.lower(User.email) == normalized_email)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_active_membership_for_login(
    session: AsyncSession,
    *,
    user_id: str,
    organization_slug: str | None = None,
) -> list[Membership]:
    """Lấy danh sách tư cách thành viên đang hoạt động của một người dùng khi đăng nhập.

    Nếu có `organization_slug`, lọc đúng tổ chức đó để tránh lẫn lộn giữa nhiều tổ chức.
    """
    stmt = (
        sa.select(Membership)
        .join(Organization, Organization.id == Membership.organization_id)
        .options(
            selectinload(Membership.organization),
            selectinload(Membership.department),
            selectinload(Membership.user),
        )
        .where(
            Membership.user_id == user_id,
            Membership.status == MembershipStatus.ACTIVE.value,
            Organization.is_active.is_(True),
        )
    )
    if organization_slug:
        stmt = stmt.where(Organization.slug == organization_slug.strip().lower())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_membership_with_context(
    session: AsyncSession,
    *,
    membership_id: str,
    organization_id: str,
) -> Membership | None:
    """Nạp đầy đủ thông tin hiện hành của thành viên, người dùng, tổ chức và phòng ban.

    Luôn kiểm tra đồng thời cả `membership_id` và `organization_id` để cô lập chặt theo tổ chức.
    """
    stmt = (
        sa.select(Membership)
        .options(
            selectinload(Membership.user),
            selectinload(Membership.organization),
            selectinload(Membership.department),
        )
        .where(
            Membership.id == membership_id,
            Membership.organization_id == organization_id,
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_roles_and_permissions_for_membership(
    session: AsyncSession,
    *,
    membership_id: str,
    organization_id: str,
) -> tuple[list[str], list[str]]:
    """Truy vấn danh sách mã vai trò và mã quyền mới nhất từ cơ sở dữ liệu.

    Hàm này chạy độc lập với nội dung thẻ JWT để đảm bảo mọi thay đổi thu hồi quyền
    có hiệu lực ngay lập tức.
    """
    roles_stmt = (
        sa.select(Role.code)
        .join(MembershipRole, MembershipRole.role_id == Role.id)
        .where(
            MembershipRole.membership_id == membership_id,
            Role.organization_id == organization_id,
        )
        .order_by(Role.code)
    )
    role_rows = (await session.execute(roles_stmt)).scalars().all()

    perms_stmt = (
        sa.select(sa.distinct(Permission.code))
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(MembershipRole, MembershipRole.role_id == Role.id)
        .where(
            MembershipRole.membership_id == membership_id,
            Role.organization_id == organization_id,
        )
        .order_by(Permission.code)
    )
    perm_rows = (await session.execute(perms_stmt)).scalars().all()
    return list(role_rows), list(perm_rows)


async def create_refresh_session(
    session: AsyncSession,
    *,
    organization_id: str,
    membership_id: str,
    jti: str,
    token_hash: str,
    expires_at: datetime,
) -> RefreshTokenSession:
    """Lưu bản ghi phiên thẻ làm mới mới vào cơ sở dữ liệu."""
    record = RefreshTokenSession(
        organization_id=organization_id,
        membership_id=membership_id,
        jti=jti,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(record)
    await session.flush()
    return record


async def get_refresh_session_by_jti(
    session: AsyncSession,
    *,
    jti: str,
    organization_id: str,
) -> RefreshTokenSession | None:
    """Tìm phiên thẻ làm mới theo mã `jti` trong đúng phạm vi tổ chức."""
    stmt = sa.select(RefreshTokenSession).where(
        RefreshTokenSession.jti == jti,
        RefreshTokenSession.organization_id == organization_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def revoke_all_refresh_sessions_for_membership(
    session: AsyncSession,
    *,
    membership_id: str,
    organization_id: str,
) -> None:
    """Thu hồi toàn bộ thẻ làm mới còn hiệu lực của thành viên khi phát hiện dấu hiệu dùng lại thẻ cũ."""
    now = datetime.now(timezone.utc)
    stmt = (
        sa.update(RefreshTokenSession)
        .where(
            RefreshTokenSession.membership_id == membership_id,
            RefreshTokenSession.organization_id == organization_id,
            RefreshTokenSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await session.execute(stmt)


async def list_departments_by_org(
    session: AsyncSession,
    *,
    organization_id: str,
    page: int,
    page_size: int,
) -> tuple[list[Department], int]:
    """Lấy danh sách phòng ban có phân trang trong phạm vi một tổ chức."""
    base_filter = (Department.organization_id == organization_id, Department.is_active.is_(True))
    count_stmt = sa.select(sa.func.count()).select_from(Department).where(*base_filter)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = (
        sa.select(Department)
        .where(*base_filter)
        .order_by(Department.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await session.execute(stmt)).scalars().all())
    return items, total


async def list_memberships_by_org(
    session: AsyncSession,
    *,
    organization_id: str,
    page: int,
    page_size: int,
    department_id: str | None = None,
    user_kind: str | None = None,
) -> tuple[list[tuple[Membership, list[str]]], int]:
    """Lấy danh sách thành viên và vai trò tương ứng trong phạm vi một tổ chức."""
    filters: list[sa.ColumnElement[bool]] = [Membership.organization_id == organization_id]
    if department_id:
        filters.append(Membership.department_id == department_id)
    if user_kind:
        filters.append(Membership.user_kind == user_kind)

    count_stmt = sa.select(sa.func.count()).select_from(Membership).where(*filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = (
        sa.select(Membership)
        .options(
            selectinload(Membership.user),
            selectinload(Membership.department),
        )
        .where(*filters)
        .order_by(Membership.created_at.asc(), Membership.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    memberships = list((await session.execute(stmt)).scalars().all())
    if not memberships:
        return [], total

    membership_ids = [m.id for m in memberships]
    role_rows = await session.execute(
        sa.select(MembershipRole.membership_id, Role.code)
        .join(Role, Role.id == MembershipRole.role_id)
        .where(
            MembershipRole.membership_id.in_(membership_ids),
            Role.organization_id == organization_id,
        )
        .order_by(Role.code)
    )
    roles_map: dict[str, list[str]] = {mid: [] for mid in membership_ids}
    for mid, role_code in role_rows.all():
        roles_map[mid].append(role_code)

    return [(m, roles_map.get(m.id, [])) for m in memberships], total
