import json
from pathlib import Path

import pytest

from backend.rpa.harness.profile_runner import render_profile_summary, run_harness_profile
from backend.rpa.harness.run_harness_profile import main as run_harness_profile_main


def _write_asset(
    root: Path,
    *,
    asset_id: str,
    promotion_status: str = "candidate",
    runner_modes: list[str] | None = None,
    step_text: str = "ScienceClaw",
) -> None:
    asset_dir = root / asset_id
    step_dir = asset_dir / "steps" / "001"
    step_dir.mkdir(parents=True, exist_ok=True)
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
                "asset_status": "active",
                "sensitivity": "local-only",
                "page_patterns": ["repository-detail"],
                "governance": {
                    "promotion_status": promotion_status,
                    "runner_modes": runner_modes or ["offline_core_chain"],
                    "core_chain_coverage": [
                        "html_to_raw_snapshot",
                        "raw_to_compact_snapshot",
                        "trace_to_skill",
                    ],
                    "expected_signals_reviewed": True,
                    "sensitivity_reviewed": True,
                    "review_notes": "reviewed for deterministic profile",
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
                "page_patterns": ["repository-detail"],
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


def test_deterministic_profile_wraps_governed_regression_report(tmp_path: Path):
    _write_asset(tmp_path, asset_id="candidate-ready")

    report = run_harness_profile(tmp_path, profile="deterministic")

    assert report["schema_version"] == "rpa-harness-profile-run-v1"
    assert report["profile"] == {
        "name": "deterministic",
        "execution_mode": "scripted-assets",
        "uses_live_planner": False,
        "uses_live_url_oracle": False,
        "governance_mode": "human-governed-assets",
    }
    assert report["summary"]["status"] == "passed"
    assert report["summary"]["blocking"] is False
    assert report["summary"]["first_failure_category"] == ""
    assert report["summary"]["selected_asset_count"] == 1
    assert report["summary"]["excluded_asset_count"] == 0
    assert report["summary"]["warning_only_observation_count"] == 0
    assert report["deterministic"]["schema_version"] == "rpa-harness-governed-offline-regression-v0"
    assert report["deterministic"]["summary"]["selected_asset_ids"] == ["candidate-ready"]


def test_deterministic_profile_preserves_first_failure_category(tmp_path: Path):
    _write_asset(tmp_path, asset_id="candidate-broken", step_text="Expected text")
    expected_path = tmp_path / "candidate-broken" / "steps" / "001" / "expected.json"
    expected_path.write_text(
        json.dumps({"snapshot_signals": {"must_contain_text": ["Missing text"]}}),
        encoding="utf-8",
    )

    report = run_harness_profile(tmp_path, profile="deterministic")

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["blocking"] is True
    assert report["summary"]["first_failure_category"] == "snapshot-regression-failed"


def test_profile_interpretation_passed_single_run_is_no_meaningful_change(tmp_path: Path):
    _write_asset(tmp_path, asset_id="candidate-ready")

    report = run_harness_profile(tmp_path, profile="deterministic")

    interpretation = report["interpretation"]
    assert interpretation["verdict"] == "no meaningful change"
    assert interpretation["bounded"] is True
    assert interpretation["comparison_basis"] == "single-run"
    assert interpretation["first_failure_category"] == ""
    assert "No baseline comparison report was supplied" in interpretation["evidence_limits"]
    assert interpretation["recommended_agent_flow"][:4] == [
        "interpretation",
        "summary",
        "profile",
        "deterministic.observability",
    ]


def test_profile_interpretation_failed_run_is_regression(tmp_path: Path):
    _write_asset(tmp_path, asset_id="candidate-broken", step_text="Expected text")
    expected_path = tmp_path / "candidate-broken" / "steps" / "001" / "expected.json"
    expected_path.write_text(
        json.dumps({"snapshot_signals": {"must_contain_text": ["Missing text"]}}),
        encoding="utf-8",
    )

    report = run_harness_profile(tmp_path, profile="deterministic")

    interpretation = report["interpretation"]
    assert interpretation["verdict"] == "regression"
    assert interpretation["bounded"] is True
    assert interpretation["comparison_basis"] == "single-run"
    assert interpretation["first_failure_category"] == "snapshot-regression-failed"
    assert "deterministic.observability.runner_signals" in interpretation["basis"]


def test_profile_interpretation_without_selected_assets_is_insufficient_evidence(tmp_path: Path):
    report = run_harness_profile(tmp_path, profile="deterministic")

    interpretation = report["interpretation"]
    assert interpretation["verdict"] == "insufficient evidence"
    assert interpretation["bounded"] is True
    assert interpretation["comparison_basis"] == "single-run"
    assert "No selected governed assets ran" in interpretation["evidence_limits"]


def test_profile_interpretation_without_runner_signals_is_insufficient_evidence(tmp_path: Path, monkeypatch):
    from backend.rpa.harness import profile_runner

    def fake_governed_regression(_assets_root: Path):
        return {
            "schema_version": "rpa-harness-governed-offline-regression-v0",
            "summary": {
                "status": "passed",
                "failure_category": "",
                "selected_capture_count": 1,
                "excluded_capture_count": 0,
                "selected_asset_ids": ["candidate-ready"],
                "excluded_asset_ids": [],
                "candidate_lite_observed_count": 0,
                "candidate_lite_warning_count": 0,
            },
            "observability": {},
        }

    monkeypatch.setattr(
        profile_runner,
        "run_governed_offline_regression",
        fake_governed_regression,
    )

    report = run_harness_profile(tmp_path, profile="deterministic")

    interpretation = report["interpretation"]
    assert interpretation["verdict"] == "insufficient evidence"
    assert "Missing deterministic.observability.runner_signals" in interpretation["evidence_limits"]
    assert "deterministic.observability.runner_signals=missing" in interpretation["basis"]


def test_full_profile_is_explicitly_out_of_phase_one(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsupported RPA Harness profile: full"):
        run_harness_profile(tmp_path, profile="full")


def test_profile_summary_names_profile_and_machine_report_path(tmp_path: Path):
    _write_asset(tmp_path, asset_id="candidate-ready")
    report = run_harness_profile(tmp_path, profile="deterministic")

    summary = render_profile_summary(report, machine_report_path="tmp-profile.json")

    assert "RPA Harness Profile: deterministic" in summary
    assert "Status: passed" in summary
    assert "Selected assets: candidate-ready" in summary
    assert "Machine report: tmp-profile.json" in summary
    assert "Interpretation: no meaningful change" in summary
    assert "Comparison basis: single-run" in summary
    assert "Bounded interpretation: true" in summary
    assert (
        "Basis: summary.status=passed; summary.selected_asset_count=1; "
        "summary.first_failure_category=none; deterministic.observability.runner_signals"
    ) in summary
    assert "Agent JSON-first fields: interpretation, summary, profile, deterministic.observability" in summary


def test_profile_cli_writes_json_report(tmp_path: Path):
    _write_asset(tmp_path, asset_id="candidate-ready")
    output_path = tmp_path / "profile.json"

    exit_code = run_harness_profile_main(
        [
            "--assets",
            str(tmp_path),
            "--profile",
            "deterministic",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "rpa-harness-profile-run-v1"
    assert report["profile"]["name"] == "deterministic"
    assert report["summary"]["status"] == "passed"


def test_profile_cli_summary_includes_machine_report_path(tmp_path: Path):
    _write_asset(tmp_path, asset_id="candidate-ready")
    output_path = tmp_path / "profile-summary.md"
    machine_report_path = tmp_path / "profile.json"

    exit_code = run_harness_profile_main(
        [
            "--assets",
            str(tmp_path),
            "--profile",
            "deterministic",
            "--format",
            "summary",
            "--output",
            str(output_path),
            "--machine-report",
            str(machine_report_path),
        ]
    )

    assert exit_code == 0
    summary = output_path.read_text(encoding="utf-8")
    assert f"Machine report: {machine_report_path}" in summary
