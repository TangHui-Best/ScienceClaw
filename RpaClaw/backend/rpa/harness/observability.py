from __future__ import annotations

from collections import Counter
from typing import Any


def _counter_dict(values: list[str]) -> dict[str, int]:
    counter = Counter(value for value in values if value)
    return {key: counter[key] for key in sorted(counter)}


def _failure_categories(report: dict[str, Any], section: str) -> dict[str, int]:
    return _counter_dict(
        [
            str(item.get("failure_category") or "")
            for item in report.get(section, {}).get("assets", [])
            if isinstance(item, dict) and item.get("status") != "passed"
        ]
    )


def _coverage_risks(report: dict[str, Any]) -> list[str]:
    summary = report.get("summary", {})
    selected_count = int(summary.get("selected_capture_count") or 0)
    promotion_statuses = summary.get("promotion_statuses") or {}
    page_patterns = list(summary.get("page_patterns") or [])
    core_chain_coverage = summary.get("core_chain_coverage") or {}

    risks: list[str] = []
    if selected_count == 0:
        risks.append("no-governed-offline-assets")
    elif selected_count == 1 and promotion_statuses.get("candidate") == 1:
        risks.append("single-candidate-asset-baseline")
    elif selected_count == 1:
        risks.append("single-governed-asset-baseline")
    if not page_patterns:
        risks.append("missing-page-pattern-coverage")
    if not core_chain_coverage:
        risks.append("missing-core-chain-coverage")
    return risks


def build_observability_contract(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {})
    selection = report.get("selection", {})
    catalog_summary = report.get("catalog", {}).get("summary", {})
    validation_summary = report.get("validation", {}).get("summary", {})
    blast_summary = report.get("blast_radius", {}).get("summary", {})
    excluded_captures = list(selection.get("excluded_captures") or [])

    return {
        "schema_version": "rpa-harness-observability-v0",
        "asset_qualification": {
            "scanned_capture_count": len(selection.get("selected_captures") or []) + len(excluded_captures),
            "selected_capture_count": int(summary.get("selected_capture_count") or 0),
            "excluded_capture_count": int(summary.get("excluded_capture_count") or 0),
            "selected_asset_ids": list(summary.get("selected_asset_ids") or []),
            "excluded_asset_ids": list(summary.get("excluded_asset_ids") or []),
            "selected_promotion_status_counts": dict(summary.get("promotion_statuses") or {}),
            "excluded_reason_counts": _counter_dict(
                [
                    str(reason)
                    for capture in excluded_captures
                    if isinstance(capture, dict)
                    for reason in capture.get("reasons", [])
                ]
            ),
        },
        "coverage": {
            "selected_step_count": int(summary.get("selected_step_count") or 0),
            "page_patterns": list(summary.get("page_patterns") or []),
            "core_chain_coverage": dict(summary.get("core_chain_coverage") or {}),
            "recording_modes": dict(catalog_summary.get("recording_modes") or {}),
            "runtime_statuses": dict(catalog_summary.get("runtime_statuses") or {}),
            "hosts": list(catalog_summary.get("hosts") or []),
            "coverage_risks": _coverage_risks(report),
        },
        "runner_signals": {
            "validation_blocking_issue_count": int(
                summary.get("validation_blocking_issue_count") or 0
            ),
            "validation_issue_categories": dict(validation_summary.get("categories") or {}),
            "snapshot_failed": int(summary.get("snapshot_failed") or 0),
            "snapshot_failure_categories": _failure_categories(report, "snapshot"),
            "compiler_failed": int(summary.get("compiler_failed") or 0),
            "compiler_failure_categories": _failure_categories(report, "compiler"),
        },
        "blast_radius": {
            "status": str(blast_summary.get("status") or "unknown"),
            "blocking_failed_steps": int(blast_summary.get("blocking_failed_steps") or 0),
            "warning_failed_steps": int(blast_summary.get("warning_failed_steps") or 0),
            "affected_assets": list(blast_summary.get("affected_assets") or []),
            "affected_page_patterns": list(blast_summary.get("affected_page_patterns") or []),
            "affected_hosts": list(blast_summary.get("affected_hosts") or []),
            "failures_by_category": dict(report.get("blast_radius", {}).get("failures_by_category") or {}),
        },
        "confidence": {
            "status": str(summary.get("status") or "unknown"),
            "failure_category": str(summary.get("failure_category") or ""),
            "risks": _coverage_risks(report),
        },
    }


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else plural or f"{singular}s"
    return f"{count} {word}"


def _asset_phrase(observability: dict[str, Any]) -> str:
    qualification = observability["asset_qualification"]
    selected_count = qualification["selected_capture_count"]
    promotion_counts = qualification.get("selected_promotion_status_counts") or {}
    parts = [
        _plural(int(promotion_counts[status]), f"{status} asset")
        for status in ["candidate", "golden"]
        if int(promotion_counts.get(status) or 0)
    ]
    return ", ".join(parts) if parts else _plural(selected_count, "governed asset")


def _format_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _format_counts(values: dict[str, int]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{key}={values[key]}" for key in sorted(values))


def render_human_summary(report: dict[str, Any]) -> str:
    observability = report.get("observability") or build_observability_contract(report)
    summary = report.get("summary", {})
    qualification = observability["asset_qualification"]
    coverage = observability["coverage"]
    runner_signals = observability["runner_signals"]
    blast_radius = observability["blast_radius"]
    confidence = observability["confidence"]

    lines = [
        f"Governed Offline Regression: {summary.get('status', 'unknown')}",
        "",
        f"Evaluated: {_asset_phrase(observability)}, {_plural(coverage['selected_step_count'], 'step')}",
        f"Coverage: {_format_list(coverage['page_patterns'])}",
        f"Core chain: {_format_counts(coverage['core_chain_coverage'])}",
        (
            "Excluded: "
            f"{_plural(qualification['excluded_capture_count'], 'capture')}; "
            f"reasons={_format_counts(qualification['excluded_reason_counts'])}"
        ),
        (
            "Signals: "
            f"validation blocking={runner_signals['validation_blocking_issue_count']}, "
            f"snapshot failed={runner_signals['snapshot_failed']}, "
            f"compiler failed={runner_signals['compiler_failed']}"
        ),
        (
            "Blast radius: "
            f"affected assets={_format_list(blast_radius['affected_assets'])}; "
            f"affected page patterns={_format_list(blast_radius['affected_page_patterns'])}"
        ),
        f"Confidence risks: {_format_list(confidence['risks'])}",
    ]
    failure_category = confidence.get("failure_category")
    if failure_category:
        lines.insert(1, f"Failure category: {failure_category}")
    return "\n".join(lines) + "\n"
