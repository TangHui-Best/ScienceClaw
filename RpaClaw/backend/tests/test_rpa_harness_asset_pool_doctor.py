import json
from pathlib import Path

from backend.rpa.harness.asset_pool_doctor import build_asset_pool_doctor_report
from backend.rpa.harness.run_asset_pool_doctor import main as run_asset_pool_doctor_main


def _write_asset(
    root: Path,
    *,
    asset_id: str,
    asset_status: str = "draft",
    promotion_status: str = "captured",
    expected_signals_reviewed: bool = False,
    sensitivity_reviewed: bool = False,
    runner_modes: list[str] | None = None,
    core_chain_coverage: list[str] | None = None,
    page_patterns: list[str] | None = None,
) -> None:
    asset_dir = root / asset_id
    asset_dir.mkdir(parents=True)
    (asset_dir / "scenario.json").write_text(
        json.dumps(
            {
                "schema_version": "rpa-harness-scenario-v0",
                "asset_id": asset_id,
                "capture_scope": "full_sop",
                "sop_intent": f"Review {asset_id}",
                "source": {
                    "recording_id": f"rec-{asset_id}",
                    "captured_at": "2026-05-31T10:00:00",
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
                    "review_notes": "doctor test fixture",
                },
                "step_checkpoints": [],
            }
        ),
        encoding="utf-8",
    )


def test_asset_pool_doctor_marks_pool_not_ready_without_blocking_baseline(tmp_path: Path):
    _write_asset(tmp_path, asset_id="draft-asset")
    _write_asset(
        tmp_path,
        asset_id="candidate-lite-asset",
        promotion_status="candidate-lite",
        core_chain_coverage=["html_to_raw_snapshot", "trace_to_skill"],
    )

    report = build_asset_pool_doctor_report(tmp_path)

    assert report["schema_version"] == "rpa-harness-asset-pool-doctor-v1"
    assert report["summary"]["readiness"] == "not_ready"
    assert report["summary"]["blocking_baseline_count"] == 0
    assert report["summary"]["warning_only_count"] == 1
    assert report["summary"]["recommended_next_action"] == "review_or_promote_assets"
    assert report["blocking_baseline_asset_ids"] == []
    assert report["warning_only_asset_ids"] == ["candidate-lite-asset"]
    by_id = {asset["asset_id"]: asset for asset in report["excluded_assets"]}
    assert by_id["draft-asset"]["reasons"] == [
        "asset-status-draft",
        "promotion-status-captured",
        "missing-core-chain-coverage",
        "expected-signals-not-reviewed",
        "sensitivity-not-reviewed",
    ]
    assert by_id["candidate-lite-asset"]["reasons"] == [
        "asset-status-draft",
        "promotion-status-candidate-lite",
        "expected-signals-not-reviewed",
        "sensitivity-not-reviewed",
    ]
    assert report["human_governance"]["agents_may_promote_automatically"] is False


def test_asset_pool_doctor_reports_ready_with_reviewed_candidate(tmp_path: Path):
    _write_asset(
        tmp_path,
        asset_id="candidate-ready",
        asset_status="active",
        promotion_status="candidate",
        expected_signals_reviewed=True,
        sensitivity_reviewed=True,
        core_chain_coverage=["html_to_raw_snapshot", "raw_to_compact_snapshot", "trace_to_skill"],
        page_patterns=["card-list", "detail-page"],
    )

    report = build_asset_pool_doctor_report(tmp_path)

    assert report["summary"]["readiness"] == "ready"
    assert report["summary"]["status"] == "pass"
    assert report["summary"]["blocking_baseline_count"] == 1
    assert report["summary"]["recommended_next_action"] == "run_deterministic_profile"
    assert report["blocking_baseline_asset_ids"] == ["candidate-ready"]
    assert report["excluded_assets"] == []
    assert "card-list" in report["coverage_boundary"]["page_patterns"]


def test_asset_pool_doctor_cli_writes_json_report(tmp_path: Path):
    _write_asset(tmp_path, asset_id="candidate-lite-asset", promotion_status="candidate-lite")
    output_path = tmp_path / "doctor.json"

    exit_code = run_asset_pool_doctor_main(
        ["--assets", str(tmp_path), "--output", str(output_path)]
    )

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["summary"]["readiness"] == "not_ready"
    assert report["warning_only_asset_ids"] == ["candidate-lite-asset"]


def test_asset_pool_doctor_cli_writes_chinese_summary(tmp_path: Path):
    _write_asset(tmp_path, asset_id="candidate-lite-asset", promotion_status="candidate-lite")
    output_path = tmp_path / "doctor-summary.md"

    exit_code = run_asset_pool_doctor_main(
        ["--assets", str(tmp_path), "--format", "summary", "--lang", "zh", "--output", str(output_path)]
    )

    assert exit_code == 0
    summary = output_path.read_text(encoding="utf-8")
    assert "资产池体检：not_ready" in summary
    assert "blocking baseline：0" in summary
    assert "candidate-lite-asset" in summary
