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


def _snapshot_quality(report: dict[str, Any]) -> dict[str, Any]:
    items = [
        item
        for item in report.get("snapshot", {}).get("assets", [])
        if isinstance(item, dict)
    ]
    if not items:
        return {
            "source": "none",
            "checked_steps": 0,
            "raw_signal_present": 0,
            "compact_signal_present": 0,
            "raw_signal_missing": 0,
            "compact_signal_missing": 0,
            "average_compression_ratio": 0,
        }

    ratios = [
        float(item.get("compression_ratio") or 0)
        for item in items
        if item.get("compression_ratio") is not None
    ]
    sources = _counter_dict([str(item.get("snapshot_source") or "") for item in items])
    source = next(iter(sources), "unknown")
    if len(sources) > 1:
        source = "mixed"
    return {
        "source": source,
        "checked_steps": len(items),
        "raw_signal_present": len(
            [item for item in items if item.get("raw_signal_status") == "present"]
        ),
        "compact_signal_present": len(
            [item for item in items if item.get("compact_signal_status") == "present"]
        ),
        "raw_signal_missing": len(
            [item for item in items if item.get("raw_signal_status") == "missing"]
        ),
        "compact_signal_missing": len(
            [item for item in items if item.get("compact_signal_status") == "missing"]
        ),
        "average_compression_ratio": round(sum(ratios) / len(ratios), 4) if ratios else 0,
    }


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
            "snapshot_quality": _snapshot_quality(report),
            "compiler_failed": int(summary.get("compiler_failed") or 0),
            "compiler_failure_categories": _failure_categories(report, "compiler"),
            "skill_replay_checked": int(
                report.get("skill_replay", {}).get("summary", {}).get("total") or 0
            ),
            "skill_replay_failed": int(summary.get("skill_replay_failed") or 0),
            "skill_replay_failure_categories": _failure_categories(report, "skill_replay"),
            "stateful_sop_checked": int(
                report.get("stateful_sop", {}).get("summary", {}).get("total") or 0
            ),
            "stateful_sop_failed": int(summary.get("stateful_sop_failed") or 0),
            "stateful_sop_failure_categories": _failure_categories(report, "stateful_sop"),
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


def _zh_count(count: int, noun: str) -> str:
    return f"{count} 个{noun}"


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


def _zh_asset_phrase(observability: dict[str, Any]) -> str:
    qualification = observability["asset_qualification"]
    selected_count = qualification["selected_capture_count"]
    promotion_counts = qualification.get("selected_promotion_status_counts") or {}
    parts = [
        _zh_count(int(promotion_counts[status]), f" {status} 资产")
        for status in ["candidate", "golden"]
        if int(promotion_counts.get(status) or 0)
    ]
    return "，".join(parts) if parts else _zh_count(selected_count, "受治理资产")


def _format_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _zh_format_list(values: list[str]) -> str:
    return ", ".join(values) if values else "无"


def _format_counts(values: dict[str, int]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{key}={values[key]}" for key in sorted(values))


def _zh_format_counts(values: dict[str, int]) -> str:
    if not values:
        return "无"
    return ", ".join(f"{key}={values[key]}" for key in sorted(values))


def _zh_status(status: str) -> str:
    return {
        "passed": "通过",
        "failed": "失败",
        "passed_with_warnings": "通过但有警告",
    }.get(status, status or "未知")


def render_human_summary(report: dict[str, Any]) -> str:
    observability = report.get("observability") or build_observability_contract(report)
    summary = report.get("summary", {})
    qualification = observability["asset_qualification"]
    coverage = observability["coverage"]
    runner_signals = observability["runner_signals"]
    snapshot_quality = runner_signals["snapshot_quality"]
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
            "Skill replay: "
            f"checked={runner_signals['skill_replay_checked']}, "
            f"failed={runner_signals['skill_replay_failed']}"
        ),
        (
            "Stateful SOP: "
            f"checked={runner_signals['stateful_sop_checked']}, "
            f"failed={runner_signals['stateful_sop_failed']}"
        ),
        (
            "Snapshot quality: "
            f"source={snapshot_quality['source']}, "
            f"checked steps={snapshot_quality['checked_steps']}, "
            f"raw signal present={snapshot_quality['raw_signal_present']}, "
            f"compact signal present={snapshot_quality['compact_signal_present']}, "
            f"avg compact/raw={snapshot_quality['average_compression_ratio']}"
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


def render_chinese_summary(report: dict[str, Any]) -> str:
    observability = report.get("observability") or build_observability_contract(report)
    summary = report.get("summary", {})
    qualification = observability["asset_qualification"]
    coverage = observability["coverage"]
    runner_signals = observability["runner_signals"]
    snapshot_quality = runner_signals["snapshot_quality"]
    blast_radius = observability["blast_radius"]
    confidence = observability["confidence"]

    lines = [
        f"受治理离线回归：{_zh_status(str(summary.get('status') or 'unknown'))}",
        "",
        f"本次评估：{_zh_asset_phrase(observability)}，{_zh_count(coverage['selected_step_count'], '步骤')}",
        f"覆盖范围：{_zh_format_list(coverage['page_patterns'])}",
        f"核心链路：{_zh_format_counts(coverage['core_chain_coverage'])}",
        (
            "未纳入回归："
            f"{_zh_count(qualification['excluded_capture_count'], ' capture')}；"
            f"原因={_zh_format_counts(qualification['excluded_reason_counts'])}"
        ),
        (
            "执行信号："
            f"validation 阻塞={runner_signals['validation_blocking_issue_count']}，"
            f"snapshot 失败={runner_signals['snapshot_failed']}，"
            f"compiler 失败={runner_signals['compiler_failed']}"
        ),
        (
            "Snapshot 质量："
            f"source={snapshot_quality['source']}，"
            f"检查步骤={snapshot_quality['checked_steps']}，"
            f"raw signal 保留={snapshot_quality['raw_signal_present']}，"
            f"compact signal 保留={snapshot_quality['compact_signal_present']}，"
            f"平均 compact/raw={snapshot_quality['average_compression_ratio']}"
        ),
        (
            "影响范围："
            f"受影响资产={_zh_format_list(blast_radius['affected_assets'])}；"
            f"受影响页面形态={_zh_format_list(blast_radius['affected_page_patterns'])}"
        ),
        f"可信度边界：{_zh_format_list(confidence['risks'])}",
    ]
    failure_category = confidence.get("failure_category")
    if failure_category:
        lines.insert(1, f"失败类别：{failure_category}")
    return "\n".join(lines) + "\n"
