"""Giao diện kiểm tra quy tắc an toàn cố định và quyết định phê duyệt bởi con người."""

from .schemas import AIAnalysisOutput, GuardianDecision


def evaluate_actions(analysis: AIAnalysisOutput) -> GuardianDecision:
    """Đánh giá kết quả phân tích ``AIAnalysisOutput`` và trả về quyết định ``GuardianDecision``.

    Bộ kiểm soát này chạy bằng quy tắc logic cố định (không phụ thuộc AI) nhằm:
    xác định các quy tắc an toàn bị kích hoạt, quyết định xem có cần người duyệt
    hay không, và chỉ giữ lại những hành động được phép thực thi tự động.
    """
    raise NotImplementedError
