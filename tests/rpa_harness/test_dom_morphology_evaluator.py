from __future__ import annotations

from tests.rpa_harness.evaluators.dom_morphology import (
    DomMorphologyCase,
    DomMorphologyEvaluator,
)


CASE_ROOT = __import__("pathlib").Path(__file__).parent / "cases" / "dom_morphology"


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


def test_evaluator_reports_compact_loss_when_raw_fact_is_missing_from_compact():
    case = DomMorphologyCase(
        case_id="compact-loss",
        title="Compact loss",
        task_shape="detail_extraction",
        instruction="Extract the preserved and dropped facts",
        raw_snapshot=_snapshot_with_text("Preserved Fact", "Dropped Fact"),
        expected_raw_facts=["Dropped Fact"],
        expected_compact_facts=["Fact that compact cannot contain"],
        expected_semantic_view={"kind": "text_section"},
        expected_locator_preservation=[],
        guarded_failure_mode="compression removed a task-relevant fact",
    )

    result = DomMorphologyEvaluator([case]).evaluate()[0]

    assert result.passed is False
    assert result.attribution_layer == "compact_loss"
    assert result.missing_facts == ["Fact that compact cannot contain"]


def test_evaluator_reports_raw_missing_before_compact_loss():
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

    result = DomMorphologyEvaluator([case]).evaluate()[0]

    assert result.passed is False
    assert result.attribution_layer == "raw_missing"
    assert result.missing_facts == ["Absent Raw Fact"]


def test_dom_morphology_cases_cover_required_structural_shapes():
    evaluator = DomMorphologyEvaluator.from_directory(CASE_ROOT)

    assert {case.case_id for case in evaluator.cases} == {
        "candidate_cards",
        "form_fields",
        "iframe_content",
        "key_value_split_siblings",
        "table_with_row_actions",
    }


def test_curated_dom_morphology_cases_pass_snapshot_compression():
    summary = DomMorphologyEvaluator.from_directory(CASE_ROOT).summarize()

    assert summary.case_count == 5
    assert summary.failed_count == 0
    assert {result.attribution_layer for result in summary.results} == {"passed"}


def test_dom_runner_prints_case_count_and_pass_summary(capsys):
    from tests.rpa_harness.run import main

    exit_code = main(["dom"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "DOM morphology cases: 5" in output
    assert "pass: 5" in output
    assert "fail: 0" in output
