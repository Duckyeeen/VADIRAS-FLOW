"""Tầng xử lý nghiệp vụ cho đăng nhập, xoay vòng thẻ, kiểm tra quyền và cô lập tổ chức."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AuthenticationError, AuthorizationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
    verify_password,
)

from . import repository
from .models import Department, Membership, MembershipStatus, UserKind
from .schemas import (
    CurrentActorOut,
    DepartmentListResponse,
    DepartmentOut,
    PaginationMeta,
    TokenResponse,
    UserListItemOut,
    UserListResponse,
)


@dataclass(frozen=True, slots=True)
class AuthenticatedActor:
    """Thông tin đầy đủ của người dùng đang thao tác, luôn được nạp mới từ cơ sở dữ liệu."""

    user_id: str
    membership_id: str
    organization_id: str
    organization_slug: str
    email: str
    full_name: str
    user_kind: str
    customer_account_ref: str | None
    department: Department | None
    roles: frozenset[str]
    permissions: frozenset[str]


def _normalize_utc(dt: datetime) -> datetime:
    """Chuẩn hóa đối tượng thời gian về múi giờ UTC để so sánh an toàn trên cả SQLite và PostgreSQL."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_department_out(dept: Department | None) -> DepartmentOut | None:
    """Chuyển đổi bản ghi bảng `Department` sang khuôn mẫu đầu ra an toàn."""
    if dept is None:
        return None
    return DepartmentOut(
        id=dept.id,
        organization_id=dept.organization_id,
        code=dept.code,
        name=dept.name,
        description=dept.description,
        is_active=dept.is_active,
    )


def require_permission(actor: AuthenticatedActor, permission_code: str) -> None:
    """Kiểm tra người dùng hiện tại có sở hữu quyền cụ thể hay không.

    Ném `AuthorizationError` (mã HTTP 403) nếu thiếu quyền.
    """
    if permission_code not in actor.permissions:
        raise AuthorizationError(
            f"Tài khoản không có quyền `{permission_code}` để thực hiện thao tác này.",
            code="PERMISSION_DENIED",
        )


def require_employee(actor: AuthenticatedActor) -> None:
    """Đảm bảo chỉ nhân viên nội bộ mới được truy cập dữ liệu quản trị nội bộ."""
    if actor.user_kind != UserKind.EMPLOYEE.value:
        raise AuthorizationError(
            "Tài khoản khách hàng không được phép truy cập thông tin nội bộ của tổ chức.",
            code="INTERNAL_ONLY_RESOURCE",
        )


def require_same_organization(actor: AuthenticatedActor, target_organization_id: str) -> None:
    """Chặn mọi hành vi đọc hoặc ghi dữ liệu thuộc tổ chức khác."""
    if actor.organization_id != target_organization_id:
        raise AuthorizationError(
            "Không được phép truy cập dữ liệu ngoài tổ chức của bạn.",
            code="CROSS_ORGANIZATION_FORBIDDEN",
        )


async def login_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    organization_slug: str | None,
    settings: Settings,
) -> TokenResponse:
    """Xác thực tài khoản người dùng và phát hành cặp thẻ truy cập / làm mới JWT.

    Các bước xử lý:
    1. Tìm tài khoản theo email và kiểm tra tài khoản có đang hoạt động (`is_active`) không.
    2. Đối chiếu mật khẩu bằng thuật toán Argon2id.
    3. Tìm tư cách thành viên đang hoạt động trong tổ chức tương ứng.
    4. Tạo cặp thẻ `access_token` ngắn hạn và `refresh_token`, lưu mã băm thẻ làm mới xuống CSDL.
    """
    user = await repository.get_user_by_email(session, email)
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise AuthenticationError("Email hoặc mật khẩu không chính xác.", code="INVALID_CREDENTIALS")

    memberships = await repository.get_active_membership_for_login(
        session,
        user_id=user.id,
        organization_slug=organization_slug,
    )
    if not memberships:
        raise AuthenticationError(
            "Tài khoản chưa có tư cách thành viên hoạt động trong tổ chức.",
            code="MEMBERSHIP_INACTIVE",
        )
    if len(memberships) > 1 and not organization_slug:
        raise AuthenticationError(
            "Tài khoản thuộc nhiều tổ chức, vui lòng chỉ định mã tổ chức khi đăng nhập.",
            code="ORGANIZATION_REQUIRED",
        )

    membership = memberships[0]
    access_token, _, _ = create_access_token(
        user_id=user.id,
        organization_id=membership.organization_id,
        membership_id=membership.id,
        user_kind=membership.user_kind,
        settings=settings,
    )
    refresh_token, refresh_jti, refresh_exp = create_refresh_token(
        user_id=user.id,
        organization_id=membership.organization_id,
        membership_id=membership.id,
        settings=settings,
    )
    await repository.create_refresh_session(
        session,
        organization_id=membership.organization_id,
        membership_id=membership.id,
        jti=refresh_jti,
        token_hash=hash_token(refresh_token),
        expires_at=refresh_exp,
    )
    await session.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in_seconds=settings.jwt_access_token_expire_minutes * 60,
    )


async def refresh_user_tokens(
    session: AsyncSession,
    *,
    refresh_token: str,
    settings: Settings,
) -> TokenResponse:
    """Xoay vòng thẻ làm mới để cấp cặp thẻ mới an toàn và chống dùng lại thẻ cũ.

    Các bước bảo mật:
    1. Giải mã thẻ làm mới và kiểm tra loại thẻ phải là `refresh`.
    2. Tìm bản ghi phiên trong CSDL và đối chiếu mã băm SHA-256.
    3. Nếu phát hiện thẻ đã từng bị thu hồi (`revoked_at` khác rỗng) -> nghi ngờ bị đánh cắp,
       hệ thống thu hồi ngay toàn bộ phiên còn lại của thành viên đó và từ chối cấp thẻ mới.
    4. Kiểm tra tài khoản, tư cách thành viên và tổ chức vẫn đang hoạt động.
    5. Thu hồi thẻ cũ, ghi vết `replaced_by_jti` và phát hành cặp thẻ mới.
    """
    payload = decode_token(refresh_token, expected_type="refresh", settings=settings)
    jti = str(payload["jti"])
    org_id = str(payload["org_id"])
    membership_id = str(payload["mid"])

    session_record = await repository.get_refresh_session_by_jti(
        session,
        jti=jti,
        organization_id=org_id,
    )
    if session_record is None or session_record.token_hash != hash_token(refresh_token):
        raise AuthenticationError("Phiên làm mới không tồn tại hoặc không hợp lệ.", code="INVALID_REFRESH_TOKEN")

    if session_record.revoked_at is not None:
        # Phát hiện dùng lại thẻ cũ đã xoay vòng -> thu hồi toàn bộ phiên để bảo vệ tài khoản
        await repository.revoke_all_refresh_sessions_for_membership(
            session,
            membership_id=membership_id,
            organization_id=org_id,
        )
        await session.commit()
        raise AuthenticationError(
            "Thẻ làm mới đã bị sử dụng hoặc thu hồi. Toàn bộ phiên đã được đóng để bảo vệ tài khoản.",
            code="REFRESH_TOKEN_REUSED",
        )

    if _normalize_utc(session_record.expires_at) <= datetime.now(timezone.utc):
        raise AuthenticationError("Thẻ làm mới đã hết hạn.", code="REFRESH_TOKEN_EXPIRED")

    membership = await repository.get_membership_with_context(
        session,
        membership_id=membership_id,
        organization_id=org_id,
    )
    if (
        membership is None
        or membership.status != MembershipStatus.ACTIVE.value
        or not membership.user.is_active
        or not membership.organization.is_active
    ):
        raise AuthenticationError("Tài khoản hoặc tư cách thành viên không còn hoạt động.", code="ACTOR_INACTIVE")

    new_access, _, _ = create_access_token(
        user_id=membership.user_id,
        organization_id=membership.organization_id,
        membership_id=membership.id,
        user_kind=membership.user_kind,
        settings=settings,
    )
    new_refresh, new_jti, new_exp = create_refresh_token(
        user_id=membership.user_id,
        organization_id=membership.organization_id,
        membership_id=membership.id,
        settings=settings,
    )

    session_record.revoked_at = datetime.now(timezone.utc)
    session_record.replaced_by_jti = new_jti
    await repository.create_refresh_session(
        session,
        organization_id=membership.organization_id,
        membership_id=membership.id,
        jti=new_jti,
        token_hash=hash_token(new_refresh),
        expires_at=new_exp,
    )
    await session.commit()

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in_seconds=settings.jwt_access_token_expire_minutes * 60,
    )


async def logout_user(
    session: AsyncSession,
    *,
    refresh_token: str,
    settings: Settings,
) -> None:
    """Đăng xuất và vô hiệu hóa thẻ làm mới tương ứng trong cơ sở dữ liệu."""
    payload = decode_token(refresh_token, expected_type="refresh", settings=settings)
    session_record = await repository.get_refresh_session_by_jti(
        session,
        jti=str(payload["jti"]),
        organization_id=str(payload["org_id"]),
    )
    if session_record is not None and session_record.revoked_at is None:
        session_record.revoked_at = datetime.now(timezone.utc)
        await session.commit()


async def resolve_current_actor(
    session: AsyncSession,
    *,
    access_token: str,
    settings: Settings,
) -> AuthenticatedActor:
    """Giải mã thẻ truy cập và nạp mới hoàn toàn hồ sơ + quyền hạn từ cơ sở dữ liệu.

    Không bao giờ tin vào quyền cũ ghi trong token; nếu tài khoản vừa bị khóa hoặc
    vừa bị gỡ vai trò trong CSDL, lời gọi tiếp theo sẽ phản ánh ngay lập tức.
    """
    payload = decode_token(access_token, expected_type="access", settings=settings)
    membership_id = str(payload["mid"])
    org_id = str(payload["org_id"])
    user_id = str(payload["sub"])

    membership = await repository.get_membership_with_context(
        session,
        membership_id=membership_id,
        organization_id=org_id,
    )
    if (
        membership is None
        or membership.user_id != user_id
        or membership.status != MembershipStatus.ACTIVE.value
        or not membership.user.is_active
        or not membership.organization.is_active
    ):
        raise AuthenticationError("Tài khoản hoặc phiên thành viên không còn hiệu lực.", code="ACTOR_INACTIVE")

    roles, permissions = await repository.get_roles_and_permissions_for_membership(
        session,
        membership_id=membership.id,
        organization_id=membership.organization_id,
    )
    return AuthenticatedActor(
        user_id=membership.user.id,
        membership_id=membership.id,
        organization_id=membership.organization_id,
        organization_slug=membership.organization.slug,
        email=membership.user.email,
        full_name=membership.user.full_name,
        user_kind=membership.user_kind,
        customer_account_ref=membership.customer_account_ref,
        department=membership.department,
        roles=frozenset(roles),
        permissions=frozenset(permissions),
    )


def actor_to_out(actor: AuthenticatedActor) -> CurrentActorOut:
    """Chuyển thông tin người dùng hiện tại sang khuôn mẫu phản hồi API an toàn."""
    return CurrentActorOut(
        user_id=actor.user_id,
        membership_id=actor.membership_id,
        organization_id=actor.organization_id,
        organization_slug=actor.organization_slug,
        email=actor.email,
        full_name=actor.full_name,
        user_kind=actor.user_kind,
        customer_account_ref=actor.customer_account_ref,
        department=_to_department_out(actor.department),
        roles=sorted(actor.roles),
        permissions=sorted(actor.permissions),
    )


async def list_departments_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    page: int,
    page_size: int,
) -> DepartmentListResponse:
    """Trả danh sách phòng ban thuộc đúng tổ chức của nhân viên gọi API."""
    require_employee(actor)
    require_permission(actor, "departments:read")
    items, total = await repository.list_departments_by_org(
        session,
        organization_id=actor.organization_id,
        page=page,
        page_size=page_size,
    )
    return DepartmentListResponse(
        items=[_to_department_out(dept) for dept in items if dept is not None],
        pagination=PaginationMeta(page=page, page_size=page_size, total=total),
    )


async def list_users_for_actor(
    session: AsyncSession,
    *,
    actor: AuthenticatedActor,
    page: int,
    page_size: int,
    department_id: str | None = None,
    user_kind: str | None = None,
) -> UserListResponse:
    """Trả danh sách thành viên thuộc tổ chức của người gọi (chỉ dành cho Quản lý/Quản trị)."""
    require_employee(actor)
    require_permission(actor, "users:read")
    rows, total = await repository.list_memberships_by_org(
        session,
        organization_id=actor.organization_id,
        page=page,
        page_size=page_size,
        department_id=department_id,
        user_kind=user_kind,
    )
    items = [
        UserListItemOut(
            user_id=membership.user.id,
            membership_id=membership.id,
            organization_id=membership.organization_id,
            email=membership.user.email,
            full_name=membership.user.full_name,
            user_kind=membership.user_kind,
            status=membership.status,
            department=_to_department_out(membership.department),
            roles=role_codes,
        )
        for membership, role_codes in rows
    ]
    return UserListResponse(
        items=items,
        pagination=PaginationMeta(page=page, page_size=page_size, total=total),
    )
