from __future__ import annotations

from pathlib import Path

from tests.rpa_harness.evaluators.dom_morphology import DomMorphologyCase
from tests.rpa_harness.evaluators.snapshot_diff import SnapshotDiffEvaluator


CASE_ROOT = Path(__file__).parent / "cases" / "dom_morphology"


def _snapshot_with_text(*texts: str) -> dict:
    return {
        "url": "https://structure.test",
        "title": "Structure Fixture",
        "containers": [
            {
                "container_id": "fixture",
                "container_kind": "section",
                "name": "Fixture",
            }
        ],
        "content_nodes": [
            {
                "node_id": f"text-{index}",
                "container_id": "fixture",
                "semantic_kind": "text",
                "text": text,
                "bbox": {"x": 10, "y": 20 + index * 20, "width": 240, "height": 16},
            }
            for index, text in enumerate(texts)
        ],
        "actionable_nodes": [],
        "frames": [],
    }


def test_snapshot_diff_reports_raw_missing_before_compact_loss():
    case = DomMorphologyCase(
        case_id="raw-missing",
        title="Raw missing",
        task_shape="detail_extraction",
        instruction="Extract the absent fact",
        raw_snapshot=_snapshot_with_text("Only visible fact"),
        expected_raw_facts=["Absent Raw Fact"],
        expected_compact_facts=["Absent Raw Fact"],
        expected_semantic_view={"kind": "text_section"},
        expected_locator_preservation=[],
        guarded_failure_mode="raw snapshot never captured the task fact",
    )

    result = SnapshotDiffEvaluator([case]).evaluate()[0]

    assert result.passed is False
    assert result.attribution_layer == "raw_missing"
    assert [fact.key for fact in result.missing_facts] == [
        "expected.raw.Absent Raw Fact"
    ]


def test_snapshot_diff_reports_compact_loss_with_structured_fact_key():
    case = DomMorphologyCase(
        case_id="compact-loss",
        title="Compact loss",
        task_shape="detail_extraction",
        instruction="Extract the dropped fact",
        raw_snapshot=_snapshot_with_text("Dropped Fact"),
        expected_raw_facts=["Dropped Fact"],
        expected_compact_facts=["Fact that compact cannot contain"],
        expected_semantic_view={"kind": "text_section"},
        expected_locator_preservation=[],
        guarded_failure_mode="compression removed a task-relevant fact",
    )

    result = SnapshotDiffEvaluator([case]).evaluate()[0]

    assert result.passed is False
    assert result.attribution_layer == "compact_loss"
    assert [fact.key for fact in result.missing_facts] == [
        "expected.compact.Fact that compact cannot contain"
    ]


def test_snapshot_diff_reuses_dom_morphology_cases_with_task_shape_fact_keys():
    summary = SnapshotDiffEvaluator.from_directory(CASE_ROOT).summarize()

    assert summary.case_count == 5
    assert summary.failed_count == 0
    candidate = next(
        result for result in summary.results if result.case_id == "candidate_cards"
    )
    assert "candidate.title.Beta Research" in candidate.checked_fact_keys
    assert "candidate.locator.Beta Research" in candidate.checked_fact_keys


def test_snapshot_runner_prints_summary_and_failed_details(capsys):
    from tests.rpa_harness.run import main

    exit_code = main(["snapshot"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Snapshot diff cases: 5" in output
    assert "pass: 5" in output
    assert "fail: 0" in output
