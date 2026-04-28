import importlib
import sys
import types
from datetime import datetime, timezone

import pytest

from backend.rpa.trace_models import (
    RPAAcceptedTrace,
    RPAPageState,
    RPATraceDiagnostic,
    RPATraceType,
)
from backend.rpa.trace_timeline import build_trace_timeline_items


def _import_route_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delitem(sys.modules, "backend.route.rpa", raising=False)

    cdp_module = types.ModuleType("backend.rpa.cdp_connector")
    cdp_module.get_cdp_connector = lambda: None
    monkeypatch.setitem(sys.modules, "backend.rpa.cdp_connector", cdp_module)

    assistant_module = types.ModuleType("backend.rpa.assistant")

    class RPAAssistant:
        pass

    class RPAReActAgent:
        pass

    assistant_module.RPAAssistant = RPAAssistant
    assistant_module.RPAReActAgent = RPAReActAgent
    assistant_module._active_agents = {}
    monkeypatch.setitem(sys.modules, "backend.rpa.assistant", assistant_module)

    runtime_module = types.ModuleType("backend.rpa.recording_runtime_agent")

    class RecordingRuntimeAgent:
        pass

    class RecordingAgentResult:
        pass

    runtime_module.RecordingRuntimeAgent = RecordingRuntimeAgent
    runtime_module.RecordingAgentResult = RecordingAgentResult
    monkeypatch.setitem(sys.modules, "backend.rpa.recording_runtime_agent", runtime_module)

    screencast_module = types.ModuleType("backend.rpa.screencast")

    class SessionScreencastController:
        pass

    screencast_module.SessionScreencastController = SessionScreencastController
    monkeypatch.setitem(sys.modules, "backend.rpa.screencast", screencast_module)

    vault_module = types.ModuleType("backend.credential.vault")

    async def inject_credentials(*args, **kwargs):
        return {}

    vault_module.inject_credentials = inject_credentials
    monkeypatch.setitem(sys.modules, "backend.credential.vault", vault_module)

    playwright_module = types.ModuleType("playwright")
    async_api_module = types.ModuleType("playwright.async_api")
    async_api_module.Page = object
    async_api_module.BrowserContext = object
    async_api_module.Browser = object
    async_api_module.Playwright = object
    async_api_module.async_playwright = lambda: None
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api_module)

    sse_starlette_module = types.ModuleType("sse_starlette")
    sse_module = types.ModuleType("sse_starlette.sse")

    class EventSourceResponse:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    sse_module.EventSourceResponse = EventSourceResponse
    monkeypatch.setitem(sys.modules, "sse_starlette", sse_starlette_module)
    monkeypatch.setitem(sys.modules, "sse_starlette.sse", sse_module)
    return importlib.import_module("backend.route.rpa")


class FakeSession:
    def __init__(self, *, id: str, user_id: str):
        self.id = id
        self.user_id = user_id
        self.traces = []
        self.trace_diagnostics = []


def test_trace_timeline_projects_manual_and_ai_traces_in_order():
    traces = [
        RPAAcceptedTrace(
            trace_id="trace-manual",
            trace_type=RPATraceType.MANUAL_ACTION,
            source="manual",
            action="click",
            description="Click Save",
            after_page=RPAPageState(url="https://example.test/edit", title="Editor"),
            locator_candidates=[
                {
                    "locator": {"method": "role", "role": "button", "name": "Save"},
                    "selected": True,
                }
            ],
            signals={"recording": {"event_timestamp_ms": 1000}},
        ),
        RPAAcceptedTrace(
            trace_id="trace-ai",
            trace_type=RPATraceType.AI_OPERATION,
            source="ai",
            user_instruction="Extract rows",
            description="Extract rows",
            signals={"recording": {"event_timestamp_ms": 2000}},
        ),
    ]

    items = build_trace_timeline_items(traces=traces, diagnostics=[])

    assert [item.trace_id for item in items] == ["trace-manual", "trace-ai"]
    assert items[0].kind == "trace"
    assert items[0].action == "click"
    assert items[0].title == "Click Save"
    assert items[0].url == "https://example.test/edit"
    assert items[0].locator["name"] == "Save"
    assert items[0].deletable is True
    assert items[0].editable is True
    assert items[1].source == "ai"
    assert items[1].editable is False


def test_trace_timeline_projects_diagnostics_without_accepting_them():
    diagnostic = RPATraceDiagnostic(
        diagnostic_id="diag-1",
        trace_id="trace-failed",
        source="manual",
        message="accepted interactive action requires canonical target",
        raw={
            "action": "click",
            "url": "https://example.test/broken",
            "locator_candidates": [{"locator": {"method": "css", "value": ".x"}}],
        },
    )

    items = build_trace_timeline_items(traces=[], diagnostics=[diagnostic])

    assert len(items) == 1
    assert items[0].kind == "diagnostic"
    assert items[0].diagnostic_id == "diag-1"
    assert items[0].trace_id == "trace-failed"
    assert items[0].action == "click"
    assert items[0].summary == "accepted interactive action requires canonical target"
    assert items[0].locator["value"] == ".x"
    assert items[0].deletable is True
    assert items[0].editable is False
    assert items[0].raw_diagnostic["diagnostic_id"] == "diag-1"


def test_trace_timeline_order_prefers_recording_timestamp_then_started_at_then_input_order():
    no_time_a = RPAAcceptedTrace(
        trace_id="trace-no-time-a",
        trace_type=RPATraceType.AI_OPERATION,
        source="ai",
        description="no time a",
    )
    no_time_a.started_at = None
    no_time_b = RPAAcceptedTrace(
        trace_id="trace-no-time-b",
        trace_type=RPATraceType.AI_OPERATION,
        source="ai",
        description="no time b",
    )
    no_time_b.started_at = None

    traces = [
        RPAAcceptedTrace(
            trace_id="trace-started-late",
            trace_type=RPATraceType.AI_OPERATION,
            source="ai",
            description="started late",
            started_at=datetime.fromtimestamp(20, tz=timezone.utc),
        ),
        RPAAcceptedTrace(
            trace_id="trace-recording",
            trace_type=RPATraceType.MANUAL_ACTION,
            source="manual",
            action="click",
            description="recording time wins",
            signals={"recording": {"event_timestamp_ms": 500}},
            started_at=datetime.fromtimestamp(30, tz=timezone.utc),
        ),
        RPAAcceptedTrace(
            trace_id="trace-started-early",
            trace_type=RPATraceType.AI_OPERATION,
            source="ai",
            description="started early",
            started_at=datetime.fromtimestamp(10, tz=timezone.utc),
        ),
        no_time_a,
        no_time_b,
    ]

    items = build_trace_timeline_items(traces=traces, diagnostics=[])

    assert [item.trace_id for item in items] == [
        "trace-recording",
        "trace-started-early",
        "trace-started-late",
        "trace-no-time-a",
        "trace-no-time-b",
    ]


@pytest.mark.asyncio
async def test_get_session_includes_trace_timeline_projection(monkeypatch):
    route_module = _import_route_module(monkeypatch)
    manager = route_module.rpa_manager
    session = FakeSession(id="route-session-timeline", user_id="u1")
    session.traces.append(
        RPAAcceptedTrace(
            trace_id="trace-ai",
            trace_type=RPATraceType.AI_OPERATION,
            source="ai",
            user_instruction="Extract rows",
            description="Extract rows",
        )
    )
    manager.sessions[session.id] = session

    try:
        user = type("User", (), {"id": "u1"})()
        response = await route_module.get_rpa_session(session.id, user)

        assert response["status"] == "success"
        assert response["session"]["id"] == session.id
        assert response["session"]["timeline"][0]["trace_id"] == "trace-ai"
        assert response["timeline"][0]["trace_id"] == "trace-ai"
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_get_session_timeline_returns_projection_only(monkeypatch):
    route_module = _import_route_module(monkeypatch)
    manager = route_module.rpa_manager
    session = FakeSession(id="route-timeline", user_id="u1")
    session.trace_diagnostics.append(
        RPATraceDiagnostic(
            diagnostic_id="diag-1",
            trace_id="trace-failed",
            source="ai",
            message="operation failed",
            raw={"action": "ai_operation"},
        )
    )
    manager.sessions[session.id] = session

    try:
        user = type("User", (), {"id": "u1"})()
        response = await route_module.get_session_timeline(session.id, user)

        assert set(response) == {"timeline"}
        assert len(response["timeline"]) == 1
        item = response["timeline"][0]
        assert item["kind"] == "diagnostic"
        assert item["diagnostic_id"] == "diag-1"
        assert item["trace_id"] == "trace-failed"
        assert item["action"] == "ai_operation"
        assert item["title"] == "operation failed"
        assert item["editable"] is False
        assert item["deletable"] is True
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_delete_trace_diagnostic_endpoint_removes_diagnostic(monkeypatch):
    route_module = _import_route_module(monkeypatch)
    manager = route_module.rpa_manager
    session = FakeSession(id="route-delete-diagnostic", user_id="u1")
    session.trace_diagnostics.append(
        RPATraceDiagnostic(
            diagnostic_id="diag-delete",
            trace_id="trace-failed",
            source="ai",
            message="operation failed",
        )
    )
    manager.sessions[session.id] = session

    try:
        user = type("User", (), {"id": "u1"})()
        response = await route_module.delete_trace_diagnostic(session.id, "diag-delete", user)

        assert response == {"status": "success"}
        assert session.trace_diagnostics == []
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_delete_trace_endpoint_removes_trace_without_step_index(monkeypatch):
    route_module = _import_route_module(monkeypatch)
    manager = route_module.rpa_manager
    session = FakeSession(id="route-delete-direct-trace", user_id="u1")
    session.traces.append(
        RPAAcceptedTrace(
            trace_id="trace-delete",
            trace_type=RPATraceType.AI_OPERATION,
            source="ai",
            user_instruction="Extract rows",
            description="Extract rows",
        )
    )
    manager.sessions[session.id] = session

    try:
        user = type("User", (), {"id": "u1"})()
        response = await route_module.delete_trace(session.id, "trace-delete", user)

        assert response == {"status": "success"}
        assert session.traces == []
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_promote_trace_locator_candidate_updates_selected_candidate(monkeypatch):
    route_module = _import_route_module(monkeypatch)
    manager = route_module.rpa_manager
    session = FakeSession(id="route-promote-trace-locator", user_id="u1")
    session.traces.append(
        RPAAcceptedTrace(
            trace_id="trace-1",
            trace_type=RPATraceType.MANUAL_ACTION,
            source="manual",
            action="click",
            description="Click Save",
            locator_candidates=[
                {"kind": "css", "locator": {"method": "css", "value": ".old"}, "selected": True},
                {
                    "kind": "role",
                    "locator": {"method": "role", "role": "button", "name": "Save"},
                    "selected": False,
                    "strict_match_count": 1,
                },
            ],
            validation={"status": "fallback"},
        )
    )
    manager.sessions[session.id] = session

    try:
        user = type("User", (), {"id": "u1"})()
        response = await route_module.promote_trace_locator(
            session.id,
            "trace-1",
            route_module.PromoteLocatorRequest(candidate_index=1),
            user,
        )

        assert response["status"] == "success"
        candidates = response["trace"]["locator_candidates"]
        assert candidates[0]["selected"] is False
        assert candidates[0]["locator"]["value"] == ".old"
        assert candidates[1]["selected"] is True
        assert candidates[1]["kind"] == "role"
        assert session.traces[0].validation["selected_candidate_index"] == 1
        assert session.traces[0].validation["status"] == "ok"
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_promote_trace_locator_candidate_rejects_invalid_candidate(monkeypatch):
    route_module = _import_route_module(monkeypatch)
    manager = route_module.rpa_manager
    session = FakeSession(id="route-promote-trace-locator-invalid", user_id="u1")
    session.traces.append(
        RPAAcceptedTrace(
            trace_id="trace-1",
            trace_type=RPATraceType.MANUAL_ACTION,
            source="manual",
            action="click",
            locator_candidates=[
                {"locator": {"method": "css", "value": ".old"}, "selected": True},
            ],
        )
    )
    manager.sessions[session.id] = session

    try:
        user = type("User", (), {"id": "u1"})()
        with pytest.raises(route_module.HTTPException) as exc_info:
            await route_module.promote_trace_locator(
                session.id,
                "trace-1",
                route_module.PromoteLocatorRequest(candidate_index=2),
                user,
            )

        assert exc_info.value.status_code == 400
        assert session.traces[0].locator_candidates == [
            {"locator": {"method": "css", "value": ".old"}, "selected": True},
        ]
    finally:
        manager.sessions.pop(session.id, None)
