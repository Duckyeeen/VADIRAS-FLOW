"""Giao diện kiểm tra hợp lệ, lọc thông tin nhạy cảm và chống xử lý trùng lặp."""

from .schemas import InboundRequest, PreprocessedContext


def validate_and_sanitize(request: InboundRequest) -> PreprocessedContext:
    """Kiểm tra yêu cầu đầu vào ``InboundRequest`` và tạo ngữ cảnh sạch ``PreprocessedContext``.

    Hàm này thực hiện kiểm tra các trường bắt buộc, tạo mã băm chống trùng lặp,
    ẩn các thông tin cá nhân nhạy cảm (như email, số điện thoại) và làm sạch nội dung
    trước khi đưa sang bước tìm kiếm ngữ cảnh và phân tích AI.
    """
    raise NotImplementedError
