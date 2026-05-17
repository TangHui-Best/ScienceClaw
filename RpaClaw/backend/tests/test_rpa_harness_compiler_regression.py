import json
from pathlib import Path

from backend.rpa.harness.compiler_regression import run_compiler_regression
from backend.rpa.harness.expected_signals import build_expected_signal_draft


def _write_compiler_asset(
    root: Path,
    *,
    expected_compiler_signals: dict,
    baseline_script: str | None = None,
) -> Path:
    step_dir = root / "asset-1" / "steps" / "001"
    step_dir.mkdir(parents=True)
    (step_dir / "before.html").write_text("<html></html>", encoding="utf-8")
    (step_dir / "trace_events.json").write_text(
        json.dumps([{"trace_id": "trace-1", "trace_type": "ai_operation"}]),
        encoding="utf-8",
    )
    (step_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "step_index": 1,
                "step_id": "step-1",
                "step_intent": "Open selected project",
                "recording_mode": "natural_language",
                "page_patterns": ["card-list"],
                "before": {
                    "url": "https://example.test/search",
                    "title": "Search",
                    "html_path": "steps/001/before.html",
                    "html_sha256": "abc",
                },
                "action": {
                    "trace_events_path": "steps/001/trace_events.json",
                    "expected_action_type": "click",
                },
                "after": {
                    "url": "https://example.test/project",
                    "title": "Project",
                    "html_path": "steps/001/before.html",
                    "html_sha256": "abc",
                    "same_as_before": True,
                },
                "runtime_result": {"status": "success"},
                "captured_at": "2026-05-17T10:00:00",
                "expected_path": "steps/001/expected.json",
            }
        ),
        encoding="utf-8",
    )
    (step_dir / "expected.json").write_text(
        json.dumps({"compiler_signals": expected_compiler_signals}),
        encoding="utf-8",
    )
    if baseline_script is not None:
        (step_dir / "baseline_skill.py").write_text(baseline_script, encoding="utf-8")
    return root


def test_compiler_regression_passes_when_script_preserves_expected_signals(tmp_path: Path):
    assets = _write_compiler_asset(
        tmp_path,
        expected_compiler_signals={
            "must_not_hardcode_observed_values": ["Recorded Project"],
            "must_preserve_dataflow_refs": ["_results['selected_project']"],
        },
    )

    report = run_compiler_regression(
        assets,
        compiler=lambda trace_events, checkpoint: "url = _results['selected_project']['url']",
    )

    item = report["assets"][0]
    assert report["summary"]["failed"] == 0
    assert item["asset_id"] == "asset-1"
    assert item["step_id"] == "step-1"
    assert item["page_patterns"] == ["card-list"]


def test_compiler_regression_flags_hardcoded_observed_values(tmp_path: Path):
    assets = _write_compiler_asset(
        tmp_path,
        expected_compiler_signals={
            "must_not_hardcode_observed_values": ["Recorded Project"],
        },
    )

    report = run_compiler_regression(
        assets,
        compiler=lambda trace_events, checkpoint: "await page.get_by_text('Recorded Project').click()",
    )

    item = report["assets"][0]
    assert report["summary"]["failed"] == 1
    assert item["failure_category"] == "compiler-hardcoded-observed-value"
    assert item["hardcoded_values"] == ["Recorded Project"]


def test_compiler_regression_flags_missing_dataflow_refs(tmp_path: Path):
    assets = _write_compiler_asset(
        tmp_path,
        expected_compiler_signals={
            "must_preserve_dataflow_refs": ["_results['selected_project']"],
        },
    )

    report = run_compiler_regression(
        assets,
        compiler=lambda trace_events, checkpoint: "await page.goto('https://example.test/project')",
    )

    item = report["assets"][0]
    assert report["summary"]["failed"] == 1
    assert item["failure_category"] == "compiler-dataflow-lost"
    assert item["missing_dataflow_refs"] == ["_results['selected_project']"]


def test_compiler_regression_reports_baseline_script_diff(tmp_path: Path):
    assets = _write_compiler_asset(
        tmp_path,
        expected_compiler_signals={},
        baseline_script="await page.goto('old')\n",
    )

    report = run_compiler_regression(
        assets,
        compiler=lambda trace_events, checkpoint: "await page.goto('new')\n",
    )

    item = report["assets"][0]
    assert item["script_changed"] is True
    assert "--- baseline" in item["script_diff"]
    assert "+++ current" in item["script_diff"]


def test_compiler_regression_consumes_enriched_extraction_expected_signals(tmp_path: Path):
    expected = build_expected_signal_draft(
        step_intent="Extract star count",
        recording_mode="natural_language",
        trace_events=[
            {
                "trace_type": "ai_operation",
                "action": "extract",
                "output_key": "star_count",
                "output": {"star_count": "123"},
            }
        ],
    )
    assets = _write_compiler_asset(
        tmp_path,
        expected_compiler_signals=expected.compiler_signals,
    )

    report = run_compiler_regression(
        assets,
        compiler=lambda trace_events, checkpoint: "return {'star_count': '123'}",
    )

    item = report["assets"][0]
    assert report["summary"]["failed"] == 1
    assert item["failure_category"] == "compiler-hardcoded-observed-value"
    assert item["hardcoded_values"] == ["123"]
    assert item["missing_output_keys"] == ["star_count"]


def test_compiler_regression_accepts_runtime_ai_output_key_argument(tmp_path: Path):
    expected = build_expected_signal_draft(
        step_intent="Extract star count",
        recording_mode="natural_language",
        trace_events=[
            {
                "trace_type": "ai_operation",
                "action": "extract",
                "output_key": "star_count",
                "output": {"star_count": ""},
                "signals": {"output_contract": {"allow_empty": True}},
            }
        ],
    )
    assets = _write_compiler_asset(
        tmp_path,
        expected_compiler_signals=expected.compiler_signals,
    )

    report = run_compiler_regression(
        assets,
        compiler=lambda trace_events, checkpoint: (
            "_result = await _execute_runtime_ai_instruction(current_page, _results, kwargs, 'Extract star count', 'star_count')"
        ),
    )

    item = report["assets"][0]
    assert report["summary"]["failed"] == 0
    assert item["missing_output_keys"] == []

