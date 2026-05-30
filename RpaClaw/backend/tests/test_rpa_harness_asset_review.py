import json
from pathlib import Path

from backend.rpa.harness.asset_review import write_asset_review_packet
from backend.rpa.harness.run_asset_review import main as run_asset_review_main


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_asset(root: Path, *, asset_id: str = "asset-1") -> Path:
    capture_dir = root / asset_id
    _write_json(
        capture_dir / "scenario.json",
        {
            "schema_version": "rpa-harness-scenario-v0",
            "asset_id": asset_id,
            "capture_scope": "full_sop",
            "sop_intent": "",
            "source": {
                "recording_id": "session-1",
                "captured_at": "2026-05-19T14:00:00",
                "capture_mode": "harness",
                "capture_trigger": "full_sop",
            },
            "asset_status": "draft",
            "sensitivity": "local-only",
            "governance": {
                "promotion_status": "captured",
                "runner_modes": ["offline_core_chain"],
                "core_chain_coverage": [],
                "expected_signals_reviewed": False,
                "sensitivity_reviewed": False,
                "review_notes": "",
            },
            "step_checkpoints": [
                {"step_index": 1, "checkpoint_path": "steps/001/checkpoint.json"},
                {"step_index": 2, "checkpoint_path": "steps/002/checkpoint.json"},
                {"step_index": 3, "checkpoint_path": "steps/003/checkpoint.json"},
            ],
        },
    )
    _write_step(
        capture_dir,
        step_index=1,
        step_intent="Navigate to GitHub Trending",
        before_url="about:blank",
        before_title="",
        after_url="https://github.com/trending",
        after_title="Trending repositories on GitHub today",
        trace_events=[
            {
                "trace_id": "trace-step-1",
                "trace_type": "navigation",
                "source": "manual",
                "action": "goto",
                "description": "Navigate to trending repositories",
                "before_page": {"url": "about:blank", "title": ""},
                "after_page": {"url": "https://github.com/trending", "title": "Trending repositories on GitHub today"},
                "output": None,
                "accepted": True,
                "started_at": "2026-05-19T14:00:00",
                "ended_at": "2026-05-19T14:00:00",
            }
        ],
        expected={"action_signals": {"expected_action_type": "goto"}},
    )
    _write_step(
        capture_dir,
        step_index=2,
        step_intent="Open repository result tinyhumansai / openhuman",
        before_url="https://github.com/trending",
        before_title="Trending repositories on GitHub today",
        after_url="https://github.com/tinyhumansai/openhuman",
        after_title="GitHub - tinyhumansai/openhuman: Your Personal AI super intelligence",
        action_target={"role": "link", "text": "tinyhumansai / openhuman"},
        trace_events=[
            {
                "trace_id": "trace-step-2",
                "trace_type": "manual_action",
                "source": "manual",
                "action": "click",
                "description": "Click repository result",
                "before_page": {"url": "https://github.com/trending", "title": "Trending repositories on GitHub today"},
                "after_page": {
                    "url": "https://github.com/tinyhumansai/openhuman",
                    "title": "GitHub - tinyhumansai/openhuman: Your Personal AI super intelligence",
                },
                "target_evidence": {"role": "link", "text": "tinyhumansai / openhuman"},
                "locator_candidates": [
                    {
                        "kind": "role",
                        "selected": True,
                        "locator": {"method": "role", "role": "link", "name": "tinyhumansai / openhuman"},
                    }
                ],
                "output": None,
                "accepted": True,
                "started_at": "2026-05-19T14:00:00",
                "ended_at": "2026-05-19T14:00:00",
            }
        ],
        expected={
            "snapshot_signals": {"must_contain_text": ["tinyhumansai / openhuman"]},
            "action_signals": {
                "expected_action_type": "click",
                "target_text_contains": "tinyhumansai / openhuman",
            },
        },
    )
    _write_step(
        capture_dir,
        step_index=3,
        step_intent="Extract repository star count",
        before_url="https://github.com/tinyhumansai/openhuman",
        before_title="GitHub - tinyhumansai/openhuman: Your Personal AI super intelligence",
        after_url="https://github.com/tinyhumansai/openhuman",
        after_title="GitHub - tinyhumansai/openhuman: Your Personal AI super intelligence",
        trace_events=[
            {
                "trace_id": "trace-step-3",
                "trace_type": "ai_operation",
                "source": "ai",
                "action": "extract",
                "description": "Extract repository star count",
                "before_page": {
                    "url": "https://github.com/tinyhumansai/openhuman",
                    "title": "GitHub - tinyhumansai/openhuman: Your Personal AI super intelligence",
                },
                "after_page": {
                    "url": "https://github.com/tinyhumansai/openhuman",
                    "title": "GitHub - tinyhumansai/openhuman: Your Personal AI super intelligence",
                },
                "output_key": "star_count",
                "output": {"star_count": "18.3k stars"},
                "ai_execution": {
                    "language": "python",
                    "code": "async def run(page, results):\n    return {'star_count': '18.3k stars'}",
                    "output": {"star_count": "18.3k stars"},
                },
                "accepted": True,
                "started_at": "2026-05-19T14:00:00",
                "ended_at": "2026-05-19T14:00:00",
            }
        ],
        expected={
            "action_signals": {"expected_action_type": "ai_operation"},
            "compiler_signals": {
                "must_preserve_output_keys": ["star_count"],
                "must_not_hardcode_observed_values": ["18.3k stars"],
            },
            "state_signals": {
                "output_key": "star_count",
                "observed_output_shape": {"type": "object", "keys": ["star_count"]},
            },
        },
    )
    return capture_dir


def _write_step(
    capture_dir: Path,
    *,
    step_index: int,
    step_intent: str,
    before_url: str,
    before_title: str,
    after_url: str,
    after_title: str,
    trace_events: list[dict],
    expected: dict,
    action_target: dict | None = None,
) -> None:
    step_dir = capture_dir / "steps" / f"{step_index:03d}"
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / "before.html").write_text("<html><body>before</body></html>", encoding="utf-8")
    (step_dir / "after.html").write_text("<html><body>after</body></html>", encoding="utf-8")
    _write_json(step_dir / "trace_events.json", trace_events)
    _write_json(step_dir / "expected.json", expected)
    _write_json(
        step_dir / "checkpoint.json",
        {
            "step_index": step_index,
            "step_id": f"step-{step_index}",
            "step_intent": step_intent,
            "recording_mode": "manual",
            "before": {
                "url": before_url,
                "title": before_title,
                "html_path": f"steps/{step_index:03d}/before.html",
                "html_sha256": f"before-{step_index}",
            },
            "action": {
                "trace_events_path": f"steps/{step_index:03d}/trace_events.json",
                "expected_action_type": "",
                "target_evidence": action_target or {},
            },
            "after": {
                "url": after_url,
                "title": after_title,
                "html_path": f"steps/{step_index:03d}/after.html",
                "html_sha256": f"after-{step_index}",
            },
            "runtime_result": {"status": "success"},
            "captured_at": "2026-05-19T14:00:00",
            "expected_path": f"steps/{step_index:03d}/expected.json",
        },
    )


def test_review_packet_infers_identity_from_captured_evidence_without_live_urls(tmp_path: Path):
    capture_dir = _write_asset(tmp_path)

    review_path = write_asset_review_packet(tmp_path, "asset-1")

    assert review_path == capture_dir / "review.md"
    content = review_path.read_text(encoding="utf-8")
    assert "# 资产审查包" in content
    assert "## 场景身份" in content
    assert "来自捕获证据推断" in content
    assert "置信度: 高" in content
    assert "来源站点: github.com" in content
    assert "步骤数: 3" in content
    assert "最终输出: star_count = 18.3k stars" in content
    assert "Extract repository star count" in content
    assert "star_count" in content
    assert "18.3k stars" in content
    assert "tinyhumansai / openhuman" in content
    assert "observed_output: null" not in content
    assert "## 人类可读 SOP" in content
    assert "## 证据摘要" in content
    assert "| 步骤 | 意图 | 前置页面 | 动作 | 后置页面 | 输出 |" in content
    assert "## 自动检查" in content
    assert "资产校验: 通过" in content
    assert "Snapshot 回归:" in content
    assert "Compiler 回归:" in content
    assert "## 人工确认问题" in content
    assert "## 建议升级" in content
    assert "candidate-lite: 建议" in content
    assert "candidate-lite" in content
    assert "https://" not in content
    assert "http://" not in content


def test_asset_review_cli_writes_selected_asset_review_packet(tmp_path: Path):
    capture_dir = _write_asset(tmp_path)

    exit_code = run_asset_review_main(["--assets", str(tmp_path), "--asset-id", "asset-1"])

    assert exit_code == 0
    content = (capture_dir / "review.md").read_text(encoding="utf-8")
    assert "资产 ID: `asset-1`" in content
    assert "Extract repository star count" in content


def test_review_packet_surfaces_region_acquisition_without_promoting_asset(tmp_path: Path):
    capture_dir = tmp_path / "region-capture"
    _write_json(
        capture_dir / "scenario.json",
        {
            "schema_version": "rpa-harness-scenario-v0",
            "asset_id": "region-capture",
            "capture_scope": "full_sop",
            "sop_intent": "Review region and picked-element capture evidence",
            "source": {
                "recording_id": "session-region-capture",
                "captured_at": "2026-05-30T09:00:00",
                "capture_mode": "harness",
                "capture_trigger": "full_sop",
            },
            "asset_status": "draft",
            "sensitivity": "local-only",
            "governance": {
                "promotion_status": "captured",
                "runner_modes": ["offline_core_chain"],
                "core_chain_coverage": [],
                "expected_signals_reviewed": False,
                "sensitivity_reviewed": False,
                "review_notes": "F020 captured region-selection review fixture.",
            },
            "step_checkpoints": [
                {"step_index": 1, "checkpoint_path": "steps/001/checkpoint.json"},
                {"step_index": 2, "checkpoint_path": "steps/002/checkpoint.json"},
            ],
        },
    )
    _write_step(
        capture_dir,
        step_index=1,
        step_intent="Extract text from dragged region",
        before_url="https://fixture.local/report",
        before_title="Report",
        after_url="https://fixture.local/report",
        after_title="Report",
        trace_events=[
            {
                "trace_id": "trace-region-capture-1",
                "trace_type": "ai_operation",
                "source": "ai",
                "action": "extract",
                "description": "Extract selected region text",
                "region_context": {
                    "region_id": "region-summary-panel",
                    "inferred_kind": "text_region",
                    "acquisition": "drag_region",
                    "local_text": ["Quarterly summary"],
                },
                "signals": {
                    "region_selection": {
                        "region_id": "region-summary-panel",
                        "acquisition": "drag_region",
                    }
                },
                "accepted": True,
            }
        ],
        expected={},
    )
    _write_step(
        capture_dir,
        step_index=2,
        step_intent="Click the first row name",
        before_url="https://fixture.local/report",
        before_title="Report",
        after_url="https://fixture.local/report",
        after_title="Report",
        trace_events=[
            {
                "trace_id": "trace-region-capture-2",
                "trace_type": "ai_operation",
                "source": "ai",
                "action": "click",
                "description": "Click selected first-row element",
                "region_context": {
                    "region_id": "region-first-row-name",
                    "inferred_kind": "action_region",
                    "acquisition": "picked_element",
                    "local_text": ["report.xlsx"],
                },
                "signals": {
                    "region_selection": {
                        "region_id": "region-first-row-name",
                        "acquisition": "picked_element",
                    }
                },
                "accepted": True,
            }
        ],
        expected={},
    )

    review_path = write_asset_review_packet(tmp_path, "region-capture")

    content = review_path.read_text(encoding="utf-8")
    assert "Region Selection Evidence" in content
    assert "region-summary-panel" in content
    assert "drag_region" in content
    assert "region-first-row-name" in content
    assert "picked_element" in content
    assert "Promotion: `captured`" in content
    assert "Expected signals reviewed: `false`" in content
    assert "Sensitivity reviewed: `false`" in content
    assert "candidate-lite" in content


def test_review_packet_includes_lifecycle_and_eligibility_snapshot(tmp_path: Path):
    capture_dir = _write_asset(tmp_path, asset_id="candidate-review")
    scenario_path = capture_dir / "scenario.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario["asset_status"] = "active"
    scenario["sensitivity"] = "repo-safe"
    scenario["governance"]["promotion_status"] = "candidate"
    scenario["governance"]["runner_modes"] = ["offline_core_chain", "skill_replay_e2e"]
    scenario["governance"]["core_chain_coverage"] = ["html_to_raw_snapshot", "trace_to_skill"]
    scenario["governance"]["expected_signals_reviewed"] = True
    scenario["governance"]["sensitivity_reviewed"] = True
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    review_path = write_asset_review_packet(tmp_path, "candidate-review")

    content = review_path.read_text(encoding="utf-8")
    assert "## 生命周期状态（Lifecycle State）" in content
    assert "Promotion: `candidate`" in content
    assert "Asset status: `active`" in content
    assert "Expected signals reviewed: `true`" in content
    assert "Sensitivity reviewed: `true`" in content
    assert "Runner coverage: `offline_core_chain`, `skill_replay_e2e`" in content
    assert "Core-chain coverage: `html_to_raw_snapshot`, `trace_to_skill`" in content
    assert "Golden eligibility: `eligible`" in content
    assert "Human approval required: `true`" in content
