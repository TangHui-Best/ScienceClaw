from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .trace_models import RPAAcceptedTrace


def trace_order_ms(trace: RPAAcceptedTrace) -> float | None:
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


def trace_order_sequence(trace: RPAAcceptedTrace) -> float | None:
    recording = (trace.signals or {}).get("recording") if isinstance(trace.signals, dict) else None
    if isinstance(recording, dict):
        value = recording.get("sequence")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def trace_order_key(trace: RPAAcceptedTrace, index: int) -> tuple[int, float, int, float, int]:
    order_ms = trace_order_ms(trace)
    sequence = trace_order_sequence(trace)
    return (
        0 if order_ms is not None else 1,
        order_ms or 0,
        0 if sequence is not None else 1,
        sequence or 0,
        index,
    )


def order_traces_by_recording_time(traces: Iterable[RPAAcceptedTrace]) -> list[RPAAcceptedTrace]:
    return [
        trace
        for _, trace in sorted(
            (trace_order_key(trace, index), trace)
            for index, trace in enumerate(list(traces))
        )
    ]
