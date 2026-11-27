"""Giao diện kiểm tra thời hạn cam kết xử lý (SLA) của yêu cầu."""

from datetime import datetime

from .schemas import InboundRequest, WorkflowAuditRecord


def evaluate_sla(
    request: InboundRequest,
    audit_record: WorkflowAuditRecord,
    now: datetime | None = None,
) -> WorkflowAuditRecord:
    """Đánh giá trạng thái thời hạn xử lý của yêu cầu và cập nhật ``WorkflowAuditRecord``.

    Nhận vào yêu cầu gốc và bản ghi lịch sử trạng thái hiện tại; tham số ``now`` cho phép
    truyền vào một mốc thời gian có múi giờ để kiểm tra kết quả một cách nhất quán khi thử nghiệm.
    """
    raise NotImplementedError
