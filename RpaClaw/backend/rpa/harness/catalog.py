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


def _counter_from_values(values: list[str]) -> dict[str, int]:
    return _counter_dict(Counter(value for value in values if value))


def _asset_lifecycle(capture: dict[str, Any]) -> str:
    governance = capture.get("governance") or {}
    promotion_status = str(governance.get("promotion_status") or "")
    if promotion_status == "captured":
        return "draft"
    return promotion_status or "unknown"


def _blocking_baseline_reasons(capture: dict[str, Any]) -> list[str]:
    governance = capture.get("governance") or {}
    reasons: list[str] = []
    asset_status = str(capture.get("asset_status") or "")
    promotion_status = str(governance.get("promotion_status") or "")
    runner_modes = set(governance.get("runner_modes") or [])
    core_chain_coverage = list(governance.get("core_chain_coverage") or [])
    if asset_status != "active":
        reasons.append(f"asset-status-{asset_status or 'unknown'}")
    if promotion_status not in {"candidate", "golden"}:
        reasons.append(f"promotion-status-{promotion_status or 'unknown'}")
    if "offline_core_chain" not in runner_modes:
        reasons.append("offline-core-chain-not-enabled")
    if not core_chain_coverage:
        reasons.append("missing-core-chain-coverage")
    if governance.get("expected_signals_reviewed") is not True:
        reasons.append("expected-signals-not-reviewed")
    if governance.get("sensitivity_reviewed") is not True:
        reasons.append("sensitivity-not-reviewed")
    return reasons


def _golden_eligibility_reasons(capture: dict[str, Any]) -> list[str]:
    governance = capture.get("governance") or {}
    reasons: list[str] = []
    asset_status = str(capture.get("asset_status") or "")
    promotion_status = str(governance.get("promotion_status") or "")
    runner_modes = set(governance.get("runner_modes") or [])
    core_chain_coverage = list(governance.get("core_chain_coverage") or [])
    if promotion_status != "candidate":
        reasons.append(f"promotion-status-{promotion_status or 'unknown'}")
    if asset_status != "active":
        reasons.append(f"asset-status-{asset_status or 'unknown'}")
    if governance.get("expected_signals_reviewed") is not True:
        reasons.append("expected-signals-not-reviewed")
    if governance.get("sensitivity_reviewed") is not True:
        reasons.append("sensitivity-not-reviewed")
    if "offline_core_chain" not in runner_modes:
        reasons.append("offline-core-chain-not-enabled")
    if not core_chain_coverage:
        reasons.append("missing-core-chain-coverage")
    return reasons


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


def build_asset_lifecycle_summary(
    assets_root: str | Path,
    *,
    asset_ids: set[str] | None = None,
    include_catalog: bool = False,
) -> dict[str, Any]:
    catalog = build_harness_catalog(assets_root, asset_ids=asset_ids)
    captures = [capture for capture in catalog.get("captures", []) if isinstance(capture, dict)]
    lifecycle_values = [_asset_lifecycle(capture) for capture in captures]
    blocking_baseline: list[str] = []
    warning_only: list[str] = []
    golden: list[str] = []
    lifecycle_warnings: list[dict[str, Any]] = []

    for capture in captures:
        asset_id = str(capture.get("asset_id") or "")
        governance = capture.get("governance") or {}
        promotion_status = str(governance.get("promotion_status") or "")
        if promotion_status == "candidate-lite" and asset_id:
            warning_only.append(asset_id)
        if promotion_status == "golden" and asset_id:
            golden.append(asset_id)

        reasons = _blocking_baseline_reasons(capture)
        if not reasons and asset_id:
            blocking_baseline.append(asset_id)
        elif promotion_status in {"candidate", "golden"} and asset_id:
            lifecycle_warnings.append({"asset_id": asset_id, "reasons": reasons})

    expected_reviewed = len(
        [
            capture
            for capture in captures
            if (capture.get("governance") or {}).get("expected_signals_reviewed") is True
        ]
    )
    sensitivity_reviewed = len(
        [
            capture
            for capture in captures
            if (capture.get("governance") or {}).get("sensitivity_reviewed") is True
        ]
    )
    summary = catalog.get("summary") or {}
    report = {
        "schema_version": "rpa-harness-asset-lifecycle-summary-v1",
        "summary": {
            "asset_count": len(captures),
            "lifecycle_distribution": _counter_from_values(lifecycle_values),
            "promotion_statuses": dict(summary.get("promotion_statuses") or {}),
            "asset_statuses": dict(summary.get("asset_statuses") or {}),
            "sensitivity": dict(summary.get("sensitivity") or {}),
        },
        "review_state": {
            "expected_signals_reviewed": expected_reviewed,
            "expected_signals_unreviewed": len(captures) - expected_reviewed,
            "sensitivity_reviewed": sensitivity_reviewed,
            "sensitivity_unreviewed": len(captures) - sensitivity_reviewed,
        },
        "blocking_baseline_asset_ids": sorted(blocking_baseline),
        "warning_only_asset_ids": sorted(warning_only),
        "golden_asset_ids": sorted(golden),
        "coverage_boundary": {
            "runner_modes": dict(summary.get("runner_modes") or {}),
            "core_chain_coverage": dict(summary.get("core_chain_coverage") or {}),
            "page_patterns": list(summary.get("page_patterns") or []),
            "hosts": list(summary.get("hosts") or []),
        },
        "lifecycle_warnings": sorted(lifecycle_warnings, key=lambda item: str(item["asset_id"])),
        "trust_limits": [
            "Current asset pool coverage is narrow",
            "bootstrap coverage does not prove global RPA health",
            "candidate-lite assets are warning-only and not blocking baseline",
            "golden eligibility is advisory until human approval",
        ],
    }
    if include_catalog:
        report["catalog"] = catalog
    return report


def build_golden_eligibility_report(
    assets_root: str | Path,
    *,
    asset_ids: set[str] | None = None,
) -> dict[str, Any]:
    lifecycle = build_asset_lifecycle_summary(
        assets_root,
        asset_ids=asset_ids,
        include_catalog=True,
    )
    captures = [
        capture
        for capture in lifecycle["catalog"].get("captures", [])
        if isinstance(capture, dict)
    ]
    assets: list[dict[str, Any]] = []
    for capture in captures:
        reasons = _golden_eligibility_reasons(capture)
        governance = capture.get("governance") or {}
        assets.append(
            {
                "asset_id": str(capture.get("asset_id") or ""),
                "eligible": not reasons,
                "requires_human_approval": True,
                "blocking_reasons": reasons,
                "asset_status": str(capture.get("asset_status") or "unknown"),
                "promotion_status": str(governance.get("promotion_status") or "unknown"),
                "expected_signals_reviewed": governance.get("expected_signals_reviewed") is True,
                "sensitivity_reviewed": governance.get("sensitivity_reviewed") is True,
                "runner_modes": list(governance.get("runner_modes") or []),
                "core_chain_coverage": list(governance.get("core_chain_coverage") or []),
            }
        )

    return {
        "schema_version": "rpa-harness-golden-eligibility-v1",
        "summary": {
            "asset_count": len(assets),
            "eligible_count": len([asset for asset in assets if asset["eligible"]]),
            "ineligible_count": len([asset for asset in assets if not asset["eligible"]]),
            "eligible_asset_ids": sorted(
                asset["asset_id"] for asset in assets if asset["eligible"] and asset["asset_id"]
            ),
        },
        "assets": sorted(assets, key=lambda item: str(item["asset_id"])),
        "lifecycle_summary": {
            "lifecycle_distribution": lifecycle["summary"]["lifecycle_distribution"],
            "blocking_baseline_asset_ids": lifecycle["blocking_baseline_asset_ids"],
            "warning_only_asset_ids": lifecycle["warning_only_asset_ids"],
            "trust_limits": lifecycle["trust_limits"],
        },
        "human_governance": {
            "required_for_promotion": True,
            "agents_may_recommend": True,
            "agents_may_promote_automatically": False,
        },
    }
