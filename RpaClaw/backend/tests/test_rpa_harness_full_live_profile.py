import json
from pathlib import Path

import pytest

from backend.rpa.harness.full_live_profile import (
    render_full_live_profile_summary,
    run_full_live_profile,
)
from backend.rpa.harness.run_harness_profile import main as run_harness_profile_main


def _write_source_asset(
    root: Path,
    *,
    asset_id: str = "candidate-live-source",
    event_kind: str = "natural_language_instruction",
    promotion_status: str = "candidate",
    region_context: dict | None = None,
) -> Path:
    asset_dir = root / asset_id
    step_dir = asset_dir / "steps" / "001"
    step_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "scenario.json").write_text(
        json.dumps(
            {
                "schema_version": "rpa-harness-scenario-v0",
                "asset_id": asset_id,
                "capture_scope": "full_sop",
                "sop_intent": "Extract invoice total",
                "source": {
                    "recording_id": f"rec-{asset_id}",
                    "captured_at": "2026-05-28T10:00:00",
                    "capture_mode": "harness",
                    "capture_trigger": "full_sop",
                },
                "asset_status": "active",
                "sensitivity": "repo-safe",
                "page_patterns": ["invoice-detail"],
                "governance": {
                    "promotion_status": promotion_status,
                    "runner_modes": ["offline_core_chain", "skill_replay_e2e", "stateful_sop_capture_to_skill"],
                    "core_chain_coverage": [
                        "html_to_raw_snapshot",
                        "raw_to_compact_snapshot",
                        "planner_action_selection",
                        "trace_to_skill",
                        "skill_replay",
                        "stateful_capture_to_skill",
                    ],
                    "expected_signals_reviewed": promotion_status in {"candidate", "golden"},
                    "sensitivity_reviewed": promotion_status in {"candidate", "golden"},
                    "review_notes": "full-live profile source fixture",
                },
                "step_checkpoints": [{"step_index": 1, "checkpoint_path": "steps/001/checkpoint.json"}],
            }
        ),
        encoding="utf-8",
    )
    (step_dir / "before.html").write_text(
        """
        <html>
          <head><title>Invoice</title></head>
          <body>
            <main>
              <h1>Invoice #42</h1>
              <dl><dt>Invoice Total</dt><dd id="invoice-total">$42.00</dd></dl>
            </main>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    (step_dir / "after.html").write_text((step_dir / "before.html").read_text(encoding="utf-8"), encoding="utf-8")
    trace_event = (
        {
            "trace_id": f"trace-{asset_id}-1",
            "trace_type": "ai_operation",
            "source": "ai",
            "user_instruction": "Extract the invoice total",
            "description": "Extract invoice total from the page",
            "output_key": "invoice_total",
            "output": {"invoice_total": "$42.00"},
            "signals": {"region": region_context} if region_context else {},
            "ai_execution": {"error": None, "repair_attempted": False},
            "accepted": True,
        }
        if event_kind == "natural_language_instruction"
        else {
            "trace_id": f"trace-{asset_id}-1",
            "trace_type": "manual_action",
            "source": "manual",
            "action": "click",
            "description": "Click invoice row",
            "accepted": True,
        }
    )
    (step_dir / "trace_events.json").write_text(json.dumps([trace_event]), encoding="utf-8")
    (step_dir / "expected.json").write_text(
        json.dumps({"snapshot_signals": {"must_contain_text": ["Invoice Total", "$42.00"]}}),
        encoding="utf-8",
    )
    target_evidence = {"region": region_context} if region_context else {}
    (step_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "step_index": 1,
                "step_id": f"trace-{asset_id}-1",
                "step_intent": "Extract the invoice total",
                "recording_mode": "natural_language" if event_kind == "natural_language_instruction" else "manual",
                "page_patterns": ["invoice-detail"],
                "before": {
                    "url": "https://fixture.local/invoice",
                    "title": "Invoice",
                    "html_path": "steps/001/before.html",
                    "html_sha256": "before",
                },
                "action": {
                    "trace_events_path": "steps/001/trace_events.json",
                    "expected_action_type": "extract" if event_kind == "natural_language_instruction" else "click",
                    "target_evidence": target_evidence,
                },
                "after": {
                    "url": "https://fixture.local/invoice",
                    "title": "Invoice",
                    "html_path": "steps/001/after.html",
                    "html_sha256": "after",
                    "capture_quality": {"status": "stable", "ready_state": "complete"},
                },
                "runtime_result": {"status": "success"},
                "captured_at": "2026-05-28T10:00:00",
                "expected_path": "steps/001/expected.json",
            }
        ),
        encoding="utf-8",
    )
    return asset_dir


def _remove_before_html(root: Path, asset_id: str = "candidate-live-source") -> None:
    (root / asset_id / "steps" / "001" / "before.html").unlink()


def _set_before_html_path(root: Path, html_path: str, asset_id: str = "candidate-live-source") -> None:
    checkpoint_path = root / asset_id / "steps" / "001" / "checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["before"]["html_path"] = html_path
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")


@pytest.mark.asyncio
async def test_full_live_profile_invokes_planner_and_returns_v1_report(tmp_path: Path):
    source_root = tmp_path / "source-assets"
    generated_root = tmp_path / "generated-assets"
    _write_source_asset(source_root)
    planner_calls = []

    async def planner(payload):
        planner_calls.append(payload)
        assert payload["instruction"] == "Extract the invoice total"
        return {
            "description": "Extract invoice total from the invoice page",
            "output_key": "invoice_total",
            "code": """
async def run(page, results):
    return (await page.locator('#invoice-total').inner_text()).strip()
""",
        }

    report = await run_full_live_profile(
        source_root,
        generated_assets_root=generated_root,
        planner=planner,
    )

    assert report["schema_version"] == "rpa-harness-full-live-profile-v1"
    assert report["kind"] == "full_live_profile"
    assert report["profile"]["name"] == "full-live"
    assert report["profile"]["uses_live_planner"] is True
    assert report["profile"]["uses_live_url_oracle"] is False
    assert report["profile"]["uses_outer_agent_ui_control"] is False
    assert report["summary"]["status"] == "passed", report
    assert report["summary"]["planner_invocation_count"] == 1
    assert report["summary"]["selected_input_event_count"] == 1
    assert report["summary"]["generated_asset_ids"] == ["hcap-live-candidate-live-source-step-1"]
    assert len(planner_calls) == 1
    assert report["source_asset_ids"] == ["candidate-live-source"]
    assert report["selected_input_events"][0]["event_kind"] == "natural_language_instruction"
    assert report["controlled_fixtures"][0]["html_source"] == "captured-before-html"
    assert report["controlled_fixtures"][0]["source_checkpoint_path"] == (
        "candidate-live-source/steps/001/checkpoint.json"
    )
    assert report["post_capture"]["warning_count"] == 0
    assert report["governance_boundary"]["agents_may_promote_automatically"] is False

    assert not (source_root / "hcap-live-candidate-live-source-step-1").exists()
    generated_scenario = json.loads(
        (generated_root / "hcap-live-candidate-live-source-step-1" / "scenario.json").read_text(encoding="utf-8")
    )
    assert generated_scenario["governance"]["promotion_status"] == "candidate-lite"


@pytest.mark.asyncio
async def test_full_live_profile_without_natural_language_input_is_insufficient_evidence(tmp_path: Path):
    source_root = tmp_path / "source-assets"
    _write_source_asset(source_root, event_kind="click")
    planner_calls = []

    async def planner(payload):
        planner_calls.append(payload)
        return {"description": "unused", "code": "async def run(page, results):\n    return None"}

    report = await run_full_live_profile(
        source_root,
        generated_assets_root=tmp_path / "generated-assets",
        planner=planner,
    )

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["failure_category"] == "no-full-live-input-events"
    assert report["summary"]["selected_input_event_count"] == 0
    assert report["interpretation"]["verdict"] == "insufficient evidence"
    assert planner_calls == []


@pytest.mark.asyncio
async def test_full_live_profile_preserves_region_context_as_generic_context(tmp_path: Path):
    source_root = tmp_path / "source-assets"
    region_context = {
        "region_id": "region-invoice-total",
        "inferred_kind": "text_region",
        "rect": {"x": 10, "y": 20, "width": 240, "height": 80},
        "local_text": ["Invoice Total", "$42.00"],
    }
    _write_source_asset(source_root, region_context=region_context)

    planner_payloads = []

    async def planner(payload):
        planner_payloads.append(payload)
        return {
            "description": "Extract invoice total from selected region",
            "output_key": "invoice_total",
            "code": """
async def run(page, results):
    return (await page.locator('#invoice-total').inner_text()).strip()
""",
        }

    report = await run_full_live_profile(
        source_root,
        generated_assets_root=tmp_path / "generated-assets",
        planner=planner,
    )

    assert report["selected_input_events"][0]["region_context"] == {
        "target_evidence": region_context,
        "signals": region_context,
    }
    assert report["controlled_fixtures"][0]["source_region_context"] == {
        "target_evidence": region_context,
        "signals": region_context,
    }
    assert report["controlled_fixtures"][0]["runtime_region_context"]["rect"] == region_context["rect"]
    assert report["controlled_fixtures"][0]["runtime_region_context"]["local_text"] == region_context["local_text"]
    assert report["controlled_fixtures"][0]["runtime_region_context"]["evidence"]["rect"] == region_context["rect"]
    assert planner_payloads[0]["snapshot"]["region_scope"]["region_id"] == region_context["region_id"]
    assert planner_payloads[0]["snapshot"]["region_scope"]["frame_rect"] == region_context["rect"]
    generated_trace = report["live_agent_eval"]["scenarios"][0]
    assert report["live_agent_eval"]["scenarios"][0]["region_context"]["region_id"] == region_context["region_id"]
    assert report["live_agent_eval"]["scenarios"][0]["region_context"]["rect"] == region_context["rect"]
    assert report["live_agent_eval"]["scenarios"][0]["region_context"]["evidence"]["local_text"] == region_context["local_text"]
    assert generated_trace["post_capture"]["stateful_sop"]["assets"][0]["accepted_trace_count"] == 1
    assert "region_context is passed as generic RecordingRuntimeAgent context" in report["trust_limits"]


@pytest.mark.asyncio
async def test_full_live_profile_rejects_generated_assets_inside_source_root(tmp_path: Path):
    source_root = tmp_path / "source-assets"
    _write_source_asset(source_root)

    with pytest.raises(ValueError, match="generated assets root must not equal source assets root"):
        await run_full_live_profile(
            source_root,
            generated_assets_root=source_root,
            planner=lambda _payload: None,
        )


@pytest.mark.asyncio
async def test_full_live_profile_rejects_generated_assets_descendant_of_source_root(tmp_path: Path):
    source_root = tmp_path / "source-assets"
    _write_source_asset(source_root)

    with pytest.raises(ValueError, match="generated assets root must be outside source assets root"):
        await run_full_live_profile(
            source_root,
            generated_assets_root=source_root / "generated-profile-artifacts",
            planner=lambda _payload: None,
        )


@pytest.mark.asyncio
async def test_full_live_profile_reports_fixture_build_failure_without_throwing(tmp_path: Path):
    source_root = tmp_path / "source-assets"
    _write_source_asset(source_root)
    _remove_before_html(source_root)
    planner_calls = []

    async def planner(payload):
        planner_calls.append(payload)
        return {"description": "unused", "code": "async def run(page, results):\n    return None"}

    report = await run_full_live_profile(
        source_root,
        generated_assets_root=tmp_path / "generated-assets",
        planner=planner,
    )

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["failure_category"] == "controlled-fixture-build-failed"
    assert report["summary"]["selected_input_event_count"] == 1
    assert report["summary"]["fixture_build_failure_count"] == 1
    assert report["summary"]["planner_invocation_count"] == 0
    assert planner_calls == []
    assert report["failures"][0]["failure_category"] == "controlled-fixture-build-failed"
    assert report["failures"][0]["source_checkpoint_path"] == "candidate-live-source/steps/001/checkpoint.json"
    assert report["failures"][0]["before_html_path"] == "steps/001/before.html"


@pytest.mark.asyncio
async def test_full_live_profile_rejects_before_html_path_outside_source_asset(tmp_path: Path):
    source_root = tmp_path / "source-assets"
    _write_source_asset(source_root)
    outside_secret = tmp_path / "outside-secret.html"
    outside_secret.write_text("<html><body>OUTSIDE_SECRET_123</body></html>", encoding="utf-8")
    _set_before_html_path(source_root, "../../outside-secret.html")
    planner_calls = []

    async def planner(payload):
        planner_calls.append(payload)
        return {
            "description": "unused",
            "output_key": "leaked",
            "code": """
async def run(page, results):
    return (await page.locator('body').inner_text()).strip()
""",
        }

    report = await run_full_live_profile(
        source_root,
        generated_assets_root=tmp_path / "generated-assets",
        planner=planner,
    )

    serialized_report = json.dumps(report, ensure_ascii=False)
    assert report["summary"]["status"] == "failed"
    assert report["summary"]["failure_category"] == "controlled-fixture-build-failed"
    assert report["summary"]["fixture_build_failure_count"] == 1
    assert report["summary"]["planner_invocation_count"] == 0
    assert planner_calls == []
    assert report["failures"][0]["before_html_path"] == "../../outside-secret.html"
    assert "before_page.html_path must stay inside source asset directory" in report["failures"][0]["error"]
    assert "OUTSIDE_SECRET_123" not in serialized_report


@pytest.mark.asyncio
async def test_full_live_profile_rejects_absolute_before_html_path(tmp_path: Path):
    source_root = tmp_path / "source-assets"
    _write_source_asset(source_root)
    outside_secret = tmp_path / "absolute-secret.html"
    outside_secret.write_text("<html><body>ABSOLUTE_SECRET_456</body></html>", encoding="utf-8")
    _set_before_html_path(source_root, str(outside_secret))
    planner_calls = []

    async def planner(payload):
        planner_calls.append(payload)
        return {"description": "unused", "code": "async def run(page, results):\n    return None"}

    report = await run_full_live_profile(
        source_root,
        generated_assets_root=tmp_path / "generated-assets",
        planner=planner,
    )

    serialized_report = json.dumps(report, ensure_ascii=False)
    assert report["summary"]["status"] == "failed"
    assert report["summary"]["failure_category"] == "controlled-fixture-build-failed"
    assert report["summary"]["planner_invocation_count"] == 0
    assert planner_calls == []
    assert "before_page.html_path must be relative to source asset directory" in report["failures"][0]["error"]
    assert "ABSOLUTE_SECRET_456" not in serialized_report


@pytest.mark.asyncio
async def test_full_live_post_capture_warning_from_generated_candidate_lite_is_warning_only(
    tmp_path: Path,
    monkeypatch,
):
    from backend.rpa.harness import full_live_profile

    source_root = tmp_path / "source-assets"
    _write_source_asset(source_root)

    async def fake_live_agent_eval(*, scenarios_root, assets_root, planner=None, model_config=None):
        return {
            "schema_version": "rpa-harness-live-agent-eval-v0",
            "summary": {
                "status": "failed",
                "scenario_count": 1,
                "passed": 0,
                "failed": 1,
                "planner_invocation_count": 1,
            },
            "scenarios": [
                {
                    "scenario_id": "candidate-live-source-step-1",
                    "asset_id": "hcap-live-candidate-live-source-step-1",
                    "instruction": "Extract the invoice total",
                    "status": "failed",
                    "failure_category": "post-capture-regression-warning",
                    "planner_invocation_count": 1,
                    "output_key": "invoice_total",
                    "actual_output": "$42.00",
                    "missing_text": [],
                    "error": "",
                    "post_capture": {"warning_count": 1},
                }
            ],
        }

    monkeypatch.setattr(full_live_profile, "run_live_agent_eval", fake_live_agent_eval)

    report = await run_full_live_profile(
        source_root,
        generated_assets_root=tmp_path / "generated-assets",
        planner=lambda _payload: None,
    )

    assert report["summary"]["status"] == "passed"
    assert report["summary"]["blocking_failure_count"] == 0
    assert report["summary"]["warning_only_failure_count"] == 1
    assert report["failures"][0]["failure_category"] == "post-capture-regression-warning"
    assert report["failures"][0]["baseline_role"] == "warning-only-generated-asset"


def test_full_live_profile_cli_writes_json_for_no_input_failure(tmp_path: Path):
    source_root = tmp_path / "source-assets"
    output_path = tmp_path / "full-live.json"
    _write_source_asset(source_root, event_kind="click")

    exit_code = run_harness_profile_main(
        [
            "--assets",
            str(source_root),
            "--profile",
            "full-live",
            "--generated-assets",
            str(tmp_path / "generated-assets"),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["profile"]["name"] == "full-live"
    assert report["summary"]["failure_category"] == "no-full-live-input-events"


def test_deterministic_cli_ignores_full_live_model_config_options(tmp_path: Path):
    output_path = tmp_path / "deterministic.json"

    exit_code = run_harness_profile_main(
        [
            "--assets",
            str(tmp_path / "empty-assets"),
            "--profile",
            "deterministic",
            "--model-config-file",
            str(tmp_path / "missing-model-config.json"),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 1
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["profile"]["name"] == "deterministic"
    assert report["summary"]["status"] == "failed"


def test_profile_summary_reads_existing_machine_report_without_rerunning(tmp_path: Path, monkeypatch):
    from backend.rpa.harness import run_harness_profile

    machine_report = tmp_path / "full-live.json"
    summary_path = tmp_path / "summary.md"
    machine_report.write_text(
        json.dumps(
            {
                "schema_version": "rpa-harness-full-live-profile-v1",
                "kind": "full_live_profile",
                "profile": {"name": "full-live"},
                "summary": {
                    "status": "passed",
                    "failure_category": "",
                    "selected_input_event_count": 7,
                    "planner_invocation_count": 3,
                    "generated_asset_ids": ["generated-from-json"],
                },
                "source_asset_ids": ["source-from-json"],
                "trust_limits": ["loaded from existing machine report"],
            }
        ),
        encoding="utf-8",
    )

    def fail_if_runner_executes(*args, **kwargs):
        raise AssertionError("summary rendering should not rerun the profile")

    monkeypatch.setattr(run_harness_profile, "run_harness_profile", fail_if_runner_executes)

    exit_code = run_harness_profile_main(
        [
            "--assets",
            str(tmp_path / "source-assets"),
            "--profile",
            "full-live",
            "--format",
            "summary",
            "--machine-report",
            str(machine_report),
            "--output",
            str(summary_path),
        ]
    )

    assert exit_code == 0
    summary = summary_path.read_text(encoding="utf-8")
    assert "Selected input events: 7" in summary
    assert "Generated assets: generated-from-json" in summary
    assert "loaded from existing machine report" in summary


def test_full_live_profile_summary_names_governance_boundary(tmp_path: Path):
    report = {
        "profile": {"name": "full-live"},
        "summary": {
            "status": "failed",
            "failure_category": "no-full-live-input-events",
            "selected_input_event_count": 0,
            "planner_invocation_count": 0,
            "generated_asset_ids": [],
        },
        "source_asset_ids": [],
        "trust_limits": ["No eligible natural-language input events ran"],
    }

    summary = render_full_live_profile_summary(report, machine_report_path=tmp_path / "report.json")

    assert "RPA Harness Profile: full-live" in summary
    assert "Status: failed" in summary
    assert "Governance: Scripts execute; Agents explain; Humans govern" in summary
    assert f"Machine report: {tmp_path / 'report.json'}" in summary
