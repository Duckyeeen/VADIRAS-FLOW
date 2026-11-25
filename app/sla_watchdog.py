"""SLA status evaluation interface."""

from datetime import datetime

from .schemas import InboundRequest, WorkflowAuditRecord


def evaluate_sla(
    request: InboundRequest,
    audit_record: WorkflowAuditRecord,
    now: datetime | None = None,
) -> WorkflowAuditRecord:
    """Evaluate a request's SLA and return its updated ``WorkflowAuditRecord``.

    Inputs are the source request and current audit state; ``now`` optionally
    supplies the timezone-aware evaluation time for deterministic checks.
    """
    raise NotImplementedError
