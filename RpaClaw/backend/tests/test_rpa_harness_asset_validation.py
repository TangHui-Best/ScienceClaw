import json
from pathlib import Path

from backend.rpa.harness.asset_validation import validate_harness_assets
from backend.rpa.harness.run_asset_validation import main as run_asset_validation_main


def _write_scenario(
    root: Path,
    *,
    asset_id: str = "asset-1",
    capture_scope: str = "full_sop",
    asset_status: str = "draft",
    step_indexes: list[int],
) -> Path:
    capture_dir = root / asset_id
    capture_dir.mkdir(parents=True, exist_ok=True)
    (capture_dir / "scenario.json").write_text(
        json.dumps(
            {
                "schema_version": "rpa-harness-scenario-v0",
                "asset_id": asset_id,
                "capture_scope": capture_scope,
                "source": {
                    "recording_id": "session-1",
                    "captured_at": "2026-05-18T10:00:00",
                    "capture_mode": "harness",
                    "capture_trigger": capture_scope,
                },
                "asset_status": asset_status,
                "sensitivity": "local-only",
                "step_checkpoints": [
                    {"step_index": index, "checkpoint_path": f"steps/{index:03d}/checkpoint.json"}
                    for index in step_indexes
                ],
            }
        ),
        encoding="utf-8",
    )
    return capture_dir


def _write_checkpoint(
    capture_dir: Path,
    *,
    step_index: int,
    write_before: bool = True,
    write_after: bool = True,
    write_trace: bool = True,
    write_expected: bool = True,
    same_as_before: bool = False,
    after_html: str = "<html><body>after</body></html>",
) -> None:
    step_dir = capture_dir / "steps" / f"{step_index:03d}"
    step_dir.mkdir(parents=True, exist_ok=True)
    if write_before:
        (step_dir / "before.html").write_text("<html><body>before</body></html>", encoding="utf-8")
    if write_after:
        (step_dir / "after.html").write_text(after_html, encoding="utf-8")
    if write_trace:
        (step_dir / "trace_events.json").write_text(json.dumps([{"trace_id": f"trace-{step_index}"}]), encoding="utf-8")
    if write_expected:
        (step_dir / "expected.json").write_text(json.dumps({}), encoding="utf-8")
    after_path = "steps/%03d/before.html" % step_index if same_as_before else "steps/%03d/after.html" % step_index
    (step_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "step_index": step_index,
                "step_id": f"trace-{step_index}",
                "step_intent": f"Step {step_index}",
                "recording_mode": "manual",
                "before": {
                    "url": "https://example.test/before",
                    "title": "Before",
                    "html_path": f"steps/{step_index:03d}/before.html",
                    "html_sha256": "before",
                },
                "action": {
                    "trace_events_path": f"steps/{step_index:03d}/trace_events.json",
                },
                "after": {
                    "url": "https://example.test/after",
                    "title": "After",
                    "html_path": after_path,
                    "html_sha256": "after",
                    "same_as_before": same_as_before,
                },
                "runtime_result": {"status": "success"},
                "captured_at": "2026-05-18T10:00:00",
                "expected_path": f"steps/{step_index:03d}/expected.json",
            }
        ),
        encoding="utf-8",
    )


def test_validation_reports_full_sop_missing_entry_checkpoint_without_site_rules(tmp_path: Path):
    capture_dir = _write_scenario(tmp_path, step_indexes=[2])
    _write_checkpoint(capture_dir, step_index=2)

    report = validate_harness_assets(tmp_path)

    assert report["summary"]["issue_count"] == 1
    issue = report["issues"][0]
    assert issue["asset_id"] == "asset-1"
    assert issue["category"] == "missing-entry-checkpoint"
    assert issue["blocking"] is False


def test_validation_reports_step_index_gap_and_active_assets_as_blocking(tmp_path: Path):
    capture_dir = _write_scenario(tmp_path, asset_status="active", step_indexes=[1, 3])
    _write_checkpoint(capture_dir, step_index=1)
    _write_checkpoint(capture_dir, step_index=3)

    report = validate_harness_assets(tmp_path)

    assert report["summary"]["blocking_issue_count"] == 1
    issue = report["issues"][0]
    assert issue["category"] == "step-index-gap"
    assert issue["missing_step_indexes"] == [2]
    assert issue["blocking"] is True


def test_validation_reports_missing_checkpoint_evidence_files(tmp_path: Path):
    capture_dir = _write_scenario(tmp_path, step_indexes=[1])
    _write_checkpoint(
        capture_dir,
        step_index=1,
        write_before=False,
        write_after=False,
        write_trace=False,
        write_expected=False,
    )

    report = validate_harness_assets(tmp_path)

    assert {issue["category"] for issue in report["issues"]} == {
        "missing-before-html",
        "missing-after-html",
        "missing-trace-events",
        "missing-expected-signals",
    }


def test_validation_reports_empty_after_html_for_successful_changed_state(tmp_path: Path):
    capture_dir = _write_scenario(tmp_path, step_indexes=[1])
    _write_checkpoint(capture_dir, step_index=1, after_html="")

    report = validate_harness_assets(tmp_path)

    assert report["summary"]["issue_count"] == 1
    issue = report["issues"][0]
    assert issue["category"] == "empty-after-html"
    assert issue["step_index"] == 1
    assert issue["blocking"] is False


def test_validation_allows_same_as_before_success_without_after_file(tmp_path: Path):
    capture_dir = _write_scenario(tmp_path, capture_scope="selected_steps", step_indexes=[3])
    _write_checkpoint(capture_dir, step_index=3, same_as_before=True, write_after=False)

    report = validate_harness_assets(tmp_path)

    assert report["summary"]["issue_count"] == 0


def test_asset_validation_cli_writes_report_and_fails_only_for_blocking_issues(tmp_path: Path):
    capture_dir = _write_scenario(tmp_path, asset_status="active", step_indexes=[1, 3])
    _write_checkpoint(capture_dir, step_index=1)
    _write_checkpoint(capture_dir, step_index=3)
    output_path = tmp_path / "validation.json"

    exit_code = run_asset_validation_main(["--assets", str(tmp_path), "--output", str(output_path)])

    assert exit_code == 1
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["summary"]["blocking_issue_count"] == 1
    assert report["issues"][0]["category"] == "step-index-gap"
