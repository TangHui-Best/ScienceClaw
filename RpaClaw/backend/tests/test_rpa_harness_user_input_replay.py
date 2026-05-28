import json
from pathlib import Path

from backend.rpa.harness.run_user_input_replay import main as run_user_input_replay_main
from backend.rpa.harness.user_input_replay import (
    render_user_input_replay_summary,
    run_user_input_replay,
)


def _write_scenario_asset(
    root: Path,
    *,
    asset_id: str,
    promotion_status: str = "candidate",
    asset_status: str = "active",
    expected_signals_reviewed: bool | None = None,
    sensitivity_reviewed: bool | None = None,
    runner_modes: list[str] | None = None,
    step_count: int = 2,
) -> Path:
    if expected_signals_reviewed is None:
        expected_signals_reviewed = promotion_status in {"candidate", "golden"}
    if sensitivity_reviewed is None:
        sensitivity_reviewed = promotion_status in {"candidate", "golden"}
    asset_dir = root / asset_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    refs = [
        {"step_index": index, "checkpoint_path": f"steps/{index:03d}/checkpoint.json"}
        for index in range(1, step_count + 1)
    ]
    (asset_dir / "scenario.json").write_text(
        json.dumps(
            {
                "schema_version": "rpa-harness-scenario-v0",
                "asset_id": asset_id,
                "capture_scope": "full_sop",
                "sop_intent": f"Replay user input for {asset_id}",
                "source": {
                    "recording_id": f"rec-{asset_id}",
                    "captured_at": "2026-05-28T10:00:00",
                    "capture_mode": "harness",
                    "capture_trigger": "full_sop",
                },
                "asset_status": asset_status,
                "sensitivity": "repo-safe" if sensitivity_reviewed else "local-only",
                "page_patterns": ["card-list", "detail-page"],
                "governance": {
                    "promotion_status": promotion_status,
                    "runner_modes": runner_modes or ["offline_core_chain", "stateful_sop_capture_to_skill"],
                    "core_chain_coverage": ["planner_action_selection", "trace_to_skill"],
                    "expected_signals_reviewed": expected_signals_reviewed,
                    "sensitivity_reviewed": sensitivity_reviewed,
                    "review_notes": "user input replay fixture",
                },
                "step_checkpoints": refs,
            }
        ),
        encoding="utf-8",
    )
    return asset_dir


def _write_checkpoint(
    root: Path,
    *,
    asset_id: str,
    step_index: int,
    step_intent: str,
    recording_mode: str,
    trace_events: list[dict] | None,
    expected_action_type: str = "",
    target_evidence: dict | None = None,
    before_url: str = "https://example.test/start",
    after_url: str = "https://example.test/done",
) -> None:
    step_dir = root / asset_id / "steps" / f"{step_index:03d}"
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / "before.html").write_text("<html><body>before</body></html>", encoding="utf-8")
    (step_dir / "after.html").write_text("<html><body>after</body></html>", encoding="utf-8")
    if trace_events is not None:
        (step_dir / "trace_events.json").write_text(json.dumps(trace_events), encoding="utf-8")
    (step_dir / "expected.json").write_text("{}", encoding="utf-8")
    (step_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "step_index": step_index,
                "step_id": f"trace-{asset_id}-{step_index}",
                "step_intent": step_intent,
                "recording_mode": recording_mode,
                "page_patterns": ["card-list" if step_index == 1 else "detail-page"],
                "before": {
                    "url": before_url,
                    "title": "Before",
                    "html_path": f"steps/{step_index:03d}/before.html",
                    "html_sha256": "before",
                },
                "action": {
                    "trace_events_path": f"steps/{step_index:03d}/trace_events.json",
                    "expected_action_type": expected_action_type,
                    "target_evidence": target_evidence or {},
                },
                "after": {
                    "url": after_url,
                    "title": "After",
                    "html_path": f"steps/{step_index:03d}/after.html",
                    "html_sha256": "after",
                    "capture_quality": {"status": "stable", "ready_state": "complete"},
                },
                "runtime_result": {"status": "success"},
                "captured_at": "2026-05-28T10:00:00",
                "expected_path": f"steps/{step_index:03d}/expected.json",
            }
        ),
        encoding="utf-8",
    )


def _manual_click_event(asset_id: str, step_index: int = 1) -> dict:
    return {
        "trace_id": f"trace-{asset_id}-{step_index}",
        "trace_type": "manual_action",
        "source": "manual",
        "action": "navigate_click",
        "description": "Click repository result",
        "locator_candidates": [
            {
                "kind": "role",
                "selected": True,
                "playwright_locator": 'page.get_by_role("link", name="ScienceClaw")',
                "locator": {"method": "role", "role": "link", "name": "ScienceClaw"},
            }
        ],
        "signals": {
            "recording": {"sequence": step_index, "event_timestamp_ms": 1779102589340},
            "tab": {"tab_id": "tab-main"},
        },
        "value": "",
        "accepted": True,
    }


def _natural_language_event(asset_id: str, step_index: int = 2) -> dict:
    return {
        "trace_id": f"trace-{asset_id}-{step_index}",
        "trace_type": "ai_operation",
        "source": "ai",
        "user_instruction": "Extract star count",
        "action": None,
        "description": "Extract the star count from the page",
        "signals": {"tab": {"tab_id": "tab-main"}},
        "output_key": "star_count",
        "output": {"star_count": "42 stars"},
        "ai_execution": {"error": None, "repair_attempted": False},
        "accepted": True,
    }


def _write_replay_fixture(root: Path, *, asset_id: str = "candidate-ready") -> None:
    _write_scenario_asset(root, asset_id=asset_id)
    _write_checkpoint(
        root,
        asset_id=asset_id,
        step_index=1,
        step_intent="Click ScienceClaw result",
        recording_mode="manual",
        trace_events=[_manual_click_event(asset_id, 1)],
        expected_action_type="click",
        target_evidence={"role": "link", "text_contains": "ScienceClaw"},
    )
    _write_checkpoint(
        root,
        asset_id=asset_id,
        step_index=2,
        step_intent="Extract star count",
        recording_mode="natural_language",
        trace_events=[_natural_language_event(asset_id, 2)],
        before_url="https://example.test/repo",
        after_url="https://example.test/repo",
    )


def test_user_input_replay_selects_candidate_and_golden_as_blocking_baseline(tmp_path: Path):
    _write_replay_fixture(tmp_path, asset_id="candidate-ready")
    _write_replay_fixture(tmp_path, asset_id="golden-ready")
    scenario_path = tmp_path / "golden-ready" / "scenario.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario["governance"]["promotion_status"] = "golden"
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
    _write_scenario_asset(tmp_path, asset_id="draft-capture", promotion_status="captured", asset_status="draft", step_count=0)

    report = run_user_input_replay(tmp_path)

    assert report["schema_version"] == "rpa-harness-user-input-replay-v1"
    assert report["kind"] == "user_input_replay"
    assert report["summary"]["blocking_asset_count"] == 2
    assert report["summary"]["warning_only_asset_count"] == 0
    assert report["selection"]["blocking_baseline_asset_ids"] == ["candidate-ready", "golden-ready"]
    assert report["selection"]["excluded_asset_ids"] == ["draft-capture"]
    assert report["asset_pool"]["summary"]["lifecycle_distribution"] == {
        "candidate": 1,
        "draft": 1,
        "golden": 1,
    }
    assert all(asset["baseline_role"] == "blocking" for asset in report["selected_assets"])


def test_user_input_replay_keeps_candidate_lite_warning_only(tmp_path: Path):
    _write_replay_fixture(tmp_path, asset_id="candidate-ready")
    _write_replay_fixture(tmp_path, asset_id="candidate-lite-watch")
    scenario_path = tmp_path / "candidate-lite-watch" / "scenario.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario["governance"]["promotion_status"] = "candidate-lite"
    scenario["governance"]["expected_signals_reviewed"] = False
    scenario["governance"]["sensitivity_reviewed"] = False
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")

    report = run_user_input_replay(tmp_path)

    assert report["summary"]["status"] == "passed"
    assert report["summary"]["blocking_asset_count"] == 1
    assert report["summary"]["warning_only_asset_count"] == 1
    assert report["selection"]["blocking_baseline_asset_ids"] == ["candidate-ready"]
    assert report["selection"]["warning_only_asset_ids"] == ["candidate-lite-watch"]
    assert report["warning_only_observation"]["asset_ids"] == ["candidate-lite-watch"]
    warning_events = [
        event
        for event in report["replayed_input_events"]
        if event["asset_id"] == "candidate-lite-watch"
    ]
    assert warning_events
    assert {event["baseline_role"] for event in warning_events} == {"warning-only"}
    assert report["governance_boundary"]["candidate_lite_warning_only"] is True


def test_user_input_replay_excludes_candidate_without_core_chain_boundary(tmp_path: Path):
    _write_replay_fixture(tmp_path, asset_id="candidate-ready")
    _write_scenario_asset(
        tmp_path,
        asset_id="candidate-no-offline",
        runner_modes=["stateful_sop_capture_to_skill"],
        step_count=0,
    )
    no_offline_path = tmp_path / "candidate-no-offline" / "scenario.json"
    no_offline = json.loads(no_offline_path.read_text(encoding="utf-8"))
    no_offline["governance"]["core_chain_coverage"] = []
    no_offline_path.write_text(json.dumps(no_offline), encoding="utf-8")

    report = run_user_input_replay(tmp_path)

    assert report["selection"]["blocking_baseline_asset_ids"] == ["candidate-ready"]
    excluded = {item["asset_id"]: item for item in report["selection"]["excluded_assets"]}
    assert excluded["candidate-no-offline"]["reasons"] == [
        "offline-core-chain-not-enabled",
        "missing-core-chain-coverage",
    ]


def test_user_input_replay_without_blocking_assets_is_insufficient_evidence(tmp_path: Path):
    _write_scenario_asset(
        tmp_path,
        asset_id="draft-capture",
        promotion_status="captured",
        asset_status="draft",
        step_count=0,
    )

    report = run_user_input_replay(tmp_path)

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["failure_category"] == "no-replay-baseline-assets"
    assert report["summary"]["blocking_asset_count"] == 0
    assert report["summary"]["replayed_event_count"] == 0
    assert report["failures"] == []
    assert "No blocking replay baseline assets ran" in report["trust_limits"]


def test_user_input_replay_cli_returns_failure_when_no_blocking_baseline(tmp_path: Path):
    _write_scenario_asset(
        tmp_path,
        asset_id="draft-capture",
        promotion_status="captured",
        asset_status="draft",
        step_count=0,
    )
    output_path = tmp_path / "empty-replay.json"

    exit_code = run_user_input_replay_main(["--assets", str(tmp_path), "--output", str(output_path)])

    assert exit_code == 1
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["summary"]["status"] == "failed"
    assert report["summary"]["failure_category"] == "no-replay-baseline-assets"


def test_candidate_lite_replay_failure_stays_warning_only(tmp_path: Path):
    _write_scenario_asset(
        tmp_path,
        asset_id="candidate-lite-broken",
        promotion_status="candidate-lite",
        expected_signals_reviewed=False,
        sensitivity_reviewed=False,
        step_count=1,
    )
    _write_checkpoint(
        tmp_path,
        asset_id="candidate-lite-broken",
        step_index=1,
        step_intent="Candidate lite missing trace",
        recording_mode="manual",
        trace_events=None,
        expected_action_type="click",
    )

    report = run_user_input_replay(tmp_path)

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["failure_category"] == "no-replay-baseline-assets"
    assert report["summary"]["blocking_failure_count"] == 0
    assert report["summary"]["warning_only_failure_count"] == 1
    assert report["warning_only_observation"] == {
        "asset_ids": ["candidate-lite-broken"],
        "blocking": False,
        "failure_count": 1,
    }
    assert report["failures"][0]["baseline_role"] == "warning-only"


def test_user_input_replay_extracts_click_and_natural_language_events(tmp_path: Path):
    _write_replay_fixture(tmp_path, asset_id="candidate-ready")

    report = run_user_input_replay(tmp_path)

    events = report["replayed_input_events"]
    assert [event["event_kind"] for event in events] == ["click", "natural_language_instruction"]
    assert events[0]["injected_boundary"] == "scripted_manual_input_boundary"
    assert events[0]["target"]["role"] == "link"
    assert events[0]["locator_candidates"][0]["locator"]["name"] == "ScienceClaw"
    assert events[1]["injected_boundary"] == "scripted_natural_language_instruction_boundary"
    assert events[1]["user_instruction"] == "Extract star count"
    assert events[1]["output_key"] == "star_count"
    assert events[1]["trace_id"] == "trace-candidate-ready-2"
    assert events[1]["session_id"] == "rec-candidate-ready"
    assert events[1]["result_id"] == "candidate-ready:2:star_count"
    assert events[1]["source_metadata"] == {
        "checkpoint_path": "candidate-ready/steps/002/checkpoint.json",
        "trace_events_path": "candidate-ready/steps/002/trace_events.json",
        "recording_mode": "natural_language",
        "trace_type": "ai_operation",
    }
    assert events[1]["payload"]["user_instruction"] == "Extract star count"
    assert events[1]["result_refs"]["output_key"] == "star_count"
    assert events[1]["diagnostics"]["accepted"] is True
    assert events[1]["diagnostics"]["ai_execution_error"] is None
    assert report["summary"]["boundary_injection_count"] == 2
    assert report["summary"]["boundary_injection_failed_count"] == 0
    assert [item["status"] for item in report["boundary_injections"]] == ["passed", "passed"]
    assert events[0]["injection"]["adapter"] == "manual_input_boundary_adapter"
    assert events[1]["injection"]["adapter"] == "natural_language_instruction_boundary_adapter"
    assert events[1]["injection"]["executed_by"] == "scripted_user_input_replay_adapter"


def test_user_input_replay_marks_failed_event_injection_as_skipped(tmp_path: Path):
    _write_scenario_asset(tmp_path, asset_id="candidate-broken", step_count=1)
    _write_checkpoint(
        tmp_path,
        asset_id="candidate-broken",
        step_index=1,
        step_intent="Click without trace",
        recording_mode="manual",
        trace_events=None,
        expected_action_type="click",
    )

    report = run_user_input_replay(tmp_path)

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["boundary_injection_count"] == 1
    assert report["summary"]["boundary_injection_failed_count"] == 0
    assert report["boundary_injections"][0]["status"] == "skipped"
    assert report["boundary_injections"][0]["failure_category"] == "missing-trace-events"
    assert report["replayed_input_events"][0]["injection"]["status"] == "skipped"


def test_user_input_replay_extracts_type_select_and_submit_events(tmp_path: Path):
    _write_scenario_asset(tmp_path, asset_id="candidate-form", step_count=3)
    _write_checkpoint(
        tmp_path,
        asset_id="candidate-form",
        step_index=1,
        step_intent="Type owner name",
        recording_mode="manual",
        trace_events=[
            {
                **_manual_click_event("candidate-form", 1),
                "action": "fill",
                "value": "Ada",
                "description": "Fill owner name",
            }
        ],
        expected_action_type="fill",
    )
    _write_checkpoint(
        tmp_path,
        asset_id="candidate-form",
        step_index=2,
        step_intent="Select status",
        recording_mode="manual",
        trace_events=[{**_manual_click_event("candidate-form", 2), "action": "select_option"}],
        expected_action_type="select",
    )
    _write_checkpoint(
        tmp_path,
        asset_id="candidate-form",
        step_index=3,
        step_intent="Submit form",
        recording_mode="manual",
        trace_events=[{**_manual_click_event("candidate-form", 3), "action": "submit"}],
        expected_action_type="submit",
    )

    report = run_user_input_replay(tmp_path)

    events = report["replayed_input_events"]
    assert [event["event_kind"] for event in events] == ["type", "select", "submit"]
    assert {event["injected_boundary"] for event in events} == {"scripted_manual_input_boundary"}
    assert events[0]["payload"]["value"] == "Ada"


def test_user_input_replay_preserves_region_context_as_generic_event_fact(tmp_path: Path):
    _write_scenario_asset(tmp_path, asset_id="candidate-ready", step_count=1)
    _write_checkpoint(
        tmp_path,
        asset_id="candidate-ready",
        step_index=1,
        step_intent="Click selected region",
        recording_mode="manual",
        trace_events=[
            {
                **_manual_click_event("candidate-ready", 1),
                "signals": {
                    "region": {"x": 10, "y": 20, "width": 200, "height": 120},
                    "tab": {"tab_id": "tab-main"},
                },
            }
        ],
        target_evidence={"region": {"label": "primary card", "source": "selected_region"}},
    )

    report = run_user_input_replay(tmp_path)

    event = report["replayed_input_events"][0]
    assert event["event_kind"] == "click"
    assert event["region_context"] == {
        "target_evidence": {"label": "primary card", "source": "selected_region"},
        "signals": {"x": 10, "y": 20, "width": 200, "height": 120},
    }
    assert "region selection is represented as generic user input context" in report["trust_limits"]


def test_user_input_replay_failure_retains_checkpoint_and_trace_log_context(tmp_path: Path):
    _write_scenario_asset(tmp_path, asset_id="candidate-broken", step_count=1)
    _write_checkpoint(
        tmp_path,
        asset_id="candidate-broken",
        step_index=1,
        step_intent="Click without trace",
        recording_mode="manual",
        trace_events=None,
        expected_action_type="click",
        before_url="https://example.test/list",
        after_url="https://example.test/list",
    )

    report = run_user_input_replay(tmp_path)

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["blocking_failure_count"] == 1
    failure = report["failures"][0]
    assert failure["asset_id"] == "candidate-broken"
    assert failure["step_index"] == 1
    assert failure["failure_category"] == "missing-trace-events"
    assert failure["checkpoint_path"] == "candidate-broken/steps/001/checkpoint.json"
    assert failure["trace_events_path"] == "candidate-broken/steps/001/trace_events.json"
    assert failure["step_intent"] == "Click without trace"
    assert failure["before_page"]["url"] == "https://example.test/list"
    assert failure["runtime_result"] == {"status": "success", "error": ""}
    assert failure["source_metadata"]["checkpoint_path"] == "candidate-broken/steps/001/checkpoint.json"
    assert failure["diagnostics"]["error"].startswith("FileNotFoundError:")


def test_user_input_replay_cli_writes_json_and_summary(tmp_path: Path):
    _write_replay_fixture(tmp_path, asset_id="candidate-ready")
    output_path = tmp_path / "replay.json"
    summary_path = tmp_path / "replay.md"

    exit_code = run_user_input_replay_main(["--assets", str(tmp_path), "--output", str(output_path)])

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "rpa-harness-user-input-replay-v1"
    assert report["summary"]["replayed_event_count"] == 2

    summary_exit = run_user_input_replay_main(
        [
            "--assets",
            str(tmp_path),
            "--format",
            "summary",
            "--lang",
            "zh",
            "--output",
            str(summary_path),
            "--machine-report",
            str(output_path),
        ]
    )

    assert summary_exit == 0
    summary = summary_path.read_text(encoding="utf-8")
    assert "RPA Harness User Input Replay: deterministic" in summary
    assert "状态: passed" in summary
    assert "Boundary injections: 2" in summary
    assert f"机器报告: {output_path}" in summary
    assert "Agent may explain; humans govern promotion" in render_user_input_replay_summary(report)
