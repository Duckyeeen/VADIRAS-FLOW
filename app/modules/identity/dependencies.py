"""Các hàm phụ thuộc FastAPI phục vụ xác thực và kiểm tra quyền tại các tuyến API."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError
from app.db.session import get_db_session

from .service import AuthenticatedActor, require_permission, resolve_current_actor

# Bộ tách Bearer token (đặt auto_error=False để chủ động trả về mã lỗi chuẩn của hệ thống)
_bearer_scheme = HTTPBearer(auto_error=False)


def get_app_settings(request: Request) -> Settings:
    """Lấy cấu hình ứng dụng hiện tại (ưu tiên cấu hình đã gắn trên `app.state` nếu có)."""
    return getattr(request.app.state, "settings", None) or get_settings()


async def get_current_actor(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> AuthenticatedActor:
    """Xác thực thẻ JWT từ tiêu đề `Authorization` và nạp quyền mới nhất từ CSDL.

    Đầu vào: yêu cầu HTTP hiện tại, cặp chứng thực Bearer và phiên CSDL.
    Đầu ra: đối tượng `AuthenticatedActor` đã được xác minh đầy đủ.
    """
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise AuthenticationError("Thiếu thẻ xác thực Bearer trong yêu cầu.", code="MISSING_TOKEN")

    settings = get_app_settings(request)
    return await resolve_current_actor(
        session,
        access_token=credentials.credentials,
        settings=settings,
    )


def require_permissions(
    *permission_codes: str,
) -> Callable[..., Coroutine[Any, Any, AuthenticatedActor]]:
    """Tạo bộ kiểm tra quyền gắn vào tuyến API.

    Đảm bảo người gọi đã đăng nhập hợp lệ và có đầy đủ tất cả mã quyền được liệt kê.
    """

    async def _dependency(
        actor: AuthenticatedActor = Depends(get_current_actor),
    ) -> AuthenticatedActor:
        for code in permission_codes:
            require_permission(actor, code)
        return actor

    return _dependency
