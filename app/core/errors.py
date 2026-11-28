"""Định nghĩa hệ thống lỗi chuẩn và bộ chuyển đổi lỗi thống nhất cho mọi tuyến API."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .correlation import get_correlation_id


class AppError(Exception):
    """Lớp lỗi nền dùng chung cho toàn bộ tầng nghiệp vụ.

    Mỗi lỗi đều mang mã lỗi ổn định (`code`), thông báo dễ hiểu (`message`),
    mã trạng thái HTTP (`status_code`) và chi tiết bổ sung nếu cần (`details`).
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []


class AuthenticationError(AppError):
    """Lỗi khi người dùng chưa đăng nhập hoặc thông tin đăng nhập không hợp lệ."""

    def __init__(self, message: str = "Xác thực không thành công.", code: str = "AUTHENTICATION_FAILED") -> None:
        super().__init__(code=code, message=message, status_code=status.HTTP_401_UNAUTHORIZED)


class AuthorizationError(AppError):
    """Lỗi khi tài khoản không có quyền hoặc không thuộc phạm vi tổ chức/dữ liệu được phép."""

    def __init__(self, message: str = "Bạn không có quyền thực hiện thao tác này.", code: str = "FORBIDDEN") -> None:
        super().__init__(code=code, message=message, status_code=status.HTTP_403_FORBIDDEN)


class NotFoundError(AppError):
    """Lỗi khi không tìm thấy tài nguyên yêu cầu trong phạm vi tổ chức."""

    def __init__(self, message: str = "Không tìm thấy dữ liệu yêu cầu.", code: str = "NOT_FOUND") -> None:
        super().__init__(code=code, message=message, status_code=status.HTTP_404_NOT_FOUND)


class ConflictError(AppError):
    """Lỗi khi thao tác xung đột với trạng thái hiện tại hoặc trùng khóa duy nhất."""

    def __init__(self, message: str = "Dữ liệu bị xung đột với trạng thái hiện tại.", code: str = "CONFLICT") -> None:
        super().__init__(code=code, message=message, status_code=status.HTTP_409_CONFLICT)


class ValidationAppError(AppError):
    """Lỗi khi dữ liệu đầu vào vi phạm quy tắc kiểm tra nghiệp vụ."""

    def __init__(
        self,
        message: str = "Dữ liệu đầu vào không hợp lệ.",
        details: list[dict[str, Any]] | None = None,
        code: str = "VALIDATION_ERROR",
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=422,
            details=details,
        )


def _build_error_payload(
    *,
    request: Request,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Đóng gói cấu trúc phản hồi lỗi thống nhất kèm mã theo dõi `correlation_id`."""
    correlation_id = getattr(request.state, "correlation_id", "") or get_correlation_id() or "-"
    return {
        "error": {
            "code": code,
            "message": message,
            "correlation_id": correlation_id,
            "details": details or [],
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    """Đăng ký các bộ xử lý ngoại lệ tập trung lên ứng dụng FastAPI.

    Đảm bảo mọi lỗi nghiệp vụ, lỗi kiểm tra dữ liệu đầu vào và lỗi hệ thống bất ngờ
    đều trả về cùng một khuôn mẫu JSON, không làm lộ thông tin kỹ thuật nhạy cảm.
    """

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_build_error_payload(
                request=request,
                code=exc.code,
                message=exc.message,
                details=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        formatted_details = [
            {
                "location": ".".join(str(part) for part in err.get("loc", [])),
                "message": err.get("msg", "Giá trị không hợp lệ"),
                "type": err.get("type", "value_error"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_build_error_payload(
                request=request,
                code="VALIDATION_ERROR",
                message="Dữ liệu đầu vào không đúng định dạng yêu cầu.",
                details=formatted_details,
            ),
        )
