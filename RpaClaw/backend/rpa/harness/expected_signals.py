from __future__ import annotations

from typing import Any

from .models import HarnessExpectedSignals, RecordingMode


def _first_trace_event(trace_events: list[dict[str, Any]]) -> dict[str, Any]:
    return trace_events[0] if trace_events else {}


def _target_evidence(trace_event: dict[str, Any]) -> dict[str, Any]:
    evidence = trace_event.get("target_evidence")
    if isinstance(evidence, dict):
        return evidence
    signals = trace_event.get("signals")
    if isinstance(signals, dict):
        evidence = signals.get("target_evidence")
        if isinstance(evidence, dict):
            return evidence
    locator_evidence = _selected_locator_evidence(trace_event)
    if locator_evidence:
        return locator_evidence
    return {}


def _selected_locator_evidence(trace_event: dict[str, Any]) -> dict[str, Any]:
    candidates = trace_event.get("locator_candidates")
    if not isinstance(candidates, list):
        return {}
    selected = next(
        (candidate for candidate in candidates if isinstance(candidate, dict) and candidate.get("selected") is True),
        None,
    )
    if selected is None:
        selected = next((candidate for candidate in candidates if isinstance(candidate, dict)), None)
    if not isinstance(selected, dict):
        return {}
    locator = selected.get("locator")
    if not isinstance(locator, dict):
        return {}
    method = str(locator.get("method") or "").strip()
    role = str(locator.get("role") or "").strip()
    name = str(locator.get("name") or locator.get("value") or "").strip()
    evidence: dict[str, Any] = {}
    if role:
        evidence["role"] = role
    elif method:
        evidence["role"] = method
    if name:
        evidence["text"] = name
    return evidence


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            text = _first_text(item)
            if text:
                return text
    return ""


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _output_shape(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {"type": "object", "keys": sorted(str(key) for key in value.keys())}
    if isinstance(value, list):
        return {"type": "array", "length": len(value)}
    if value is None:
        return {"type": "null"}
    return {"type": type(value).__name__}


def _non_empty_observed_strings(value: Any) -> list[str]:
    strings: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for item in node.values():
                visit(item)
            return
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if isinstance(node, str):
            _append_unique(strings, node.strip())

    visit(value)
    return strings


def _output_contract(trace_event: dict[str, Any]) -> dict[str, Any]:
    signals = trace_event.get("signals")
    if not isinstance(signals, dict):
        return {}
    contract = signals.get("output_contract")
    return contract if isinstance(contract, dict) else {}


def _selected_dataflow_ref(trace_event: dict[str, Any]) -> str:
    dataflow = trace_event.get("dataflow")
    if not isinstance(dataflow, dict):
        return ""
    return str(dataflow.get("selected_source_ref") or "").strip()


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _region_expected_signal(trace_event: dict[str, Any]) -> dict[str, Any]:
    region_scope = _dict_value(trace_event.get("region_scope"))
    region_context = _dict_value(trace_event.get("region_context"))
    signals = _dict_value(trace_event.get("signals"))
    region_selection = _dict_value(signals.get("region_selection"))

    region_id = str(
        region_scope.get("region_id")
        or region_context.get("region_id")
        or region_selection.get("region_id")
        or ""
    ).strip()
    if not region_id:
        return {}

    signal: dict[str, Any] = {"region_id": region_id}
    mode = str(region_scope.get("mode") or "region_scoped_snapshot").strip()
    if mode:
        signal["mode"] = mode
    frame_path = region_scope.get("frame_path") or region_context.get("frame_path")
    if isinstance(frame_path, list):
        signal["frame_path"] = [str(item) for item in frame_path if str(item)]
    inferred_kind = str(
        region_context.get("inferred_kind")
        or region_selection.get("inferred_kind")
        or ""
    ).strip()
    if inferred_kind:
        signal["inferred_kind"] = inferred_kind
    return signal


def build_expected_signal_draft(
    *,
    step_intent: str,
    recording_mode: RecordingMode,
    trace_events: list[dict[str, Any]],
) -> HarnessExpectedSignals:
    event = _first_trace_event(trace_events)
    evidence = _target_evidence(event)
    action = str(event.get("action") or event.get("type") or event.get("trace_type") or "").strip()
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

    region_signal = _region_expected_signal(event)
    if region_signal:
        snapshot_signals["must_preserve_region_scope"] = dict(region_signal)
        action_signals["region_selection"] = dict(region_signal)
        compiler_signals["must_preserve_region_context"] = {
            key: value
            for key, value in region_signal.items()
            if key in {"region_id", "inferred_kind", "frame_path"}
        }

    output_key = str(event.get("output_key") or "").strip()
    if output_key:
        state_signals["output_key"] = output_key
        compiler_signals["must_preserve_output_keys"] = [output_key]

    if "output" in event:
        output = event.get("output")
        state_signals["observed_output_shape"] = _output_shape(output)
        if _output_contract(event).get("allow_empty") is True:
            state_signals["allow_empty_output"] = True
        if not bool(event.get("sensitive")):
            observed_values = _non_empty_observed_strings(output)
            if observed_values:
                compiler_signals["must_not_hardcode_observed_values"] = observed_values

    dataflow_ref = _selected_dataflow_ref(event)
    if dataflow_ref:
        refs = list(compiler_signals.get("must_preserve_dataflow_refs") or [])
        _append_unique(refs, f"_resolve_result_ref(_results, {dataflow_ref!r})")
        compiler_signals["must_preserve_dataflow_refs"] = refs
        if not bool(event.get("sensitive")):
            observed_values = list(compiler_signals.get("must_not_hardcode_observed_values") or [])
            for value in _non_empty_observed_strings(event.get("value")):
                _append_unique(observed_values, value)
            if observed_values:
                compiler_signals["must_not_hardcode_observed_values"] = observed_values

    return HarnessExpectedSignals(
        snapshot_signals=snapshot_signals,
        action_signals=action_signals,
        compiler_signals=compiler_signals,
        state_signals=state_signals,
    )
