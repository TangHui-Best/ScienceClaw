from __future__ import annotations

import json
from collections import Counter
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .catalog import build_asset_lifecycle_summary, build_harness_catalog
from .models import HarnessScenarioAsset, HarnessStepCheckpoint


_MODE = "deterministic"
_GOVERNED_PROMOTIONS = {"candidate", "golden"}
_WARNING_ONLY_PROMOTION = "candidate-lite"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _counter_dict(values: list[str]) -> dict[str, int]:
    counter = Counter(value for value in values if value)
    return {key: counter[key] for key in sorted(counter)}


def _source_recording_id(scenario: HarnessScenarioAsset) -> str:
    if isinstance(scenario.source, dict):
        return str(scenario.source.get("recording_id") or "")
    return str(scenario.source.recording_id or "")


def _scenario_paths(root: Path) -> list[Path]:
    return sorted(root.glob("*/scenario.json")) if root.exists() else []


def _checkpoint_paths(asset_dir: Path, scenario: HarnessScenarioAsset) -> list[Path]:
    refs = sorted(scenario.step_checkpoints, key=lambda ref: ref.step_index)
    if refs:
        return [asset_dir / ref.checkpoint_path for ref in refs]
    return sorted(asset_dir.glob("steps/*/checkpoint.json"))


def _page_state(page: Any) -> dict[str, Any]:
    return {
        "url": str(getattr(page, "url", "") or ""),
        "title": str(getattr(page, "title", "") or ""),
        "html_path": str(getattr(page, "html_path", "") or ""),
    }


def _selected_trace_event(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and item.get("accepted", True) is not False:
                return item
    if isinstance(payload, dict) and payload.get("accepted", True) is not False:
        return payload
    return {}


def _replay_exclusion_reasons(capture: dict[str, Any]) -> list[str]:
    governance = capture.get("governance") or {}
    asset_status = str(capture.get("asset_status") or "")
    promotion_status = str(governance.get("promotion_status") or "")
    runner_modes = list(governance.get("runner_modes") or [])
    core_chain_coverage = list(governance.get("core_chain_coverage") or [])
    reasons: list[str] = []

    if asset_status != "active":
        reasons.append(f"asset-status-{asset_status or 'unknown'}")
    if promotion_status == _WARNING_ONLY_PROMOTION:
        if not runner_modes:
            reasons.append("missing-runner-mode")
        return reasons
    if promotion_status not in _GOVERNED_PROMOTIONS:
        reasons.append(f"promotion-status-{promotion_status or 'unknown'}")
    if governance.get("expected_signals_reviewed") is not True:
        reasons.append("expected-signals-not-reviewed")
    if governance.get("sensitivity_reviewed") is not True:
        reasons.append("sensitivity-not-reviewed")
    if "offline_core_chain" not in set(runner_modes):
        reasons.append("offline-core-chain-not-enabled")
    if not core_chain_coverage:
        reasons.append("missing-core-chain-coverage")
    return reasons


def _selection(catalog: dict[str, Any]) -> dict[str, Any]:
    blocking_assets: list[dict[str, Any]] = []
    warning_only_assets: list[dict[str, Any]] = []
    excluded_assets: list[dict[str, Any]] = []

    for capture in catalog.get("captures", []):
        if not isinstance(capture, dict):
            continue
        asset_id = str(capture.get("asset_id") or "")
        governance = capture.get("governance") or {}
        promotion_status = str(governance.get("promotion_status") or "")
        entry = {
            "asset_id": asset_id,
            "asset_status": str(capture.get("asset_status") or "unknown"),
            "promotion_status": promotion_status or "unknown",
            "lifecycle": "draft" if promotion_status == "captured" else promotion_status or "unknown",
            "runner_modes": list(governance.get("runner_modes") or []),
            "core_chain_coverage": list(governance.get("core_chain_coverage") or []),
            "page_patterns": list(capture.get("page_patterns") or []),
        }
        reasons = _replay_exclusion_reasons(capture)
        if reasons:
            excluded_assets.append({**entry, "reasons": reasons})
        elif promotion_status == _WARNING_ONLY_PROMOTION:
            warning_only_assets.append({**entry, "baseline_role": "warning-only"})
        else:
            blocking_assets.append({**entry, "baseline_role": "blocking"})

    return {
        "blocking_baseline_assets": sorted(blocking_assets, key=lambda item: item["asset_id"]),
        "warning_only_assets": sorted(warning_only_assets, key=lambda item: item["asset_id"]),
        "excluded_assets": sorted(excluded_assets, key=lambda item: item["asset_id"]),
        "blocking_baseline_asset_ids": sorted(item["asset_id"] for item in blocking_assets if item["asset_id"]),
        "warning_only_asset_ids": sorted(item["asset_id"] for item in warning_only_assets if item["asset_id"]),
        "excluded_asset_ids": sorted(item["asset_id"] for item in excluded_assets if item["asset_id"]),
    }


def _event_kind(checkpoint: HarnessStepCheckpoint, event: dict[str, Any]) -> str:
    source = str(event.get("source") or "").lower()
    trace_type = str(event.get("trace_type") or "").lower()
    if source == "ai" or trace_type == "ai_operation" or event.get("user_instruction"):
        return "natural_language_instruction"

    value = " ".join(
        [
            str(event.get("action") or ""),
            str(checkpoint.action.expected_action_type or ""),
            str(event.get("description") or ""),
        ]
    ).lower()
    if "select" in value:
        return "select"
    if "submit" in value or "press_enter" in value or "press enter" in value:
        return "submit"
    if "fill" in value or "type" in value or "input" in value:
        return "type"
    if "click" in value:
        return "click"
    if "navigate" in value or (
        checkpoint.after is not None and checkpoint.before.url != checkpoint.after.url
    ):
        return "navigation"
    return "unknown_input"


def _injected_boundary(event_kind: str) -> str:
    if event_kind == "navigation":
        return "scripted_navigation_boundary"
    if event_kind in {"click", "type", "select", "submit"}:
        return "scripted_manual_input_boundary"
    if event_kind == "natural_language_instruction":
        return "scripted_natural_language_instruction_boundary"
    return "scripted_recording_input_boundary"


def _region_context(checkpoint: HarnessStepCheckpoint, event: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    target_region = checkpoint.action.target_evidence.get("region")
    if isinstance(target_region, dict) and target_region:
        context["target_evidence"] = target_region
    event_region = event.get("region_context")
    if not isinstance(event_region, dict) or not event_region:
        event_region = event.get("region")
    if isinstance(event_region, dict) and event_region:
        context["event"] = event_region
    region_scope = event.get("region_scope")
    if isinstance(region_scope, dict) and region_scope:
        context["region_scope"] = region_scope
    signals = event.get("signals") if isinstance(event.get("signals"), dict) else {}
    signal_region = signals.get("region_selection") if isinstance(signals, dict) else None
    if not isinstance(signal_region, dict) or not signal_region:
        signal_region = signals.get("region") if isinstance(signals, dict) else None
    if isinstance(signal_region, dict) and signal_region:
        context["signals"] = signal_region
    return context


def _selected_locator(locator_candidates: list[Any]) -> dict[str, Any]:
    for candidate in locator_candidates:
        if isinstance(candidate, dict) and candidate.get("selected") is True:
            return candidate
    for candidate in locator_candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def _target(checkpoint: HarnessStepCheckpoint, event: dict[str, Any]) -> dict[str, Any]:
    target = dict(checkpoint.action.target_evidence or {})
    selected = _selected_locator(list(event.get("locator_candidates") or []))
    locator = selected.get("locator") if isinstance(selected, dict) else {}
    if isinstance(locator, dict):
        target.setdefault("role", locator.get("role", ""))
        target.setdefault("name", locator.get("name", ""))
        target.setdefault("method", locator.get("method", ""))
    if event.get("value") not in (None, ""):
        target.setdefault("value", event.get("value"))
    return {key: value for key, value in target.items() if value not in ("", None, [], {})}


def _result_id(asset_id: str, checkpoint: HarnessStepCheckpoint, event: dict[str, Any]) -> str:
    output_key = str(event.get("output_key") or "").strip()
    if output_key:
        return f"{asset_id}:{checkpoint.step_index}:{output_key}"
    trace_id = str(event.get("trace_id") or checkpoint.step_id or "").strip()
    return f"{asset_id}:{checkpoint.step_index}:{trace_id or 'no-result'}"


def _event_from_checkpoint(
    *,
    root: Path,
    asset_dir: Path,
    scenario: HarnessScenarioAsset,
    checkpoint_path: Path,
    checkpoint: HarnessStepCheckpoint,
    baseline_role: str,
    trace_event: dict[str, Any],
) -> dict[str, Any]:
    event_kind = _event_kind(checkpoint, trace_event)
    trace_id = str(trace_event.get("trace_id") or checkpoint.step_id or "")
    session_id = _source_recording_id(scenario) or scenario.asset_id
    checkpoint_rel = _relative(checkpoint_path, root)
    trace_events_rel = _relative(asset_dir / checkpoint.action.trace_events_path, root)
    target = _target(checkpoint, trace_event)
    region_context = _region_context(checkpoint, trace_event)
    output_key = trace_event.get("output_key")
    result_id = _result_id(scenario.asset_id, checkpoint, trace_event)
    runtime_result = {
        "status": checkpoint.runtime_result.status,
        "error": checkpoint.runtime_result.error or "",
    }
    ai_execution = trace_event.get("ai_execution") if isinstance(trace_event.get("ai_execution"), dict) else {}
    payload = {
        "action": trace_event.get("action"),
        "user_instruction": str(trace_event.get("user_instruction") or ""),
        "value": trace_event.get("value"),
        "target": target,
        "locator_candidates": list(trace_event.get("locator_candidates") or []),
        "selected_locator": _selected_locator(list(trace_event.get("locator_candidates") or [])),
        "region_context": region_context,
        "before_page": _page_state(checkpoint.before),
        "after_page": _page_state(checkpoint.after or checkpoint.before),
    }
    diagnostics = {
        "accepted": trace_event.get("accepted", True) is not False,
        "validation": dict(trace_event.get("validation") or {}),
        "signals": dict(trace_event.get("signals") or {}),
        "ai_execution_error": ai_execution.get("error"),
        "repair_attempted": bool(ai_execution.get("repair_attempted") or False),
        "diagnostics_ref": trace_event.get("diagnostics_ref"),
        "error": "",
    }
    return {
        "event_id": f"{scenario.asset_id}:{checkpoint.step_index}:{trace_id or 'event'}",
        "asset_id": scenario.asset_id,
        "baseline_role": baseline_role,
        "step_index": checkpoint.step_index,
        "step_id": checkpoint.step_id,
        "event_kind": event_kind,
        "source": str(trace_event.get("source") or checkpoint.recording_mode),
        "recording_mode": checkpoint.recording_mode,
        "user_instruction": str(trace_event.get("user_instruction") or ""),
        "description": str(trace_event.get("description") or checkpoint.step_intent),
        "step_intent": checkpoint.step_intent,
        "action": trace_event.get("action"),
        "value": trace_event.get("value"),
        "target": target,
        "locator_candidates": payload["locator_candidates"],
        "region_context": region_context,
        "before_page": payload["before_page"],
        "after_page": payload["after_page"],
        "checkpoint_path": checkpoint_rel,
        "trace_events_path": trace_events_rel,
        "injected_boundary": _injected_boundary(event_kind),
        "trace_id": trace_id,
        "session_id": session_id,
        "result_id": result_id,
        "output_key": output_key,
        "output_shape": _output_shape(trace_event.get("output")),
        "source_metadata": {
            "checkpoint_path": checkpoint_rel,
            "trace_events_path": trace_events_rel,
            "recording_mode": checkpoint.recording_mode,
            "trace_type": str(trace_event.get("trace_type") or ""),
        },
        "payload": payload,
        "result_refs": {
            "output_key": output_key,
            "output": trace_event.get("output"),
            "session_id": session_id,
            "trace_id": trace_id,
            "result_id": result_id,
        },
        "diagnostics": diagnostics,
        "runtime_result": runtime_result,
        "status": "passed",
        "failure_category": "",
        "error": "",
    }


def _output_shape(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {"type": "object", "keys": sorted(str(key) for key in value)}
    if isinstance(value, list):
        return {"type": "array", "length": len(value)}
    if value is None:
        return {"type": "null"}
    return {"type": type(value).__name__}


def _adapter_for_boundary(boundary: str) -> str:
    return {
        "scripted_navigation_boundary": "navigation_boundary_adapter",
        "scripted_manual_input_boundary": "manual_input_boundary_adapter",
        "scripted_natural_language_instruction_boundary": "natural_language_instruction_boundary_adapter",
        "scripted_recording_input_boundary": "recording_input_boundary_adapter",
    }.get(boundary, "recording_input_boundary_adapter")


def _execute_boundary_injection(event: dict[str, Any]) -> dict[str, Any]:
    boundary = str(event.get("injected_boundary") or "scripted_recording_input_boundary")
    status = "passed" if event.get("status") == "passed" else "skipped"
    failure_category = "" if status == "passed" else str(event.get("failure_category") or "event-not-replayable")
    return {
        "injection_id": f"{event.get('event_id', 'event')}:injection",
        "event_id": event.get("event_id", ""),
        "asset_id": event.get("asset_id", ""),
        "step_index": event.get("step_index", 0),
        "event_kind": event.get("event_kind", "unknown_input"),
        "boundary": boundary,
        "adapter": _adapter_for_boundary(boundary),
        "executed_by": "scripted_user_input_replay_adapter",
        "status": status,
        "failure_category": failure_category,
        "trace_id": event.get("trace_id", ""),
        "session_id": event.get("session_id", ""),
        "result_id": event.get("result_id", ""),
        "input_signal": {
            "action": event.get("action"),
            "user_instruction": event.get("user_instruction", ""),
            "value": event.get("value"),
            "target": dict(event.get("target") or {}),
            "region_context": dict(event.get("region_context") or {}),
        },
        "side_effects": "recorded-boundary-injection-only",
    }


def _attach_boundary_injections(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    injections: list[dict[str, Any]] = []
    for event in events:
        injection = _execute_boundary_injection(event)
        event["injection"] = {
            "injection_id": injection["injection_id"],
            "boundary": injection["boundary"],
            "adapter": injection["adapter"],
            "executed_by": injection["executed_by"],
            "status": injection["status"],
            "failure_category": injection["failure_category"],
        }
        injections.append(injection)
    return injections


def _failure_event(
    *,
    root: Path,
    asset_dir: Path,
    scenario: HarnessScenarioAsset,
    checkpoint_path: Path,
    checkpoint: HarnessStepCheckpoint | None,
    baseline_role: str,
    failure_category: str,
    error: str,
    trace_events_path: Path | None = None,
) -> dict[str, Any]:
    step_index = checkpoint.step_index if checkpoint is not None else 0
    step_id = checkpoint.step_id if checkpoint is not None else ""
    step_intent = checkpoint.step_intent if checkpoint is not None else ""
    before = _page_state(checkpoint.before) if checkpoint is not None else {}
    after = _page_state(checkpoint.after or checkpoint.before) if checkpoint is not None else {}
    trace_path = trace_events_path or (asset_dir / checkpoint.action.trace_events_path if checkpoint is not None else asset_dir)
    checkpoint_rel = _relative(checkpoint_path, root)
    trace_events_rel = _relative(trace_path, root)
    runtime_result = (
        {
            "status": checkpoint.runtime_result.status,
            "error": checkpoint.runtime_result.error or "",
        }
        if checkpoint is not None
        else {"status": "unknown", "error": ""}
    )
    return {
        "event_id": f"{scenario.asset_id}:{step_index}:failed",
        "asset_id": scenario.asset_id,
        "baseline_role": baseline_role,
        "step_index": step_index,
        "step_id": step_id,
        "event_kind": "unknown_input",
        "source": "asset",
        "recording_mode": checkpoint.recording_mode if checkpoint is not None else "unknown",
        "user_instruction": "",
        "description": step_intent,
        "step_intent": step_intent,
        "action": None,
        "value": None,
        "target": {},
        "locator_candidates": [],
        "region_context": {},
        "before_page": before,
        "after_page": after,
        "checkpoint_path": checkpoint_rel,
        "trace_events_path": trace_events_rel,
        "injected_boundary": "scripted_recording_input_boundary",
        "trace_id": step_id,
        "session_id": _source_recording_id(scenario) or scenario.asset_id,
        "result_id": f"{scenario.asset_id}:{step_index}:failed",
        "output_key": None,
        "output_shape": {"type": "null"},
        "source_metadata": {
            "checkpoint_path": checkpoint_rel,
            "trace_events_path": trace_events_rel,
            "recording_mode": checkpoint.recording_mode if checkpoint is not None else "unknown",
            "trace_type": "",
        },
        "payload": {
            "action": None,
            "user_instruction": "",
            "value": None,
            "target": {},
            "locator_candidates": [],
            "selected_locator": {},
            "region_context": {},
            "before_page": before,
            "after_page": after,
        },
        "result_refs": {
            "output_key": None,
            "output": None,
            "session_id": _source_recording_id(scenario) or scenario.asset_id,
            "trace_id": step_id,
            "result_id": f"{scenario.asset_id}:{step_index}:failed",
        },
        "diagnostics": {
            "accepted": False,
            "validation": {},
            "signals": {},
            "ai_execution_error": None,
            "repair_attempted": False,
            "diagnostics_ref": None,
            "error": error,
        },
        "runtime_result": runtime_result,
        "status": "failed",
        "failure_category": failure_category,
        "error": error,
    }


def _replay_asset(
    *,
    root: Path,
    asset_dir: Path,
    scenario: HarnessScenarioAsset,
    baseline_role: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for checkpoint_path in _checkpoint_paths(asset_dir, scenario):
        checkpoint: HarnessStepCheckpoint | None = None
        try:
            checkpoint = HarnessStepCheckpoint.model_validate(_load_json(checkpoint_path))
            trace_path = asset_dir / checkpoint.action.trace_events_path
            if not trace_path.exists():
                events.append(
                    _failure_event(
                        root=root,
                        asset_dir=asset_dir,
                        scenario=scenario,
                        checkpoint_path=checkpoint_path,
                        checkpoint=checkpoint,
                        baseline_role=baseline_role,
                        failure_category="missing-trace-events",
                        error=f"FileNotFoundError: {trace_path}",
                        trace_events_path=trace_path,
                    )
                )
                continue
            trace_payload = _load_json(trace_path)
            trace_event = _selected_trace_event(trace_payload)
            if not trace_event:
                events.append(
                    _failure_event(
                        root=root,
                        asset_dir=asset_dir,
                        scenario=scenario,
                        checkpoint_path=checkpoint_path,
                        checkpoint=checkpoint,
                        baseline_role=baseline_role,
                        failure_category="missing-accepted-trace",
                        error="No accepted trace event was found",
                        trace_events_path=trace_path,
                    )
                )
                continue
            events.append(
                _event_from_checkpoint(
                    root=root,
                    asset_dir=asset_dir,
                    scenario=scenario,
                    checkpoint_path=checkpoint_path,
                    checkpoint=checkpoint,
                    baseline_role=baseline_role,
                    trace_event=trace_event,
                )
            )
        except JSONDecodeError as exc:
            events.append(
                _failure_event(
                    root=root,
                    asset_dir=asset_dir,
                    scenario=scenario,
                    checkpoint_path=checkpoint_path,
                    checkpoint=checkpoint,
                    baseline_role=baseline_role,
                    failure_category="invalid-json",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
        except Exception as exc:
            events.append(
                _failure_event(
                    root=root,
                    asset_dir=asset_dir,
                    scenario=scenario,
                    checkpoint_path=checkpoint_path,
                    checkpoint=checkpoint,
                    baseline_role=baseline_role,
                    failure_category="replay-event-extraction-failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return events


def _load_selected_scenarios(
    root: Path,
    selected_assets: list[dict[str, Any]],
) -> list[tuple[Path, HarnessScenarioAsset, str]]:
    by_id = {item["asset_id"]: item["baseline_role"] for item in selected_assets}
    scenarios: list[tuple[Path, HarnessScenarioAsset, str]] = []
    for scenario_path in _scenario_paths(root):
        asset_dir = scenario_path.parent
        try:
            scenario = HarnessScenarioAsset.model_validate(_load_json(scenario_path))
        except Exception:
            continue
        baseline_role = by_id.get(scenario.asset_id)
        if baseline_role:
            scenarios.append((asset_dir, scenario, baseline_role))
    return sorted(scenarios, key=lambda item: item[1].asset_id)


def _summary(
    *,
    selected_assets: list[dict[str, Any]],
    warning_only_assets: list[dict[str, Any]],
    excluded_assets: list[dict[str, Any]],
    events: list[dict[str, Any]],
    boundary_injections: list[dict[str, Any]],
) -> dict[str, Any]:
    failures = [event for event in events if event.get("status") == "failed"]
    blocking_failures = [event for event in failures if event.get("baseline_role") == "blocking"]
    warning_failures = [event for event in failures if event.get("baseline_role") == "warning-only"]
    blocking_asset_count = len([asset for asset in selected_assets if asset["baseline_role"] == "blocking"])
    failure_category = ""
    if blocking_asset_count <= 0:
        failure_category = "no-replay-baseline-assets"
    elif blocking_failures:
        failure_category = "user-input-replay-failed"
    region_acquisitions = _counter_dict(
        [
            _region_acquisition(event.get("region_context"))
            for event in events
            if isinstance(event.get("region_context"), dict)
        ]
    )
    return {
        "status": "failed" if failure_category else "passed",
        "failure_category": failure_category,
        "mode": _MODE,
        "selected_asset_count": len(selected_assets),
        "blocking_asset_count": blocking_asset_count,
        "warning_only_asset_count": len(warning_only_assets),
        "excluded_asset_count": len(excluded_assets),
        "replayed_event_count": len(events),
        "passed_event_count": len([event for event in events if event.get("status") == "passed"]),
        "failed_event_count": len(failures),
        "blocking_failure_count": len(blocking_failures),
        "warning_only_failure_count": len(warning_failures),
        "boundary_injection_count": len(boundary_injections),
        "boundary_injection_failed_count": len(
            [item for item in boundary_injections if item.get("status") == "failed"]
        ),
        "boundary_injection_skipped_count": len(
            [item for item in boundary_injections if item.get("status") == "skipped"]
        ),
        "event_kinds": _counter_dict([str(event.get("event_kind") or "") for event in events]),
        "injected_boundaries": _counter_dict([str(event.get("injected_boundary") or "") for event in events]),
        "region_context_event_count": len(
            [event for event in events if event.get("region_context")]
        ),
        "region_acquisitions": region_acquisitions,
        "trace_ids": sorted({str(event.get("trace_id") or "") for event in events if event.get("trace_id")}),
        "session_ids": sorted({str(event.get("session_id") or "") for event in events if event.get("session_id")}),
        "result_ids": sorted({str(event.get("result_id") or "") for event in events if event.get("result_id")}),
    }


def _region_acquisition(region_context: Any) -> str:
    if not isinstance(region_context, dict):
        return ""
    for key in ("event", "target_evidence", "signals", "region_scope"):
        candidate = region_context.get(key)
        if isinstance(candidate, dict):
            acquisition = str(candidate.get("acquisition") or "").strip()
            if acquisition:
                return acquisition
    return str(region_context.get("acquisition") or "").strip()


def run_user_input_replay(
    assets_root: str | Path,
    *,
    mode: str = _MODE,
) -> dict[str, Any]:
    if mode != _MODE:
        raise ValueError(f"Unsupported RPA Harness user input replay mode: {mode}")

    root = Path(assets_root)
    catalog = build_harness_catalog(root)
    asset_pool = build_asset_lifecycle_summary(root)
    selection = _selection(catalog)
    selected_assets = selection["blocking_baseline_assets"] + selection["warning_only_assets"]
    events: list[dict[str, Any]] = []

    for asset_dir, scenario, baseline_role in _load_selected_scenarios(root, selected_assets):
        events.extend(
            _replay_asset(
                root=root,
                asset_dir=asset_dir,
                scenario=scenario,
                baseline_role=baseline_role,
            )
        )

    boundary_injections = _attach_boundary_injections(events)
    failures = [event for event in events if event.get("status") == "failed"]
    report_summary = _summary(
        selected_assets=selected_assets,
        warning_only_assets=selection["warning_only_assets"],
        excluded_assets=selection["excluded_assets"],
        events=events,
        boundary_injections=boundary_injections,
    )
    trust_limits = [
        "Current replay uses captured asset facts rather than live user operation",
        "Passing covered assets does not prove global RPA health",
        "candidate-lite assets are warning-only and not blocking baseline",
        "region selection is represented as generic user input context",
        "Agent explanations are advisory and cannot promote assets automatically",
    ]
    if report_summary["blocking_asset_count"] <= 0:
        trust_limits.insert(3, "No blocking replay baseline assets ran")

    return {
        "schema_version": "rpa-harness-user-input-replay-v1",
        "kind": "user_input_replay",
        "profile": {
            "name": _MODE,
            "execution_mode": "scripted-user-input-events",
            "uses_live_planner": False,
            "uses_live_url_oracle": False,
            "uses_outer_agent_ui_control": False,
            "governance_mode": "human-governed-assets",
        },
        "mode": _MODE,
        "summary": report_summary,
        "asset_pool": asset_pool,
        "selected_assets": selected_assets,
        "selection": selection,
        "warning_only_observation": {
            "asset_ids": selection["warning_only_asset_ids"],
            "blocking": False,
            "failure_count": report_summary["warning_only_failure_count"],
        },
        "replayed_input_events": events,
        "boundary_injections": boundary_injections,
        "failures": failures,
        "trace_session_result_ids": {
            "trace_ids": report_summary["trace_ids"],
            "session_ids": report_summary["session_ids"],
            "result_ids": report_summary["result_ids"],
        },
        "trust_limits": trust_limits,
        "governance_boundary": {
            "scripts_execute": True,
            "agents_explain": True,
            "humans_govern": True,
            "candidate_lite_warning_only": True,
            "agents_may_promote_automatically": False,
        },
    }


def _format_values(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _format_counts(values: dict[str, Any]) -> str:
    parts = [f"{key}={values[key]}" for key in sorted(values)]
    return ", ".join(parts) if parts else "none"


def render_user_input_replay_summary(
    report: dict[str, Any],
    *,
    machine_report_path: str | Path | None = None,
    lang: str = "en",
) -> str:
    summary = report.get("summary") or {}
    asset_pool = report.get("asset_pool") or {}
    selection = report.get("selection") or {}
    lifecycle_distribution = (asset_pool.get("summary") or {}).get("lifecycle_distribution") or {}
    machine_path = str(machine_report_path) if machine_report_path else "not written"
    boundaries = _format_counts(summary.get("injected_boundaries") or {})
    event_kinds = _format_counts(summary.get("event_kinds") or {})

    if lang == "zh":
        lines = [
            f"RPA Harness User Input Replay: {summary.get('mode', 'unknown')}",
            f"状态: {summary.get('status', 'unknown')}",
            f"Blocking assets: {_format_values(list(selection.get('blocking_baseline_asset_ids') or []))}",
            f"Warning-only assets: {_format_values(list(selection.get('warning_only_asset_ids') or []))}",
            f"Excluded assets: {_format_values(list(selection.get('excluded_asset_ids') or []))}",
            f"Lifecycle distribution: {_format_counts(lifecycle_distribution)}",
            f"Replayed events: {summary.get('replayed_event_count', 0)}",
            f"Boundary injections: {summary.get('boundary_injection_count', 0)}",
            f"Event kinds: {event_kinds}",
            f"Injected boundaries: {boundaries}",
            f"Blocking failures: {summary.get('blocking_failure_count', 0)}",
            f"Warning-only failures: {summary.get('warning_only_failure_count', 0)}",
            "Governance: Scripts execute; Agents explain; Humans govern",
            f"机器报告: {machine_path}",
        ]
    else:
        lines = [
            f"RPA Harness User Input Replay: {summary.get('mode', 'unknown')}",
            f"Status: {summary.get('status', 'unknown')}",
            f"Blocking assets: {_format_values(list(selection.get('blocking_baseline_asset_ids') or []))}",
            f"Warning-only assets: {_format_values(list(selection.get('warning_only_asset_ids') or []))}",
            f"Excluded assets: {_format_values(list(selection.get('excluded_asset_ids') or []))}",
            f"Lifecycle distribution: {_format_counts(lifecycle_distribution)}",
            f"Replayed events: {summary.get('replayed_event_count', 0)}",
            f"Boundary injections: {summary.get('boundary_injection_count', 0)}",
            f"Event kinds: {event_kinds}",
            f"Injected boundaries: {boundaries}",
            f"Blocking failures: {summary.get('blocking_failure_count', 0)}",
            f"Warning-only failures: {summary.get('warning_only_failure_count', 0)}",
            "Governance: Scripts execute; Agent may explain; humans govern promotion",
            f"Machine report: {machine_path}",
        ]
    return "\n".join(lines) + "\n"
