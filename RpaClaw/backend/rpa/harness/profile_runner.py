from __future__ import annotations

from pathlib import Path
from typing import Any

from .catalog import build_asset_lifecycle_summary
from .governed_regression import run_governed_offline_regression


_DETERMINISTIC_PROFILE = "deterministic"
_FULL_LIVE_PROFILE = "full-live"


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


def _profile_interpretation(
    governed_report: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    status = str(summary.get("status") or "unknown")
    selected_asset_count = int(summary.get("selected_asset_count") or 0)
    first_failure_category = str(summary.get("first_failure_category") or "")
    observability = governed_report.get("observability") or {}
    runner_signals = observability.get("runner_signals")
    runner_signals_missing = not isinstance(runner_signals, dict) or not runner_signals

    evidence_limits = ["No baseline comparison report was supplied"]
    if selected_asset_count <= 0:
        verdict = "insufficient evidence"
        evidence_limits.append("No selected governed assets ran")
    elif runner_signals_missing:
        verdict = "insufficient evidence"
        evidence_limits.append("Missing deterministic.observability.runner_signals")
    elif status == "failed":
        verdict = "regression"
    elif status == "passed":
        verdict = "no meaningful change"
        evidence_limits.append("Passing covered assets does not prove global RPA health")
    else:
        verdict = "insufficient evidence"
        evidence_limits.append(f"Profile status is not interpretable: {status}")

    return {
        "verdict": verdict,
        "bounded": True,
        "comparison_basis": "single-run",
        "first_failure_category": first_failure_category,
        "basis": [
            f"summary.status={status}",
            f"summary.selected_asset_count={selected_asset_count}",
            f"summary.first_failure_category={first_failure_category or 'none'}",
            (
                "deterministic.observability.runner_signals=missing"
                if runner_signals_missing
                else "deterministic.observability.runner_signals"
            ),
            f"snapshot_failed={(runner_signals or {}).get('snapshot_failed', 0)}",
            f"compiler_failed={(runner_signals or {}).get('compiler_failed', 0)}",
            f"skill_replay_failed={(runner_signals or {}).get('skill_replay_failed', 0)}",
            f"stateful_sop_failed={(runner_signals or {}).get('stateful_sop_failed', 0)}",
        ],
        "evidence_limits": evidence_limits,
        "allowed_verdicts": [
            "regression",
            "improvement",
            "no meaningful change",
            "insufficient evidence",
        ],
        "recommended_agent_flow": [
            "interpretation",
            "summary",
            "profile",
            "deterministic.observability",
            "deterministic.validation",
            "deterministic.snapshot",
            "deterministic.compiler",
            "deterministic.skill_replay",
            "deterministic.stateful_sop",
        ],
        "non_goals": [
            "no automatic root-cause diagnosis",
            "no automatic asset promotion",
            "no live/full profile inference",
        ],
    }


def run_harness_profile(
    assets_root: str | Path,
    *,
    profile: str = _DETERMINISTIC_PROFILE,
    generated_assets_root: str | Path | None = None,
    planner: Any | None = None,
    model_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if profile == _FULL_LIVE_PROFILE:
        from .full_live_profile import run_full_live_profile_sync

        return run_full_live_profile_sync(
            assets_root,
            generated_assets_root=generated_assets_root,
            planner=planner,
            model_config=model_config,
        )

    if profile != _DETERMINISTIC_PROFILE:
        raise ValueError(f"Unsupported RPA Harness profile: {profile}")

    governed_report = run_governed_offline_regression(assets_root)
    summary = _profile_summary(governed_report)
    asset_pool = build_asset_lifecycle_summary(assets_root)
    return {
        "schema_version": "rpa-harness-profile-run-v1",
        "profile": _profile_metadata(),
        "summary": summary,
        "asset_pool": asset_pool,
        "interpretation": _profile_interpretation(governed_report, summary),
        "deterministic": governed_report,
    }


def _format_values(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _format_basis(values: list[str]) -> str:
    return "; ".join(values) if values else "none"


def _format_counts(values: dict[str, Any]) -> str:
    parts = [f"{key}={values[key]}" for key in sorted(values)]
    return ", ".join(parts) if parts else "none"


def render_profile_summary(
    report: dict[str, Any],
    *,
    machine_report_path: str | Path | None = None,
    lang: str = "en",
) -> str:
    profile = report.get("profile", {})
    if profile.get("name") == _FULL_LIVE_PROFILE:
        from .full_live_profile import render_full_live_profile_summary

        return render_full_live_profile_summary(
            report,
            machine_report_path=machine_report_path,
            lang=lang,
        )

    summary = report.get("summary", {})
    interpretation = report.get("interpretation", {})
    governed = report.get("deterministic", {})
    governed_summary = governed.get("summary", {})
    asset_pool = report.get("asset_pool") or {}
    lifecycle_distribution = (asset_pool.get("summary") or {}).get("lifecycle_distribution") or {}
    coverage_boundary = asset_pool.get("coverage_boundary") or {}
    machine_path = str(machine_report_path) if machine_report_path else "not written"
    agent_flow = ", ".join(list(interpretation.get("recommended_agent_flow") or [])[:4])
    basis = _format_basis(list(interpretation.get("basis") or [])[:4])

    if lang == "zh":
        lines = [
            f"RPA Harness Profile: {profile.get('name', 'unknown')}",
            f"状态: {summary.get('status', 'unknown')}",
            f"Interpretation: {interpretation.get('verdict', 'unknown')}",
            f"Comparison basis: {interpretation.get('comparison_basis', 'unknown')}",
            f"Bounded interpretation: {str(interpretation.get('bounded', False)).lower()}",
            f"Basis: {basis}",
            f"选中资产: {_format_values(list(summary.get('selected_asset_ids') or []))}",
            f"Lifecycle distribution: {_format_counts(lifecycle_distribution)}",
            f"Blocking baseline assets: {_format_values(list(asset_pool.get('blocking_baseline_asset_ids') or []))}",
            f"Warning-only assets: {_format_values(list(asset_pool.get('warning_only_asset_ids') or []))}",
            (
                "Coverage boundary: "
                f"runner_modes={_format_counts(coverage_boundary.get('runner_modes') or {})}; "
                f"core_chain={_format_counts(coverage_boundary.get('core_chain_coverage') or {})}"
            ),
            f"排除资产数: {summary.get('excluded_asset_count', 0)}",
            f"首个失败类别: {summary.get('first_failure_category') or 'none'}",
            (
                "Candidate-lite 观察: "
                f"assets={summary.get('warning_only_observation_count', 0)}, "
                f"warnings={summary.get('warning_only_issue_count', 0)}"
            ),
            f"机器报告: {machine_path}",
            f"Agent JSON-first fields: {agent_flow}",
        ]
    else:
        lines = [
            f"RPA Harness Profile: {profile.get('name', 'unknown')}",
            f"Status: {summary.get('status', 'unknown')}",
            f"Interpretation: {interpretation.get('verdict', 'unknown')}",
            f"Comparison basis: {interpretation.get('comparison_basis', 'unknown')}",
            f"Bounded interpretation: {str(interpretation.get('bounded', False)).lower()}",
            f"Basis: {basis}",
            f"Selected assets: {_format_values(list(summary.get('selected_asset_ids') or []))}",
            f"Lifecycle distribution: {_format_counts(lifecycle_distribution)}",
            f"Blocking baseline assets: {_format_values(list(asset_pool.get('blocking_baseline_asset_ids') or []))}",
            f"Warning-only assets: {_format_values(list(asset_pool.get('warning_only_asset_ids') or []))}",
            (
                "Coverage boundary: "
                f"runner_modes={_format_counts(coverage_boundary.get('runner_modes') or {})}; "
                f"core_chain={_format_counts(coverage_boundary.get('core_chain_coverage') or {})}"
            ),
            f"Excluded asset count: {summary.get('excluded_asset_count', 0)}",
            f"First failure category: {summary.get('first_failure_category') or 'none'}",
            (
                "Candidate-lite observation: "
                f"assets={summary.get('warning_only_observation_count', 0)}, "
                f"warnings={summary.get('warning_only_issue_count', 0)}"
            ),
            f"Machine report: {machine_path}",
            f"Agent JSON-first fields: {agent_flow}",
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
