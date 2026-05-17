from __future__ import annotations

from collections import Counter
from typing import Any


_NON_BLOCKING_STATUSES = {"draft", "flaky", "archived", "superseded"}


def _step_key(item: dict[str, Any]) -> tuple[str, int]:
    return str(item.get("asset_id") or ""), int(item.get("step_index") or 0)


def _unique_sorted(values: list[str]) -> list[str]:
    return sorted({value for value in values if value})


def _catalog_indexes(catalog: dict[str, Any] | None) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, int], dict[str, Any]]]:
    if not catalog:
        return {}, {}
    capture_index = {
        str(capture.get("asset_id") or ""): capture
        for capture in catalog.get("captures", [])
        if isinstance(capture, dict)
    }
    step_index = {
        (str(step.get("asset_id") or ""), int(step.get("step_index") or 0)): step
        for step in catalog.get("steps", [])
        if isinstance(step, dict)
    }
    return capture_index, step_index


def _runner_index(report: dict[str, Any] | None) -> dict[tuple[str, int], dict[str, Any]]:
    if not report:
        return {}
    return {
        _step_key(item): item
        for item in report.get("assets", [])
        if isinstance(item, dict) and item.get("asset_id") and item.get("step_index") is not None
    }


def _runner_failure(runner: str, item: dict[str, Any] | None) -> dict[str, str] | None:
    if not item or item.get("status") == "passed":
        return None
    return {
        "runner": runner,
        "status": str(item.get("status") or "unknown"),
        "failure_category": str(item.get("failure_category") or "unknown"),
    }


def _missing_runner_failure(runner: str, item: dict[str, Any] | None) -> dict[str, str] | None:
    if item is not None:
        return None
    return {
        "runner": runner,
        "status": "missing",
        "failure_category": "incomplete-runner-evidence",
    }


def _metadata_for_step(
    key: tuple[str, int],
    *,
    snapshot_item: dict[str, Any] | None,
    compiler_item: dict[str, Any] | None,
    catalog_steps: dict[tuple[str, int], dict[str, Any]],
    catalog_captures: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    asset_id, step_index = key
    catalog_step = catalog_steps.get(key, {})
    capture = catalog_captures.get(asset_id, {})
    first_item = snapshot_item or compiler_item or {}
    page_patterns = _unique_sorted(
        list(catalog_step.get("page_patterns") or [])
        + list(first_item.get("page_patterns") or [])
        + list((snapshot_item or {}).get("page_patterns") or [])
        + list((compiler_item or {}).get("page_patterns") or [])
    )
    return {
        "asset_id": asset_id,
        "step_index": step_index,
        "step_id": catalog_step.get("step_id") or first_item.get("step_id") or "",
        "step_intent": catalog_step.get("step_intent") or first_item.get("step_intent") or "",
        "sop_intent": capture.get("sop_intent") or "",
        "asset_status": capture.get("asset_status") or "unknown",
        "capture_scope": capture.get("capture_scope") or "unknown",
        "runtime_status": catalog_step.get("runtime_status") or "",
        "before_url": catalog_step.get("before_url") or "",
        "after_url": catalog_step.get("after_url") or "",
        "hosts": _unique_sorted(list(catalog_step.get("hosts") or [])),
        "page_patterns": page_patterns,
    }


def _report_status(blocking_failed_steps: int, warning_failed_steps: int) -> str:
    if blocking_failed_steps:
        return "failed"
    if warning_failed_steps:
        return "passed_with_warnings"
    return "passed"


def build_blast_radius_report(
    *,
    snapshot_report: dict[str, Any] | None = None,
    compiler_report: dict[str, Any] | None = None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog_captures, catalog_steps = _catalog_indexes(catalog)
    snapshot_items = _runner_index(snapshot_report)
    compiler_items = _runner_index(compiler_report)
    keys = sorted(set(snapshot_items) | set(compiler_items))

    affected_steps: list[dict[str, Any]] = []
    warning_steps: list[dict[str, Any]] = []
    passed_steps = 0
    failure_categories: Counter[str] = Counter()

    for key in keys:
        snapshot_item = snapshot_items.get(key)
        compiler_item = compiler_items.get(key)
        runner_statuses = {}
        if snapshot_item is not None:
            runner_statuses["snapshot"] = str(snapshot_item.get("status") or "unknown")
        else:
            runner_statuses["snapshot"] = "missing"
        if compiler_item is not None:
            runner_statuses["compiler"] = str(compiler_item.get("status") or "unknown")
        else:
            runner_statuses["compiler"] = "missing"

        failures = [
            failure
            for failure in [
                _runner_failure("snapshot", snapshot_item),
                _runner_failure("compiler", compiler_item),
                _missing_runner_failure("snapshot", snapshot_item),
                _missing_runner_failure("compiler", compiler_item),
            ]
            if failure is not None
        ]
        if not failures:
            passed_steps += 1
            continue

        metadata = _metadata_for_step(
            key,
            snapshot_item=snapshot_item,
            compiler_item=compiler_item,
            catalog_steps=catalog_steps,
            catalog_captures=catalog_captures,
        )
        affected = {
            **metadata,
            "runner_statuses": dict(sorted(runner_statuses.items())),
            "runner_failures": failures,
        }
        for failure in failures:
            failure_categories[failure["failure_category"]] += 1
        if metadata["asset_status"] in _NON_BLOCKING_STATUSES:
            warning_steps.append(affected)
        else:
            affected_steps.append(affected)

    all_failed_steps = affected_steps + warning_steps
    return {
        "schema_version": "rpa-harness-blast-radius-v0",
        "summary": {
            "status": _report_status(len(affected_steps), len(warning_steps)),
            "checked_steps": len(keys),
            "passed_steps": passed_steps,
            "failed_steps": len(all_failed_steps),
            "blocking_failed_steps": len(affected_steps),
            "warning_failed_steps": len(warning_steps),
            "affected_assets": _unique_sorted([step["asset_id"] for step in all_failed_steps]),
            "blocking_affected_assets": _unique_sorted([step["asset_id"] for step in affected_steps]),
            "warning_affected_assets": _unique_sorted([step["asset_id"] for step in warning_steps]),
            "affected_page_patterns": _unique_sorted(
                [pattern for step in all_failed_steps for pattern in step["page_patterns"]]
            ),
            "affected_hosts": _unique_sorted([host for step in all_failed_steps for host in step["hosts"]]),
        },
        "affected_steps": affected_steps,
        "failures_by_category": {key: failure_categories[key] for key in sorted(failure_categories)},
        "warnings": warning_steps,
    }
