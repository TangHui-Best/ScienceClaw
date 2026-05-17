from __future__ import annotations

from typing import Any

from .trace_ordering import order_traces_by_recording_time
from .trace_models import RPAAcceptedTrace, RPATraceType


def _first_locator_candidate(trace: RPAAcceptedTrace) -> dict[str, Any]:
    for candidate in trace.locator_candidates or []:
        if candidate.get("selected"):
            return candidate.get("locator") or candidate
    if trace.locator_candidates:
        candidate = trace.locator_candidates[0]
        return candidate.get("locator") or candidate
    return {}


def trace_to_mcp_step(trace: RPAAcceptedTrace) -> dict[str, Any]:
    locator = _first_locator_candidate(trace)
    if trace.trace_type == RPATraceType.AI_OPERATION:
        action = "ai_script"
        value = trace.ai_execution.code if trace.ai_execution else ""
    elif trace.trace_type == RPATraceType.NAVIGATION:
        action = "navigate"
        value = trace.value
    else:
        action = trace.action or trace.trace_type.value
        value = trace.value

    return {
        "id": trace.trace_id,
        "action": action,
        "target": locator,
        "frame_path": list(trace.frame_path or []),
        "locator_candidates": list(trace.locator_candidates or []),
        "validation": dict(trace.validation or {}),
        "signals": dict(trace.signals or {}),
        "value": value,
        "description": trace.description or trace.user_instruction or trace.trace_type.value,
        "label": trace.user_instruction or trace.action or trace.trace_type.value,
        "url": trace.after_page.url or "",
        "source": "ai" if trace.source == "ai" or trace.trace_type == RPATraceType.AI_OPERATION else "record",
        "prompt": trace.user_instruction,
        "result_key": trace.output_key,
        "configurable": False,
        "rpa_trace": trace.model_dump(mode="json"),
    }


def session_to_mcp_steps(session: Any) -> list[dict[str, Any]]:
    traces = list(getattr(session, "traces", None) or [])
    return [trace_to_mcp_step(trace) for trace in order_traces_by_recording_time(traces)]
