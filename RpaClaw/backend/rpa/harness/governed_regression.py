from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .asset_validation import validate_harness_assets
from .blast_radius import build_blast_radius_report
from .catalog import build_harness_catalog
from .compiler_regression import run_compiler_regression
from .snapshot_regression import run_snapshot_regression


_GOVERNED_PROMOTIONS = {"candidate", "golden"}


def _counter_dict(values: list[str]) -> dict[str, int]:
    counter = Counter(value for value in values if value)
    return {key: counter[key] for key in sorted(counter)}


def _unique_sorted(values: list[str]) -> list[str]:
    return sorted({value for value in values if value})


def _exclusion_reasons(capture: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    governance = capture.get("governance") or {}
    asset_status = str(capture.get("asset_status") or "")
    promotion_status = str(governance.get("promotion_status") or "")
    runner_modes = set(governance.get("runner_modes") or [])
    core_chain_coverage = list(governance.get("core_chain_coverage") or [])

    if asset_status != "active":
        reasons.append(f"asset-status-{asset_status or 'unknown'}")
    if promotion_status not in _GOVERNED_PROMOTIONS:
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


def _selection(catalog: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for capture in catalog.get("captures", []):
        if not isinstance(capture, dict):
            continue
        reasons = _exclusion_reasons(capture)
        entry = {
            "asset_id": capture.get("asset_id") or "",
            "asset_status": capture.get("asset_status") or "unknown",
            "promotion_status": (capture.get("governance") or {}).get("promotion_status") or "unknown",
            "runner_modes": list((capture.get("governance") or {}).get("runner_modes") or []),
            "core_chain_coverage": list((capture.get("governance") or {}).get("core_chain_coverage") or []),
            "page_patterns": list(capture.get("page_patterns") or []),
        }
        if reasons:
            excluded.append({**entry, "reasons": reasons})
        else:
            selected.append(entry)
    return {
        "selected_captures": sorted(selected, key=lambda item: str(item["asset_id"])),
        "excluded_captures": sorted(excluded, key=lambda item: str(item["asset_id"])),
    }


def _report_status(
    *,
    selected_capture_count: int,
    validation: dict[str, Any],
    snapshot: dict[str, Any],
    compiler: dict[str, Any],
    blast_radius: dict[str, Any],
) -> str:
    if selected_capture_count == 0:
        return "failed"
    if validation["summary"]["blocking_issue_count"]:
        return "failed"
    if snapshot["summary"]["failed"] or compiler["summary"]["failed"]:
        return "failed"
    if blast_radius["summary"]["status"] == "failed":
        return "failed"
    return "passed"


def run_governed_offline_regression(assets_root: str | Path) -> dict[str, Any]:
    root = Path(assets_root)
    full_catalog = build_harness_catalog(root)
    selection = _selection(full_catalog)
    selected_asset_ids = [
        str(capture["asset_id"])
        for capture in selection["selected_captures"]
        if capture.get("asset_id")
    ]
    selected_id_set = set(selected_asset_ids)

    governed_catalog = build_harness_catalog(root, asset_ids=selected_id_set)
    validation = validate_harness_assets(root, asset_ids=selected_id_set)
    snapshot = run_snapshot_regression(root, asset_ids=selected_id_set)
    compiler = run_compiler_regression(root, asset_ids=selected_id_set)
    blast_radius = build_blast_radius_report(
        snapshot_report=snapshot,
        compiler_report=compiler,
        catalog=governed_catalog,
    )

    selected_captures = selection["selected_captures"]
    status = _report_status(
        selected_capture_count=len(selected_captures),
        validation=validation,
        snapshot=snapshot,
        compiler=compiler,
        blast_radius=blast_radius,
    )
    failure_category = ""
    if not selected_captures:
        failure_category = "no-governed-offline-assets"
    elif validation["summary"]["blocking_issue_count"]:
        failure_category = "governed-asset-validation-blocked"
    elif snapshot["summary"]["failed"]:
        failure_category = "snapshot-regression-failed"
    elif compiler["summary"]["failed"]:
        failure_category = "compiler-regression-failed"
    elif blast_radius["summary"]["status"] == "failed":
        failure_category = "blast-radius-failed"
    return {
        "schema_version": "rpa-harness-governed-offline-regression-v0",
        "summary": {
            "status": status,
            "failure_category": failure_category,
            "selected_capture_count": len(selected_captures),
            "excluded_capture_count": len(selection["excluded_captures"]),
            "selected_step_count": governed_catalog["summary"]["step_count"],
            "selected_asset_ids": selected_asset_ids,
            "excluded_asset_ids": [
                str(capture["asset_id"])
                for capture in selection["excluded_captures"]
                if capture.get("asset_id")
            ],
            "promotion_statuses": _counter_dict(
                [str(capture.get("promotion_status") or "") for capture in selected_captures]
            ),
            "page_patterns": _unique_sorted(
                [
                    pattern
                    for capture in selected_captures
                    for pattern in capture.get("page_patterns", [])
                ]
                + list(governed_catalog["summary"].get("page_patterns", []))
            ),
            "core_chain_coverage": governed_catalog["summary"].get("core_chain_coverage", {}),
            "validation_blocking_issue_count": validation["summary"]["blocking_issue_count"],
            "snapshot_failed": snapshot["summary"]["failed"],
            "compiler_failed": compiler["summary"]["failed"],
        },
        "selection": selection,
        "catalog": governed_catalog,
        "validation": validation,
        "snapshot": snapshot,
        "compiler": compiler,
        "blast_radius": blast_radius,
    }
