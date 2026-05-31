from __future__ import annotations

from pathlib import Path
from typing import Any

from .catalog import _blocking_baseline_reasons, build_asset_lifecycle_summary


def _excluded_assets(captures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    excluded: list[dict[str, Any]] = []
    for capture in captures:
        reasons = _blocking_baseline_reasons(capture)
        if not reasons:
            continue
        governance = capture.get("governance") or {}
        excluded.append(
            {
                "asset_id": str(capture.get("asset_id") or ""),
                "asset_status": str(capture.get("asset_status") or "unknown"),
                "promotion_status": str(governance.get("promotion_status") or "unknown"),
                "reasons": reasons,
            }
        )
    return sorted(excluded, key=lambda item: item["asset_id"])


def _recommended_next_action(
    *,
    blocking_count: int,
    warning_only_count: int,
    asset_count: int,
) -> str:
    if blocking_count > 0:
        return "run_deterministic_profile"
    if warning_only_count > 0 or asset_count > 0:
        return "review_or_promote_assets"
    return "capture_or_import_assets"


def build_asset_pool_doctor_report(assets_root: str | Path) -> dict[str, Any]:
    lifecycle = build_asset_lifecycle_summary(assets_root, include_catalog=True)
    catalog = lifecycle.get("catalog") or {}
    captures = [capture for capture in catalog.get("captures", []) if isinstance(capture, dict)]
    blocking_ids = list(lifecycle.get("blocking_baseline_asset_ids") or [])
    warning_only_ids = list(lifecycle.get("warning_only_asset_ids") or [])
    asset_count = int((lifecycle.get("summary") or {}).get("asset_count") or 0)
    blocking_count = len(blocking_ids)
    warning_only_count = len(warning_only_ids)
    readiness = "ready" if blocking_count > 0 else "not_ready"
    status = "pass" if readiness == "ready" else "warning" if warning_only_count else "fail"

    return {
        "schema_version": "rpa-harness-asset-pool-doctor-v1",
        "summary": {
            "status": status,
            "readiness": readiness,
            "asset_count": asset_count,
            "blocking_baseline_count": blocking_count,
            "warning_only_count": warning_only_count,
            "golden_count": len(lifecycle.get("golden_asset_ids") or []),
            "expected_signals_reviewed": (lifecycle.get("review_state") or {}).get(
                "expected_signals_reviewed",
                0,
            ),
            "expected_signals_unreviewed": (lifecycle.get("review_state") or {}).get(
                "expected_signals_unreviewed",
                0,
            ),
            "sensitivity_reviewed": (lifecycle.get("review_state") or {}).get(
                "sensitivity_reviewed",
                0,
            ),
            "sensitivity_unreviewed": (lifecycle.get("review_state") or {}).get(
                "sensitivity_unreviewed",
                0,
            ),
            "recommended_next_action": _recommended_next_action(
                blocking_count=blocking_count,
                warning_only_count=warning_only_count,
                asset_count=asset_count,
            ),
        },
        "blocking_baseline_asset_ids": blocking_ids,
        "warning_only_asset_ids": warning_only_ids,
        "golden_asset_ids": list(lifecycle.get("golden_asset_ids") or []),
        "excluded_assets": _excluded_assets(captures),
        "coverage_boundary": lifecycle.get("coverage_boundary") or {},
        "lifecycle_distribution": (lifecycle.get("summary") or {}).get("lifecycle_distribution", {}),
        "trust_limits": lifecycle.get("trust_limits") or [],
        "human_governance": {
            "required_for_candidate_or_golden": True,
            "agents_may_recommend": True,
            "agents_may_promote_automatically": False,
        },
        "recommended_commands": [
            "python -m backend.rpa.harness.run_asset_review --assets <asset_root> --asset-id <asset_id>",
            "python -m backend.rpa.harness.run_asset_sensitivity_scan --assets <asset_root> --asset-id <asset_id>",
            "python -m backend.rpa.harness.run_harness_profile --assets <asset_root> --profile deterministic --output tmp-harness-profile-deterministic.json",
        ],
    }


def render_asset_pool_doctor_summary(report: dict[str, Any], *, lang: str = "zh") -> str:
    summary = report.get("summary") or {}
    blocking = report.get("blocking_baseline_asset_ids") or []
    warning_only = report.get("warning_only_asset_ids") or []
    excluded = report.get("excluded_assets") or []
    trust_limits = report.get("trust_limits") or []

    if lang != "zh":
        lines = [
            f"Asset pool doctor: {summary.get('readiness', 'unknown')}",
            f"status: {summary.get('status', 'unknown')}",
            f"blocking baseline: {summary.get('blocking_baseline_count', 0)}",
            f"warning-only: {summary.get('warning_only_count', 0)}",
            f"recommended next action: {summary.get('recommended_next_action', '')}",
            "",
            "Blocking assets:",
        ]
        lines.extend(f"- {asset_id}" for asset_id in blocking)
        lines.append("Warning-only assets:")
        lines.extend(f"- {asset_id}" for asset_id in warning_only)
        lines.append("Excluded assets:")
        lines.extend(f"- {item.get('asset_id')}: {', '.join(item.get('reasons') or [])}" for item in excluded)
        return "\n".join(lines).rstrip() + "\n"

    lines = [
        f"资产池体检：{summary.get('readiness', 'unknown')}",
        f"状态：{summary.get('status', 'unknown')}",
        f"资产总数：{summary.get('asset_count', 0)}",
        f"blocking baseline：{summary.get('blocking_baseline_count', 0)}",
        f"warning-only：{summary.get('warning_only_count', 0)}",
        f"expected reviewed/unreviewed：{summary.get('expected_signals_reviewed', 0)}/{summary.get('expected_signals_unreviewed', 0)}",
        f"sensitivity reviewed/unreviewed：{summary.get('sensitivity_reviewed', 0)}/{summary.get('sensitivity_unreviewed', 0)}",
        f"建议下一步：{summary.get('recommended_next_action', '')}",
        "",
        "Blocking assets:",
    ]
    lines.extend(f"- {asset_id}" for asset_id in blocking)
    lines.append("Warning-only assets:")
    lines.extend(f"- {asset_id}" for asset_id in warning_only)
    lines.append("Excluded assets:")
    lines.extend(f"- {item.get('asset_id')}: {', '.join(item.get('reasons') or [])}" for item in excluded)
    lines.append("Trust limits:")
    lines.extend(f"- {limit}" for limit in trust_limits)
    return "\n".join(lines).rstrip() + "\n"
