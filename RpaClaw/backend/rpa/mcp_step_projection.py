from __future__ import annotations

from datetime import datetime
from typing import Any

from .trace_models import RPAAcceptedTrace, RPATraceType


def _first_locator_candidate(trace: RPAAcceptedTrace) -> dict[str, Any]:
    for candidate in trace.locator_candidates or []:
        if candidate.get("selected"):
            return candidate.get("locator") or candidate
    if trace.locator_candidates:
        candidate = trace.locator_candidates[0]
        return candidate.get("locator") or candidate
    return {}


def _trace_order_ms(trace: RPAAcceptedTrace) -> float | None:
    recording = (trace.signals or {}).get("recording") if isinstance(trace.signals, dict) else None
    if isinstance(recording, dict):
        value = recording.get("event_timestamp_ms")
        if isinstance(value, (int, float)):
            return float(value)

    started_at = getattr(trace, "started_at", None)
    if started_at is not None:
        try:
            return started_at.timestamp() * 1000
        except OSError:
            return (
                started_at.replace(tzinfo=None) - datetime(1970, 1, 1)
            ).total_seconds() * 1000

    return None


def _trace_order_sequence(trace: RPAAcceptedTrace) -> float | None:
    recording = (trace.signals or {}).get("recording") if isinstance(trace.signals, dict) else None
    if isinstance(recording, dict):
        value = recording.get("sequence")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _order_projected_steps(projected: list[tuple[float | None, float | None, int, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [
        step
        for _, _, _, _, _, step in sorted(
            (
                (
                    0 if order_ms is not None else 1,
                    order_ms or 0,
                    0 if sequence is not None else 1,
                    sequence or 0,
                    index,
                    step,
                )
                for order_ms, sequence, index, step in projected
            ),
            key=lambda item: (item[0], item[1], item[2], item[3], item[4]),
        )
    ]


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
    return _order_projected_steps([
        (_trace_order_ms(trace), _trace_order_sequence(trace), index, trace_to_mcp_step(trace))
        for index, trace in enumerate(traces)
    ])
