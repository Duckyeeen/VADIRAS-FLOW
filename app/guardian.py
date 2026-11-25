"""Deterministic policy and human approval interface."""

from .schemas import AIAnalysisOutput, GuardianDecision


def evaluate_actions(analysis: AIAnalysisOutput) -> GuardianDecision:
    """Evaluate an ``AIAnalysisOutput`` and return a policy-bound ``GuardianDecision``.

    The decision identifies triggered rules, approval requirements, and only the
    permitted proposed actions for the request.
    """
    raise NotImplementedError
