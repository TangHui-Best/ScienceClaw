import json
from pathlib import Path

import pytest

from backend.rpa.harness.capture import (
    HarnessCaptureSessionState,
    capture_step_checkpoint,
)
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


@pytest.mark.asyncio
async def test_successful_selected_step_writes_before_and_after_html(tmp_path: Path):
    state = HarnessCaptureSessionState(
        capture_id="hcap-test",
        session_id="session-1",
        capture_scope="selected_steps",
        selected_step_indexes=[2],
    )
    store = HarnessAssetStore(tmp_path)

    checkpoint = await capture_step_checkpoint(
        state,
        store,
        step_index=2,
        step_id="step-2",
        step_intent="Click the ScienceClaw result",
        recording_mode="natural_language",
        before_page=_FakePage(
            url="https://example.test/search",
            title="Search",
            html="<html><body><a>ScienceClaw</a></body></html>",
        ),
        after_page=_FakePage(
            url="https://example.test/project/scienceclaw",
            title="ScienceClaw",
            html="<html><body><h1>ScienceClaw</h1></body></html>",
        ),
        trace_events=[{"trace_id": "trace-1", "action": "click"}],
        runtime_status="success",
    )

    step_dir = tmp_path / "hcap-test" / "steps" / "002"
    assert checkpoint is not None
    assert (step_dir / "before.html").read_text(encoding="utf-8") == "<html><body><a>ScienceClaw</a></body></html>"
    assert (step_dir / "after.html").read_text(encoding="utf-8") == "<html><body><h1>ScienceClaw</h1></body></html>"
    assert json.loads((step_dir / "trace_events.json").read_text(encoding="utf-8")) == [
        {"trace_id": "trace-1", "action": "click"}
    ]
    assert checkpoint.step_intent == "Click the ScienceClaw result"
    assert checkpoint.before.url == "https://example.test/search"
    assert checkpoint.after is not None
    assert checkpoint.after.url == "https://example.test/project/scienceclaw"


@pytest.mark.asyncio
async def test_identical_after_html_is_hash_deduplicated(tmp_path: Path):
    state = HarnessCaptureSessionState(
        capture_id="hcap-test",
        session_id="session-1",
        capture_scope="full_sop",
    )
    store = HarnessAssetStore(tmp_path)
    html = "<html><body><p>No visible change</p></body></html>"

    checkpoint = await capture_step_checkpoint(
        state,
        store,
        step_index=1,
        step_id="step-1",
        step_intent="Read the current title",
        recording_mode="manual",
        before_page=_FakePage(url="https://example.test", title="Same", html=html),
        after_page=_FakePage(url="https://example.test", title="Same", html=html),
        trace_events=[{"trace_id": "trace-1", "action": "extract"}],
        runtime_status="success",
    )

    step_dir = tmp_path / "hcap-test" / "steps" / "001"
    assert checkpoint is not None
    assert checkpoint.after is not None
    assert checkpoint.after.same_as_before is True
    assert checkpoint.after.html_path == "steps/001/before.html"
    assert not (step_dir / "after.html").exists()


@pytest.mark.asyncio
async def test_failed_step_records_before_state_and_failure_evidence(tmp_path: Path):
    state = HarnessCaptureSessionState(
        capture_id="hcap-test",
        session_id="session-1",
        capture_scope="selected_steps",
        selected_step_indexes=[4],
    )
    store = HarnessAssetStore(tmp_path)

    checkpoint = await capture_step_checkpoint(
        state,
        store,
        step_index=4,
        step_id="step-4",
        step_intent="Click the missing export button",
        recording_mode="natural_language",
        before_page=_FakePage(
            url="https://example.test/report",
            title="Report",
            html="<html><body><main>Report</main></body></html>",
        ),
        after_page=None,
        trace_events=[{"trace_id": "trace-4", "action": "click"}],
        runtime_status="failed",
        error="button not found",
    )

    step_dir = tmp_path / "hcap-test" / "steps" / "004"
    failure = json.loads((step_dir / "failure.json").read_text(encoding="utf-8"))
    assert checkpoint is not None
    assert checkpoint.after is None
    assert checkpoint.failure_path == "steps/004/failure.json"
    assert failure["error"] == "button not found"
    assert (step_dir / "before.html").exists()


@pytest.mark.asyncio
async def test_unselected_step_is_not_captured(tmp_path: Path):
    state = HarnessCaptureSessionState(
        capture_id="hcap-test",
        session_id="session-1",
        capture_scope="selected_steps",
        selected_step_indexes=[7],
    )
    store = HarnessAssetStore(tmp_path)

    checkpoint = await capture_step_checkpoint(
        state,
        store,
        step_index=3,
        step_id="step-3",
        step_intent="Ignored step",
        recording_mode="manual",
        before_page=_FakePage(url="https://example.test", title="Ignored", html="<html></html>"),
        after_page=_FakePage(url="https://example.test", title="Ignored", html="<html></html>"),
        trace_events=[],
        runtime_status="success",
    )

    assert checkpoint is None
    assert not (tmp_path / "hcap-test").exists()

