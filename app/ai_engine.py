"""Structured AI analysis interface."""

from .schemas import AIAnalysisOutput, InboundRequest, PreprocessedContext


def analyze_request(
    request: InboundRequest,
    context: PreprocessedContext,
) -> AIAnalysisOutput:
    """Analyze an ``InboundRequest`` with its ``PreprocessedContext``.

    Returns the validated structured classification, risk, routing, and proposed
    actions as ``AIAnalysisOutput``.
    """
    raise NotImplementedError
