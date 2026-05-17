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

