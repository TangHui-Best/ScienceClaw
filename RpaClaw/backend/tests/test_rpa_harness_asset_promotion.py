import json
from pathlib import Path

import pytest

from backend.rpa.harness.asset_promotion import PromotionError, promote_harness_asset
from backend.rpa.harness.run_asset_promote import main as run_asset_promote_main


def _write_asset(root: Path, *, asset_id: str = "draft-asset") -> Path:
    asset_dir = root / asset_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "scenario.json").write_text(
        json.dumps(
            {
                "schema_version": "rpa-harness-scenario-v0",
                "asset_id": asset_id,
                "capture_scope": "full_sop",
                "sop_intent": "Review a captured workflow",
                "source": {
                    "recording_id": f"rec-{asset_id}",
                    "captured_at": "2026-05-19T10:00:00",
                    "capture_mode": "harness",
                    "capture_trigger": "full_sop",
                },
                "asset_status": "draft",
                "sensitivity": "local-only",
                "page_patterns": ["detail-page"],
                "governance": {
                    "promotion_status": "captured",
                    "runner_modes": ["offline_core_chain"],
                    "core_chain_coverage": [],
                    "expected_signals_reviewed": False,
                    "sensitivity_reviewed": False,
                    "review_notes": "fresh capture",
                },
                "step_checkpoints": [],
            }
        ),
        encoding="utf-8",
    )
    return asset_dir


def _read_scenario(asset_dir: Path) -> dict:
    return json.loads((asset_dir / "scenario.json").read_text(encoding="utf-8"))


def test_candidate_lite_promotion_updates_governance_without_review_confirmations(tmp_path: Path):
    asset_dir = _write_asset(tmp_path, asset_id="draft-capture")

    result = promote_harness_asset(tmp_path, "draft-capture", "candidate-lite")

    scenario = _read_scenario(asset_dir)
    assert result["asset_id"] == "draft-capture"
    assert result["promotion_status"] == "candidate-lite"
    assert scenario["asset_status"] == "draft"
    assert scenario["governance"]["promotion_status"] == "candidate-lite"
    assert scenario["governance"]["expected_signals_reviewed"] is False
    assert scenario["governance"]["sensitivity_reviewed"] is False
    assert scenario["governance"]["runner_modes"] == [
        "offline_core_chain",
        "skill_replay_e2e",
        "stateful_sop_capture_to_skill",
    ]
    assert scenario["governance"]["core_chain_coverage"] == [
        "html_to_raw_snapshot",
        "raw_to_compact_snapshot",
        "planner_action_selection",
        "trace_to_skill",
        "skill_replay",
        "stateful_capture_to_skill",
    ]


def test_candidate_and_golden_promotion_require_explicit_review_confirmations(tmp_path: Path):
    asset_dir = _write_asset(tmp_path, asset_id="reviewed-capture")

    with pytest.raises(PromotionError, match="expected-signal"):
        promote_harness_asset(tmp_path, "reviewed-capture", "candidate", confirm_sensitivity=True)

    assert _read_scenario(asset_dir)["governance"]["promotion_status"] == "captured"

    result = promote_harness_asset(
        tmp_path,
        "reviewed-capture",
        "candidate",
        confirm_expected=True,
        confirm_sensitivity=True,
    )

    scenario = _read_scenario(asset_dir)
    assert result["promotion_status"] == "candidate"
    assert scenario["asset_status"] == "active"
    assert scenario["governance"]["promotion_status"] == "candidate"
    assert scenario["governance"]["expected_signals_reviewed"] is True
    assert scenario["governance"]["sensitivity_reviewed"] is True
    assert scenario["governance"]["runner_modes"] == [
        "offline_core_chain",
        "skill_replay_e2e",
        "stateful_sop_capture_to_skill",
    ]
    assert scenario["governance"]["core_chain_coverage"] == [
        "html_to_raw_snapshot",
        "raw_to_compact_snapshot",
        "planner_action_selection",
        "trace_to_skill",
        "skill_replay",
        "stateful_capture_to_skill",
    ]

    golden_dir = _write_asset(tmp_path, asset_id="golden-capture")

    with pytest.raises(PromotionError, match="sensitivity"):
        promote_harness_asset(tmp_path, "golden-capture", "golden", confirm_expected=True)

    assert _read_scenario(golden_dir)["governance"]["promotion_status"] == "captured"

    golden_result = promote_harness_asset(
        tmp_path,
        "golden-capture",
        "golden",
        confirm_expected=True,
        confirm_sensitivity=True,
    )

    golden_scenario = _read_scenario(golden_dir)
    assert golden_result["promotion_status"] == "golden"
    assert golden_scenario["asset_status"] == "active"
    assert golden_scenario["governance"]["promotion_status"] == "golden"
    assert golden_scenario["governance"]["expected_signals_reviewed"] is True
    assert golden_scenario["governance"]["sensitivity_reviewed"] is True


def test_asset_promote_cli_supports_candidate_lite(tmp_path: Path):
    asset_dir = _write_asset(tmp_path, asset_id="cli-capture")

    exit_code = run_asset_promote_main(
        ["--assets", str(tmp_path), "--asset-id", "cli-capture", "--level", "candidate-lite"]
    )

    scenario = _read_scenario(asset_dir)
    assert exit_code == 0
    assert scenario["governance"]["promotion_status"] == "candidate-lite"
    assert scenario["governance"]["expected_signals_reviewed"] is False
    assert scenario["governance"]["sensitivity_reviewed"] is False
