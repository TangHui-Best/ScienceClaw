import json

import pytest

from backend.deepagent.full_sandbox_backend import FullSandboxBackend, _sanitize_command_for_log
from backend.deepagent.skill_command import parse_skill_command


class _FakeSkillRepo:
    def __init__(self, doc):
        self._doc = doc

    async def find_one(self, _query):
        return self._doc


@pytest.mark.anyio
async def test_full_sandbox_injects_runtime_ai_context_as_json_cli_args(monkeypatch):
    async def forbidden_default_model(_user_id):
        raise AssertionError("session model should win")

    monkeypatch.setattr(
        "backend.rpa.runtime_context.resolve_default_model_config",
        forbidden_default_model,
    )
    monkeypatch.setattr(
        "backend.storage.get_repository",
        lambda _name: _FakeSkillRepo(
            {
                "params": {},
                "files": {
                    "skill.meta.json": json.dumps(
                        {
                            "kind": "rpa-recording",
                            "runtime_requirements": {"runtime_ai": True},
                        }
                    )
                },
            }
        ),
    )

    backend = FullSandboxBackend(
        session_id="session-1",
        user_id="user-1",
        session_model_config={
            "id": "chat-model",
            "is_system": False,
            "user_id": "user-1",
            "api_key": "sk-chat",
            "model_name": "chat-model",
        },
    )

    command = await backend._maybe_inject_credentials("cd runtime_ai_skill && python skill.py --query=science")
    parsed = parse_skill_command(command)

    assert parsed is not None
    assert parsed.kwargs["query"] == "science"
    model_config = json.loads(parsed.kwargs["_model_config"])
    runtime_context = json.loads(parsed.kwargs["_runtime_context"])
    assert model_config["api_key"] == "sk-chat"
    assert runtime_context["runtime_ai"]["source"] == "session_model_config"


@pytest.mark.anyio
async def test_full_sandbox_does_not_inject_runtime_ai_context_for_plain_skill(monkeypatch):
    async def forbidden_default_model(_user_id):
        raise AssertionError("plain skill should not resolve runtime AI model")

    monkeypatch.setattr(
        "backend.rpa.runtime_context.resolve_default_model_config",
        forbidden_default_model,
    )
    monkeypatch.setattr(
        "backend.storage.get_repository",
        lambda _name: _FakeSkillRepo(
            {
                "params": {},
                "files": {
                    "skill.meta.json": json.dumps(
                        {
                            "kind": "custom-skill",
                            "runtime_requirements": {"runtime_ai": False},
                        }
                    )
                },
            }
        ),
    )

    backend = FullSandboxBackend(
        session_id="session-1",
        user_id="user-1",
        session_model_config={
            "id": "chat-model",
            "is_system": False,
            "user_id": "user-1",
            "api_key": "sk-chat",
            "model_name": "chat-model",
        },
    )

    command = await backend._maybe_inject_credentials("cd plain_skill && python skill.py --query=science")
    parsed = parse_skill_command(command)

    assert parsed is not None
    assert parsed.kwargs["query"] == "science"
    assert "_model_config" not in parsed.kwargs
    assert "_runtime_context" not in parsed.kwargs


def test_full_sandbox_runtime_context_log_sanitizer_redacts_secret_args():
    command = (
        "python skill.py --_model_config='{\"api_key\":\"sk-secret\"}' "
        "--_runtime_context='{\"runtime_ai\":{\"model_config\":{\"api_key\":\"sk-secret\"}}}'"
    )

    sanitized = _sanitize_command_for_log(command)

    assert "sk-secret" not in sanitized
    assert sanitized.count("<redacted>") == 2
