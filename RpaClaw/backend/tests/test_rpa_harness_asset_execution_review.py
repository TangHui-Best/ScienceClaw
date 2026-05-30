import json
from pathlib import Path

from backend.rpa.harness.asset_execution_review import write_asset_execution_review_packet
from backend.rpa.harness.run_asset_execution_review import main as run_asset_execution_review_main


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_execution_asset(root: Path, asset_id: str = "asset-exec") -> Path:
    asset_dir = root / asset_id
    _write_json(
        asset_dir / "scenario.json",
        {
            "schema_version": "rpa-harness-scenario-v0",
            "asset_id": asset_id,
            "capture_scope": "full_sop",
            "sop_intent": "Open issues and extract titles",
            "source": {
                "recording_id": "session-1",
                "captured_at": "2026-05-30T12:00:00",
                "capture_mode": "harness",
                "capture_trigger": "full_sop",
            },
            "asset_status": "draft",
            "sensitivity": "sanitized",
            "environment": {"sanitized_from_asset_id": "raw-asset"},
            "governance": {
                "promotion_status": "candidate-lite",
                "runner_modes": ["offline_core_chain", "skill_replay_e2e", "stateful_sop_capture_to_skill"],
                "core_chain_coverage": ["trace_to_skill", "skill_replay", "stateful_capture_to_skill"],
                "expected_signals_reviewed": False,
                "sensitivity_reviewed": False,
                "review_notes": "",
            },
            "step_checkpoints": [],
        },
    )
    _write_json(
        asset_dir / "stateful_sop_execution_report.json",
        {
            "summary": {
                "status": "failed",
                "eligible_capture_count": 1,
                "total": 1,
                "passed": 0,
                "failed": 1,
                "failure_categories": {"controlled-replay-execution-error": 1},
            },
            "assets": [
                {
                    "asset_id": asset_id,
                    "status": "failed",
                    "failure_category": "controlled-replay-execution-error",
                    "step_count": 5,
                    "accepted_trace_count": 5,
                    "runtime_result_keys": ["about_content", "issue_titles"],
                    "generated_skill_size": 15572,
                    "replay": {
                        "status": "failed",
                        "failure_category": "controlled-replay-execution-error",
                        "error": "RuntimeError: Runtime semantic instruction failed: Missing credentials. Please pass an api_key.",
                    },
                }
            ],
        },
    )
    _write_json(
        asset_dir / "skill_replay_execution_report.json",
        {
            "summary": {
                "status": "failed",
                "eligible_capture_count": 1,
                "total": 5,
                "passed": 2,
                "failed": 3,
                "failure_categories": {"replay-output-shape-mismatch": 2, "replay-execution-error": 1},
            },
            "assets": [
                {
                    "step_index": 3,
                    "step_intent": "Extract About",
                    "status": "failed",
                    "failure_category": "replay-output-shape-mismatch",
                    "output_key": "about_content",
                    "error": "",
                }
            ],
        },
    )
    _write_json(
        asset_dir / "compiler_execution_report.json",
        {
            "summary": {"total": 5, "passed": 3, "failed": 2},
            "assets": [
                {
                    "step_index": 4,
                    "step_intent": 'Click link("Issues 10")',
                    "status": "failed",
                    "failure_category": "compiler-hardcoded-observed-value",
                    "hardcoded_values": ["Issues 10"],
                }
            ],
        },
    )
    _write_json(
        asset_dir / "snapshot_execution_report.json",
        {"summary": {"total": 5, "passed": 5, "failed": 0}, "assets": []},
    )
    return asset_dir


def test_write_asset_execution_review_packet_summarizes_runner_failures_for_humans(tmp_path: Path):
    asset_dir = _write_execution_asset(tmp_path)

    result = write_asset_execution_review_packet(asset_dir)

    content = (asset_dir / "execution_review.md").read_text(encoding="utf-8")
    assert result["status"] == "generated"
    assert "SOP→Skill 链路: 已触发但未通过" in content
    assert "模型配置未注入或凭证缺失" in content
    assert "Issues 10" in content
    assert "输出形态与 expected 不一致" in content
    assert "真实 UI/RPA 服务入口" in content
    assert "stateful_sop_execution_report.json" in content


def test_asset_execution_review_cli_writes_generation_report(tmp_path: Path):
    _write_execution_asset(tmp_path, asset_id="cli-asset")
    output_path = tmp_path / "generation.json"

    exit_code = run_asset_execution_review_main(
        [
            "--assets",
            str(tmp_path),
            "--asset-id",
            "cli-asset",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["summary"]["asset_count"] == 1
    assert report["assets"][0]["asset_id"] == "cli-asset"
    assert (tmp_path / "cli-asset" / "execution_review.md").exists()
