import json
from pathlib import Path

from backend.rpa.harness.stateful_sop import run_stateful_sop_capture_to_skill


_REPO_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP_ASSET_ROOT = _REPO_ROOT / "data" / "rpa_harness_assets_bootstrap"
_REAL_CANDIDATE_ASSET_ID = "hcap-4be6265f43eb42dfa259182207aa64cc"


def _write_stateful_asset(root: Path, *, expected_text: str = "Fork 1.3k") -> Path:
    asset_dir = root / "asset-stateful"
    step_1 = asset_dir / "steps" / "001"
    step_2 = asset_dir / "steps" / "002"
    step_3 = asset_dir / "steps" / "003"
    for step_dir in [step_1, step_2, step_3]:
        step_dir.mkdir(parents=True, exist_ok=True)

    (asset_dir / "scenario.json").write_text(
        json.dumps(
            {
                "schema_version": "rpa-harness-scenario-v0",
                "asset_id": "asset-stateful",
                "capture_scope": "full_sop",
                "sop_intent": "Open a repo and extract fork count",
                "source": {
                    "recording_id": "rec-stateful",
                    "captured_at": "2026-05-19T10:00:00",
                    "capture_mode": "harness",
                    "capture_trigger": "full_sop",
                },
                "asset_status": "active",
                "sensitivity": "local-only",
                "page_patterns": ["card-list", "detail-page", "data-extraction"],
                "governance": {
                    "promotion_status": "candidate",
                    "runner_modes": [
                        "offline_core_chain",
                        "stateful_sop_capture_to_skill",
                    ],
                    "core_chain_coverage": [
                        "html_to_raw_snapshot",
                        "raw_to_compact_snapshot",
                        "trace_to_skill",
                        "stateful_capture_to_skill",
                    ],
                    "expected_signals_reviewed": True,
                    "sensitivity_reviewed": True,
                    "review_notes": "Controlled fixture for stateful SOP runner contract.",
                },
                "step_checkpoints": [
                    {"step_index": 1, "checkpoint_path": "steps/001/checkpoint.json"},
                    {"step_index": 2, "checkpoint_path": "steps/002/checkpoint.json"},
                    {"step_index": 3, "checkpoint_path": "steps/003/checkpoint.json"},
                ],
            }
        ),
        encoding="utf-8",
    )

    (step_1 / "before.html").write_text("<html><body></body></html>", encoding="utf-8")
    (step_1 / "after.html").write_text(
        "<html><body><main><a href='https://example.test/repo'>tiny / repo</a></main></body></html>",
        encoding="utf-8",
    )
    (step_1 / "trace_events.json").write_text(
        json.dumps(
            [
                {
                    "trace_id": "trace-step-1",
                    "trace_type": "navigation",
                    "source": "manual",
                    "action": "navigate",
                    "description": "Open listing page",
                    "before_page": {"url": "about:blank", "title": ""},
                    "after_page": {"url": "https://example.test/list", "title": "List"},
                    "signals": {"recording": {"sequence": 1}},
                    "accepted": True,
                    "started_at": "2026-05-19T10:00:00",
                    "ended_at": "2026-05-19T10:00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    (step_1 / "expected.json").write_text(
        json.dumps({"snapshot_signals": {"must_contain_text": ["tiny / repo"]}}),
        encoding="utf-8",
    )
    (step_1 / "checkpoint.json").write_text(
        json.dumps(
            {
                "step_index": 1,
                "step_id": "trace-step-1",
                "step_intent": "Open listing page",
                "recording_mode": "manual",
                "page_patterns": ["card-list"],
                "before": {
                    "url": "about:blank",
                    "title": "",
                    "html_path": "steps/001/before.html",
                    "html_sha256": "before-1",
                },
                "action": {"trace_events_path": "steps/001/trace_events.json"},
                "after": {
                    "url": "https://example.test/list",
                    "title": "List",
                    "html_path": "steps/001/after.html",
                    "html_sha256": "after-1",
                },
                "runtime_result": {"status": "success"},
                "captured_at": "2026-05-19T10:00:00",
                "expected_path": "steps/001/expected.json",
            }
        ),
        encoding="utf-8",
    )

    (step_2 / "before.html").write_text((step_1 / "after.html").read_text(encoding="utf-8"), encoding="utf-8")
    (step_2 / "after.html").write_text(
        "<html><body><main><a href='/forks'>Fork 1.3k</a></main></body></html>",
        encoding="utf-8",
    )
    (step_2 / "trace_events.json").write_text(
        json.dumps(
            [
                {
                    "trace_id": "trace-step-2",
                    "trace_type": "manual_action",
                    "source": "manual",
                    "action": "navigate_click",
                    "description": "Open repository",
                    "before_page": {"url": "https://example.test/list", "title": "List"},
                    "after_page": {"url": "https://example.test/repo", "title": "Repo"},
                    "locator_candidates": [
                        {
                            "kind": "role",
                            "selected": True,
                            "locator": {"method": "role", "role": "link", "name": "tiny / repo"},
                        }
                    ],
                    "validation": {"status": "ok"},
                    "signals": {"recording": {"sequence": 2}},
                    "accepted": True,
                    "started_at": "2026-05-19T10:00:00",
                    "ended_at": "2026-05-19T10:00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    (step_2 / "expected.json").write_text(
        json.dumps({"snapshot_signals": {"must_contain_text": ["Fork 1.3k"]}}),
        encoding="utf-8",
    )
    (step_2 / "checkpoint.json").write_text(
        json.dumps(
            {
                "step_index": 2,
                "step_id": "trace-step-2",
                "step_intent": "Open repository",
                "recording_mode": "manual",
                "page_patterns": ["card-list"],
                "before": {
                    "url": "https://example.test/list",
                    "title": "List",
                    "html_path": "steps/002/before.html",
                    "html_sha256": "before-2",
                },
                "action": {"trace_events_path": "steps/002/trace_events.json"},
                "after": {
                    "url": "https://example.test/repo",
                    "title": "Repo",
                    "html_path": "steps/002/after.html",
                    "html_sha256": "after-2",
                },
                "runtime_result": {"status": "success"},
                "captured_at": "2026-05-19T10:00:00",
                "expected_path": "steps/002/expected.json",
            }
        ),
        encoding="utf-8",
    )

    (step_3 / "before.html").write_text((step_2 / "after.html").read_text(encoding="utf-8"), encoding="utf-8")
    (step_3 / "after.html").write_text((step_2 / "after.html").read_text(encoding="utf-8"), encoding="utf-8")
    (step_3 / "trace_events.json").write_text(
        json.dumps(
            [
                {
                    "trace_id": "trace-step-3",
                    "trace_type": "ai_operation",
                    "source": "ai",
                    "user_instruction": "Extract fork count",
                    "description": "Extract fork count",
                    "before_page": {"url": "https://example.test/repo", "title": "Repo"},
                    "after_page": {"url": "https://example.test/repo", "title": "Repo"},
                    "output_key": "fork_count",
                    "output": "Fork 1.3k",
                    "ai_execution": {
                        "language": "python",
                        "code": (
                            "async def run(page, results):\n"
                            "    locator = page.get_by_role('link', name=re.compile(r'^Fork\\s'))\n"
                            "    await locator.wait_for(state='visible', timeout=5000)\n"
                            "    return await locator.inner_text()\n"
                        ),
                        "output": "Fork 1.3k",
                    },
                    "accepted": True,
                    "started_at": "2026-05-19T10:00:00",
                    "ended_at": "2026-05-19T10:00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    (step_3 / "expected.json").write_text(
        json.dumps(
            {
                "state_signals": {
                    "output_key": "fork_count",
                    "must_contain_text": [expected_text],
                    "observed_output_shape": {"type": "str"},
                }
            }
        ),
        encoding="utf-8",
    )
    (step_3 / "checkpoint.json").write_text(
        json.dumps(
            {
                "step_index": 3,
                "step_id": "trace-step-3",
                "step_intent": "Extract fork count",
                "recording_mode": "natural_language",
                "page_patterns": ["detail-page", "data-extraction"],
                "before": {
                    "url": "https://example.test/repo",
                    "title": "Repo",
                    "html_path": "steps/003/before.html",
                    "html_sha256": "before-3",
                },
                "action": {"trace_events_path": "steps/003/trace_events.json"},
                "after": {
                    "url": "https://example.test/repo",
                    "title": "Repo",
                    "html_path": "steps/003/after.html",
                    "html_sha256": "after-3",
                    "same_as_before": True,
                },
                "runtime_result": {"status": "success"},
                "captured_at": "2026-05-19T10:00:00",
                "expected_path": "steps/003/expected.json",
            }
        ),
        encoding="utf-8",
    )
    return root


def test_stateful_sop_rebuilds_session_traces_compiles_full_skill_and_replays(tmp_path: Path):
    assets = _write_stateful_asset(tmp_path)

    report = run_stateful_sop_capture_to_skill(assets)

    assert report["schema_version"] == "rpa-harness-stateful-sop-capture-to-skill-v0"
    assert report["summary"]["status"] == "passed"
    assert report["summary"]["eligible_capture_count"] == 1
    assert report["summary"]["total"] == 1
    assert report["summary"]["failed"] == 0
    item = report["assets"][0]
    assert item["asset_id"] == "asset-stateful"
    assert item["accepted_trace_count"] == 3
    assert item["generated_skill_size"] > 0
    assert item["replay"]["status"] == "passed"
    assert item["replay"]["actual_output"]["fork_count"] == "Fork 1.3k"
    assert [step["input_boundary"] for step in item["steps"]] == [
        "manual_recording_adapter",
        "manual_recording_adapter",
        "natural_language_runtime_result",
    ]


def test_stateful_sop_reports_controlled_replay_signal_mismatch(tmp_path: Path):
    assets = _write_stateful_asset(tmp_path, expected_text="Fork 9.9k")

    report = run_stateful_sop_capture_to_skill(assets)

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["failed"] == 1
    item = report["assets"][0]
    assert item["status"] == "failed"
    assert item["failure_category"] == "controlled-replay-output-missing-signal"
    assert item["replay"]["missing_text"] == ["Fork 9.9k"]


def test_stateful_sop_reports_missing_trace_events_as_bounded_asset_failure(tmp_path: Path):
    assets = _write_stateful_asset(tmp_path)
    (assets / "asset-stateful" / "steps" / "002" / "trace_events.json").unlink()

    report = run_stateful_sop_capture_to_skill(assets)

    assert report["summary"]["status"] == "failed"
    item = report["assets"][0]
    assert item["status"] == "failed"
    assert item["failure_category"] == "missing-trace-events"
    failed_step = next(step for step in item["steps"] if step["status"] == "failed")
    assert failed_step["step_index"] == 2
    assert failed_step["failure_category"] == "missing-trace-events"


def test_stateful_sop_reports_invalid_trace_events_as_bounded_asset_failure(tmp_path: Path):
    assets = _write_stateful_asset(tmp_path)
    trace_path = assets / "asset-stateful" / "steps" / "002" / "trace_events.json"
    trace_path.write_text("{not-json", encoding="utf-8")

    report = run_stateful_sop_capture_to_skill(assets)

    assert report["summary"]["status"] == "failed"
    item = report["assets"][0]
    assert item["status"] == "failed"
    assert item["failure_category"] == "invalid-trace-events"
    failed_step = next(step for step in item["steps"] if step["status"] == "failed")
    assert failed_step["step_index"] == 2
    assert failed_step["failure_category"] == "invalid-trace-events"


def test_stateful_sop_reports_invalid_checkpoint_as_bounded_asset_failure(tmp_path: Path):
    assets = _write_stateful_asset(tmp_path)
    checkpoint_path = assets / "asset-stateful" / "steps" / "002" / "checkpoint.json"
    checkpoint_path.write_text("{not-json", encoding="utf-8")

    report = run_stateful_sop_capture_to_skill(assets)

    assert report["summary"]["status"] == "failed"
    item = report["assets"][0]
    assert item["status"] == "failed"
    assert item["failure_category"] == "invalid-checkpoint"
    assert item["steps"][0]["input_boundary"] == "scenario_asset_loader"
    assert item["steps"][0]["failure_category"] == "invalid-checkpoint"


def test_stateful_sop_does_not_compile_rejected_trace_events(tmp_path: Path):
    assets = _write_stateful_asset(tmp_path)
    trace_path = assets / "asset-stateful" / "steps" / "003" / "trace_events.json"
    traces = json.loads(trace_path.read_text(encoding="utf-8"))
    traces[0]["accepted"] = False
    trace_path.write_text(json.dumps(traces), encoding="utf-8")

    report = run_stateful_sop_capture_to_skill(assets)

    assert report["summary"]["status"] == "failed"
    item = report["assets"][0]
    assert item["status"] == "failed"
    assert item["failure_category"] == "missing-accepted-trace"
    assert item["accepted_trace_count"] == 2
    failed_step = next(step for step in item["steps"] if step["status"] == "failed")
    assert failed_step["step_index"] == 3
    assert failed_step["failure_category"] == "missing-accepted-trace"


def test_stateful_sop_replays_real_governed_candidate_asset():
    report = run_stateful_sop_capture_to_skill(
        _BOOTSTRAP_ASSET_ROOT,
        asset_ids={_REAL_CANDIDATE_ASSET_ID},
    )

    assert report["summary"]["status"] == "passed"
    assert report["summary"]["eligible_capture_count"] == 1
    assert report["summary"]["total"] == 1
    item = report["assets"][0]
    assert item["asset_id"] == _REAL_CANDIDATE_ASSET_ID
    assert item["accepted_trace_count"] == 3
    assert item["runtime_result_keys"] == ["fork_count"]
    assert item["replay"]["actual_output"]["fork_count"] == "Fork 1.3k"
