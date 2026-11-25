"""Request validation, sanitization, and idempotency interface."""

from .schemas import InboundRequest, PreprocessedContext


def validate_and_sanitize(request: InboundRequest) -> PreprocessedContext:
    """Validate an ``InboundRequest`` and return sanitized ``PreprocessedContext``.

    The output includes the idempotency hash, duplicate flag, validation findings,
    PII redactions, and sanitized request text.
    """
    raise NotImplementedError
