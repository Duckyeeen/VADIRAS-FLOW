"""Khuôn mẫu dữ liệu vào/ra đã kiểm tra chặt chẽ cho phân hệ Định danh và Tổ chức."""

from __future__ import annotations

from pydantic import Field

from app.core.schemas import ContractModel


class LoginRequest(ContractModel):
    """Dữ liệu đầu vào khi người dùng đăng nhập bằng email và mật khẩu."""

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)
    organization_slug: str | None = Field(default=None, min_length=1, max_length=100)


class RefreshRequest(ContractModel):
    """Dữ liệu đầu vào khi xin cấp lại cặp thẻ truy cập mới."""

    refresh_token: str = Field(min_length=20, max_length=4096)


class LogoutRequest(ContractModel):
    """Dữ liệu đầu vào khi đăng xuất và thu hồi thẻ làm mới."""

    refresh_token: str = Field(min_length=20, max_length=4096)


class TokenResponse(ContractModel):
    """Cặp thẻ truy cập trả về sau khi đăng nhập hoặc xoay vòng phiên thành công."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


class DepartmentOut(ContractModel):
    """Thông tin hiển thị của một phòng ban trong tổ chức."""

    id: str
    organization_id: str
    code: str
    name: str
    description: str
    is_active: bool


class CurrentActorOut(ContractModel):
    """Hồ sơ đầy đủ của tài khoản đang đăng nhập (tuyệt đối không chứa mật khẩu)."""

    user_id: str
    membership_id: str
    organization_id: str
    organization_slug: str
    email: str
    full_name: str
    user_kind: str
    customer_account_ref: str | None
    department: DepartmentOut | None
    roles: list[str]
    permissions: list[str]


class UserListItemOut(ContractModel):
    """Thông tin một thành viên khi Quản lý hoặc Quản trị viên tra cứu danh sách."""

    user_id: str
    membership_id: str
    organization_id: str
    email: str
    full_name: str
    user_kind: str
    status: str
    department: DepartmentOut | None
    roles: list[str]


class PaginationMeta(ContractModel):
    """Thông tin phân trang chuẩn cho các danh sách kết quả."""

    page: int
    page_size: int
    total: int


class DepartmentListResponse(ContractModel):
    """Phản hồi danh sách phòng ban thuộc tổ chức của người gọi."""

    items: list[DepartmentOut]
    pagination: PaginationMeta


class UserListResponse(ContractModel):
    """Phản hồi danh sách người dùng có phân trang thuộc tổ chức của người gọi."""

    items: list[UserListItemOut]
    pagination: PaginationMeta
