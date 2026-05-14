from __future__ import annotations

import importlib
import sys
import types

import pytest


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


ROUTE_MODULE = _load_route_module()

from backend.rpa.manager import RPASession, RPAStep
from backend.rpa.manual_recording_models import (
    ManualActionKind,
    ManualRecordedAction,
    ManualRecordingDiagnostic,
)
from backend.rpa.trace_models import (
    RPAAcceptedTrace,
    RPADataflowMapping,
    RPATargetField,
    RPATraceDiagnostic,
    RPATraceType,
)


@pytest.mark.asyncio
async def test_delete_trace_route_uses_trace_id_and_ignores_legacy_poison():
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="trace-mutation-delete", user_id="u1", sandbox_session_id="sandbox")
    session.steps.append(
        RPAStep(
            id="poison-step",
            action="click",
            target='{"marker": "DO_NOT_USE_LEGACY"}',
            description="DO_NOT_USE_LEGACY",
            validation={"status": "ok"},
        )
    )
    session.recorded_actions.append(
        ManualRecordedAction(
            step_id="poison-step",
            action_kind=ManualActionKind.CLICK,
            description="DO_NOT_USE_LEGACY",
            target={"method": "css", "value": "DO_NOT_USE_LEGACY"},
            validation={"status": "ok"},
        )
    )
    session.traces.extend(
        [
            RPAAcceptedTrace(
                trace_id="trace-poison-step",
                trace_type=RPATraceType.MANUAL_ACTION,
                source="manual",
                action="click",
                description="trace-native target",
                output_key="deleted",
                output={"value": "old"},
            ),
            RPAAcceptedTrace(
                trace_id="trace-keep",
                trace_type=RPATraceType.AI_OPERATION,
                source="ai",
                output_key="kept",
                output={"value": "new"},
            ),
        ]
    )
    session.runtime_results.write("deleted", {"value": "old"})
    session.runtime_results.write("kept", {"value": "new"})
    manager.sessions[session.id] = session

    try:
        user = type("User", (), {"id": "u1"})()
        response = await ROUTE_MODULE.delete_trace_item(session.id, "trace-poison-step", user)

        assert response == {"status": "success"}
        assert [trace.trace_id for trace in session.traces] == ["trace-keep"]
        assert session.runtime_results.values == {"kept": {"value": "new"}}
        assert [step.id for step in session.steps] == ["poison-step"]
        assert session.steps[0].description == "DO_NOT_USE_LEGACY"
        assert session.recorded_actions[0].description == "DO_NOT_USE_LEGACY"
        assert "DO_NOT_USE_LEGACY" not in repr(response)
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_promote_trace_locator_route_selects_one_candidate_and_updates_dataflow():
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="trace-mutation-promote", user_id="u1", sandbox_session_id="sandbox")
    session.traces.append(
        RPAAcceptedTrace(
            trace_id="trace-fill",
            trace_type=RPATraceType.DATAFLOW_FILL,
            source="manual",
            action="fill",
            locator_candidates=[
                {
                    "kind": "css",
                    "locator": {"method": "css", "value": "#old"},
                    "selected": True,
                    "strict_match_count": 2,
                },
                {
                    "kind": "role",
                    "locator": {"method": "role", "role": "textbox", "name": "Search"},
                    "selected": False,
                    "strict_match_count": 1,
                },
            ],
            validation={"status": "fallback"},
            dataflow=RPADataflowMapping(
                target_field=RPATargetField(
                    label="Search",
                    locator_candidates=[
                        {
                            "kind": "css",
                            "locator": {"method": "css", "value": "#old"},
                            "selected": True,
                            "strict_match_count": 2,
                        }
                    ],
                )
            ),
        )
    )
    manager.sessions[session.id] = session

    try:
        user = type("User", (), {"id": "u1"})()
        response = await ROUTE_MODULE.promote_trace_locator(
            session.id,
            "trace-fill",
            ROUTE_MODULE.PromoteLocatorRequest(candidate_index=1),
            user,
        )

        trace = response["trace"]
        assert response["status"] == "success"
        assert [candidate["selected"] for candidate in trace.locator_candidates] == [False, True]
        assert sum(1 for candidate in trace.locator_candidates if candidate["selected"]) == 1
        assert trace.validation["selected_candidate_index"] == 1
        assert trace.validation["selected_candidate_kind"] == "role"
        assert trace.validation["status"] == "ok"
        assert trace.dataflow.target_field.locator_candidates == trace.locator_candidates
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_promote_trace_locator_route_promotes_manual_diagnostic_without_step_api():
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(
        id="trace-mutation-promote-manual-diagnostic",
        user_id="u1",
        sandbox_session_id="sandbox",
    )
    manager.sessions[session.id] = session

    try:
        await manager.add_step(
            session.id,
            {
                "action": "click",
                "target": "",
                "description": "click missing target",
                "source": "record",
                "locator_candidates": [
                    {
                        "kind": "role",
                        "playwright_locator": 'page.locator(".unknown")',
                        "selected": True,
                    },
                    {
                        "kind": "role",
                        "locator": {"method": "role", "role": "button", "name": "Search"},
                        "selected": False,
                        "strict_match_count": 1,
                    },
                ],
                "validation": {"status": "ok"},
            },
        )

        assert session.traces == []
        assert len(session.trace_diagnostics) == 1
        trace_id = session.trace_diagnostics[0].trace_id

        user = type("User", (), {"id": "u1"})()
        response = await ROUTE_MODULE.promote_trace_locator(
            session.id,
            trace_id,
            ROUTE_MODULE.PromoteLocatorRequest(candidate_index=1),
            user,
        )

        trace = response["trace"]
        assert response["status"] == "success"
        assert trace.trace_id == trace_id
        assert [candidate["selected"] for candidate in trace.locator_candidates] == [True]
        assert trace.locator_candidates[0]["locator"] == {
            "method": "role",
            "role": "button",
            "name": "Search",
        }
        assert session.trace_diagnostics == []
        assert [item.trace_id for item in session.traces] == [trace_id]
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_delete_diagnostic_route_uses_diagnostic_id():
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="trace-mutation-diagnostic", user_id="u1", sandbox_session_id="sandbox")
    session.trace_diagnostics.extend(
        [
            RPATraceDiagnostic(
                diagnostic_id="diag-delete",
                trace_id="trace-a",
                source="ai",
                message="delete me",
            ),
            RPATraceDiagnostic(
                diagnostic_id="diag-keep",
                trace_id="trace-b",
                source="manual",
                message="keep me",
            ),
        ]
    )
    manager.sessions[session.id] = session

    try:
        user = type("User", (), {"id": "u1"})()
        response = await ROUTE_MODULE.delete_diagnostic_item(session.id, "diag-delete", user)

        assert response == {"status": "success"}
        assert [diagnostic.diagnostic_id for diagnostic in session.trace_diagnostics] == ["diag-keep"]
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_delete_manual_diagnostic_route_deletes_backing_bad_step():
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(
        id="trace-mutation-delete-manual-diagnostic",
        user_id="u1",
        sandbox_session_id="sandbox",
    )
    manager.sessions[session.id] = session

    try:
        await manager.add_step(
            session.id,
            {
                "action": "click",
                "target": "",
                "description": "click missing target",
                "source": "record",
                "locator_candidates": [
                    {
                        "kind": "role",
                        "playwright_locator": 'page.locator(".unknown")',
                        "selected": True,
                    }
                ],
                "validation": {"status": "ok"},
            },
        )

        assert len(session.steps) == 1
        assert session.traces == []
        assert len(session.recording_diagnostics) == 1
        assert len(session.trace_diagnostics) == 1
        diagnostic_id = session.trace_diagnostics[0].diagnostic_id

        user = type("User", (), {"id": "u1"})()
        response = await ROUTE_MODULE.delete_diagnostic_item(session.id, diagnostic_id, user)

        assert response == {"status": "success"}
        assert session.steps == []
        assert session.traces == []
        assert session.recorded_actions == []
        assert session.recording_diagnostics == []
        assert session.trace_diagnostics == []
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_generate_script_blocks_on_trace_diagnostics():
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="trace-diagnostic-generate-block", user_id="u1", sandbox_session_id="sandbox")
    session.trace_diagnostics.append(
        RPATraceDiagnostic(
            diagnostic_id="diag-block",
            trace_id="trace-fill",
            source="manual",
            message="canonical target missing",
        )
    )
    manager.sessions[session.id] = session

    try:
        user = type("User", (), {"id": "u1"})()
        with pytest.raises(ROUTE_MODULE.HTTPException) as exc_info:
            await ROUTE_MODULE.generate_script(session.id, ROUTE_MODULE.GenerateRequest(), user)
        assert exc_info.value.status_code == 400
        assert "unresolved diagnostics" in exc_info.value.detail
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_generate_script_ignores_legacy_recording_diagnostics_poison(monkeypatch):
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="trace-diagnostic-generate-legacy-poison", user_id="u1", sandbox_session_id="sandbox")
    session.recording_diagnostics.append(
        ManualRecordingDiagnostic(
            related_action_kind=ManualActionKind.FILL,
            failure_reason="DO_NOT_USE_LEGACY",
        )
    )
    manager.sessions[session.id] = session

    try:
        user = type("User", (), {"id": "u1"})()
        monkeypatch.setattr(ROUTE_MODULE, "_generate_session_script", lambda *_args, **_kwargs: "ok")

        response = await ROUTE_MODULE.generate_script(session.id, ROUTE_MODULE.GenerateRequest(), user)

        assert response == {"status": "success", "script": "ok"}
    finally:
        manager.sessions.pop(session.id, None)


def test_failed_trace_retry_context_uses_trace_candidates_and_ignores_legacy_steps():
    session = RPASession(id="trace-retry-context", user_id="u1", sandbox_session_id="sandbox")
    session.steps.append(
        RPAStep(
            id="legacy-step",
            action="click",
            description="DO_NOT_USE_LEGACY",
            target='{"method": "css", "value": "#legacy"}',
            validation={"status": "ok"},
        )
    )
    session.traces.extend(
        [
            RPAAcceptedTrace(
                trace_id="trace-first",
                trace_type=RPATraceType.MANUAL_ACTION,
                source="manual",
                action="click",
            ),
            RPAAcceptedTrace(
                trace_id="trace-failed",
                trace_type=RPATraceType.MANUAL_ACTION,
                source="manual",
                action="click",
                locator_candidates=[
                    {
                        "kind": "css",
                        "locator": {"method": "css", "value": "#old"},
                        "selected": True,
                    },
                    {
                        "kind": "role",
                        "locator": {"method": "role", "role": "button", "name": "Save"},
                        "selected": False,
                        "strict_match_count": 1,
                        "score": 0.1,
                    },
                    {
                        "kind": "css",
                        "locator": {"method": "css", "value": "#none-score"},
                        "selected": False,
                        "strict_match_count": 1,
                        "score": None,
                    },
                ],
            ),
        ]
    )

    context = ROUTE_MODULE._failed_trace_retry_context(
        session,
        {"success": False, "failed_trace_index": 1, "failed_step_index": 0},
    )

    assert context["failed_trace_id"] == "trace-failed"
    assert context["failed_trace_index"] == 1
    assert context["failed_step_candidates"] == [
        {
            "kind": "role",
            "locator": {"method": "role", "role": "button", "name": "Save"},
            "selected": False,
            "strict_match_count": 1,
            "score": 0.1,
            "original_index": 1,
        },
        {
            "kind": "css",
            "locator": {"method": "css", "value": "#none-score"},
            "selected": False,
            "strict_match_count": 1,
            "score": None,
            "original_index": 2,
        }
    ]
    assert "DO_NOT_USE_LEGACY" not in repr(context)

    legacy_only_context = ROUTE_MODULE._failed_trace_retry_context(
        session,
        {"success": False, "failed_step_index": 1},
    )
    assert legacy_only_context == {
        "failed_trace_id": None,
        "failed_trace_index": None,
        "failed_step_candidates": [],
    }
