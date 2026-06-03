from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .asset_validation import validate_harness_assets
from .blast_radius import build_blast_radius_report
from .catalog import build_harness_catalog
from .compiler_regression import run_compiler_regression
from .observability import build_observability_contract
from .snapshot_regression import run_snapshot_regression
from .skill_replay import run_skill_replay_e2e
from .stateful_sop import run_stateful_sop_capture_to_skill


_GOVERNED_PROMOTIONS = {"candidate", "golden"}
_CANDIDATE_LITE_PROMOTION = "candidate-lite"


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


def _candidate_lite_observed_captures(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    observed: list[dict[str, Any]] = []
    for capture in catalog.get("captures", []):
        if not isinstance(capture, dict):
            continue
        governance = capture.get("governance") or {}
        if governance.get("promotion_status") != _CANDIDATE_LITE_PROMOTION:
            continue
        runner_modes = list(governance.get("runner_modes") or [])
        if not runner_modes:
            continue
        observed.append(
            {
                "asset_id": capture.get("asset_id") or "",
                "asset_status": capture.get("asset_status") or "unknown",
                "promotion_status": _CANDIDATE_LITE_PROMOTION,
                "runner_modes": runner_modes,
                "core_chain_coverage": list(governance.get("core_chain_coverage") or []),
                "page_patterns": list(capture.get("page_patterns") or []),
            }
        )
    return sorted(observed, key=lambda item: str(item["asset_id"]))


def _empty_candidate_lite_observation() -> dict[str, Any]:
    return {
        "schema_version": "rpa-harness-candidate-lite-observation-v0",
        "summary": {
            "status": "skipped",
            "observed_capture_count": 0,
            "observed_asset_ids": [],
            "warning_count": 0,
            "validation_issue_count": 0,
            "snapshot_failed": 0,
            "compiler_failed": 0,
            "skill_replay_failed": 0,
            "stateful_sop_failed": 0,
        },
        "selection": {"observed_captures": []},
        "catalog": {},
        "validation": {},
        "snapshot": {},
        "compiler": {},
        "skill_replay": {},
        "stateful_sop": {},
    }


def _candidate_lite_observation(
    root: Path,
    catalog: dict[str, Any],
    *,
    model_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observed_captures = _candidate_lite_observed_captures(catalog)
    observed_asset_ids = [
        str(capture["asset_id"])
        for capture in observed_captures
        if capture.get("asset_id")
    ]
    if not observed_asset_ids:
        return _empty_candidate_lite_observation()

    observed_id_set = set(observed_asset_ids)
    offline_id_set = {
        str(capture["asset_id"])
        for capture in observed_captures
        if "offline_core_chain" in set(capture.get("runner_modes") or [])
    }
    observed_catalog = build_harness_catalog(root, asset_ids=observed_id_set)
    validation = validate_harness_assets(root, asset_ids=observed_id_set)
    snapshot = run_snapshot_regression(root, asset_ids=offline_id_set)
    compiler = run_compiler_regression(root, asset_ids=offline_id_set)
    skill_replay = run_skill_replay_e2e(
        root,
        asset_ids=observed_id_set,
        model_config=model_config,
    )
    stateful_sop = run_stateful_sop_capture_to_skill(
        root,
        asset_ids=observed_id_set,
        include_candidate_lite=True,
        model_config=model_config,
    )
    warning_count = (
        validation["summary"]["issue_count"]
        + snapshot["summary"]["failed"]
        + compiler["summary"]["failed"]
        + skill_replay["summary"]["failed"]
        + stateful_sop["summary"]["failed"]
    )
    return {
        "schema_version": "rpa-harness-candidate-lite-observation-v0",
        "summary": {
            "status": "warning" if warning_count else "passed",
            "observed_capture_count": len(observed_captures),
            "observed_asset_ids": observed_asset_ids,
            "warning_count": warning_count,
            "validation_issue_count": validation["summary"]["issue_count"],
            "snapshot_failed": snapshot["summary"]["failed"],
            "compiler_failed": compiler["summary"]["failed"],
            "skill_replay_failed": skill_replay["summary"]["failed"],
            "stateful_sop_failed": stateful_sop["summary"]["failed"],
        },
        "selection": {"observed_captures": observed_captures},
        "catalog": observed_catalog,
        "validation": validation,
        "snapshot": snapshot,
        "compiler": compiler,
        "skill_replay": skill_replay,
        "stateful_sop": stateful_sop,
    }


def _report_status(
    *,
    selected_capture_count: int,
    validation: dict[str, Any],
    snapshot: dict[str, Any],
    compiler: dict[str, Any],
    skill_replay: dict[str, Any],
    stateful_sop: dict[str, Any],
    blast_radius: dict[str, Any],
) -> str:
    if selected_capture_count == 0:
        return "failed"
    if validation["summary"]["blocking_issue_count"]:
        return "failed"
    if snapshot["summary"]["failed"] or compiler["summary"]["failed"]:
        return "failed"
    if skill_replay["summary"]["failed"]:
        return "failed"
    if stateful_sop["summary"]["failed"]:
        return "failed"
    if blast_radius["summary"]["status"] == "failed":
        return "failed"
    return "passed"


def run_governed_offline_regression(
    assets_root: str | Path,
    *,
    model_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(assets_root)
    full_catalog = build_harness_catalog(root)
    selection = _selection(full_catalog)
    candidate_lite_observation = _candidate_lite_observation(
        root,
        full_catalog,
        model_config=model_config,
    )
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
    skill_replay = run_skill_replay_e2e(
        root,
        asset_ids=selected_id_set,
        model_config=model_config,
    )
    stateful_sop = run_stateful_sop_capture_to_skill(
        root,
        asset_ids=selected_id_set,
        model_config=model_config,
    )
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
        skill_replay=skill_replay,
        stateful_sop=stateful_sop,
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
    elif skill_replay["summary"]["failed"]:
        failure_category = "skill-replay-e2e-failed"
    elif stateful_sop["summary"]["failed"]:
        failure_category = "stateful-sop-capture-to-skill-failed"
    elif blast_radius["summary"]["status"] == "failed":
        failure_category = "blast-radius-failed"
    report = {
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
            "skill_replay_failed": skill_replay["summary"]["failed"],
            "stateful_sop_failed": stateful_sop["summary"]["failed"],
            "candidate_lite_observed_count": candidate_lite_observation["summary"][
                "observed_capture_count"
            ],
            "candidate_lite_warning_count": candidate_lite_observation["summary"][
                "warning_count"
            ],
        },
        "selection": selection,
        "candidate_lite_observation": candidate_lite_observation,
        "catalog": governed_catalog,
        "validation": validation,
        "snapshot": snapshot,
        "compiler": compiler,
        "skill_replay": skill_replay,
        "stateful_sop": stateful_sop,
        "blast_radius": blast_radius,
    }
    report["observability"] = build_observability_contract(report)
    return report
