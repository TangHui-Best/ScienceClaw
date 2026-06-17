import importlib

import pytest


RUNTIME_CONTEXT = importlib.import_module("backend.rpa.runtime_context")


@pytest.mark.anyio
async def test_runtime_ai_context_prefers_valid_session_model(monkeypatch):
    async def forbidden_default_model(_user_id):
        raise AssertionError("session model should win over default resolution")

    monkeypatch.setattr(RUNTIME_CONTEXT, "resolve_default_model_config", forbidden_default_model)

    session_model = {
        "id": "model-session",
        "is_system": False,
        "user_id": "user-1",
        "api_key": "sk-session",
        "model_name": "session-model",
    }

    kwargs = await RUNTIME_CONTEXT.inject_runtime_context_kwargs(
        "user-1",
        {},
        session_model_config=session_model,
    )

    assert kwargs["_model_config"]["id"] == "model-session"
    assert kwargs["_runtime_context"]["runtime_ai"]["model_config"]["api_key"] == "sk-session"
    assert kwargs["_runtime_context"]["runtime_ai"]["source"] == "session_model_config"


@pytest.mark.anyio
async def test_runtime_ai_context_ignores_cross_user_session_model(monkeypatch):
    async def fake_default_model(user_id):
        assert user_id == "user-1"
        return {
            "id": "model-default",
            "is_system": False,
            "user_id": "user-1",
            "api_key": "sk-default",
            "model_name": "default-model",
        }

    monkeypatch.setattr(RUNTIME_CONTEXT, "resolve_default_model_config", fake_default_model)

    kwargs = await RUNTIME_CONTEXT.inject_runtime_context_kwargs(
        "user-1",
        {},
        session_model_config={
            "id": "model-other",
            "is_system": False,
            "user_id": "other-user",
            "api_key": "sk-other",
            "model_name": "other-model",
        },
    )

    assert kwargs["_model_config"]["id"] == "model-default"
    assert kwargs["_runtime_context"]["runtime_ai"]["source"] == "user_default_model"


@pytest.mark.anyio
async def test_runtime_ai_context_preserves_existing_business_kwargs(monkeypatch):
    async def fake_default_model(user_id):
        assert user_id == "user-1"
        return {
            "id": "model-default",
            "is_system": False,
            "user_id": "user-1",
            "api_key": "sk-default",
            "model_name": "default-model",
        }

    monkeypatch.setattr(RUNTIME_CONTEXT, "resolve_default_model_config", fake_default_model)

    kwargs = await RUNTIME_CONTEXT.inject_runtime_context_kwargs(
        "user-1",
        {"query": "recorded query"},
    )

    assert kwargs["query"] == "recorded query"
    assert kwargs["_model_config"]["model_name"] == "default-model"


def test_should_inject_runtime_ai_context_requires_rpa_recording_runtime_requirement():
    assert RUNTIME_CONTEXT.should_inject_runtime_ai_context(
        {
            "kind": "rpa-recording",
            "runtime_requirements": {"runtime_ai": True},
        }
    )
    assert not RUNTIME_CONTEXT.should_inject_runtime_ai_context(
        {
            "kind": "rpa-recording",
            "runtime_requirements": {"runtime_ai": False},
        }
    )
    assert not RUNTIME_CONTEXT.should_inject_runtime_ai_context(
        {
            "kind": "custom-skill",
            "runtime_requirements": {"runtime_ai": True},
        }
    )


def test_should_inject_runtime_ai_context_falls_back_to_legacy_recording_traces():
    assert RUNTIME_CONTEXT.should_inject_runtime_ai_context(
        {
            "kind": "rpa-recording",
            "recording": {
                "traces": [
                    {
                        "trace_type": "ai_operation",
                        "source": "ai",
                        "user_instruction": "open the project most related to SKILL",
                        "description": "Click semantic project",
                        "signals": {"runtime_ai": {"preserve": True}},
                    }
                ],
            },
        }
    )
