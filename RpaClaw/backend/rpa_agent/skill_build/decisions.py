"""Pure deterministic eligibility decisions for frozen manual browser facts."""

from __future__ import annotations

from ..contracts.models import CoreTrace
from ..contracts.validators import validate_trace
from .contracts import CompileDecision


def decide_core_trace(trace: CoreTrace) -> CompileDecision:
    """Decide only from a frozen fact; no session, runtime, or AI history is read."""

    reason_codes: list[str] = []
    if trace.action.kind == "agent":
        reason_codes.append("manual_trace.agent_action_not_playwright")
    try:
        validate_trace(trace)
    except ValueError:
        reason_codes.append("manual_trace.fact_contract_invalid")
    return CompileDecision(
        trace_id=trace.trace_id,
        mode="playwright" if not reason_codes else "review_required",
        reason_codes=reason_codes,
    )
