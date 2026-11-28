"""Quản lý mã theo dõi xuyên suốt một lượt yêu cầu HTTP và tác vụ nền."""

from __future__ import annotations

from contextvars import ContextVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_HEADER = "X-Correlation-ID"

# Biến ngữ cảnh theo từng luồng xử lý bất đồng bộ để lưu mã theo dõi hiện tại
_correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Lấy mã theo dõi của lượt xử lý hiện tại.

    Trả về chuỗi rỗng nếu mã chưa được gán trong ngữ cảnh đang chạy.
    """
    return _correlation_id_ctx.get()


def set_correlation_id(value: str) -> None:
    """Gán mã theo dõi vào ngữ cảnh xử lý hiện tại."""
    _correlation_id_ctx.set(value)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Bộ đón đầu mỗi yêu cầu HTTP để đảm bảo luôn có mã theo dõi xuyên suốt.

    1. Đọc mã từ tiêu đề `X-Correlation-ID` nếu phía gọi có gửi kèm (tối đa 128 ký tự).
    2. Nếu chưa có hoặc rỗng, tự sinh mã UUID4 mới.
    3. Gán mã vào ngữ cảnh hiện tại và gắn lại vào tiêu đề phản hồi trả về cho người gọi.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        incoming_id = request.headers.get(CORRELATION_HEADER, "").strip()
        correlation_id = incoming_id[:128] if incoming_id else str(uuid4())
        token = _correlation_id_ctx.set(correlation_id)
        try:
            request.state.correlation_id = correlation_id
            response = await call_next(request)
            response.headers[CORRELATION_HEADER] = correlation_id
            return response
        finally:
            _correlation_id_ctx.reset(token)
