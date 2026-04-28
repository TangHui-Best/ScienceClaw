from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .trace_models import RPAAcceptedTrace, RPATraceDiagnostic


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
    editable: bool = False
    deletable: bool = False
    order_ms: float | None = None
    raw_trace: dict[str, Any] | None = None
    raw_diagnostic: dict[str, Any] | None = None


def build_trace_timeline_items(
    *,
    traces: list[RPAAcceptedTrace],
    diagnostics: list[RPATraceDiagnostic],
) -> list[RPATimelineItem]:
    keyed_items: list[tuple[bool, float, int, RPATimelineItem]] = []
    for index, trace in enumerate(traces):
        item = _trace_to_item(trace)
        keyed_items.append((item.order_ms is None, item.order_ms or 0, index, item))

    diagnostic_offset = len(traces)
    for index, diagnostic in enumerate(diagnostics):
        item = _diagnostic_to_item(diagnostic)
        keyed_items.append(
            (item.order_ms is None, item.order_ms or 0, diagnostic_offset + index, item)
        )

    return [
        item
        for _, _, _, item in sorted(
            keyed_items,
            key=lambda keyed_item: (keyed_item[0], keyed_item[1], keyed_item[2]),
        )
    ]


def _trace_to_item(trace: RPAAcceptedTrace) -> RPATimelineItem:
    locator_candidate = _first_locator_candidate(trace)
    locator = _candidate_locator(locator_candidate)
    action = _trace_action(trace)
    title = _trace_title(trace)
    summary = trace.description or trace.user_instruction or action

    return RPATimelineItem(
        id=trace.trace_id,
        kind="trace",
        trace_id=trace.trace_id,
        source=trace.source or "manual",
        trace_type=str(trace.trace_type.value if hasattr(trace.trace_type, "value") else trace.trace_type),
        action=action,
        title=title,
        summary=summary,
        url=_trace_url(trace),
        frame_path=list(trace.frame_path or []),
        locator=locator,
        locator_candidates=list(trace.locator_candidates or []),
        validation=dict(trace.validation or {}),
        editable=(trace.source == "manual" and bool(trace.locator_candidates)),
        deletable=True,
        order_ms=_trace_order_ms(trace),
        raw_trace=trace.model_dump(mode="json"),
    )


def _diagnostic_to_item(diagnostic: RPATraceDiagnostic) -> RPATimelineItem:
    raw = diagnostic.raw if isinstance(diagnostic.raw, dict) else {}
    locator_candidates = _raw_locator_candidates(raw)
    locator = _candidate_locator(_first_candidate(locator_candidates))
    action = _raw_string(raw, "action") or "diagnostic"
    message = diagnostic.message or "Trace diagnostic"

    return RPATimelineItem(
        id=diagnostic.diagnostic_id,
        kind="diagnostic",
        trace_id=diagnostic.trace_id,
        diagnostic_id=diagnostic.diagnostic_id,
        source=diagnostic.source or "manual",
        trace_type=_raw_string(raw, "trace_type") or None,
        action=action,
        title=message,
        summary=message,
        url=_raw_string(raw, "url"),
        frame_path=_raw_string_list(raw.get("frame_path")),
        locator=locator,
        locator_candidates=locator_candidates,
        validation=_raw_dict(raw.get("validation")),
        editable=False,
        deletable=True,
        order_ms=_diagnostic_order_ms(diagnostic),
        raw_diagnostic=diagnostic.model_dump(mode="json"),
    )


def _trace_order_ms(trace: RPAAcceptedTrace) -> float | None:
    recording = (trace.signals or {}).get("recording") if isinstance(trace.signals, dict) else None
    if isinstance(recording, dict):
        timestamp = _number(recording.get("event_timestamp_ms"))
        if timestamp is not None:
            return timestamp

    return _datetime_ms(getattr(trace, "started_at", None))


def _diagnostic_order_ms(diagnostic: RPATraceDiagnostic) -> float | None:
    raw = diagnostic.raw if isinstance(diagnostic.raw, dict) else {}
    recording = raw.get("signals", {}).get("recording") if isinstance(raw.get("signals"), dict) else None
    if isinstance(recording, dict):
        timestamp = _number(recording.get("event_timestamp_ms"))
        if timestamp is not None:
            return timestamp

    for key in ("event_timestamp_ms", "order_ms"):
        timestamp = _number(raw.get(key))
        if timestamp is not None:
            return timestamp

    return _datetime_ms(getattr(diagnostic, "timestamp", None))


def _first_locator_candidate(trace: RPAAcceptedTrace) -> dict[str, Any]:
    return _first_candidate(trace.locator_candidates)


def _first_candidate(candidates: list[dict[str, Any]] | Any) -> dict[str, Any]:
    if not isinstance(candidates, list):
        return {}

    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("selected") is True:
            return candidate
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def _candidate_locator(candidate: dict[str, Any]) -> dict[str, Any]:
    locator = candidate.get("locator") if isinstance(candidate, dict) else None
    if isinstance(locator, dict):
        return dict(locator)
    if candidate and all(key in candidate for key in ("method",)):
        return dict(candidate)
    return {}


def _trace_action(trace: RPAAcceptedTrace) -> str:
    if trace.action:
        return trace.action
    if trace.trace_type:
        return str(trace.trace_type.value if hasattr(trace.trace_type, "value") else trace.trace_type)
    return "trace"


def _trace_title(trace: RPAAcceptedTrace) -> str:
    return trace.description or trace.user_instruction or _trace_action(trace)


def _trace_url(trace: RPAAcceptedTrace) -> str:
    after_url = getattr(getattr(trace, "after_page", None), "url", "")
    before_url = getattr(getattr(trace, "before_page", None), "url", "")
    return after_url or before_url or ""


def _datetime_ms(value: Any) -> float | None:
    if not isinstance(value, datetime):
        return None
    try:
        return value.timestamp() * 1000
    except OSError:
        return (value.replace(tzinfo=None) - datetime(1970, 1, 1)).total_seconds() * 1000


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _raw_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    return value if isinstance(value, str) else ""


def _raw_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _raw_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _raw_locator_candidates(raw: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = raw.get("locator_candidates")
    if not isinstance(candidates, list):
        return []
    return [dict(candidate) for candidate in candidates if isinstance(candidate, dict)]
