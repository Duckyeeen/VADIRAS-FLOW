"""Giao diện phân tích yêu cầu có cấu trúc bằng trí tuệ nhân tạo (AI)."""

from .schemas import AIAnalysisOutput, InboundRequest, PreprocessedContext


def analyze_request(
    request: InboundRequest,
    context: PreprocessedContext,
) -> AIAnalysisOutput:
    """Phân tích yêu cầu ``InboundRequest`` dựa trên ngữ cảnh sạch ``PreprocessedContext``.

    Trả về kết quả ``AIAnalysisOutput`` đã được kiểm tra chặt cấu trúc, bao gồm:
    phân loại yêu cầu, mức độ ưu tiên, đánh giá rủi ro, bộ phận phụ trách phù hợp
    và danh sách hành động được đề xuất.
    """
    raise NotImplementedError
