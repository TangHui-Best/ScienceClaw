from __future__ import annotations

import asyncio
import json
from json import JSONDecodeError
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from backend.rpa.recording_runtime_agent import RecordingRuntimeAgent
from backend.rpa.trace_models import RPAAcceptedTrace, RPAPageState, RPARuntimeResults
from backend.rpa.trace_recorder import (
    infer_dataflow_for_ai_fill,
    infer_dataflow_for_fill,
    manual_step_to_trace,
)
from backend.rpa.trace_skill_compiler import TraceSkillCompiler

from .models import HarnessExpectedSignals, HarnessScenarioAsset, HarnessStepCheckpoint
from .skill_replay import _install_controlled_replay_routes, _load_execute_skill


_GOVERNED_PROMOTIONS = {"candidate", "golden"}
_CANDIDATE_LITE_PROMOTION = "candidate-lite"
_RUNNER_MODE = "stateful_sop_capture_to_skill"


@dataclass
class _SessionBuildResult:
    traces: list[RPAAcceptedTrace]
    runtime_results: RPARuntimeResults
    steps: list[dict[str, Any]]


class _HarnessPage:
    def __init__(self, *, url: str, title: str) -> None:
        self.url = url
        self._title = title

    async def title(self) -> str:
        return self._title


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_required_json(path: Path, *, missing_category: str) -> Any:
    if not path.exists():
        raise FileNotFoundError(missing_category)
    return json.loads(path.read_text(encoding="utf-8"))


def _counter_dict(values: list[str]) -> dict[str, int]:
    counter = Counter(value for value in values if value)
    return {key: counter[key] for key in sorted(counter)}


def _asset_id_for_checkpoint(assets_root: Path, checkpoint_path: Path) -> str:
    try:
        return checkpoint_path.relative_to(assets_root).parts[0]
    except Exception:
        return checkpoint_path.parent.parent.parent.name


def _is_http_url(url: str) -> bool:
    return str(url or "").startswith(("http://", "https://"))


def _normalize_url(url: str) -> str:
    return str(url or "").split("#", 1)[0].rstrip("/")


def _asset_is_eligible(
    scenario: HarnessScenarioAsset,
    *,
    include_candidate_lite: bool = False,
) -> bool:
    governance = scenario.governance
    if (
        include_candidate_lite
        and scenario.capture_scope == "full_sop"
        and governance.promotion_status == _CANDIDATE_LITE_PROMOTION
    ):
        return _RUNNER_MODE in set(governance.runner_modes or [])
    return (
        scenario.capture_scope == "full_sop"
        and scenario.asset_status == "active"
        and governance.promotion_status in _GOVERNED_PROMOTIONS
        and _RUNNER_MODE in set(governance.runner_modes or [])
        and governance.expected_signals_reviewed is True
        and governance.sensitivity_reviewed is True
    )


def _checkpoint_paths(asset_dir: Path, scenario: HarnessScenarioAsset) -> list[Path]:
    refs = sorted(scenario.step_checkpoints, key=lambda ref: ref.step_index)
    if refs:
        return [asset_dir / ref.checkpoint_path for ref in refs]
    return sorted(asset_dir.glob("steps/*/checkpoint.json"))


def _selected_event(trace_events: Any) -> dict[str, Any]:
    if isinstance(trace_events, list):
        for event in trace_events:
            if (
                isinstance(event, dict)
                and event.get("trace_type")
                and event.get("accepted", True) is not False
            ):
                return event
    return {}


def _manual_step_payload(
    checkpoint: HarnessStepCheckpoint,
    event: dict[str, Any],
) -> dict[str, Any]:
    action = str(event.get("action") or "").strip()
    if not action and checkpoint.before.url != (checkpoint.after.url if checkpoint.after else ""):
        action = "navigate"
    payload = {
        "id": checkpoint.step_id.removeprefix("trace-") or f"step-{checkpoint.step_index}",
        "action": action or "unknown",
        "source": "record",
        "description": event.get("description") or checkpoint.step_intent,
        "before_url": checkpoint.before.url,
        "url": checkpoint.after.url if checkpoint.after is not None else checkpoint.before.url,
        "title": checkpoint.after.title if checkpoint.after is not None else checkpoint.before.title,
        "target": event.get("target") or event.get("value") or "",
        "locator_candidates": list(event.get("locator_candidates") or []),
        "validation": dict(event.get("validation") or {}),
        "signals": dict(event.get("signals") or {}),
        "value": event.get("value"),
        "result_key": event.get("output_key"),
        "output": event.get("output"),
        "sensitive": bool(event.get("sensitive") or False),
    }
    recording_signal = payload["signals"].get("recording")
    if isinstance(recording_signal, dict):
        payload["sequence"] = recording_signal.get("sequence")
        payload["event_timestamp_ms"] = recording_signal.get("event_timestamp_ms")
    tab_signal = payload["signals"].get("tab")
    if isinstance(tab_signal, dict):
        payload["tab_id"] = tab_signal.get("tab_id")
        payload["source_tab_id"] = tab_signal.get("source_tab_id")
        payload["target_tab_id"] = tab_signal.get("target_tab_id")
    return payload


def _trace_step_item(
    *,
    checkpoint: HarnessStepCheckpoint,
    input_boundary: str,
    status: str,
    failure_category: str = "",
    error: str = "",
) -> dict[str, Any]:
    return {
        "step_index": checkpoint.step_index,
        "step_id": checkpoint.step_id,
        "step_intent": checkpoint.step_intent,
        "recording_mode": checkpoint.recording_mode,
        "input_boundary": input_boundary,
        "status": status,
        "failure_category": failure_category,
        "error": error,
    }


async def _natural_language_trace_from_runtime_result(
    checkpoint: HarnessStepCheckpoint,
    event: dict[str, Any],
) -> RPAAcceptedTrace:
    after = checkpoint.after or checkpoint.before
    agent = RecordingRuntimeAgent()
    before = RPAPageState(url=checkpoint.before.url, title=checkpoint.before.title)
    ai_execution = event.get("ai_execution") if isinstance(event.get("ai_execution"), dict) else {}
    plan = {
        "description": event.get("description") or checkpoint.step_intent,
        "output_key": event.get("output_key"),
        "code": ai_execution.get("code") or "",
        "action_type": event.get("signals", {}).get("action_type") if isinstance(event.get("signals"), dict) else "",
    }
    result = {
        "output": event.get("output"),
        "error": ai_execution.get("error"),
        "signals": event.get("signals") if isinstance(event.get("signals"), dict) else {},
    }
    trace = await agent._accepted_trace(
        _HarnessPage(url=after.url, title=after.title),
        str(event.get("user_instruction") or checkpoint.step_intent),
        plan,
        result,
        before,
        repair_attempted=bool(ai_execution.get("repair_attempted") or False),
    )
    trace.trace_id = checkpoint.step_id or trace.trace_id
    trace.accepted = bool(event.get("accepted", True))
    return trace


async def _build_session_from_asset(
    asset_dir: Path,
    scenario: HarnessScenarioAsset,
    checkpoints: list[tuple[Path, HarnessStepCheckpoint]],
) -> _SessionBuildResult:
    traces: list[RPAAcceptedTrace] = []
    steps: list[dict[str, Any]] = []
    runtime_results = RPARuntimeResults()

    for _checkpoint_path, checkpoint in checkpoints:
        try:
            trace_path = asset_dir / checkpoint.action.trace_events_path
            trace_events = _load_required_json(
                trace_path,
                missing_category="missing-trace-events",
            )
            event = _selected_event(trace_events)
            if not event:
                raise ValueError("missing-accepted-trace")
            if checkpoint.recording_mode == "manual":
                trace = manual_step_to_trace(_manual_step_payload(checkpoint, event))
                trace.trace_id = checkpoint.step_id or trace.trace_id
                trace = infer_dataflow_for_fill(trace, runtime_results)
                boundary = "manual_recording_adapter"
            elif checkpoint.recording_mode == "natural_language":
                trace = await _natural_language_trace_from_runtime_result(checkpoint, event)
                trace = infer_dataflow_for_ai_fill(trace, runtime_results)
                boundary = "natural_language_runtime_result"
            else:
                raise ValueError(f"Unsupported recording_mode={checkpoint.recording_mode}")
            traces.append(trace)
            runtime_results.write(trace.output_key, trace.output)
            steps.append(_trace_step_item(checkpoint=checkpoint, input_boundary=boundary, status="passed"))
        except FileNotFoundError as exc:
            failure_category = str(exc) or "missing-trace-events"
            steps.append(
                _trace_step_item(
                    checkpoint=checkpoint,
                    input_boundary="recording_input_adapter",
                    status="failed",
                    failure_category=failure_category,
                    error=f"{type(exc).__name__}: {trace_path}",
                )
            )
        except JSONDecodeError as exc:
            steps.append(
                _trace_step_item(
                    checkpoint=checkpoint,
                    input_boundary="recording_input_adapter",
                    status="failed",
                    failure_category="invalid-trace-events",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
        except Exception as exc:
            failure_category = str(exc) if str(exc) == "missing-accepted-trace" else "capture-to-trace-error"
            steps.append(
                _trace_step_item(
                    checkpoint=checkpoint,
                    input_boundary="recording_input_adapter",
                    status="failed",
                    failure_category=failure_category,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return _SessionBuildResult(traces=traces, runtime_results=runtime_results, steps=steps)


def _compile_skill(traces: list[RPAAcceptedTrace]) -> str:
    return TraceSkillCompiler().generate_script(traces, {}, is_local=True)


def _url_html_map(asset_dir: Path, checkpoints: list[HarnessStepCheckpoint]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for checkpoint in checkpoints:
        for page_state in [checkpoint.before, checkpoint.after]:
            if page_state is None or not _is_http_url(page_state.url):
                continue
            html_path = asset_dir / page_state.html_path
            if html_path.exists():
                mapping[_normalize_url(page_state.url)] = html_path.read_text(encoding="utf-8")
    return mapping


def _expected_state_signals(asset_dir: Path, checkpoints: list[HarnessStepCheckpoint]) -> list[HarnessExpectedSignals]:
    expected: list[HarnessExpectedSignals] = []
    for checkpoint in checkpoints:
        payload = _load_json(asset_dir / checkpoint.expected_path) if checkpoint.expected_path else {}
        expected.append(HarnessExpectedSignals.model_validate(payload))
    return expected


def _json_contains_text(payload: Any, text: str) -> bool:
    return text in json.dumps(payload, ensure_ascii=False, default=str)


def _output_shape(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {"type": "object", "keys": sorted(str(key) for key in value.keys())}
    if isinstance(value, list):
        return {"type": "array", "length": len(value)}
    if value is None:
        return {"type": "null"}
    return {"type": type(value).__name__}


def _validate_expected_state_signals(
    results: dict[str, Any],
    expected_items: list[HarnessExpectedSignals],
) -> tuple[str, str, list[str]]:
    for expected in expected_items:
        signals = expected.state_signals
        if not signals:
            continue
        output_key = str(signals.get("output_key") or "").strip()
        required_text = [
            text for text in list(signals.get("must_contain_text") or []) if isinstance(text, str)
        ]
        if not output_key and not required_text:
            continue
        actual = results.get(output_key) if output_key else results
        if output_key and output_key not in results:
            return "failed", "controlled-replay-output-key-missing", []
        expected_shape = signals.get("observed_output_shape")
        if isinstance(expected_shape, dict) and expected_shape and _output_shape(actual) != expected_shape:
            return "failed", "controlled-replay-output-shape-mismatch", []
        missing_text = [text for text in required_text if not _json_contains_text(actual, text)]
        if missing_text:
            return "failed", "controlled-replay-output-missing-signal", missing_text
    return "passed", "", []


async def _replay_skill_against_stateful_provider(
    *,
    asset_dir: Path,
    checkpoints: list[HarnessStepCheckpoint],
    script: str,
) -> dict[str, Any]:
    if not checkpoints:
        return {"status": "skipped", "failure_category": "missing-checkpoints"}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(10000)
        page.set_default_navigation_timeout(10000)
        try:
            await _install_controlled_replay_routes(page, _url_html_map(asset_dir, checkpoints))
            first = checkpoints[0]
            if _is_http_url(first.before.url):
                await page.goto(first.before.url, wait_until="domcontentloaded")
            else:
                await page.set_content(
                    (asset_dir / first.before.html_path).read_text(encoding="utf-8"),
                    wait_until="domcontentloaded",
                )
            execute_skill = _load_execute_skill(script)
            results = await execute_skill(page)
            if not isinstance(results, dict):
                results = {"value": results}
            status, failure_category, missing_text = _validate_expected_state_signals(
                results,
                _expected_state_signals(asset_dir, checkpoints),
            )
            return {
                "status": status,
                "failure_category": failure_category,
                "actual_output": results,
                "missing_text": missing_text,
                "error": "",
            }
        except Exception as exc:
            return {
                "status": "failed",
                "failure_category": "controlled-replay-execution-error",
                "actual_output": {},
                "missing_text": [],
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            await page.close()
            await browser.close()


async def _run_asset(asset_dir: Path, scenario: HarnessScenarioAsset) -> dict[str, Any]:
    checkpoint_items: list[tuple[Path, HarnessStepCheckpoint]] = []
    load_failure: dict[str, Any] | None = None
    for path in _checkpoint_paths(asset_dir, scenario):
        try:
            checkpoint = HarnessStepCheckpoint.model_validate(
                _load_required_json(path, missing_category="missing-checkpoint")
            )
            checkpoint_items.append((path, checkpoint))
        except FileNotFoundError as exc:
            load_failure = {
                "status": "failed",
                "failure_category": str(exc) or "missing-checkpoint",
                "error": f"{type(exc).__name__}: {path}",
            }
            break
        except Exception as exc:
            load_failure = {
                "status": "failed",
                "failure_category": "invalid-checkpoint",
                "error": f"{type(exc).__name__}: {exc}",
            }
            break

    checkpoints = [checkpoint for _path, checkpoint in checkpoint_items]
    if load_failure is not None:
        return {
            "asset_id": scenario.asset_id,
            "status": "failed",
            "failure_category": load_failure["failure_category"],
            "sop_intent": scenario.sop_intent,
            "step_count": len(checkpoints),
            "accepted_trace_count": 0,
            "runtime_result_keys": [],
            "generated_skill_size": 0,
            "steps": [
                {
                    "step_index": 0,
                    "step_id": "",
                    "step_intent": "",
                    "recording_mode": "unknown",
                    "input_boundary": "scenario_asset_loader",
                    "status": "failed",
                    "failure_category": load_failure["failure_category"],
                    "error": load_failure["error"],
                }
            ],
            "replay": {"status": "skipped", "failure_category": "not-run"},
        }

    session = await _build_session_from_asset(asset_dir, scenario, checkpoint_items)
    failed_step = next((step for step in session.steps if step["status"] == "failed"), None)
    script = ""
    replay: dict[str, Any] = {"status": "skipped", "failure_category": "not-run"}
    failure_category = ""
    status = "passed"
    try:
        if failed_step is not None:
            status = "failed"
            failure_category = str(failed_step.get("failure_category") or "capture-to-trace-error")
        elif not session.traces:
            status = "failed"
            failure_category = "no-accepted-traces"
        else:
            script = _compile_skill(session.traces)
            replay = await _replay_skill_against_stateful_provider(
                asset_dir=asset_dir,
                checkpoints=checkpoints,
                script=script,
            )
            if replay["status"] == "failed":
                status = "failed"
                failure_category = str(replay.get("failure_category") or "controlled-replay-failed")
    except Exception as exc:
        status = "failed"
        failure_category = "skill-compile-error"
        replay = {
            "status": "skipped",
            "failure_category": failure_category,
            "actual_output": {},
            "missing_text": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    return {
        "asset_id": scenario.asset_id,
        "status": status,
        "failure_category": failure_category,
        "sop_intent": scenario.sop_intent,
        "step_count": len(checkpoints),
        "accepted_trace_count": len(session.traces),
        "runtime_result_keys": sorted(session.runtime_results.values.keys()),
        "generated_skill_size": len(script),
        "steps": session.steps,
        "replay": replay,
    }


def run_stateful_sop_capture_to_skill(
    assets_root: str | Path,
    *,
    asset_ids: set[str] | None = None,
    include_candidate_lite: bool = False,
) -> dict[str, Any]:
    root = Path(assets_root)
    eligible: list[tuple[Path, HarnessScenarioAsset]] = []

    for scenario_path in sorted(root.glob("*/scenario.json")):
        asset_dir = scenario_path.parent
        if asset_ids is not None and asset_dir.name not in asset_ids:
            continue
        try:
            scenario = HarnessScenarioAsset.model_validate(_load_json(scenario_path))
        except Exception:
            continue
        if asset_ids is not None and scenario.asset_id not in asset_ids:
            continue
        if _asset_is_eligible(scenario, include_candidate_lite=include_candidate_lite):
            eligible.append((asset_dir, scenario))

    async def run_all() -> list[dict[str, Any]]:
        return [await _run_asset(asset_dir, scenario) for asset_dir, scenario in eligible]

    items = asyncio.run(run_all()) if eligible else []
    failed = len([item for item in items if item["status"] == "failed"])
    return {
        "schema_version": "rpa-harness-stateful-sop-capture-to-skill-v0",
        "summary": {
            "status": "failed" if failed else "passed",
            "eligible_capture_count": len(eligible),
            "total": len(items),
            "passed": len(items) - failed,
            "failed": failed,
            "failure_categories": _counter_dict(
                [str(item.get("failure_category") or "") for item in items]
            ),
        },
        "assets": items,
    }
