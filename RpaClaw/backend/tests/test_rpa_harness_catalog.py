import json
from pathlib import Path

from backend.rpa.harness.catalog import build_harness_catalog
from backend.rpa.harness.run_catalog import main as run_catalog_main


def _write_checkpoint(
    root: Path,
    *,
    asset_id: str = "asset-1",
    step_index: int = 1,
    step_id: str = "step-1",
    step_intent: str = "Click ScienceClaw",
    recording_mode: str = "natural_language",
    status: str = "success",
    before_url: str = "https://example.test/search",
    after_url: str = "https://example.test/project",
    page_patterns: list[str] | None = None,
) -> Path:
    step_dir = root / asset_id / "steps" / f"{step_index:03d}"
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "step_index": step_index,
                "step_id": step_id,
                "step_intent": step_intent,
                "recording_mode": recording_mode,
                "page_patterns": page_patterns or ["search-result"],
                "before": {
                    "url": before_url,
                    "title": "Search",
                    "html_path": f"steps/{step_index:03d}/before.html",
                    "html_sha256": "abc",
                },
                "action": {
                    "trace_events_path": f"steps/{step_index:03d}/trace_events.json",
                    "expected_action_type": "click",
                },
                "after": (
                    {
                        "url": after_url,
                        "title": "Project",
                        "html_path": f"steps/{step_index:03d}/after.html",
                        "html_sha256": "def",
                    }
                    if status == "success"
                    else None
                ),
                "runtime_result": {"status": status, "error": "not found" if status == "failed" else None},
                "captured_at": "2026-05-17T10:00:00",
                "expected_path": f"steps/{step_index:03d}/expected.json",
                "failure_path": f"steps/{step_index:03d}/failure.json" if status == "failed" else "",
            }
        ),
        encoding="utf-8",
    )
    (step_dir / "expected.json").write_text(
        json.dumps({"snapshot_signals": {"must_contain_text": ["ScienceClaw"]}}),
        encoding="utf-8",
    )
    return step_dir


def test_catalog_summarizes_capture_assets_and_step_coverage(tmp_path: Path):
    scenario_dir = tmp_path / "asset-1"
    scenario_dir.mkdir()
    (scenario_dir / "scenario.json").write_text(
        json.dumps(
            {
                "schema_version": "rpa-harness-scenario-v0",
                "asset_id": "asset-1",
                "capture_scope": "selected_steps",
                "sop_intent": "Search and open a project",
                "source": {
                    "recording_id": "rec-1",
                    "captured_at": "2026-05-17T10:00:00",
                    "capture_mode": "harness",
                    "capture_trigger": "selected_step",
                },
                "asset_status": "active",
                "sensitivity": "local-only",
                "page_patterns": ["search-result", "card-list"],
                "step_checkpoints": [{"step_index": 1, "checkpoint_path": "steps/001/checkpoint.json"}],
            }
        ),
        encoding="utf-8",
    )
    _write_checkpoint(
        tmp_path,
        page_patterns=["search-result", "card-list"],
        before_url="https://example.test/search?q=scienceclaw",
        after_url="https://example.test/projects/scienceclaw",
    )
    _write_checkpoint(
        tmp_path,
        step_index=2,
        step_id="step-2",
        step_intent="Extract repository metadata",
        recording_mode="manual",
        status="failed",
        before_url="https://docs.example.test/repositories/scienceclaw",
        after_url="",
        page_patterns=["detail-page"],
    )

    catalog = build_harness_catalog(tmp_path)

    assert catalog["summary"]["capture_count"] == 1
    assert catalog["summary"]["step_count"] == 2
    assert catalog["summary"]["successful_step_count"] == 1
    assert catalog["summary"]["failed_step_count"] == 1
    assert catalog["summary"]["asset_statuses"] == {"active": 1}
    assert catalog["summary"]["sensitivity"] == {"local-only": 1}
    assert catalog["summary"]["recording_modes"] == {"manual": 1, "natural_language": 1}
    assert catalog["summary"]["page_patterns"] == ["card-list", "detail-page", "search-result"]
    assert catalog["summary"]["hosts"] == ["docs.example.test", "example.test"]
    assert catalog["captures"][0]["capture_scope"] == "selected_steps"
    assert catalog["captures"][0]["asset_status"] == "active"
    assert catalog["steps"][0]["expected_path"] == "asset-1/steps/001/expected.json"
    assert catalog["steps"][1]["runtime_status"] == "failed"


def test_catalog_falls_back_when_scenario_manifest_is_missing(tmp_path: Path):
    _write_checkpoint(tmp_path, asset_id="hcap-local", step_index=3)

    catalog = build_harness_catalog(tmp_path)

    assert catalog["summary"]["capture_count"] == 1
    assert catalog["summary"]["asset_statuses"] == {"draft": 1}
    assert catalog["captures"][0]["asset_id"] == "hcap-local"
    assert catalog["captures"][0]["capture_scope"] == "unknown"
    assert catalog["steps"][0]["checkpoint_path"] == "hcap-local/steps/003/checkpoint.json"
    assert catalog["warnings"] == []


def test_catalog_records_warnings_for_invalid_checkpoint_assets(tmp_path: Path):
    bad_step = tmp_path / "asset-bad" / "steps" / "001"
    bad_step.mkdir(parents=True)
    (bad_step / "checkpoint.json").write_text("{not-json", encoding="utf-8")

    catalog = build_harness_catalog(tmp_path)

    assert catalog["summary"]["capture_count"] == 1
    assert catalog["summary"]["step_count"] == 0
    assert catalog["warnings"][0]["asset_id"] == "asset-bad"
    assert catalog["warnings"][0]["path"] == "asset-bad/steps/001/checkpoint.json"


def test_catalog_cli_writes_report_file(tmp_path: Path):
    _write_checkpoint(tmp_path, asset_id="asset-cli")
    output_path = tmp_path / "catalog.json"

    exit_code = run_catalog_main(["--assets", str(tmp_path), "--output", str(output_path)])

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["summary"]["step_count"] == 1
    assert report["captures"][0]["asset_id"] == "asset-cli"
