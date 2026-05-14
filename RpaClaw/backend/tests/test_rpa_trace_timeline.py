from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime

import pytest

from backend.rpa.trace_models import RPAAcceptedTrace, RPAPageState, RPATraceDiagnostic, RPATraceType
from backend.rpa.trace_timeline import build_trace_timeline_items


def _load_route_module():
    if "backend.route.rpa" in sys.modules:
        return sys.modules["backend.route.rpa"]

    langchain_openai = types.ModuleType("langchain_openai")

    class ChatOpenAI:
        def __init__(self, *args, **kwargs):
            pass

    langchain_openai.ChatOpenAI = ChatOpenAI
    sys.modules["langchain_openai"] = langchain_openai

    chat_models = types.ModuleType("langchain_openai.chat_models")
    chat_models_base = types.ModuleType("langchain_openai.chat_models.base")
    chat_models_base._convert_dict_to_message = lambda value, *args, **kwargs: value
    chat_models_base._convert_message_to_dict = lambda value, *args, **kwargs: {}
    chat_models_base._convert_delta_to_message_chunk = (
        lambda value, default_class: default_class()
    )
    sys.modules["langchain_openai.chat_models"] = chat_models
    sys.modules["langchain_openai.chat_models.base"] = chat_models_base

    langchain_core = types.ModuleType("langchain_core")
    language_models = types.ModuleType("langchain_core.language_models")

    class BaseChatModel:
        pass

    language_models.BaseChatModel = BaseChatModel
    messages = types.ModuleType("langchain_core.messages")

    class BaseMessage:
        pass

    class AIMessage(BaseMessage):
        def __init__(self, *args, **kwargs):
            self.additional_kwargs = kwargs.get("additional_kwargs", {})

    messages.AIMessage = AIMessage
    messages.BaseMessage = BaseMessage
    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.language_models"] = language_models
    sys.modules["langchain_core.messages"] = messages

    return importlib.import_module("backend.route.rpa")


def test_trace_timeline_projects_manual_and_ai_traces_in_order():
    traces = [
        RPAAcceptedTrace(
            trace_id="trace-ai",
            trace_type=RPATraceType.AI_OPERATION,
            source="ai",
            user_instruction="Extract rows",
            description="Extract rows",
            after_page=RPAPageState(url="https://example.test/table", title="Rows"),
            signals={"recording": {"event_timestamp_ms": 2000}},
        ),
        RPAAcceptedTrace(
            trace_id="trace-manual",
            trace_type=RPATraceType.MANUAL_ACTION,
            source="manual",
            action="click",
            description="Click Save",
            after_page=RPAPageState(url="https://example.test/form", title="Form"),
            frame_path=["iframe[name='editor']"],
            locator_candidates=[
                {
                    "kind": "role",
                    "locator": {"method": "role", "role": "button", "name": "Save"},
                    "selected": True,
                }
            ],
            validation={"status": "ok"},
            signals={"recording": {"event_timestamp_ms": 1000}},
        ),
    ]

    items = build_trace_timeline_items(traces=traces, trace_diagnostics=[])

    assert [item.trace_id for item in items] == ["trace-manual", "trace-ai"]
    assert items[0].id == "trace:trace-manual"
    assert items[0].kind == "trace"
    assert items[0].source == "manual"
    assert items[0].trace_type == "manual_action"
    assert items[0].action == "click"
    assert items[0].title == "Click Save"
    assert items[0].summary == "Click Save"
    assert items[0].url == "https://example.test/form"
    assert items[0].frame_path == ["iframe[name='editor']"]
    assert items[0].locator == {"method": "role", "role": "button", "name": "Save"}
    assert items[0].locator_candidates == traces[1].locator_candidates
    assert items[0].validation == {"status": "ok"}
    assert items[0].editable is True
    assert items[0].deletable is True
    assert items[0].order_ms == 1000
    assert items[0].raw_trace["trace_id"] == "trace-manual"

    assert items[1].source == "ai"
    assert items[1].action == "ai_operation"
    assert items[1].title == "Extract rows"
    assert items[1].editable is False
    assert items[1].deletable is True


def test_trace_timeline_exposes_sensitive_fill_contract_without_raw_trace_dependency():
    trace = RPAAcceptedTrace(
        trace_id="trace-password",
        trace_type=RPATraceType.MANUAL_ACTION,
        source="manual",
        action="fill",
        description="Fill password",
        value="{{credential}}",
        sensitive=True,
        locator_candidates=[
            {
                "kind": "role",
                "locator": {"method": "role", "role": "textbox", "name": "Password"},
                "selected": True,
            }
        ],
        signals={"recording": {"event_timestamp_ms": 1000}},
    )

    [item] = build_trace_timeline_items(traces=[trace], trace_diagnostics=[])

    assert item.value == "{{credential}}"
    assert item.sensitive is True
    assert item.raw_trace["value"] == "{{credential}}"
    assert item.raw_trace["sensitive"] is True


def test_trace_timeline_projects_diagnostics_without_accepting_them():
    diagnostic = RPATraceDiagnostic(
        diagnostic_id="diag-1",
        trace_id="trace-failed",
        source="manual",
        message="accepted interactive action requires canonical target",
        raw={
            "action": "click",
            "url": "https://example.test/broken",
            "frame_path": ["iframe"],
            "locator_candidates": [{"locator": {"method": "css", "value": ".x"}}],
        },
        timestamp=datetime.fromtimestamp(3),
    )

    items = build_trace_timeline_items(traces=[], trace_diagnostics=[diagnostic])

    assert len(items) == 1
    assert items[0].id == "diagnostic:diag-1"
    assert items[0].kind == "diagnostic"
    assert items[0].trace_id == "trace-failed"
    assert items[0].diagnostic_id == "diag-1"
    assert items[0].source == "manual"
    assert items[0].action == "click"
    assert items[0].title == "accepted interactive action requires canonical target"
    assert items[0].summary == "accepted interactive action requires canonical target"
    assert items[0].url == "https://example.test/broken"
    assert items[0].frame_path == ["iframe"]
    assert items[0].locator_candidates == [{"locator": {"method": "css", "value": ".x"}}]
    assert items[0].editable is False
    assert items[0].deletable is True
    assert items[0].raw_trace is None
    assert items[0].raw_diagnostic["diagnostic_id"] == "diag-1"


def test_trace_timeline_detaches_mutable_payloads_from_source_models():
    trace = RPAAcceptedTrace(
        trace_id="trace-mutable",
        trace_type=RPATraceType.MANUAL_ACTION,
        source="manual",
        action="click",
        description="Click Save",
        locator_candidates=[
            {
                "kind": "role",
                "locator": {"method": "role", "role": "button", "name": "Save"},
                "selected": True,
            }
        ],
        validation={"status": "ok", "details": {"match_count": 1}},
        signals={"recording": {"event_timestamp_ms": 1000}},
    )
    diagnostic = RPATraceDiagnostic(
        diagnostic_id="diag-mutable",
        trace_id="trace-failed",
        source="manual",
        message="missing target",
        raw={
            "action": "click",
            "locator_candidates": [
                {"locator": {"method": "css", "value": ".original"}}
            ],
            "validation": {"status": "broken"},
        },
    )

    items = build_trace_timeline_items(traces=[trace], trace_diagnostics=[diagnostic])
    trace_item = next(item for item in items if item.kind == "trace")
    diagnostic_item = next(item for item in items if item.kind == "diagnostic")

    trace_item.locator["name"] = "Changed"
    trace_item.locator_candidates[0]["locator"]["name"] = "Changed"
    trace_item.validation["details"]["match_count"] = 99
    trace_item.raw_trace["locator_candidates"][0]["locator"]["name"] = "Changed"

    diagnostic_item.locator["value"] = ".changed"
    diagnostic_item.locator_candidates[0]["locator"]["value"] = ".changed"
    diagnostic_item.validation["status"] = "changed"
    diagnostic_item.raw_diagnostic["raw"]["locator_candidates"][0]["locator"]["value"] = ".changed"

    assert trace.locator_candidates[0]["locator"]["name"] == "Save"
    assert trace.validation["details"]["match_count"] == 1
    assert diagnostic.raw["locator_candidates"][0]["locator"]["value"] == ".original"
    assert diagnostic.raw["validation"]["status"] == "broken"


@pytest.mark.asyncio
async def test_build_session_timeline_ignores_legacy_sources():
    route_module = _load_route_module()

    class FakeSession:
        traces = [
            RPAAcceptedTrace(
                trace_id="trace-only",
                trace_type=RPATraceType.MANUAL_ACTION,
                source="manual",
                action="click",
                description="Trace Save",
                locator_candidates=[
                    {
                        "kind": "role",
                        "locator": {"method": "role", "role": "button", "name": "Save"},
                        "selected": True,
                    }
                ],
                signals={"recording": {"event_timestamp_ms": 1000}},
            )
        ]
        trace_diagnostics = []
        steps = [{"id": "DO_NOT_USE_LEGACY", "description": "DO_NOT_USE_LEGACY"}]
        recorded_actions = [{"step_id": "DO_NOT_USE_LEGACY", "description": "DO_NOT_USE_LEGACY"}]
        recording_diagnostics = [{"message": "DO_NOT_USE_LEGACY"}]
        legacy_steps = [{"id": "DO_NOT_USE_LEGACY"}]

    timeline = route_module._build_session_timeline(FakeSession())

    assert len(timeline) == 1
    assert timeline[0]["trace_id"] == "trace-only"
    assert timeline[0]["title"] == "Trace Save"
    assert "DO_NOT_USE_LEGACY" not in repr(timeline)


@pytest.mark.asyncio
async def test_get_session_timeline_route_returns_trace_projection():
    route_module = _load_route_module()

    manager = route_module.rpa_manager
    session = type(
        "FakeSession",
        (),
        {
            "id": "timeline-route-session",
            "user_id": "u1",
            "traces": [
                RPAAcceptedTrace(
                    trace_id="trace-route",
                    trace_type=RPATraceType.AI_OPERATION,
                    source="ai",
                    description="Collect page title",
                    signals={"recording": {"event_timestamp_ms": 1000}},
                )
            ],
            "trace_diagnostics": [],
        },
    )()
    manager.sessions[session.id] = session

    try:
        user = type("User", (), {"id": "u1"})()
        response = await route_module.get_session_timeline(session.id, user)

        assert response["status"] == "success"
        assert response["timeline"][0]["trace_id"] == "trace-route"
        assert response["timeline"][0]["kind"] == "trace"
    finally:
        manager.sessions.pop(session.id, None)
