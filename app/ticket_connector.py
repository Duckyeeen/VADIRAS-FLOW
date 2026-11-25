"""External ticket creation interface."""

from .schemas import ExternalReferences, ProposedAction


def create_ticket(action: ProposedAction) -> ExternalReferences:
    """Execute an approved ticket ``ProposedAction`` and return ``ExternalReferences``.

    The output carries the created ticket identifier and URL when available.
    """
    raise NotImplementedError
