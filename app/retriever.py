"""Giao diện tìm kiếm tài liệu hướng dẫn và các phiếu xử lý tương tự trong quá khứ."""

from .schemas import PreprocessedContext


def retrieve_context(context: PreprocessedContext) -> PreprocessedContext:
    """Bổ sung tài liệu tham khảo và phiếu xử lý tương tự vào ``PreprocessedContext``.

    Nhận vào ngữ cảnh đã được làm sạch từ bước kiểm tra đầu vào, tìm các bài hướng dẫn
    và lịch sử xử lý liên quan nhất để điền vào hai danh sách ``retrieved_kb`` và
    ``similar_tickets``, rồi trả về đúng cấu trúc dữ liệu ban đầu.
    """
    raise NotImplementedError
