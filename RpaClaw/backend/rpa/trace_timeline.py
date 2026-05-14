from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .trace_models import RPAAcceptedTrace, RPATraceDiagnostic, RPATraceType


class RPATimelineItem(BaseModel):
    id: str
    kind: Literal["trace", "diagnostic"]
    trace_id: str | None = None
    diagnostic_id: str | None = None
    source: str = "manual"
    trace_type: str | None = None
    action: str = ""
    title: str = ""
    summary: str = ""
    url: str = ""
    frame_path: list[str] = Field(default_factory=list)
    locator: dict[str, Any] = Field(default_factory=dict)
    locator_candidates: list[dict[str, Any]] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
    value: Any = None
    sensitive: bool = False
    editable: bool = False
    deletable: bool = False
    order_ms: float | None = None
    raw_trace: dict[str, Any] | None = None
    raw_diagnostic: dict[str, Any] | None = None


def build_trace_timeline_items(
    *,
    traces: list[RPAAcceptedTrace],
    trace_diagnostics: list[RPATraceDiagnostic],
) -> list[RPATimelineItem]:
    items = [_trace_to_item(trace) for trace in traces]
    items.extend(_diagnostic_to_item(diagnostic) for diagnostic in trace_diagnostics)
    return sorted(items, key=lambda item: (item.order_ms is None, item.order_ms or 0, item.id))


def _trace_to_item(trace: RPAAcceptedTrace) -> RPATimelineItem:
    action = _trace_action(trace)
    title = _trace_title(trace, action)
    locator_candidates = deepcopy(list(trace.locator_candidates or []))
    locator_candidate = _first_locator_candidate(locator_candidates)
    locator = locator_candidate.get("locator", {}) if locator_candidate else {}
    trace_type = trace.trace_type.value if isinstance(trace.trace_type, RPATraceType) else str(trace.trace_type)
    is_manual = trace.trace_type == RPATraceType.MANUAL_ACTION or trace.source == "manual"

    return RPATimelineItem(
        id=f"trace:{trace.trace_id}",
        kind="trace",
        trace_id=trace.trace_id,
        source=trace.source,
        trace_type=trace_type,
        action=action,
        title=title,
        summary=trace.description or title,
        url=trace.after_page.url or trace.before_page.url,
        frame_path=list(trace.frame_path or []),
        locator=deepcopy(locator) if isinstance(locator, dict) else {},
        locator_candidates=locator_candidates,
        validation=deepcopy(dict(trace.validation or {})),
        value=deepcopy(trace.value),
        sensitive=bool(getattr(trace, "sensitive", False)),
        editable=bool(is_manual and trace.locator_candidates),
        deletable=True,
        order_ms=_trace_order_ms(trace),
        raw_trace=deepcopy(trace.model_dump(mode="json")),
    )


def _diagnostic_to_item(diagnostic: RPATraceDiagnostic) -> RPATimelineItem:
    raw = deepcopy(diagnostic.raw or {})
    candidates = raw.get("locator_candidates") if isinstance(raw, dict) else None
    locator_candidates = deepcopy(candidates) if isinstance(candidates, list) else []
    locator_candidate = _first_locator_candidate(locator_candidates)
    locator = locator_candidate.get("locator", {}) if locator_candidate else {}
    action = str(raw.get("action") or "diagnostic") if isinstance(raw, dict) else "diagnostic"
    title = diagnostic.message or action

    return RPATimelineItem(
        id=f"diagnostic:{diagnostic.diagnostic_id}",
        kind="diagnostic",
        trace_id=diagnostic.trace_id,
        diagnostic_id=diagnostic.diagnostic_id,
        source=diagnostic.source,
        action=action,
        title=title,
        summary=title,
        url=str(raw.get("url") or "") if isinstance(raw, dict) else "",
        frame_path=list(raw.get("frame_path") or []) if isinstance(raw, dict) else [],
        locator=deepcopy(locator) if isinstance(locator, dict) else {},
        locator_candidates=locator_candidates,
        validation=deepcopy(dict(raw.get("validation") or {})) if isinstance(raw, dict) else {},
        editable=False,
        deletable=True,
        order_ms=_diagnostic_order_ms(diagnostic),
        raw_diagnostic=deepcopy(diagnostic.model_dump(mode="json")),
    )


def _trace_order_ms(trace: RPAAcceptedTrace) -> float | None:
    recording = (trace.signals or {}).get("recording") if isinstance(trace.signals, dict) else None
    if isinstance(recording, dict):
        value = recording.get("event_timestamp_ms")
        if isinstance(value, (int, float)):
            return float(value)
    return _datetime_ms(getattr(trace, "started_at", None))


def _diagnostic_order_ms(diagnostic: RPATraceDiagnostic) -> float | None:
    raw = diagnostic.raw or {}
    signals = raw.get("signals") if isinstance(raw, dict) else None
    recording = signals.get("recording") if isinstance(signals, dict) else None
    if isinstance(recording, dict):
        value = recording.get("event_timestamp_ms")
        if isinstance(value, (int, float)):
            return float(value)
    return _datetime_ms(getattr(diagnostic, "timestamp", None))


def _datetime_ms(value: Any) -> float | None:
    if not isinstance(value, datetime):
        return None
    try:
        return value.timestamp() * 1000
    except OSError:
        return (value.replace(tzinfo=None) - datetime(1970, 1, 1)).total_seconds() * 1000


def _first_locator_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("selected") is True:
            return candidate
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def _trace_action(trace: RPAAcceptedTrace) -> str:
    if trace.action:
        return trace.action
    trace_type = trace.trace_type.value if isinstance(trace.trace_type, RPATraceType) else str(trace.trace_type)
    return trace_type or "trace"


def _trace_title(trace: RPAAcceptedTrace, action: str) -> str:
    return trace.description or trace.user_instruction or action
