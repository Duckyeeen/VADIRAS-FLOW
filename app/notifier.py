"""Giao diện gửi thông báo tới khách hàng hoặc người gửi yêu cầu."""

from .schemas import InboundRequest, ProposedAction


def send_notification(request: InboundRequest, action: ProposedAction) -> bool:
    """Gửi thông báo đã được cho phép đối với yêu cầu ``InboundRequest``.

    Tham số ``action`` cung cấp đích nhận và nội dung bản nháp; hàm trả về ``True``
    khi thông báo đã được gửi đi thành công.
    """
    raise NotImplementedError
