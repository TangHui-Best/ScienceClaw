from __future__ import annotations

from typing import Any

from .models import HarnessExpectedSignals, RecordingMode


def _first_trace_event(trace_events: list[dict[str, Any]]) -> dict[str, Any]:
    return trace_events[0] if trace_events else {}


def _target_evidence(trace_event: dict[str, Any]) -> dict[str, Any]:
    evidence = trace_event.get("target_evidence")
    if isinstance(evidence, dict):
        return evidence
    return {}


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            text = _first_text(item)
            if text:
                return text
    return ""


def build_expected_signal_draft(
    *,
    step_intent: str,
    recording_mode: RecordingMode,
    trace_events: list[dict[str, Any]],
) -> HarnessExpectedSignals:
    event = _first_trace_event(trace_events)
    evidence = _target_evidence(event)
    action = str(event.get("action") or event.get("type") or "").strip()
    role = str(evidence.get("role") or "").strip()
    text = _first_text(evidence.get("text"))
    label = _first_text(evidence.get("label"))
    placeholder = _first_text(evidence.get("placeholder"))
    container_text = _first_text(evidence.get("container_text"))

    snapshot_signals: dict[str, Any] = {}
    action_signals: dict[str, Any] = {}
    compiler_signals: dict[str, Any] = {}
    state_signals: dict[str, Any] = {}

    if action:
        action_signals["expected_action_type"] = action
    if role:
        action_signals["target_role"] = role
    if text:
        action_signals["target_text_contains"] = text
        snapshot_signals["must_contain_text"] = [text]
    if label or placeholder:
        action_signals["target_label_or_placeholder"] = label or placeholder
    if container_text:
        snapshot_signals["must_preserve_target_container_context"] = True
    if action == "fill" and (label or placeholder or role == "textbox"):
        snapshot_signals["must_preserve_label_input_relation"] = True
        compiler_signals["input_value_policy"] = "parameterize"
    if recording_mode == "natural_language" and step_intent:
        action_signals["step_intent"] = step_intent

    return HarnessExpectedSignals(
        snapshot_signals=snapshot_signals,
        action_signals=action_signals,
        compiler_signals=compiler_signals,
        state_signals=state_signals,
    )

