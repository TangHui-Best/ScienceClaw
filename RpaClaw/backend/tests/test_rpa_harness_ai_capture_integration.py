import json
import asyncio
from pathlib import Path
import sys
import types

import pytest


def _install_langchain_stubs():
    langchain_openai = types.ModuleType("langchain_openai")

    class ChatOpenAI:
        def __init__(self, *args, **kwargs):
            pass

    langchain_openai.ChatOpenAI = ChatOpenAI
    sys.modules.setdefault("langchain_openai", langchain_openai)

    chat_models = types.ModuleType("langchain_openai.chat_models")
    chat_models_base = types.ModuleType("langchain_openai.chat_models.base")
    chat_models_base._convert_dict_to_message = lambda value, *args, **kwargs: value
    chat_models_base._convert_message_to_dict = lambda value, *args, **kwargs: {}
    chat_models_base._convert_delta_to_message_chunk = (
        lambda value, default_class: default_class()
    )
    sys.modules.setdefault("langchain_openai.chat_models", chat_models)
    sys.modules.setdefault("langchain_openai.chat_models.base", chat_models_base)

    langchain_core = types.ModuleType("langchain_core")
    language_models = types.ModuleType("langchain_core.language_models")

    class BaseChatModel:
        pass

    language_models.BaseChatModel = BaseChatModel
    messages = types.ModuleType("langchain_core.messages")

    class BaseMessage:
        pass

    class AIMessage(BaseMessage):
        pass

    class AIMessageChunk(BaseMessage):
        pass

    class HumanMessage(BaseMessage):
        pass

    class SystemMessage(BaseMessage):
        pass

    class ToolMessage(BaseMessage):
        pass

    messages.AIMessage = AIMessage
    messages.AIMessageChunk = AIMessageChunk
    messages.BaseMessage = BaseMessage
    messages.HumanMessage = HumanMessage
    messages.SystemMessage = SystemMessage
    messages.ToolMessage = ToolMessage
    sys.modules.setdefault("langchain_core", langchain_core)
    sys.modules.setdefault("langchain_core.language_models", language_models)
    sys.modules.setdefault("langchain_core.messages", messages)


_install_langchain_stubs()

import backend.route.rpa as ROUTE_MODULE
from backend.rpa.manager import RPASession
from backend.rpa.recording_runtime_agent import RecordingAgentResult
from backend.rpa.trace_models import RPAAcceptedTrace, RPAAIExecution, RPAPageState, RPATraceType


class _MutableFakePage:
    def __init__(self) -> None:
        self.url = "https://example.test/search"
        self._title = "Search"
        self._html = "<html><body><a>ScienceClaw</a></body></html>"
        self.content_calls = 0
        self.goto_calls: list[tuple[str, str | None]] = []

    async def title(self) -> str:
        return self._title

    async def content(self) -> str:
        self.content_calls += 1
        return self._html

    async def goto(self, url: str) -> None:
        self.goto_calls.append((url, None))
        self.url = url
        self._title = "Trending" if url.endswith("/trending") else "Page"
        self._html = f"<html><body><main>{url}</main></body></html>"

    async def wait_for_load_state(self, state: str) -> None:
        return None

    def move_to_project(self) -> None:
        self.url = "https://example.test/project/scienceclaw"
        self._title = "ScienceClaw"
        self._html = "<html><body><h1>ScienceClaw</h1></body></html>"


async def _drain_sse(response) -> list[dict]:
    events = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, dict):
            events.append(chunk)
    return events


@pytest.fixture(autouse=True)
def _stub_user_model_resolution(monkeypatch):
    async def fake_resolve_user_model_config(*args, **kwargs):
        return None

    monkeypatch.setattr(ROUTE_MODULE, "_resolve_user_model_config", fake_resolve_user_model_config)


@pytest.mark.asyncio
async def test_ai_chat_capture_writes_real_before_after_checkpoint(monkeypatch, tmp_path: Path):
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="harness-ai-chat", user_id="u1", sandbox_session_id="sandbox")
    manager.sessions[session.id] = session
    page = _MutableFakePage()

    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_harness_capture_enabled", True)
    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_harness_assets_dir", str(tmp_path))
    manager.start_harness_capture(session.id, capture_scope="full_sop", enabled=True)

    class FakeRecordingRuntimeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, **kwargs):
            before = RPAPageState(url=page.url, title=await page.title())
            page.move_to_project()
            trace = RPAAcceptedTrace(
                trace_id="trace-ai-1",
                trace_type=RPATraceType.AI_OPERATION,
                source="ai",
                user_instruction="Click ScienceClaw",
                description="Click ScienceClaw",
                before_page=before,
                after_page=RPAPageState(url=page.url, title=await page.title()),
                ai_execution=RPAAIExecution(code="async def run(page, results):\n    return {'ok': True}"),
                signals={
                    "target_evidence": {
                        "role": "link",
                        "text": "ScienceClaw",
                    }
                },
            )
            return RecordingAgentResult(
                success=True,
                trace=trace,
                message="Recording command completed.",
            )

    monkeypatch.setattr(ROUTE_MODULE, "RecordingRuntimeAgent", FakeRecordingRuntimeAgent)
    monkeypatch.setattr(manager, "get_page", lambda target_session_id: page if target_session_id == session.id else None)

    try:
        response = await ROUTE_MODULE.chat_with_assistant(
            session.id,
            ROUTE_MODULE.ChatRequest(message="Click ScienceClaw"),
            type("User", (), {"id": "u1"})(),
        )
        await _drain_sse(response)

        step_dir = tmp_path / manager.get_harness_capture_session(session.id).capture_id / "steps" / "001"
        checkpoint = json.loads((step_dir / "checkpoint.json").read_text(encoding="utf-8"))
        assert (step_dir / "before.html").read_text(encoding="utf-8") == "<html><body><a>ScienceClaw</a></body></html>"
        assert (step_dir / "after.html").read_text(encoding="utf-8") == "<html><body><h1>ScienceClaw</h1></body></html>"
        assert checkpoint["step_intent"] == "Click ScienceClaw"
        assert checkpoint["action"]["trace_events_path"] == "steps/001/trace_events.json"
        assert json.loads((step_dir / "trace_events.json").read_text(encoding="utf-8"))[0]["trace_id"] == "trace-ai-1"
        expected = json.loads((step_dir / "expected.json").read_text(encoding="utf-8"))
        assert expected["action_signals"]["expected_action_type"] == "ai_operation"
        assert expected["action_signals"]["target_role"] == "link"
        assert expected["action_signals"]["target_text_contains"] == "ScienceClaw"
        assert expected["snapshot_signals"]["must_contain_text"] == ["ScienceClaw"]
    finally:
        manager._harness_capture_sessions.pop(session.id, None)
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_full_sop_capture_preserves_delayed_download_signal_in_core_trace(monkeypatch, tmp_path: Path):
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="harness-ai-delayed-download", user_id="u1", sandbox_session_id="sandbox")
    manager.sessions[session.id] = session
    page = _MutableFakePage()
    page._html = "<html><body><table><tbody><tr><td>first-row.xlsx</td></tr></tbody></table></body></html>"

    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_harness_capture_enabled", True)
    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_harness_assets_dir", str(tmp_path))
    manager.start_harness_capture(session.id, capture_scope="full_sop", enabled=True)

    class FakeRecordingRuntimeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, **kwargs):
            before = RPAPageState(url=page.url, title=await page.title())

            async def enqueue_download():
                await asyncio.sleep(0.05)
                session.pending_download_events.append(
                    {
                        "filename": "first-row.xlsx",
                        "url": "https://example.test/exportQuery",
                        "tab_id": "tab-export",
                    }
                )

            asyncio.create_task(enqueue_download())
            trace = RPAAcceptedTrace(
                trace_id="trace-ai-download",
                trace_type=RPATraceType.AI_OPERATION,
                source="ai",
                user_instruction="点击列表中第一行的文件名称",
                description="Click the file name link in the first row of the export list table",
                before_page=before,
                after_page=RPAPageState(url=page.url, title=await page.title()),
                ai_execution=RPAAIExecution(
                    code=(
                        "async def run(page, results):\n"
                        "    await page.locator('tbody tr').first.locator('td[data-colid=\"col_25\"] a').click()\n"
                        "    return {'action_performed': True}"
                    )
                ),
            )
            return RecordingAgentResult(
                success=True,
                trace=trace,
                message="Recording command completed.",
            )

    monkeypatch.setattr(ROUTE_MODULE, "RecordingRuntimeAgent", FakeRecordingRuntimeAgent)
    monkeypatch.setattr(manager, "get_page", lambda target_session_id: page if target_session_id == session.id else None)

    try:
        response = await ROUTE_MODULE.chat_with_assistant(
            session.id,
            ROUTE_MODULE.ChatRequest(message="点击列表中第一行的文件名称"),
            type("User", (), {"id": "u1"})(),
        )
        await _drain_sse(response)

        assert session.traces[0].signals["download"]["filename"] == "first-row.xlsx"
        step_dir = tmp_path / manager.get_harness_capture_session(session.id).capture_id / "steps" / "001"
        trace_events = json.loads((step_dir / "trace_events.json").read_text(encoding="utf-8"))
        assert trace_events[0]["signals"]["download"]["filename"] == "first-row.xlsx"
        assert trace_events[0]["signals"]["download"]["tab_id"] == "tab-export"
    finally:
        manager._harness_capture_sessions.pop(session.id, None)
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_ai_chat_without_capture_session_does_not_read_html(monkeypatch):
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="harness-ai-chat-disabled", user_id="u1", sandbox_session_id="sandbox")
    manager.sessions[session.id] = session
    page = _MutableFakePage()

    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_harness_capture_enabled", False)

    class FakeRecordingRuntimeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, **kwargs):
            return RecordingAgentResult(
                success=False,
                message="Recording command failed.",
            )

    monkeypatch.setattr(ROUTE_MODULE, "RecordingRuntimeAgent", FakeRecordingRuntimeAgent)
    monkeypatch.setattr(manager, "get_page", lambda target_session_id: page if target_session_id == session.id else None)

    try:
        response = await ROUTE_MODULE.chat_with_assistant(
            session.id,
            ROUTE_MODULE.ChatRequest(message="Click ScienceClaw"),
            type("User", (), {"id": "u1"})(),
        )
        await _drain_sse(response)

        assert page.content_calls == 0
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_ai_chat_disabled_with_existing_capture_session_does_not_read_html(monkeypatch, tmp_path: Path):
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="harness-ai-chat-stale-disabled", user_id="u1", sandbox_session_id="sandbox")
    manager.sessions[session.id] = session
    page = _MutableFakePage()

    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_harness_assets_dir", str(tmp_path))
    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_harness_capture_enabled", True)
    manager.start_harness_capture(session.id, capture_scope="full_sop", enabled=True)
    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_harness_capture_enabled", False)

    class FakeRecordingRuntimeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, **kwargs):
            page.move_to_project()
            return RecordingAgentResult(
                success=True,
                trace=None,
                message="Recording command completed.",
            )

    monkeypatch.setattr(ROUTE_MODULE, "RecordingRuntimeAgent", FakeRecordingRuntimeAgent)
    monkeypatch.setattr(manager, "get_page", lambda target_session_id: page if target_session_id == session.id else None)

    try:
        response = await ROUTE_MODULE.chat_with_assistant(
            session.id,
            ROUTE_MODULE.ChatRequest(message="Click ScienceClaw"),
            type("User", (), {"id": "u1"})(),
        )
        await _drain_sse(response)

        assert page.content_calls == 0
        assert not any(tmp_path.iterdir())
    finally:
        manager._harness_capture_sessions.pop(session.id, None)
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_ai_chat_capture_failed_step_writes_failure_evidence(monkeypatch, tmp_path: Path):
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="harness-ai-chat-failed", user_id="u1", sandbox_session_id="sandbox")
    manager.sessions[session.id] = session
    page = _MutableFakePage()

    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_harness_capture_enabled", True)
    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_harness_assets_dir", str(tmp_path))
    manager.start_harness_capture(session.id, capture_scope="full_sop", enabled=True)

    class FakeRecordingRuntimeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, **kwargs):
            return RecordingAgentResult(
                success=False,
                trace=None,
                message="Unable to click ScienceClaw.",
            )

    monkeypatch.setattr(ROUTE_MODULE, "RecordingRuntimeAgent", FakeRecordingRuntimeAgent)
    monkeypatch.setattr(manager, "get_page", lambda target_session_id: page if target_session_id == session.id else None)

    try:
        response = await ROUTE_MODULE.chat_with_assistant(
            session.id,
            ROUTE_MODULE.ChatRequest(message="Click ScienceClaw"),
            type("User", (), {"id": "u1"})(),
        )
        await _drain_sse(response)

        step_dir = tmp_path / manager.get_harness_capture_session(session.id).capture_id / "steps" / "001"
        checkpoint = json.loads((step_dir / "checkpoint.json").read_text(encoding="utf-8"))
        failure = json.loads((step_dir / "failure.json").read_text(encoding="utf-8"))
        assert (step_dir / "before.html").exists()
        assert not (step_dir / "after.html").exists()
        assert checkpoint["runtime_result"]["status"] == "failed"
        assert checkpoint["failure_path"] == "steps/001/failure.json"
        assert failure["error"] == "Unable to click ScienceClaw."
    finally:
        manager._harness_capture_sessions.pop(session.id, None)
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_selected_next_ai_step_survives_manual_trace_interleaving(monkeypatch, tmp_path: Path):
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="harness-ai-chat-selected-next", user_id="u1", sandbox_session_id="sandbox")
    session.traces.append(
        RPAAcceptedTrace(
            trace_id="trace-manual-before-selection",
            trace_type=RPATraceType.MANUAL_ACTION,
            source="manual",
            action="click",
            description="Existing manual trace",
        )
    )
    manager.sessions[session.id] = session
    page = _MutableFakePage()

    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_harness_capture_enabled", True)
    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_harness_assets_dir", str(tmp_path))
    manager.start_harness_capture(session.id, capture_scope="selected_steps", enabled=True)
    manager.mark_harness_next_natural_language_step_selected(session.id)
    session.traces.append(
        RPAAcceptedTrace(
            trace_id="trace-manual-after-selection",
            trace_type=RPATraceType.MANUAL_ACTION,
            source="manual",
            action="fill",
            description="Manual trace after selecting next AI step",
        )
    )

    class FakeRecordingRuntimeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, **kwargs):
            page.move_to_project()
            trace = RPAAcceptedTrace(
                trace_id="trace-ai-after-manual",
                trace_type=RPATraceType.AI_OPERATION,
                source="ai",
                user_instruction="Click ScienceClaw",
                description="Click ScienceClaw",
                before_page=RPAPageState(url="https://example.test/search", title="Search"),
                after_page=RPAPageState(url=page.url, title=await page.title()),
                ai_execution=RPAAIExecution(code="async def run(page, results):\n    return {'ok': True}"),
                signals={"target_evidence": {"role": "link", "text": "ScienceClaw"}},
            )
            return RecordingAgentResult(success=True, trace=trace, message="Recording command completed.")

    monkeypatch.setattr(ROUTE_MODULE, "RecordingRuntimeAgent", FakeRecordingRuntimeAgent)
    monkeypatch.setattr(manager, "get_page", lambda target_session_id: page if target_session_id == session.id else None)

    try:
        response = await ROUTE_MODULE.chat_with_assistant(
            session.id,
            ROUTE_MODULE.ChatRequest(message="Click ScienceClaw"),
            type("User", (), {"id": "u1"})(),
        )
        events = await _drain_sse(response)

        capture_state = manager.get_harness_capture_session(session.id)
        step_dir = tmp_path / capture_state.capture_id / "steps" / "003"
        assert (step_dir / "checkpoint.json").exists()
        assert not (tmp_path / capture_state.capture_id / "steps" / "002" / "checkpoint.json").exists()
        checkpoint = json.loads((step_dir / "checkpoint.json").read_text(encoding="utf-8"))
        assert checkpoint["step_id"] == "trace-ai-after-manual"
        assert capture_state.pending_natural_language_step_captures == 0
        step_done = next(event for event in events if event["event"] == "agent_step_done")
        step_done_data = json.loads(step_done["data"])
        assert step_done_data["capture"]["capture_scope"] == "selected_steps"
        assert step_done_data["capture"]["pending_natural_language_step_captures"] == 0
    finally:
        manager._harness_capture_sessions.pop(session.id, None)
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_full_sop_capture_records_entry_navigation_checkpoint(monkeypatch, tmp_path: Path):
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(
        id="harness-entry-navigation",
        user_id="u1",
        sandbox_session_id="sandbox",
        active_tab_id="tab-1",
    )
    manager.sessions[session.id] = session
    page = _MutableFakePage()
    page.url = "about:blank"
    page._title = ""
    page._html = "<html><body>blank</body></html>"
    manager._tabs[session.id] = {"tab-1": page}

    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_harness_capture_enabled", True)
    monkeypatch.setattr(ROUTE_MODULE.settings, "rpa_harness_assets_dir", str(tmp_path))
    manager.start_harness_capture(session.id, capture_scope="full_sop", enabled=True)

    try:
        await manager.navigate_active_tab(session.id, "github.com/trending")

        capture_state = manager.get_harness_capture_session(session.id)
        step_dir = tmp_path / capture_state.capture_id / "steps" / "001"
        checkpoint = json.loads((step_dir / "checkpoint.json").read_text(encoding="utf-8"))
        traces = json.loads((step_dir / "trace_events.json").read_text(encoding="utf-8"))
        assert checkpoint["recording_mode"] == "manual"
        assert checkpoint["step_intent"] == "Navigate to https://github.com/trending"
        assert checkpoint["before"]["url"] == "about:blank"
        assert checkpoint["after"]["url"] == "https://github.com/trending"
        assert traces[0]["trace_type"] == "navigation"
        assert traces[0]["action"] == "navigate"
        assert traces[0]["after_page"]["url"] == "https://github.com/trending"
        assert session.traces[0].trace_id == traces[0]["trace_id"]
    finally:
        manager._harness_capture_sessions.pop(session.id, None)
        manager._tabs.pop(session.id, None)
        manager.sessions.pop(session.id, None)
