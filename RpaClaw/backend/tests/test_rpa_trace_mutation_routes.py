from __future__ import annotations

import importlib
import json
import sys
import types
from datetime import datetime

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


def test_router_does_not_register_public_step_index_endpoints():
    paths = [getattr(route, "path", "") for route in ROUTE_MODULE.router.routes]

    assert not any("/step/" in path for path in paths)
    assert not any(path.endswith("/steps") for path in paths)


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
async def test_resolve_diagnostic_locator_route_promotes_manual_diagnostic_without_step_api():
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
        response = await ROUTE_MODULE.resolve_diagnostic_locator(
            session.id,
            session.trace_diagnostics[0].diagnostic_id,
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
    session.traces.append(
        RPAAcceptedTrace(
            trace_id="trace-ok",
            trace_type=RPATraceType.AI_OPERATION,
            source="ai",
            description="TRACE_OK",
        )
    )
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


@pytest.mark.asyncio
async def test_generate_script_rejects_empty_compile_traces():
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="trace-generate-empty-block", user_id="u1", sandbox_session_id="sandbox")
    session.steps.append(
        RPAStep(
            id="legacy-only",
            action="click",
            description="DO_NOT_USE_LEGACY",
            target='{"method": "css", "value": "#legacy"}',
        )
    )
    manager.sessions[session.id] = session

    try:
        user = type("User", (), {"id": "u1"})()
        with pytest.raises(ROUTE_MODULE.HTTPException) as exc_info:
            await ROUTE_MODULE.generate_script(session.id, ROUTE_MODULE.GenerateRequest(), user)

        assert exc_info.value.status_code == 400
        assert "No trace" in exc_info.value.detail
        assert "DO_NOT_USE_LEGACY" not in exc_info.value.detail
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_test_script_rejects_empty_compile_traces_before_executor(monkeypatch):
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="trace-test-empty-block", user_id="u1", sandbox_session_id="sandbox")
    session.steps.append(
        RPAStep(
            id="legacy-only",
            action="click",
            description="DO_NOT_USE_LEGACY",
            target='{"method": "css", "value": "#legacy"}',
        )
    )
    manager.sessions[session.id] = session

    def forbidden_generate(*_args, **_kwargs):
        raise AssertionError("_generate_session_script must not run for empty compile traces")

    async def forbidden_execute(*_args, **_kwargs):
        raise AssertionError("executor must not run for empty compile traces")

    monkeypatch.setattr(ROUTE_MODULE, "_generate_session_script", forbidden_generate)
    monkeypatch.setattr(ROUTE_MODULE.executor, "execute", forbidden_execute)

    try:
        user = type("User", (), {"id": "u1"})()
        with pytest.raises(ROUTE_MODULE.HTTPException) as exc_info:
            await ROUTE_MODULE.test_script(session.id, ROUTE_MODULE.GenerateRequest(), user)

        assert exc_info.value.status_code == 400
        assert "No trace" in exc_info.value.detail
        assert "DO_NOT_USE_LEGACY" not in exc_info.value.detail
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_save_skill_rejects_empty_compile_traces_before_export(monkeypatch):
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="trace-save-empty-block", user_id="u1", sandbox_session_id="sandbox")
    session.steps.append(
        RPAStep(
            id="legacy-only",
            action="click",
            description="DO_NOT_USE_LEGACY",
            target='{"method": "css", "value": "#legacy"}',
        )
    )
    manager.sessions[session.id] = session

    def forbidden_generate(*_args, **_kwargs):
        raise AssertionError("_generate_session_script must not run for empty compile traces")

    async def forbidden_export_skill(**_kwargs):
        raise AssertionError("export_skill must not run for empty compile traces")

    monkeypatch.setattr(ROUTE_MODULE, "_generate_session_script", forbidden_generate)
    monkeypatch.setattr(ROUTE_MODULE.exporter, "export_skill", forbidden_export_skill)

    try:
        user = type("User", (), {"id": "u1"})()
        with pytest.raises(ROUTE_MODULE.HTTPException) as exc_info:
            await ROUTE_MODULE.save_skill(
                session.id,
                ROUTE_MODULE.SaveSkillRequest(skill_name="Empty", description="Empty"),
                user,
            )

        assert exc_info.value.status_code == 400
        assert "No trace" in exc_info.value.detail
        assert session.status != "saved"
    finally:
        manager.sessions.pop(session.id, None)


@pytest.mark.asyncio
async def test_save_skill_exports_trace_metadata_without_legacy_source_facts(monkeypatch):
    manager = ROUTE_MODULE.rpa_manager
    session = RPASession(id="trace-save-meta-no-legacy", user_id="u1", sandbox_session_id="sandbox")
    session.traces.append(
        RPAAcceptedTrace(
            trace_id="trace-ok",
            trace_type=RPATraceType.MANUAL_ACTION,
            source="manual",
            action="click",
            description="TRACE_OK",
        )
    )
    session.steps.append(
        RPAStep(
            id="legacy-step",
            action="click",
            description="DO_NOT_USE_LEGACY",
            target='{"method": "css", "value": "DO_NOT_USE_LEGACY"}',
        )
    )
    session.recorded_actions.append(
        ManualRecordedAction(
            step_id="legacy-step",
            action_kind=ManualActionKind.CLICK,
            description="DO_NOT_USE_LEGACY",
            target={"method": "css", "value": "DO_NOT_USE_LEGACY"},
            validation={"status": "ok"},
        )
    )
    session.recording_diagnostics.append(
        ManualRecordingDiagnostic(
            related_action_kind=ManualActionKind.CLICK,
            failure_reason="DO_NOT_USE_LEGACY",
        )
    )
    manager.sessions[session.id] = session
    captured: dict = {}

    async def fake_export_skill(**kwargs):
        captured.update(kwargs)
        return kwargs["skill_name"]

    monkeypatch.setattr(ROUTE_MODULE, "_generate_session_script", lambda *args, **kwargs: "print('ok')\n")
    monkeypatch.setattr(ROUTE_MODULE.exporter, "export_skill", fake_export_skill)

    try:
        user = type("User", (), {"id": "u1"})()
        response = await ROUTE_MODULE.save_skill(
            session.id,
            ROUTE_MODULE.SaveSkillRequest(skill_name="saved_trace", description="Saved trace"),
            user,
        )

        assert response == {"status": "success", "skill_name": "saved_trace"}
        recording_meta = captured["recording_meta"]
        assert recording_meta["recording_source"] == "trace"
        assert [trace["trace_id"] for trace in recording_meta["traces"]] == ["trace-ok"]
        assert "legacy_steps" not in recording_meta
        assert "recorded_actions" not in recording_meta
        assert "recording_diagnostics" not in recording_meta
        assert "DO_NOT_USE_LEGACY" not in json.dumps(recording_meta, ensure_ascii=False)
        assert captured["steps"][0]["id"] == "trace-ok"
    finally:
        manager.sessions.pop(session.id, None)


def test_session_traces_for_compile_uses_only_ordered_session_traces():
    session = RPASession(id="trace-compile-poison", user_id="u1", sandbox_session_id="sandbox")
    session.traces.extend(
        [
            RPAAcceptedTrace(
                trace_id="trace-late",
                trace_type=RPATraceType.MANUAL_ACTION,
                source="manual",
                action="click",
                description="TRACE_LATE",
                started_at=datetime(2026, 5, 16, 10, 0, 1),
                ended_at=datetime(2026, 5, 16, 10, 0, 1),
                signals={"recording": {"event_timestamp_ms": 200}},
            ),
            RPAAcceptedTrace(
                trace_id="trace-early",
                trace_type=RPATraceType.AI_OPERATION,
                source="ai",
                description="TRACE_EARLY",
                started_at=datetime(2026, 5, 16, 10, 0, 2),
                ended_at=datetime(2026, 5, 16, 10, 0, 2),
                signals={"recording": {"event_timestamp_ms": 100}},
            ),
        ]
    )
    session.steps.append(
        RPAStep(
            id="late",
            action="click",
            description="DO_NOT_USE_LEGACY",
            target='{"method": "css", "value": "#legacy"}',
            locator_candidates=[
                {
                    "kind": "css",
                    "locator": {"method": "css", "value": "DO_NOT_USE_LEGACY"},
                    "selected": True,
                }
            ],
            validation={"status": "DO_NOT_USE_LEGACY"},
        )
    )
    session.recorded_actions.append(
        ManualRecordedAction(
            step_id="recorded-poison",
            action_kind=ManualActionKind.CLICK,
            description="DO_NOT_USE_LEGACY",
            target={"method": "css", "value": "DO_NOT_USE_LEGACY"},
            validation={"status": "ok"},
        )
    )

    traces = ROUTE_MODULE._session_traces_for_compile(session)

    assert [trace.trace_id for trace in traces] == ["trace-early", "trace-late"]
    traces_json = json.dumps(
        [trace.model_dump(mode="json") for trace in traces],
        ensure_ascii=False,
    )
    assert "DO_NOT_USE_LEGACY" not in traces_json


def test_session_traces_for_compile_uses_sequence_tiebreak_from_trace_signals():
    session = RPASession(id="trace-compile-sequence-order", user_id="u1", sandbox_session_id="sandbox")
    session.traces.extend(
        [
            RPAAcceptedTrace(
                trace_id="trace-second",
                trace_type=RPATraceType.MANUAL_ACTION,
                source="manual",
                action="click",
                description="TRACE_SECOND",
                signals={"recording": {"event_timestamp_ms": 1000, "sequence": 20}},
            ),
            RPAAcceptedTrace(
                trace_id="trace-first",
                trace_type=RPATraceType.MANUAL_ACTION,
                source="manual",
                action="click",
                description="TRACE_FIRST",
                signals={"recording": {"event_timestamp_ms": 1000, "sequence": 10}},
            ),
        ]
    )
    session.steps.extend(
        [
            RPAStep(id="legacy-first", action="click", description="DO_NOT_USE_LEGACY"),
            RPAStep(id="legacy-second", action="click", description="DO_NOT_USE_LEGACY"),
        ]
    )

    traces = ROUTE_MODULE._session_traces_for_compile(session)

    assert [trace.trace_id for trace in traces] == ["trace-first", "trace-second"]
    assert "DO_NOT_USE_LEGACY" not in json.dumps(
        [trace.model_dump(mode="json") for trace in traces],
        ensure_ascii=False,
    )


def test_generate_session_script_uses_trace_compiler_without_legacy_inputs(monkeypatch):
    session = RPASession(id="trace-compile-generate", user_id="u1", sandbox_session_id="sandbox")
    session.traces.append(
        RPAAcceptedTrace(
            trace_id="trace-ok",
            trace_type=RPATraceType.AI_OPERATION,
            source="ai",
            description="TRACE_OK",
        )
    )
    session.steps.append(
        RPAStep(
            id="ok",
            action="click",
            description="DO_NOT_USE_LEGACY",
            target='{"method": "css", "value": "#legacy"}',
            locator_candidates=[
                {
                    "kind": "css",
                    "locator": {"method": "css", "value": "DO_NOT_USE_LEGACY"},
                    "selected": True,
                }
            ],
        )
    )
    session.recorded_actions.append(
        ManualRecordedAction(
            step_id="recorded-poison",
            action_kind=ManualActionKind.CLICK,
            description="DO_NOT_USE_LEGACY",
            target={"method": "css", "value": "DO_NOT_USE_LEGACY"},
            validation={"status": "ok"},
        )
    )

    class TraceCompilerSpy:
        def generate_script(self, traces, params, *, is_local, test_mode):
            traces = list(traces)
            assert [trace.trace_id for trace in traces] == ["trace-ok"]
            assert "DO_NOT_USE_LEGACY" not in json.dumps(
                [trace.model_dump(mode="json") for trace in traces],
                ensure_ascii=False,
            )
            assert params == {"query": "value"}
            assert test_mode is True
            return "trace-script"

    class LegacyGeneratorPoison:
        def generate_script(self, *_args, **_kwargs):
            raise AssertionError("legacy generator fallback must not be called")

    monkeypatch.setattr(ROUTE_MODULE, "trace_compiler", TraceCompilerSpy())
    monkeypatch.setattr(ROUTE_MODULE, "generator", LegacyGeneratorPoison(), raising=False)

    script = ROUTE_MODULE._generate_session_script(
        session,
        {"query": "value"},
        test_mode=True,
    )

    assert script == "trace-script"


def test_generate_session_script_does_not_fallback_to_legacy_steps_when_trace_empty(monkeypatch):
    session = RPASession(id="trace-compile-empty", user_id="u1", sandbox_session_id="sandbox")
    session.steps.append(
        RPAStep(
            id="legacy-only",
            action="click",
            description="DO_NOT_USE_LEGACY",
            target='{"method": "css", "value": "#legacy"}',
        )
    )

    class TraceCompilerSpy:
        def generate_script(self, traces, params, *, is_local, test_mode):
            assert list(traces) == []
            assert params == {}
            assert test_mode is False
            return "empty-trace-script"

    class LegacyGeneratorPoison:
        def generate_script(self, *_args, **_kwargs):
            raise AssertionError("legacy generator fallback must not be called")

    monkeypatch.setattr(ROUTE_MODULE, "trace_compiler", TraceCompilerSpy())
    monkeypatch.setattr(ROUTE_MODULE, "generator", LegacyGeneratorPoison(), raising=False)

    script = ROUTE_MODULE._generate_session_script(session, {})

    assert script == "empty-trace-script"


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
