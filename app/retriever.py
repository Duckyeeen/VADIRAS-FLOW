"""Knowledge base and historical ticket retrieval interface."""

from .schemas import PreprocessedContext


def retrieve_context(context: PreprocessedContext) -> PreprocessedContext:
    """Enrich ``PreprocessedContext`` with ranked KB and similar ticket matches.

    Returns the same contract type with ``retrieved_kb`` and ``similar_tickets``
    populated; input is the sanitized context from the validator.
    """
    raise NotImplementedError
