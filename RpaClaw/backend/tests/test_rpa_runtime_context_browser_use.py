from __future__ import annotations

from backend.rpa.runtime_context import runtime_requirements_from_traces
from backend.rpa.trace_models import RPAAcceptedTrace, RPAAIExecution, RPAPageState, RPATraceType


def test_browser_use_trace_marks_runtime_browser_use_requirement():
    trace = RPAAcceptedTrace(
        trace_type=RPATraceType.AI_OPERATION,
        source="browser_use",
        user_instruction="Select the matching account row",
        description="Select the matching account row",
        before_page=RPAPageState(url="https://example.test/accounts", title="Accounts"),
        after_page=RPAPageState(url="https://example.test/accounts/1", title="Account"),
        signals={
            "runtime_ai": {"preserve": True, "reason": "browser_use_recording"},
            "browser_use": {"actions": [{"click_element_by_index": {"index": 8}}]},
        },
        ai_execution=RPAAIExecution(language="browser_use", code="", output={"action_count": 1}),
    )

    assert runtime_requirements_from_traces([trace]) == {
        "runtime_ai": True,
        "browser_use": True,
    }
