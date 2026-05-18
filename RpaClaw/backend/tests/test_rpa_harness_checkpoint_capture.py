import json
from pathlib import Path

import pytest

from backend.rpa.harness.catalog import build_harness_catalog
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


class _EventuallyReadyPage(_FakePage):
    def __init__(self, *, url: str, title: str, html_sequence: list[str]) -> None:
        super().__init__(url=url, title=title, html=html_sequence[-1])
        self._html_sequence = list(html_sequence)
        self.wait_calls: list[int] = []

    async def content(self) -> str:
        if len(self._html_sequence) > 1:
            return self._html_sequence.pop(0)
        return self._html_sequence[0]

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        self.wait_calls.append(timeout_ms)


class _StabilizingPage(_FakePage):
    def __init__(self, *, url: str, title_sequence: list[str], html_sequence: list[str]) -> None:
        super().__init__(url=url, title=title_sequence[-1], html=html_sequence[-1])
        self._title_sequence = list(title_sequence)
        self._html_sequence = list(html_sequence)
        self.wait_calls: list[int] = []

    async def title(self) -> str:
        if len(self._title_sequence) > 1:
            return self._title_sequence.pop(0)
        return self._title_sequence[0]

    async def content(self) -> str:
        if len(self._html_sequence) > 1:
            return self._html_sequence.pop(0)
        return self._html_sequence[0]

    async def evaluate(self, expression: str) -> str:
        if "readyState" in expression:
            return "complete"
        return ""

    async def wait_for_timeout(self, timeout_ms: int) -> None:
        self.wait_calls.append(timeout_ms)


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
    scenario = json.loads((tmp_path / "hcap-test" / "scenario.json").read_text(encoding="utf-8"))
    assert scenario["asset_id"] == "hcap-test"
    assert scenario["capture_scope"] == "selected_steps"
    assert scenario["asset_status"] == "draft"
    assert scenario["sensitivity"] == "local-only"
    assert scenario["source"]["recording_id"] == "session-1"
    assert scenario["source"]["capture_trigger"] == "selected_steps"
    assert scenario["step_checkpoints"] == [
        {"step_index": 2, "checkpoint_path": "steps/002/checkpoint.json"}
    ]
    catalog = build_harness_catalog(tmp_path)
    assert catalog["captures"][0]["capture_scope"] == "selected_steps"
    assert catalog["captures"][0]["asset_status"] == "draft"
    assert catalog["captures"][0]["sensitivity"] == "local-only"


@pytest.mark.asyncio
async def test_successful_changed_step_retries_until_after_html_is_non_empty(tmp_path: Path):
    state = HarnessCaptureSessionState(
        capture_id="hcap-test",
        session_id="session-1",
        capture_scope="full_sop",
    )
    store = HarnessAssetStore(tmp_path)
    after_page = _EventuallyReadyPage(
        url="https://example.test/project",
        title="Project",
        html_sequence=["", "<html><body><main>Project ready</main></body></html>"],
    )

    checkpoint = await capture_step_checkpoint(
        state,
        store,
        step_index=1,
        step_id="step-1",
        step_intent="Click through to the project page",
        recording_mode="manual",
        before_page=_FakePage(
            url="https://example.test/list",
            title="List",
            html="<html><body><a>Project</a></body></html>",
        ),
        after_page=after_page,
        trace_events=[{"trace_id": "trace-1", "action": "navigate_click"}],
        runtime_status="success",
    )

    step_dir = tmp_path / "hcap-test" / "steps" / "001"
    assert checkpoint is not None
    assert after_page.wait_calls
    assert (step_dir / "after.html").read_text(encoding="utf-8") == (
        "<html><body><main>Project ready</main></body></html>"
    )


@pytest.mark.asyncio
async def test_successful_navigation_waits_for_stable_after_html_and_records_quality(tmp_path: Path):
    state = HarnessCaptureSessionState(
        capture_id="hcap-test",
        session_id="session-1",
        capture_scope="full_sop",
    )
    store = HarnessAssetStore(tmp_path)
    rich_html = "<html><head><title>Project</title></head><body><main>" + ("Project ready " * 40) + "</main></body></html>"
    after_page = _StabilizingPage(
        url="https://example.test/project",
        title_sequence=["", "Project", "Project"],
        html_sequence=[
            "<html><body></body></html>",
            rich_html,
            rich_html,
        ],
    )

    checkpoint = await capture_step_checkpoint(
        state,
        store,
        step_index=1,
        step_id="step-1",
        step_intent="Click through to the project page",
        recording_mode="manual",
        before_page=_FakePage(
            url="https://example.test/list",
            title="List",
            html="<html><body><a>Project</a></body></html>",
        ),
        after_page=after_page,
        trace_events=[{"trace_id": "trace-1", "action": "navigate_click"}],
        runtime_status="success",
    )

    step_dir = tmp_path / "hcap-test" / "steps" / "001"
    checkpoint_json = json.loads((step_dir / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint is not None
    assert after_page.wait_calls
    assert (step_dir / "after.html").read_text(encoding="utf-8") == rich_html
    assert checkpoint.after is not None
    assert checkpoint.after.capture_quality["status"] == "stable"
    assert checkpoint.after.capture_quality["attempts"] == 3
    assert checkpoint.after.capture_quality["title_present"] is True
    assert checkpoint_json["after"]["capture_quality"]["status"] == "stable"


@pytest.mark.asyncio
async def test_scenario_manifest_accumulates_captured_step_refs(tmp_path: Path):
    state = HarnessCaptureSessionState(
        capture_id="hcap-test",
        session_id="session-1",
        capture_scope="full_sop",
    )
    store = HarnessAssetStore(tmp_path)

    for step_index in (1, 2):
        await capture_step_checkpoint(
            state,
            store,
            step_index=step_index,
            step_id=f"step-{step_index}",
            step_intent=f"Capture step {step_index}",
            recording_mode="natural_language",
            before_page=_FakePage(
                url=f"https://example.test/{step_index}",
                title=f"Before {step_index}",
                html=f"<html><body>Before {step_index}</body></html>",
            ),
            after_page=_FakePage(
                url=f"https://example.test/{step_index}/done",
                title=f"After {step_index}",
                html=f"<html><body>After {step_index}</body></html>",
            ),
            trace_events=[{"trace_id": f"trace-{step_index}", "action": "click"}],
            runtime_status="success",
        )

    scenario = json.loads((tmp_path / "hcap-test" / "scenario.json").read_text(encoding="utf-8"))

    assert scenario["capture_scope"] == "full_sop"
    assert scenario["step_checkpoints"] == [
        {"step_index": 1, "checkpoint_path": "steps/001/checkpoint.json"},
        {"step_index": 2, "checkpoint_path": "steps/002/checkpoint.json"},
    ]


@pytest.mark.asyncio
async def test_invalid_existing_scenario_manifest_blocks_checkpoint_capture(tmp_path: Path):
    state = HarnessCaptureSessionState(
        capture_id="hcap-test",
        session_id="session-1",
        capture_scope="full_sop",
    )
    store = HarnessAssetStore(tmp_path)
    capture_dir = tmp_path / "hcap-test"
    capture_dir.mkdir()
    scenario_path = capture_dir / "scenario.json"
    scenario_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid harness scenario manifest"):
        await capture_step_checkpoint(
            state,
            store,
            step_index=1,
            step_id="step-1",
            step_intent="Capture should not overwrite invalid lifecycle metadata",
            recording_mode="natural_language",
            before_page=_FakePage(
                url="https://example.test/bad",
                title="Bad",
                html="<html><body>Bad</body></html>",
            ),
            after_page=_FakePage(
                url="https://example.test/bad/done",
                title="Bad Done",
                html="<html><body>Bad Done</body></html>",
            ),
            trace_events=[{"trace_id": "trace-1", "action": "click"}],
            runtime_status="success",
        )

    assert scenario_path.read_text(encoding="utf-8") == "{not-json"
    assert not (capture_dir / "steps").exists()


@pytest.mark.asyncio
async def test_scenario_manifest_preserves_existing_lifecycle_metadata(tmp_path: Path):
    state = HarnessCaptureSessionState(
        capture_id="hcap-test",
        session_id="session-1",
        capture_scope="full_sop",
    )
    store = HarnessAssetStore(tmp_path)
    capture_dir = tmp_path / "hcap-test"
    capture_dir.mkdir()
    (capture_dir / "scenario.json").write_text(
        json.dumps(
            {
                "schema_version": "rpa-harness-scenario-v0",
                "asset_id": "hcap-test",
                "capture_scope": "full_sop",
                "sop_intent": "Reviewed SOP",
                "source": {
                    "recording_id": "recording-reviewed",
                    "captured_at": "2026-05-17T10:00:00",
                    "capture_mode": "harness",
                    "capture_trigger": "manual-review",
                },
                "asset_status": "active",
                "sensitivity": "repo-safe",
                "page_patterns": ["reviewed-pattern"],
                "step_checkpoints": [{"step_index": 1, "checkpoint_path": "steps/001/checkpoint.json"}],
            }
        ),
        encoding="utf-8",
    )

    await capture_step_checkpoint(
        state,
        store,
        step_index=2,
        step_id="step-2",
        step_intent="Capture reviewed step",
        recording_mode="natural_language",
        before_page=_FakePage(
            url="https://example.test/review",
            title="Review",
            html="<html><body>Review</body></html>",
        ),
        after_page=_FakePage(
            url="https://example.test/review/done",
            title="Review Done",
            html="<html><body>Review Done</body></html>",
        ),
        trace_events=[{"trace_id": "trace-2", "action": "click"}],
        runtime_status="success",
    )

    scenario = json.loads((capture_dir / "scenario.json").read_text(encoding="utf-8"))

    assert scenario["sop_intent"] == "Reviewed SOP"
    assert scenario["source"]["recording_id"] == "recording-reviewed"
    assert scenario["asset_status"] == "active"
    assert scenario["sensitivity"] == "repo-safe"
    assert scenario["page_patterns"] == ["reviewed-pattern"]
    assert scenario["step_checkpoints"] == [
        {"step_index": 1, "checkpoint_path": "steps/001/checkpoint.json"},
        {"step_index": 2, "checkpoint_path": "steps/002/checkpoint.json"},
    ]


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

