import json
from pathlib import Path

from backend.rpa.harness.governed_regression import run_governed_offline_regression
from backend.rpa.harness.run_governed_regression import main as run_governed_regression_main


def _write_asset(
    root: Path,
    *,
    asset_id: str,
    asset_status: str = "active",
    promotion_status: str = "candidate",
    runner_modes: list[str] | None = None,
    core_chain_coverage: list[str] | None = None,
    expected_signals_reviewed: bool = True,
    sensitivity_reviewed: bool = True,
    page_patterns: list[str] | None = None,
    step_text: str = "ScienceClaw",
) -> None:
    asset_dir = root / asset_id
    step_dir = asset_dir / "steps" / "001"
    step_dir.mkdir(parents=True, exist_ok=True)
    patterns = page_patterns or ["repository-detail"]
    (asset_dir / "scenario.json").write_text(
        json.dumps(
            {
                "schema_version": "rpa-harness-scenario-v0",
                "asset_id": asset_id,
                "capture_scope": "full_sop",
                "sop_intent": "Open and inspect a repository",
                "source": {
                    "recording_id": f"rec-{asset_id}",
                    "captured_at": "2026-05-18T10:00:00",
                    "capture_mode": "harness",
                    "capture_trigger": "full_sop",
                },
                "asset_status": asset_status,
                "sensitivity": "local-only",
                "page_patterns": patterns,
                "governance": {
                    "promotion_status": promotion_status,
                    "runner_modes": runner_modes or ["offline_core_chain"],
                    "core_chain_coverage": core_chain_coverage
                    or [
                        "html_to_raw_snapshot",
                        "raw_to_compact_snapshot",
                        "trace_to_skill",
                    ],
                    "expected_signals_reviewed": expected_signals_reviewed,
                    "sensitivity_reviewed": sensitivity_reviewed,
                    "review_notes": "reviewed for governed offline regression",
                },
                "step_checkpoints": [{"step_index": 1, "checkpoint_path": "steps/001/checkpoint.json"}],
            }
        ),
        encoding="utf-8",
    )
    (step_dir / "before.html").write_text(
        f"<html><body><span>{step_text}</span></body></html>",
        encoding="utf-8",
    )
    (step_dir / "after.html").write_text(
        f"<html><body><span>{step_text} after</span></body></html>",
        encoding="utf-8",
    )
    (step_dir / "trace_events.json").write_text("[]", encoding="utf-8")
    (step_dir / "expected.json").write_text(
        json.dumps({"snapshot_signals": {"must_contain_text": [step_text]}}),
        encoding="utf-8",
    )
    (step_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "step_index": 1,
                "step_id": f"trace-{asset_id}",
                "step_intent": "Inspect repository",
                "recording_mode": "manual",
                "page_patterns": patterns,
                "before": {
                    "url": "https://example.test/repo",
                    "title": "Repo",
                    "html_path": "steps/001/before.html",
                    "html_sha256": "before",
                },
                "action": {"trace_events_path": "steps/001/trace_events.json"},
                "after": {
                    "url": "https://example.test/repo",
                    "title": "Repo",
                    "html_path": "steps/001/after.html",
                    "html_sha256": "after",
                    "capture_quality": {
                        "status": "stable",
                        "ready_state": "complete",
                        "title_present": True,
                    },
                },
                "runtime_result": {"status": "success"},
                "captured_at": "2026-05-18T10:00:00",
                "expected_path": "steps/001/expected.json",
            }
        ),
        encoding="utf-8",
    )


def test_governed_offline_regression_selects_only_reviewed_candidate_and_golden_assets(tmp_path: Path):
    _write_asset(tmp_path, asset_id="candidate-ready", promotion_status="candidate")
    _write_asset(tmp_path, asset_id="golden-ready", promotion_status="golden")
    _write_asset(tmp_path, asset_id="draft-captured", asset_status="draft", promotion_status="captured")
    _write_asset(tmp_path, asset_id="candidate-unreviewed", expected_signals_reviewed=False)
    _write_asset(tmp_path, asset_id="candidate-live-only", runner_modes=["skill_replay_e2e"])

    report = run_governed_offline_regression(tmp_path)

    assert report["schema_version"] == "rpa-harness-governed-offline-regression-v0"
    assert report["summary"]["status"] == "passed"
    assert report["summary"]["selected_capture_count"] == 2
    assert report["summary"]["selected_step_count"] == 2
    assert report["summary"]["excluded_capture_count"] == 3
    assert report["summary"]["selected_asset_ids"] == ["candidate-ready", "golden-ready"]
    assert report["snapshot"]["summary"] == {"total": 2, "passed": 2, "failed": 0}
    assert report["compiler"]["summary"] == {"total": 2, "passed": 2, "failed": 0}
    assert report["blast_radius"]["summary"]["checked_steps"] == 2
    excluded = {item["asset_id"]: item["reasons"] for item in report["selection"]["excluded_captures"]}
    assert excluded["draft-captured"] == ["asset-status-draft", "promotion-status-captured"]
    assert excluded["candidate-unreviewed"] == ["expected-signals-not-reviewed"]
    assert excluded["candidate-live-only"] == ["offline-core-chain-not-enabled"]


def test_governed_offline_regression_exposes_observability_contract(tmp_path: Path):
    _write_asset(
        tmp_path,
        asset_id="candidate-ready",
        promotion_status="candidate",
        page_patterns=["card-list", "detail-page"],
    )
    _write_asset(tmp_path, asset_id="draft-captured", asset_status="draft", promotion_status="captured")

    report = run_governed_offline_regression(tmp_path)

    observability = report["observability"]
    assert observability["schema_version"] == "rpa-harness-observability-v0"
    assert observability["asset_qualification"] == {
        "scanned_capture_count": 2,
        "selected_capture_count": 1,
        "excluded_capture_count": 1,
        "selected_asset_ids": ["candidate-ready"],
        "excluded_asset_ids": ["draft-captured"],
        "selected_promotion_status_counts": {"candidate": 1},
        "excluded_reason_counts": {
            "asset-status-draft": 1,
            "promotion-status-captured": 1,
        },
    }
    assert observability["coverage"]["selected_step_count"] == 1
    assert observability["coverage"]["page_patterns"] == ["card-list", "detail-page"]
    assert observability["coverage"]["core_chain_coverage"] == {
        "html_to_raw_snapshot": 1,
        "raw_to_compact_snapshot": 1,
        "trace_to_skill": 1,
    }
    assert observability["runner_signals"]["snapshot_failure_categories"] == {}
    assert observability["runner_signals"]["compiler_failure_categories"] == {}
    assert observability["runner_signals"]["skill_replay_checked"] == 0
    assert observability["runner_signals"]["skill_replay_failed"] == 0
    assert observability["runner_signals"]["skill_replay_failure_categories"] == {}
    assert observability["runner_signals"]["snapshot_quality"] == {
        "source": "production-dom-snapshot-v1",
        "checked_steps": 1,
        "raw_signal_present": 1,
        "compact_signal_present": 1,
        "raw_signal_missing": 0,
        "compact_signal_missing": 0,
        "average_compression_ratio": observability["runner_signals"]["snapshot_quality"][
            "average_compression_ratio"
        ],
    }
    assert observability["runner_signals"]["snapshot_quality"]["average_compression_ratio"] > 0
    assert observability["confidence"]["risks"] == ["single-candidate-asset-baseline"]


def test_governed_offline_regression_exposes_skill_replay_runner_signal(tmp_path: Path):
    _write_asset(
        tmp_path,
        asset_id="candidate-ready",
        runner_modes=["offline_core_chain", "skill_replay_e2e"],
        core_chain_coverage=[
            "html_to_raw_snapshot",
            "raw_to_compact_snapshot",
            "trace_to_skill",
            "skill_replay",
        ],
    )

    report = run_governed_offline_regression(tmp_path)

    assert report["skill_replay"]["schema_version"] == "rpa-harness-skill-replay-e2e-v0"
    assert report["skill_replay"]["summary"]["total"] == 1
    assert report["summary"]["skill_replay_failed"] == 0
    assert report["observability"]["runner_signals"]["skill_replay_checked"] == 1
    assert report["observability"]["runner_signals"]["skill_replay_failed"] == 0


def test_governed_offline_regression_marks_selected_runner_failures_as_blocking(tmp_path: Path):
    _write_asset(tmp_path, asset_id="candidate-broken", step_text="Expected text")
    expected_path = tmp_path / "candidate-broken" / "steps" / "001" / "expected.json"
    expected_path.write_text(
        json.dumps({"snapshot_signals": {"must_contain_text": ["Missing text"]}}),
        encoding="utf-8",
    )

    report = run_governed_offline_regression(tmp_path)

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["snapshot_failed"] == 1
    assert report["observability"]["runner_signals"]["snapshot_failure_categories"] == {
        "source-html-missing-signal": 1
    }
    assert report["observability"]["blast_radius"]["affected_page_patterns"] == ["repository-detail"]
    assert report["blast_radius"]["summary"]["blocking_failed_steps"] == 1
    assert report["blast_radius"]["affected_steps"][0]["asset_id"] == "candidate-broken"


def test_governed_offline_regression_fails_when_no_governed_assets_exist(tmp_path: Path):
    _write_asset(tmp_path, asset_id="draft-captured", asset_status="draft", promotion_status="captured")

    report = run_governed_offline_regression(tmp_path)

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["failure_category"] == "no-governed-offline-assets"
    assert report["summary"]["selected_capture_count"] == 0
    assert report["validation"]["summary"]["capture_count"] == 0
    assert report["selection"]["excluded_captures"][0]["asset_id"] == "draft-captured"


def test_governed_offline_regression_cli_writes_report(tmp_path: Path):
    _write_asset(tmp_path, asset_id="candidate-ready")
    output_path = tmp_path / "governed-report.json"

    exit_code = run_governed_regression_main(
        ["--assets", str(tmp_path), "--output", str(output_path)]
    )

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["summary"]["selected_asset_ids"] == ["candidate-ready"]
    assert report["summary"]["status"] == "passed"


def test_governed_offline_regression_cli_can_emit_human_summary(tmp_path: Path, capsys):
    _write_asset(tmp_path, asset_id="candidate-ready")

    exit_code = run_governed_regression_main(["--assets", str(tmp_path), "--format", "summary"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Governed Offline Regression: passed" in output
    assert "Evaluated: 1 candidate asset, 1 step" in output
    assert "Coverage: repository-detail" in output
    assert "Signals: validation blocking=0, snapshot failed=0, compiler failed=0" in output
    assert "Snapshot quality: source=production-dom-snapshot-v1, checked steps=1" in output
    assert "compact signal present=1" in output
    assert "Confidence risks: single-candidate-asset-baseline" in output


def test_governed_offline_regression_cli_can_emit_chinese_summary(tmp_path: Path, capsys):
    _write_asset(tmp_path, asset_id="candidate-ready")

    exit_code = run_governed_regression_main(
        ["--assets", str(tmp_path), "--format", "summary", "--lang", "zh"]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "受治理离线回归：通过" in output
    assert "本次评估：1 个 candidate 资产，1 个步骤" in output
    assert "覆盖范围：repository-detail" in output
    assert "执行信号：validation 阻塞=0，snapshot 失败=0，compiler 失败=0" in output
    assert "Snapshot 质量：source=production-dom-snapshot-v1，检查步骤=1" in output
    assert "compact signal 保留=1" in output
    assert "可信度边界：single-candidate-asset-baseline" in output


def test_governed_offline_regression_summary_names_candidate_and_golden_assets(tmp_path: Path, capsys):
    _write_asset(tmp_path, asset_id="candidate-ready", promotion_status="candidate")
    _write_asset(tmp_path, asset_id="golden-ready", promotion_status="golden")

    exit_code = run_governed_regression_main(["--assets", str(tmp_path), "--format", "summary"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Evaluated: 1 candidate asset, 1 golden asset, 2 steps" in output
