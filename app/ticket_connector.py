"""Giao diện kết nối để tạo phiếu công việc trên hệ thống bên ngoài."""

from .schemas import ExternalReferences, ProposedAction


def create_ticket(action: ProposedAction) -> ExternalReferences:
    """Thực thi hành động tạo phiếu ``ProposedAction`` đã được duyệt và trả về ``ExternalReferences``.

    Kết quả trả về chứa mã phiếu và đường dẫn truy cập trên hệ thống bên ngoài (nếu có).
    """
    raise NotImplementedError
