import json
from pathlib import Path

from backend.rpa.harness.catalog import (
    build_asset_lifecycle_summary,
    build_golden_eligibility_report,
    build_harness_catalog,
)
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


def _write_scenario_asset(
    root: Path,
    *,
    asset_id: str,
    asset_status: str = "draft",
    promotion_status: str = "captured",
    runner_modes: list[str] | None = None,
    core_chain_coverage: list[str] | None = None,
    expected_signals_reviewed: bool = False,
    sensitivity_reviewed: bool = False,
    page_patterns: list[str] | None = None,
    before_url: str = "https://example.test/search",
) -> Path:
    asset_dir = root / asset_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "scenario.json").write_text(
        json.dumps(
            {
                "schema_version": "rpa-harness-scenario-v0",
                "asset_id": asset_id,
                "capture_scope": "full_sop",
                "sop_intent": f"Review lifecycle asset {asset_id}",
                "source": {
                    "recording_id": f"rec-{asset_id}",
                    "captured_at": "2026-05-28T10:00:00",
                    "capture_mode": "harness",
                    "capture_trigger": "full_sop",
                },
                "asset_status": asset_status,
                "sensitivity": "repo-safe" if sensitivity_reviewed else "local-only",
                "page_patterns": page_patterns or ["detail-page"],
                "governance": {
                    "promotion_status": promotion_status,
                    "runner_modes": runner_modes or ["offline_core_chain"],
                    "core_chain_coverage": core_chain_coverage or [],
                    "expected_signals_reviewed": expected_signals_reviewed,
                    "sensitivity_reviewed": sensitivity_reviewed,
                    "review_notes": "lifecycle test fixture",
                },
                "step_checkpoints": [{"step_index": 1, "checkpoint_path": "steps/001/checkpoint.json"}],
            }
        ),
        encoding="utf-8",
    )
    _write_checkpoint(
        root,
        asset_id=asset_id,
        before_url=before_url,
        after_url=before_url.rstrip("/") + "/done",
        page_patterns=page_patterns or ["detail-page"],
    )
    return asset_dir


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
                "governance": {
                    "promotion_status": "golden",
                    "runner_modes": ["offline_core_chain", "skill_replay_e2e"],
                    "core_chain_coverage": [
                        "html_to_raw_snapshot",
                        "raw_to_compact_snapshot",
                        "trace_to_skill",
                    ],
                    "expected_signals_reviewed": True,
                    "sensitivity_reviewed": True,
                },
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
    assert catalog["summary"]["promotion_statuses"] == {"golden": 1}
    assert catalog["summary"]["runner_modes"] == {"offline_core_chain": 1, "skill_replay_e2e": 1}
    assert catalog["summary"]["core_chain_coverage"] == {
        "html_to_raw_snapshot": 1,
        "raw_to_compact_snapshot": 1,
        "trace_to_skill": 1,
    }
    assert catalog["summary"]["recording_modes"] == {"manual": 1, "natural_language": 1}
    assert catalog["summary"]["page_patterns"] == ["card-list", "detail-page", "search-result"]
    assert catalog["summary"]["hosts"] == ["docs.example.test", "example.test"]
    assert catalog["captures"][0]["capture_scope"] == "selected_steps"
    assert catalog["captures"][0]["asset_status"] == "active"
    assert catalog["captures"][0]["governance"]["promotion_status"] == "golden"
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


def test_asset_lifecycle_summary_reports_distribution_and_review_state(tmp_path: Path):
    _write_scenario_asset(tmp_path, asset_id="draft-capture")
    _write_scenario_asset(
        tmp_path,
        asset_id="candidate-lite-observed",
        promotion_status="candidate-lite",
        runner_modes=["offline_core_chain", "skill_replay_e2e"],
        core_chain_coverage=["html_to_raw_snapshot", "trace_to_skill"],
        page_patterns=["card-list"],
    )
    _write_scenario_asset(
        tmp_path,
        asset_id="candidate-ready",
        asset_status="active",
        promotion_status="candidate",
        core_chain_coverage=["html_to_raw_snapshot", "raw_to_compact_snapshot", "trace_to_skill"],
        expected_signals_reviewed=True,
        sensitivity_reviewed=True,
        page_patterns=["detail-page"],
    )
    _write_scenario_asset(
        tmp_path,
        asset_id="golden-ready",
        asset_status="active",
        promotion_status="golden",
        core_chain_coverage=["html_to_raw_snapshot", "raw_to_compact_snapshot", "trace_to_skill"],
        expected_signals_reviewed=True,
        sensitivity_reviewed=True,
        page_patterns=["form"],
        before_url="https://internal.example.test/form",
    )
    _write_scenario_asset(
        tmp_path,
        asset_id="candidate-unreviewed",
        asset_status="active",
        promotion_status="candidate",
        core_chain_coverage=["trace_to_skill"],
        expected_signals_reviewed=False,
        sensitivity_reviewed=True,
    )

    summary = build_asset_lifecycle_summary(tmp_path)

    assert summary["schema_version"] == "rpa-harness-asset-lifecycle-summary-v1"
    assert summary["summary"]["asset_count"] == 5
    assert summary["summary"]["promotion_statuses"] == {
        "candidate": 2,
        "candidate-lite": 1,
        "captured": 1,
        "golden": 1,
    }
    assert summary["summary"]["lifecycle_distribution"] == {
        "draft": 1,
        "candidate-lite": 1,
        "candidate": 2,
        "golden": 1,
    }
    assert summary["review_state"] == {
        "expected_signals_reviewed": 2,
        "expected_signals_unreviewed": 3,
        "sensitivity_reviewed": 3,
        "sensitivity_unreviewed": 2,
    }
    assert summary["blocking_baseline_asset_ids"] == ["candidate-ready", "golden-ready"]
    assert summary["warning_only_asset_ids"] == ["candidate-lite-observed"]
    assert summary["golden_asset_ids"] == ["golden-ready"]
    assert summary["coverage_boundary"]["runner_modes"]["offline_core_chain"] == 5
    assert summary["coverage_boundary"]["core_chain_coverage"]["trace_to_skill"] == 4
    assert summary["coverage_boundary"]["page_patterns"] == ["card-list", "detail-page", "form"]
    assert "bootstrap coverage" in " ".join(summary["trust_limits"])
    assert {
        "asset_id": "candidate-unreviewed",
        "reasons": ["expected-signals-not-reviewed"],
    } in summary["lifecycle_warnings"]
    assert "catalog" not in summary


def test_asset_lifecycle_summary_requires_explicit_catalog_details(tmp_path: Path):
    _write_scenario_asset(
        tmp_path,
        asset_id="candidate-ready",
        asset_status="active",
        promotion_status="candidate",
        core_chain_coverage=["trace_to_skill"],
        expected_signals_reviewed=True,
        sensitivity_reviewed=True,
    )

    summary = build_asset_lifecycle_summary(tmp_path, include_catalog=True)

    assert "catalog" in summary
    assert summary["catalog"]["captures"][0]["asset_id"] == "candidate-ready"


def test_golden_eligibility_report_requires_candidate_review_and_human_approval(tmp_path: Path):
    _write_scenario_asset(
        tmp_path,
        asset_id="candidate-ready",
        asset_status="active",
        promotion_status="candidate",
        core_chain_coverage=["html_to_raw_snapshot", "trace_to_skill"],
        expected_signals_reviewed=True,
        sensitivity_reviewed=True,
    )
    _write_scenario_asset(
        tmp_path,
        asset_id="candidate-lite-observed",
        promotion_status="candidate-lite",
        core_chain_coverage=["trace_to_skill"],
    )
    _write_scenario_asset(
        tmp_path,
        asset_id="candidate-unreviewed",
        asset_status="active",
        promotion_status="candidate",
        core_chain_coverage=["trace_to_skill"],
        expected_signals_reviewed=False,
        sensitivity_reviewed=False,
    )

    before = (tmp_path / "candidate-ready" / "scenario.json").read_text(encoding="utf-8")
    report = build_golden_eligibility_report(tmp_path)
    after = (tmp_path / "candidate-ready" / "scenario.json").read_text(encoding="utf-8")

    assert report["schema_version"] == "rpa-harness-golden-eligibility-v1"
    assert before == after
    by_id = {item["asset_id"]: item for item in report["assets"]}
    assert by_id["candidate-ready"]["eligible"] is True
    assert by_id["candidate-ready"]["requires_human_approval"] is True
    assert by_id["candidate-ready"]["blocking_reasons"] == []
    assert by_id["candidate-lite-observed"]["eligible"] is False
    assert "promotion-status-candidate-lite" in by_id["candidate-lite-observed"]["blocking_reasons"]
    assert by_id["candidate-unreviewed"]["eligible"] is False
    assert by_id["candidate-unreviewed"]["blocking_reasons"] == [
        "expected-signals-not-reviewed",
        "sensitivity-not-reviewed",
    ]
