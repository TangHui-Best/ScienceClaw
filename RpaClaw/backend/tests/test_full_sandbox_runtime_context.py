import json

import pytest

from backend.deepagent.full_sandbox_backend import FullSandboxBackend, _sanitize_command_for_log
from backend.deepagent.skill_command import parse_skill_command


@pytest.mark.anyio
async def test_full_sandbox_injects_runtime_ai_context_as_json_cli_args(monkeypatch):
    async def forbidden_default_model(_user_id):
        raise AssertionError("session model should win")

    monkeypatch.setattr(
        "backend.rpa.runtime_context.resolve_default_model_config",
        forbidden_default_model,
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

    command = await backend._maybe_inject_credentials("python skill.py --query=science")
    parsed = parse_skill_command(command)

    assert parsed is not None
    assert parsed.kwargs["query"] == "science"
    model_config = json.loads(parsed.kwargs["_model_config"])
    runtime_context = json.loads(parsed.kwargs["_runtime_context"])
    assert model_config["api_key"] == "sk-chat"
    assert runtime_context["runtime_ai"]["source"] == "session_model_config"


def test_full_sandbox_runtime_context_log_sanitizer_redacts_secret_args():
    command = (
        "python skill.py --_model_config='{\"api_key\":\"sk-secret\"}' "
        "--_runtime_context='{\"runtime_ai\":{\"model_config\":{\"api_key\":\"sk-secret\"}}}'"
    )

    sanitized = _sanitize_command_for_log(command)

    assert "sk-secret" not in sanitized
    assert sanitized.count("<redacted>") == 2
