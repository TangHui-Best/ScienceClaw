from __future__ import annotations

from pathlib import Path
from typing import Any

from .governed_regression import run_governed_offline_regression


_DETERMINISTIC_PROFILE = "deterministic"


def _profile_metadata() -> dict[str, Any]:
    return {
        "name": _DETERMINISTIC_PROFILE,
        "execution_mode": "scripted-assets",
        "uses_live_planner": False,
        "uses_live_url_oracle": False,
        "governance_mode": "human-governed-assets",
    }


def _profile_summary(governed_report: dict[str, Any]) -> dict[str, Any]:
    governed_summary = governed_report.get("summary", {})
    status = str(governed_summary.get("status") or "unknown")
    return {
        "status": status,
        "blocking": status == "failed",
        "first_failure_category": str(governed_summary.get("failure_category") or ""),
        "selected_asset_count": int(governed_summary.get("selected_capture_count") or 0),
        "excluded_asset_count": int(governed_summary.get("excluded_capture_count") or 0),
        "selected_asset_ids": list(governed_summary.get("selected_asset_ids") or []),
        "excluded_asset_ids": list(governed_summary.get("excluded_asset_ids") or []),
        "warning_only_observation_count": int(
            governed_summary.get("candidate_lite_observed_count") or 0
        ),
        "warning_only_issue_count": int(
            governed_summary.get("candidate_lite_warning_count") or 0
        ),
    }


def run_harness_profile(
    assets_root: str | Path,
    *,
    profile: str = _DETERMINISTIC_PROFILE,
) -> dict[str, Any]:
    if profile != _DETERMINISTIC_PROFILE:
        raise ValueError(f"Unsupported RPA Harness profile: {profile}")

    governed_report = run_governed_offline_regression(assets_root)
    return {
        "schema_version": "rpa-harness-profile-run-v1",
        "profile": _profile_metadata(),
        "summary": _profile_summary(governed_report),
        "deterministic": governed_report,
    }


def _format_values(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def render_profile_summary(
    report: dict[str, Any],
    *,
    machine_report_path: str | Path | None = None,
    lang: str = "en",
) -> str:
    summary = report.get("summary", {})
    profile = report.get("profile", {})
    governed = report.get("deterministic", {})
    governed_summary = governed.get("summary", {})
    machine_path = str(machine_report_path) if machine_report_path else "not written"

    if lang == "zh":
        status = str(summary.get("status") or "unknown")
        lines = [
            f"RPA Harness Profile: {profile.get('name', 'unknown')}",
            f"状态: {status}",
            f"选中资产: {_format_values(list(summary.get('selected_asset_ids') or []))}",
            f"排除资产数: {summary.get('excluded_asset_count', 0)}",
            f"首个失败类别: {summary.get('first_failure_category') or 'none'}",
            (
                "Candidate-lite 观察: "
                f"assets={summary.get('warning_only_observation_count', 0)}, "
                f"warnings={summary.get('warning_only_issue_count', 0)}"
            ),
            f"机器报告: {machine_path}",
        ]
    else:
        lines = [
            f"RPA Harness Profile: {profile.get('name', 'unknown')}",
            f"Status: {summary.get('status', 'unknown')}",
            f"Selected assets: {_format_values(list(summary.get('selected_asset_ids') or []))}",
            f"Excluded asset count: {summary.get('excluded_asset_count', 0)}",
            f"First failure category: {summary.get('first_failure_category') or 'none'}",
            (
                "Candidate-lite observation: "
                f"assets={summary.get('warning_only_observation_count', 0)}, "
                f"warnings={summary.get('warning_only_issue_count', 0)}"
            ),
            f"Machine report: {machine_path}",
        ]

    if governed_summary:
        lines.append(
            "Governed runner: "
            f"snapshot_failed={governed_summary.get('snapshot_failed', 0)}, "
            f"compiler_failed={governed_summary.get('compiler_failed', 0)}, "
            f"skill_replay_failed={governed_summary.get('skill_replay_failed', 0)}, "
            f"stateful_sop_failed={governed_summary.get('stateful_sop_failed', 0)}"
        )
    return "\n".join(lines) + "\n"
