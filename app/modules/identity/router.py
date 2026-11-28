"""Các tuyến API xác thực, xem hồ sơ cá nhân, phòng ban và danh sách thành viên."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_db_session

from . import service
from .dependencies import get_app_settings, get_current_actor
from .schemas import (
    CurrentActorOut,
    DepartmentListResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserListResponse,
)

router = APIRouter(prefix="/api/v1", tags=["Định danh & Tổ chức"])


@router.post("/auth/login", response_model=TokenResponse, summary="Đăng nhập lấy thẻ JWT")
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> TokenResponse:
    """Kiểm tra email/mật khẩu và cấp cặp thẻ truy cập/làm mới cho người dùng hợp lệ."""
    return await service.login_user(
        session,
        email=payload.email,
        password=payload.password,
        organization_slug=payload.organization_slug,
        settings=settings,
    )


@router.post("/auth/refresh", response_model=TokenResponse, summary="Cấp lại cặp thẻ JWT mới")
async def refresh_tokens(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> TokenResponse:
    """Xoay vòng thẻ làm mới dùng một lần để nhận thẻ truy cập mới an toàn."""
    return await service.refresh_user_tokens(
        session,
        refresh_token=payload.refresh_token,
        settings=settings,
    )


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Đăng xuất và thu hồi thẻ làm mới",
)
async def logout(
    payload: LogoutRequest,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> None:
    """Thu hồi thẻ làm mới để ngăn việc xin cấp lại thẻ truy cập sau khi đăng xuất."""
    await service.logout_user(
        session,
        refresh_token=payload.refresh_token,
        settings=settings,
    )


@router.get("/auth/me", response_model=CurrentActorOut, summary="Xem hồ sơ tài khoản hiện tại")
async def read_current_user(
    actor: service.AuthenticatedActor = Depends(get_current_actor),
) -> CurrentActorOut:
    """Trả thông tin tổ chức, phòng ban, vai trò và quyền mới nhất của tài khoản đang đăng nhập."""
    return service.actor_to_out(actor)


@router.get("/departments", response_model=DepartmentListResponse, summary="Danh sách phòng ban")
async def list_departments(
    page: int = Query(default=1, ge=1, description="Số trang cần lấy (bắt đầu từ 1)."),
    page_size: int = Query(default=20, ge=1, le=100, description="Số bản ghi tối đa mỗi trang."),
    actor: service.AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> DepartmentListResponse:
    """Lấy danh sách phòng ban thuộc đúng tổ chức của nhân viên gọi API."""
    return await service.list_departments_for_actor(
        session,
        actor=actor,
        page=page,
        page_size=page_size,
    )


@router.get("/users", response_model=UserListResponse, summary="Danh sách thành viên trong tổ chức")
async def list_users(
    page: int = Query(default=1, ge=1, description="Số trang cần lấy (bắt đầu từ 1)."),
    page_size: int = Query(default=20, ge=1, le=100, description="Số bản ghi tối đa mỗi trang."),
    department_id: str | None = Query(default=None, description="Lọc theo mã phòng ban."),
    user_kind: str | None = Query(default=None, description="Lọc theo loại tài khoản (EMPLOYEE/CUSTOMER_CONTACT)."),
    actor: service.AuthenticatedActor = Depends(get_current_actor),
    session: AsyncSession = Depends(get_db_session),
) -> UserListResponse:
    """Lấy danh sách thành viên trong tổ chức (chỉ Quản lý hoặc Quản trị viên có quyền `users:read`)."""
    return await service.list_users_for_actor(
        session,
        actor=actor,
        page=page,
        page_size=page_size,
        department_id=department_id,
        user_kind=user_kind,
    )
