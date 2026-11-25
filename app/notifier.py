"""Customer notification interface."""

from .schemas import InboundRequest, ProposedAction


def send_notification(request: InboundRequest, action: ProposedAction) -> bool:
    """Send an approved customer message for an ``InboundRequest``.

    ``action`` supplies the target and draft message; return ``True`` when sent.
    """
    raise NotImplementedError
