from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .models import HarnessScenarioAsset, HarnessStepCheckpoint


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_blocking(asset_status: str, severity: str) -> bool:
    return asset_status == "active" and severity == "error"


def _issue(
    issues: list[dict[str, Any]],
    *,
    root: Path,
    asset_id: str,
    asset_status: str,
    category: str,
    message: str,
    severity: str = "error",
    path: Path | None = None,
    blocking: bool | None = None,
    **extra: Any,
) -> None:
    payload = {
        "asset_id": asset_id,
        "asset_status": asset_status,
        "category": category,
        "severity": severity,
        "blocking": _is_blocking(asset_status, severity) if blocking is None else blocking,
        "message": message,
        "path": _relative(path, root) if path is not None else "",
    }
    payload.update(extra)
    issues.append(payload)


def _body_text_chars_from_html(html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return len(re.sub(r"\s+", " ", text).strip())


def _is_shell_like_html(*, title: str, html: str) -> bool:
    html_bytes = len((html or "").encode("utf-8"))
    return not html.strip() or (
        not title.strip()
        and html_bytes < 50_000
        and _body_text_chars_from_html(html) < 80
    )


def _load_scenario(asset_dir: Path, root: Path, issues: list[dict[str, Any]]) -> HarnessScenarioAsset | None:
    scenario_path = asset_dir / "scenario.json"
    if not scenario_path.exists():
        _issue(
            issues,
            root=root,
            asset_id=asset_dir.name,
            asset_status="draft",
            category="missing-scenario",
            message="Harness asset is missing scenario.json",
            path=scenario_path,
        )
        return None
    try:
        return HarnessScenarioAsset.model_validate(_load_json(scenario_path))
    except Exception as exc:
        _issue(
            issues,
            root=root,
            asset_id=asset_dir.name,
            asset_status="draft",
            category="invalid-scenario",
            message=str(exc),
            path=scenario_path,
        )
        return None


def _load_checkpoint(
    checkpoint_path: Path,
    *,
    root: Path,
    asset_id: str,
    asset_status: str,
    issues: list[dict[str, Any]],
) -> HarnessStepCheckpoint | None:
    try:
        return HarnessStepCheckpoint.model_validate(_load_json(checkpoint_path))
    except Exception as exc:
        _issue(
            issues,
            root=root,
            asset_id=asset_id,
            asset_status=asset_status,
            category="invalid-checkpoint",
            message=str(exc),
            path=checkpoint_path,
        )
        return None


def _validate_scenario_governance(
    *,
    root: Path,
    asset_id: str,
    asset_status: str,
    scenario: HarnessScenarioAsset,
    issues: list[dict[str, Any]],
) -> None:
    governance = scenario.governance
    promotion_status = governance.promotion_status
    if promotion_status not in {"candidate", "golden"}:
        return

    def add_blocker(category: str, message: str) -> None:
        _issue(
            issues,
            root=root,
            asset_id=asset_id,
            asset_status=asset_status,
            category=category,
            message=message,
            blocking=True,
            promotion_status=promotion_status,
        )

    if promotion_status == "golden" and asset_status != "active":
        add_blocker("golden-asset-not-active", "Golden scenario assets must also be active regression assets")
    if not governance.runner_modes:
        add_blocker("missing-runner-mode", "Governed scenario assets must declare eligible runner modes")
    if not governance.core_chain_coverage:
        add_blocker(
            "missing-core-chain-coverage",
            "Governed scenario assets must declare covered RPA core-chain segments",
        )
    if not governance.expected_signals_reviewed:
        add_blocker(
            "unreviewed-expected-signals",
            "Governed scenario assets require expected-signal review before promotion",
        )
    if not governance.sensitivity_reviewed:
        add_blocker(
            "unreviewed-sensitivity",
            "Governed scenario assets require sensitivity review before promotion",
        )


def _validate_checkpoint_files(
    *,
    root: Path,
    capture_dir: Path,
    asset_id: str,
    asset_status: str,
    checkpoint: HarnessStepCheckpoint,
    issues: list[dict[str, Any]],
) -> None:
    before_path = capture_dir / checkpoint.before.html_path
    if not before_path.exists():
        _issue(
            issues,
            root=root,
            asset_id=asset_id,
            asset_status=asset_status,
            category="missing-before-html",
            message="Checkpoint before.html asset is missing",
            path=before_path,
            step_index=checkpoint.step_index,
        )

    trace_events_path = capture_dir / checkpoint.action.trace_events_path
    if not trace_events_path.exists():
        _issue(
            issues,
            root=root,
            asset_id=asset_id,
            asset_status=asset_status,
            category="missing-trace-events",
            message="Checkpoint trace_events.json asset is missing",
            path=trace_events_path,
            step_index=checkpoint.step_index,
        )

    if checkpoint.expected_path:
        expected_path = capture_dir / checkpoint.expected_path
        if not expected_path.exists():
            _issue(
                issues,
                root=root,
                asset_id=asset_id,
                asset_status=asset_status,
                category="missing-expected-signals",
                message="Checkpoint expected.json asset is missing",
                path=expected_path,
                step_index=checkpoint.step_index,
            )

    if checkpoint.runtime_result.status == "success":
        after = checkpoint.after
        if after is None:
            _issue(
                issues,
                root=root,
                asset_id=asset_id,
                asset_status=asset_status,
                category="missing-after-state",
                message="Successful checkpoint is missing after state",
                step_index=checkpoint.step_index,
            )
            return
        after_path = capture_dir / after.html_path
        if not after.same_as_before and not after_path.exists():
            _issue(
                issues,
                root=root,
                asset_id=asset_id,
                asset_status=asset_status,
                category="missing-after-html",
                message="Successful checkpoint after.html asset is missing",
                path=after_path,
                step_index=checkpoint.step_index,
            )
        if not after.same_as_before and after_path.exists() and after_path.stat().st_size == 0:
            _issue(
                issues,
                root=root,
                asset_id=asset_id,
                asset_status=asset_status,
                category="empty-after-html",
                message="Successful checkpoint after.html asset is empty",
                path=after_path,
                step_index=checkpoint.step_index,
            )
        if after.capture_quality.get("status") == "partial":
            _issue(
                issues,
                root=root,
                asset_id=asset_id,
                asset_status=asset_status,
                category="unstable-after-capture",
                severity="warning",
                message="Successful checkpoint after state was captured before the page became stable",
                path=after_path if after_path.exists() else None,
                step_index=checkpoint.step_index,
                reason=after.capture_quality.get("reason", ""),
            )
        if not after.same_as_before and after_path.exists() and after_path.stat().st_size > 0:
            after_html = after_path.read_text(encoding="utf-8", errors="ignore")
            if _is_shell_like_html(title=after.title, html=after_html):
                _issue(
                    issues,
                    root=root,
                    asset_id=asset_id,
                    asset_status=asset_status,
                    category="shell-like-after-html",
                    severity="warning",
                    message="Successful checkpoint after.html looks like an early navigation shell",
                    path=after_path,
                    step_index=checkpoint.step_index,
                )

    if checkpoint.runtime_result.status == "failed" and checkpoint.failure_path:
        failure_path = capture_dir / checkpoint.failure_path
        if not failure_path.exists():
            _issue(
                issues,
                root=root,
                asset_id=asset_id,
                asset_status=asset_status,
                category="missing-failure-evidence",
                message="Failed checkpoint failure evidence is missing",
                path=failure_path,
                step_index=checkpoint.step_index,
            )


def _validate_step_sequence(
    *,
    root: Path,
    asset_id: str,
    asset_status: str,
    capture_scope: str,
    step_indexes: list[int],
    issues: list[dict[str, Any]],
) -> None:
    if not step_indexes:
        if capture_scope == "full_sop":
            _issue(
                issues,
                root=root,
                asset_id=asset_id,
                asset_status=asset_status,
                category="missing-entry-checkpoint",
                message="Full SOP asset has no entry checkpoint",
            )
        return

    unique_indexes = sorted(set(step_indexes))
    if capture_scope == "full_sop" and unique_indexes[0] != 1:
        _issue(
            issues,
            root=root,
            asset_id=asset_id,
            asset_status=asset_status,
            category="missing-entry-checkpoint",
            message="Full SOP asset does not start with step index 1",
            first_step_index=unique_indexes[0],
        )

    expected = set(range(unique_indexes[0], unique_indexes[-1] + 1))
    missing = sorted(expected - set(unique_indexes))
    if missing:
        _issue(
            issues,
            root=root,
            asset_id=asset_id,
            asset_status=asset_status,
            category="step-index-gap",
            message="Harness asset step indexes are not contiguous",
            missing_step_indexes=missing,
        )


def validate_harness_assets(assets_root: str | Path) -> dict[str, Any]:
    root = Path(assets_root)
    issues: list[dict[str, Any]] = []
    asset_dirs = sorted(path for path in root.iterdir() if path.is_dir()) if root.exists() else []

    for asset_dir in asset_dirs:
        scenario = _load_scenario(asset_dir, root, issues)
        if scenario is None:
            continue
        asset_id = scenario.asset_id
        asset_status = scenario.asset_status
        _validate_scenario_governance(
            root=root,
            asset_id=asset_id,
            asset_status=asset_status,
            scenario=scenario,
            issues=issues,
        )

        ref_indexes: list[int] = []
        for ref in scenario.step_checkpoints:
            ref_indexes.append(ref.step_index)
            ref_path = asset_dir / ref.checkpoint_path
            if not ref_path.exists():
                _issue(
                    issues,
                    root=root,
                    asset_id=asset_id,
                    asset_status=asset_status,
                    category="missing-checkpoint-ref",
                    message="Scenario references a missing checkpoint",
                    path=ref_path,
                    step_index=ref.step_index,
                )

        duplicates = sorted(index for index, count in Counter(ref_indexes).items() if count > 1)
        if duplicates:
            _issue(
                issues,
                root=root,
                asset_id=asset_id,
                asset_status=asset_status,
                category="duplicate-step-index",
                message="Scenario manifest contains duplicate step indexes",
                duplicate_step_indexes=duplicates,
            )

        actual_indexes: list[int] = []
        for checkpoint_path in sorted(asset_dir.glob("steps/*/checkpoint.json")):
            checkpoint = _load_checkpoint(
                checkpoint_path,
                root=root,
                asset_id=asset_id,
                asset_status=asset_status,
                issues=issues,
            )
            if checkpoint is None:
                continue
            actual_indexes.append(checkpoint.step_index)
            _validate_checkpoint_files(
                root=root,
                capture_dir=asset_dir,
                asset_id=asset_id,
                asset_status=asset_status,
                checkpoint=checkpoint,
                issues=issues,
            )

        for checkpoint_index in sorted(set(actual_indexes) - set(ref_indexes)):
            _issue(
                issues,
                root=root,
                asset_id=asset_id,
                asset_status=asset_status,
                category="unreferenced-checkpoint",
                message="Checkpoint exists on disk but is not referenced by scenario.json",
                step_index=checkpoint_index,
            )

        _validate_step_sequence(
            root=root,
            asset_id=asset_id,
            asset_status=asset_status,
            capture_scope=scenario.capture_scope,
            step_indexes=sorted(set(ref_indexes) | set(actual_indexes)),
            issues=issues,
        )

    categories = Counter(issue["category"] for issue in issues)
    severities = Counter(issue["severity"] for issue in issues)
    return {
        "schema_version": "rpa-harness-validation-v0",
        "summary": {
            "capture_count": len(asset_dirs),
            "issue_count": len(issues),
            "blocking_issue_count": len([issue for issue in issues if issue["blocking"]]),
            "categories": {key: categories[key] for key in sorted(categories)},
            "severities": {key: severities[key] for key in sorted(severities)},
        },
        "issues": issues,
    }
