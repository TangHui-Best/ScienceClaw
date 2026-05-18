from __future__ import annotations

import difflib
import json
import tokenize
from io import StringIO
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
    missing_output_keys: list[str],
    missing_dataflow_refs: list[str],
) -> str:
    if hardcoded_values:
        return "compiler-hardcoded-observed-value"
    if missing_output_keys:
        return "compiler-output-key-lost"
    if missing_dataflow_refs:
        return "compiler-dataflow-lost"
    return ""


def _script_preserves_output_key(script: str, key: str) -> bool:
    single = repr(key)
    double = json.dumps(key, ensure_ascii=False)
    return (
        f"_results[{single}]" in script
        or f"_results[{double}]" in script
        or f", {single})" in script
        or f", {double})" in script
    )


def _split_executable_and_comment_text(script: str) -> tuple[str, str]:
    executable_parts: list[str] = []
    comment_parts: list[str] = []
    try:
        tokens = tokenize.generate_tokens(StringIO(script).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT:
                comment_parts.append(token.string)
            elif token.type not in {
                tokenize.ENCODING,
                tokenize.ENDMARKER,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.NL,
                tokenize.NEWLINE,
            }:
                executable_parts.append(token.string)
    except tokenize.TokenError:
        for line in script.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                comment_parts.append(line)
            else:
                executable_parts.append(line)
    return "\n".join(executable_parts), "\n".join(comment_parts)


def run_compiler_regression(
    assets_root: str | Path,
    *,
    compiler: Compiler = _default_compiler,
    asset_ids: set[str] | None = None,
) -> dict[str, Any]:
    root = Path(assets_root)
    items: list[dict[str, Any]] = []

    for checkpoint_path in sorted(root.glob("*/steps/*/checkpoint.json")):
        asset_id = _asset_id_for_checkpoint(root, checkpoint_path)
        if asset_ids is not None and asset_id not in asset_ids:
            continue
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
        executable_script, comment_script = _split_executable_and_comment_text(script)
        hardcoded_executable_values = [
            value for value in forbidden_values if value and value in executable_script
        ]
        hardcoded_comment_values = [
            value
            for value in forbidden_values
            if value and value in comment_script and value not in hardcoded_executable_values
        ]
        hardcoded_values = list(hardcoded_executable_values)
        expected_output_keys = [
            value
            for value in compiler_signals.get("must_preserve_output_keys", [])
            if isinstance(value, str)
        ]
        missing_output_keys = [
            value for value in expected_output_keys if value and not _script_preserves_output_key(script, value)
        ]
        expected_refs = [
            value
            for value in compiler_signals.get("must_preserve_dataflow_refs", [])
            if isinstance(value, str)
        ]
        missing_dataflow_refs = [value for value in expected_refs if value and value not in script]

        baseline_path = step_dir / "baseline_skill.py"
        baseline = baseline_path.read_text(encoding="utf-8") if baseline_path.exists() else ""
        diff = _script_diff(baseline, script) if baseline else ""
        failure_category = _first_failure_category(hardcoded_values, missing_output_keys, missing_dataflow_refs)
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
                "hardcoded_executable_values": hardcoded_executable_values,
                "hardcoded_comment_values": hardcoded_comment_values,
                "missing_output_keys": missing_output_keys,
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

