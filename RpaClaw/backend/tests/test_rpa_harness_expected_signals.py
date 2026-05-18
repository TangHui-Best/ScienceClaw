import json
from pathlib import Path

import pytest

from backend.rpa.harness.capture import (
    HarnessCaptureSessionState,
    capture_step_checkpoint,
)
from backend.rpa.harness.expected_signals import build_expected_signal_draft
from backend.rpa.harness.store import HarnessAssetStore


class _FakePage:
    def __init__(self, *, url: str, title: str, html: str) -> None:
        self.url = url
        self._title = title
        self._html = html

    async def title(self) -> str:
        return self._title

    async def content(self) -> str:
        return self._html


def test_natural_language_step_uses_intent_and_trace_target_as_signal_sources():
    draft = build_expected_signal_draft(
        step_intent="Click the search result whose title contains ScienceClaw",
        recording_mode="natural_language",
        trace_events=[
            {
                "action": "click",
                "target_evidence": {
                    "role": "link",
                    "text": "ScienceClaw",
                    "container_text": ["ScienceClaw", "repository"],
                },
            }
        ],
    )

    assert draft.action_signals["expected_action_type"] == "click"
    assert draft.action_signals["target_role"] == "link"
    assert draft.action_signals["target_text_contains"] == "ScienceClaw"
    assert draft.snapshot_signals["must_contain_text"] == ["ScienceClaw"]
    assert draft.snapshot_signals["must_preserve_target_container_context"] is True


def test_manual_step_prefers_semantic_target_context_over_absolute_selector():
    draft = build_expected_signal_draft(
        step_intent="",
        recording_mode="manual",
        trace_events=[
            {
                "action": "fill",
                "target_evidence": {
                    "role": "textbox",
                    "label": "Project name",
                    "placeholder": "Enter project name",
                    "selector": "#app > div:nth-child(3) input",
                },
            }
        ],
    )

    assert draft.action_signals["expected_action_type"] == "fill"
    assert draft.action_signals["target_role"] == "textbox"
    assert draft.action_signals["target_label_or_placeholder"] == "Project name"
    assert draft.snapshot_signals["must_preserve_label_input_relation"] is True
    assert "must_click_selector" not in draft.action_signals


def test_manual_step_derives_target_signals_from_selected_locator_candidate():
    draft = build_expected_signal_draft(
        step_intent="",
        recording_mode="manual",
        trace_events=[
            {
                "action": "navigate_click",
                "locator_candidates": [
                    {
                        "selected": True,
                        "locator": {
                            "method": "role",
                            "role": "link",
                            "name": "tinyhumansai / openhuman",
                        },
                    }
                ],
            }
        ],
    )

    assert draft.action_signals["expected_action_type"] == "navigate_click"
    assert draft.action_signals["target_role"] == "link"
    assert draft.action_signals["target_text_contains"] == "tinyhumansai / openhuman"
    assert draft.snapshot_signals["must_contain_text"] == ["tinyhumansai / openhuman"]


def test_extraction_output_key_and_observed_output_generate_compiler_signals_without_snapshot_locator():
    draft = build_expected_signal_draft(
        step_intent="Extract the star count",
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

    assert draft.state_signals["output_key"] == "star_count"
    assert draft.state_signals["observed_output_shape"] == {"type": "object", "keys": ["star_count"]}
    assert draft.compiler_signals["must_preserve_output_keys"] == ["star_count"]
    assert "must_preserve_dataflow_refs" not in draft.compiler_signals
    assert draft.compiler_signals["must_not_hardcode_observed_values"] == ["123"]
    assert "must_contain_text" not in draft.snapshot_signals


def test_empty_observed_output_is_allowed_evidence_not_global_failure():
    draft = build_expected_signal_draft(
        step_intent="Extract optional notifications",
        recording_mode="natural_language",
        trace_events=[
            {
                "trace_type": "ai_operation",
                "action": "extract",
                "output_key": "notifications",
                "output": {"notifications": ""},
                "signals": {"output_contract": {"allow_empty": True}},
            }
        ],
    )

    assert draft.state_signals["output_key"] == "notifications"
    assert draft.state_signals["allow_empty_output"] is True
    assert draft.compiler_signals["must_preserve_output_keys"] == ["notifications"]
    assert "must_preserve_dataflow_refs" not in draft.compiler_signals
    assert "must_not_hardcode_observed_values" not in draft.compiler_signals
    assert "must_have_non_empty_output" not in draft.state_signals


def test_dataflow_fill_expected_signals_preserve_source_ref_without_locator_rules():
    draft = build_expected_signal_draft(
        step_intent="Fill the report title from the previous extraction",
        recording_mode="manual",
        trace_events=[
            {
                "trace_type": "dataflow_fill",
                "action": "fill",
                "value": "Quarterly Report",
                "dataflow": {
                    "selected_source_ref": "page_title",
                    "source_ref_candidates": ["page_title"],
                },
                "target_evidence": {"label": "Title"},
            }
        ],
    )

    assert draft.compiler_signals["must_preserve_dataflow_refs"] == [
        "_resolve_result_ref(_results, 'page_title')"
    ]
    assert draft.compiler_signals["must_not_hardcode_observed_values"] == ["Quarterly Report"]
    assert draft.action_signals["target_label_or_placeholder"] == "Title"
    assert "must_click_selector" not in draft.action_signals


@pytest.mark.asyncio
async def test_capture_writes_expected_signal_draft(tmp_path: Path):
    state = HarnessCaptureSessionState(
        capture_id="hcap-test",
        session_id="session-1",
        capture_scope="full_sop",
    )
    store = HarnessAssetStore(tmp_path)

    checkpoint = await capture_step_checkpoint(
        state,
        store,
        step_index=1,
        step_id="step-1",
        step_intent="Click ScienceClaw",
        recording_mode="natural_language",
        before_page=_FakePage(
            url="https://example.test/search",
            title="Search",
            html="<html><body><a>ScienceClaw</a></body></html>",
        ),
        after_page=_FakePage(
            url="https://example.test/project",
            title="Project",
            html="<html><body><h1>ScienceClaw</h1></body></html>",
        ),
        trace_events=[
            {
                "action": "click",
                "target_evidence": {"role": "link", "text": "ScienceClaw"},
            }
        ],
        runtime_status="success",
    )

    expected_path = tmp_path / "hcap-test" / "steps" / "001" / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert checkpoint is not None
    assert checkpoint.expected_path == "steps/001/expected.json"
    assert expected["action_signals"]["expected_action_type"] == "click"
    assert expected["snapshot_signals"]["must_contain_text"] == ["ScienceClaw"]

