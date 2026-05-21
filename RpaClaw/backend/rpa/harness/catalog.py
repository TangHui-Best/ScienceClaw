from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import HarnessScenarioAsset, HarnessStepCheckpoint


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _host_from_url(url: str) -> str:
    if not url:
        return ""
    return urlparse(url).hostname or ""


def _unique_sorted(values: list[str]) -> list[str]:
    return sorted({value for value in values if value})


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _scenario_entry(asset_dir: Path, root: Path, warnings: list[dict[str, str]]) -> dict[str, Any]:
    scenario_path = asset_dir / "scenario.json"
    fallback = {
        "asset_id": asset_dir.name,
        "capture_scope": "unknown",
        "sop_intent": "",
        "asset_status": "draft",
        "sensitivity": "local-only",
        "governance": {
            "promotion_status": "captured",
            "runner_modes": ["offline_core_chain"],
            "core_chain_coverage": [],
            "expected_signals_reviewed": False,
            "sensitivity_reviewed": False,
            "review_notes": "",
        },
        "source": {},
        "page_patterns": [],
        "scenario_path": _relative(scenario_path, root) if scenario_path.exists() else "",
    }
    if not scenario_path.exists():
        return fallback
    try:
        scenario = HarnessScenarioAsset.model_validate(_load_json(scenario_path))
    except Exception as exc:
        warnings.append(
            {
                "asset_id": asset_dir.name,
                "path": _relative(scenario_path, root),
                "message": str(exc),
            }
        )
        return fallback
    return {
        "asset_id": scenario.asset_id,
        "capture_scope": scenario.capture_scope,
        "sop_intent": scenario.sop_intent,
        "asset_status": scenario.asset_status,
        "sensitivity": scenario.sensitivity,
        "governance": scenario.governance.model_dump(mode="json"),
        "source": scenario.source if isinstance(scenario.source, dict) else scenario.source.model_dump(mode="json"),
        "page_patterns": list(scenario.page_patterns),
        "scenario_path": _relative(scenario_path, root),
    }


def _step_entry(
    checkpoint_path: Path,
    root: Path,
    asset_id: str,
    warnings: list[dict[str, str]],
) -> dict[str, Any] | None:
    try:
        checkpoint = HarnessStepCheckpoint.model_validate(_load_json(checkpoint_path))
    except Exception as exc:
        warnings.append(
            {
                "asset_id": asset_id,
                "path": _relative(checkpoint_path, root),
                "message": str(exc),
            }
        )
        return None

    before_url = checkpoint.before.url
    after_url = checkpoint.after.url if checkpoint.after is not None else ""
    return {
        "asset_id": asset_id,
        "step_index": checkpoint.step_index,
        "step_id": checkpoint.step_id,
        "step_intent": checkpoint.step_intent,
        "recording_mode": checkpoint.recording_mode,
        "runtime_status": checkpoint.runtime_result.status,
        "before_url": before_url,
        "after_url": after_url,
        "before_title": checkpoint.before.title,
        "after_title": checkpoint.after.title if checkpoint.after is not None else "",
        "hosts": _unique_sorted([_host_from_url(before_url), _host_from_url(after_url)]),
        "page_patterns": list(checkpoint.page_patterns),
        "checkpoint_path": _relative(checkpoint_path, root),
        "expected_path": _relative(root / asset_id / checkpoint.expected_path, root) if checkpoint.expected_path else "",
        "failure_path": _relative(root / asset_id / checkpoint.failure_path, root) if checkpoint.failure_path else "",
    }


def build_harness_catalog(
    assets_root: str | Path,
    *,
    asset_ids: set[str] | None = None,
) -> dict[str, Any]:
    root = Path(assets_root)
    warnings: list[dict[str, str]] = []
    captures: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []

    asset_dirs = sorted(path for path in root.iterdir() if path.is_dir()) if root.exists() else []
    for asset_dir in asset_dirs:
        if asset_ids is not None and asset_dir.name not in asset_ids:
            continue
        capture = _scenario_entry(asset_dir, root, warnings)
        if asset_ids is not None and capture["asset_id"] not in asset_ids:
            continue
        asset_id = capture["asset_id"]
        checkpoint_paths = sorted(asset_dir.glob("steps/*/checkpoint.json"))
        capture_steps = [
            step
            for step in (
                _step_entry(checkpoint_path, root, asset_id, warnings)
                for checkpoint_path in checkpoint_paths
            )
            if step is not None
        ]
        capture["step_count"] = len(capture_steps)
        capture["successful_step_count"] = len(
            [step for step in capture_steps if step["runtime_status"] == "success"]
        )
        capture["failed_step_count"] = len([step for step in capture_steps if step["runtime_status"] == "failed"])
        captures.append(capture)
        steps.extend(capture_steps)

    recording_modes = Counter(step["recording_mode"] for step in steps)
    runtime_statuses = Counter(step["runtime_status"] for step in steps)
    asset_statuses = Counter(capture["asset_status"] for capture in captures)
    sensitivity = Counter(capture["sensitivity"] for capture in captures)
    promotion_statuses = Counter(capture["governance"]["promotion_status"] for capture in captures)
    runner_modes = Counter(
        mode
        for capture in captures
        for mode in capture["governance"].get("runner_modes", [])
    )
    core_chain_coverage = Counter(
        segment
        for capture in captures
        for segment in capture["governance"].get("core_chain_coverage", [])
    )
    page_patterns = _unique_sorted(
        [
            pattern
            for capture in captures
            for pattern in capture.get("page_patterns", [])
        ]
        + [pattern for step in steps for pattern in step["page_patterns"]]
    )
    hosts = _unique_sorted([host for step in steps for host in step["hosts"]])
    urls = _unique_sorted([step["before_url"] for step in steps] + [step["after_url"] for step in steps])
    successful = runtime_statuses.get("success", 0)
    failed = runtime_statuses.get("failed", 0)

    return {
        "schema_version": "rpa-harness-catalog-v0",
        "summary": {
            "capture_count": len(captures),
            "step_count": len(steps),
            "successful_step_count": successful,
            "failed_step_count": failed,
            "asset_statuses": _counter_dict(asset_statuses),
            "sensitivity": _counter_dict(sensitivity),
            "promotion_statuses": _counter_dict(promotion_statuses),
            "runner_modes": _counter_dict(runner_modes),
            "core_chain_coverage": _counter_dict(core_chain_coverage),
            "recording_modes": _counter_dict(recording_modes),
            "runtime_statuses": _counter_dict(runtime_statuses),
            "page_patterns": page_patterns,
            "hosts": hosts,
            "urls": urls,
        },
        "captures": captures,
        "steps": sorted(steps, key=lambda item: (item["asset_id"], item["step_index"])),
        "warnings": warnings,
    }
