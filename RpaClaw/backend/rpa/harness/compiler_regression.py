from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any, Callable

from backend.rpa.trace_models import RPAAcceptedTrace
from backend.rpa.trace_skill_compiler import TraceSkillCompiler

from .models import HarnessExpectedSignals, HarnessStepCheckpoint


Compiler = Callable[[list[dict[str, Any]], HarnessStepCheckpoint], str]


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _asset_id_for_checkpoint(assets_root: Path, checkpoint_path: Path) -> str:
    try:
        return checkpoint_path.relative_to(assets_root).parts[0]
    except Exception:
        return checkpoint_path.parent.parent.parent.name


def _default_compiler(trace_events: list[dict[str, Any]], _checkpoint: HarnessStepCheckpoint) -> str:
    traces = [
        RPAAcceptedTrace.model_validate(event)
        for event in trace_events
        if isinstance(event, dict) and event.get("trace_type")
    ]
    return TraceSkillCompiler().generate_script(traces, {}, is_local=True)


def _script_diff(baseline: str, current: str) -> str:
    if baseline == current:
        return ""
    return "".join(
        difflib.unified_diff(
            baseline.splitlines(keepends=True),
            current.splitlines(keepends=True),
            fromfile="baseline",
            tofile="current",
        )
    )


def _first_failure_category(
    hardcoded_values: list[str],
    missing_dataflow_refs: list[str],
) -> str:
    if hardcoded_values:
        return "compiler-hardcoded-observed-value"
    if missing_dataflow_refs:
        return "compiler-dataflow-lost"
    return ""


def run_compiler_regression(
    assets_root: str | Path,
    *,
    compiler: Compiler = _default_compiler,
) -> dict[str, Any]:
    root = Path(assets_root)
    items: list[dict[str, Any]] = []

    for checkpoint_path in sorted(root.glob("*/steps/*/checkpoint.json")):
        checkpoint = HarnessStepCheckpoint.model_validate(_load_json(checkpoint_path))
        capture_dir = checkpoint_path.parents[2]
        step_dir = checkpoint_path.parent
        trace_events = _load_json(capture_dir / checkpoint.action.trace_events_path)
        if not isinstance(trace_events, list):
            trace_events = []
        expected_payload = _load_json(capture_dir / checkpoint.expected_path)
        expected = HarnessExpectedSignals.model_validate(expected_payload)
        compiler_signals = expected.compiler_signals

        script = compiler(trace_events, checkpoint)
        forbidden_values = [
            value
            for value in compiler_signals.get("must_not_hardcode_observed_values", [])
            if isinstance(value, str)
        ]
        hardcoded_values = [value for value in forbidden_values if value and value in script]
        expected_refs = [
            value
            for value in compiler_signals.get("must_preserve_dataflow_refs", [])
            if isinstance(value, str)
        ]
        missing_dataflow_refs = [value for value in expected_refs if value and value not in script]

        baseline_path = step_dir / "baseline_skill.py"
        baseline = baseline_path.read_text(encoding="utf-8") if baseline_path.exists() else ""
        diff = _script_diff(baseline, script) if baseline else ""
        failure_category = _first_failure_category(hardcoded_values, missing_dataflow_refs)
        status = "failed" if failure_category else "passed"

        items.append(
            {
                "asset_id": _asset_id_for_checkpoint(root, checkpoint_path),
                "step_id": checkpoint.step_id,
                "step_index": checkpoint.step_index,
                "step_intent": checkpoint.step_intent,
                "page_patterns": checkpoint.page_patterns,
                "status": status,
                "failure_category": failure_category,
                "hardcoded_values": hardcoded_values,
                "missing_dataflow_refs": missing_dataflow_refs,
                "script_changed": bool(diff),
                "script_diff": diff,
            }
        )

    failed = len([item for item in items if item["status"] == "failed"])
    return {
        "summary": {
            "total": len(items),
            "passed": len(items) - failed,
            "failed": failed,
        },
        "assets": items,
    }

