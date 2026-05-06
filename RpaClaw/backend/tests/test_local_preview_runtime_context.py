from pathlib import Path
import json
import shutil
import uuid

import pytest

from backend.deepagent.local_preview_backend import LocalPreviewShellBackend, ParsedSkillCommand


class _FakePage:
    def __init__(self):
        self.calls = []

    def set_default_timeout(self, value):
        self.calls.append(("set_default_timeout", value))

    def set_default_navigation_timeout(self, value):
        self.calls.append(("set_default_navigation_timeout", value))

    async def wait_for_timeout(self, value):
        self.calls.append(("wait_for_timeout", value))


class _FakeContext:
    def __init__(self):
        self.page = _FakePage()
        self.closed = False

    async def new_page(self):
        return self.page

    async def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, context):
        self.context = context

    async def new_context(self, **_kwargs):
        return self.context


class _FakeConnector:
    def __init__(self, browser):
        self.browser = browser

    async def get_browser(self):
        return self.browser


@pytest.mark.anyio
async def test_local_preview_skill_execution_injects_session_runtime_ai_context(monkeypatch):
    skill_dir = Path.cwd() / ".test-runtime-context" / uuid.uuid4().hex / "runtime_ai_skill"
    skill_dir.mkdir(parents=True)
    try:
        script_path = skill_dir / "skill.py"
        script_path.write_text(
            """
async def execute_skill(page, **kwargs):
    return {
        "model": kwargs.get("_model_config"),
        "runtime": kwargs.get("_runtime_context"),
        "query": kwargs.get("query"),
    }
""",
            encoding="utf-8",
        )
        (skill_dir / "skill.meta.json").write_text(
            json.dumps(
                {
                    "kind": "rpa-recording",
                    "runtime_requirements": {"runtime_ai": True},
                }
            ),
            encoding="utf-8",
        )

        context = _FakeContext()
        connector = _FakeConnector(_FakeBrowser(context))

        async def noop_async(*_args, **_kwargs):
            return None

        monkeypatch.setattr(
            "backend.deepagent.local_preview_backend.get_cdp_connector",
            lambda: connector,
        )
        monkeypatch.setattr(
            "backend.deepagent.local_preview_backend.browser_preview_registry.register",
            noop_async,
        )
        monkeypatch.setattr(
            "backend.deepagent.local_preview_backend.browser_preview_registry.unregister",
            noop_async,
        )
        monkeypatch.setattr(
            "backend.rpa.runtime_context.resolve_default_model_config",
            lambda _user_id: None,
        )

        backend = LocalPreviewShellBackend.__new__(LocalPreviewShellBackend)
        backend._session_id = "chat-session"
        backend._user_id = "user-1"
        backend._session_model_config = {
            "id": "chat-model",
            "is_system": False,
            "user_id": "user-1",
            "api_key": "sk-chat",
            "model_name": "chat-model",
        }

        async def no_credentials(_script_path: Path, kwargs: dict):
            return kwargs

        backend._inject_credentials = no_credentials

        response = await backend._run_skill_command(
            ParsedSkillCommand(script_path=script_path, kwargs={"query": "science"}),
            timeout=5,
        )

        assert response.exit_code == 0
        assert "SKILL_SUCCESS" in response.output
        assert '"model_name": "chat-model"' in response.output
        assert '"query": "science"' in response.output
        assert context.closed is True
    finally:
        shutil.rmtree(skill_dir.parent, ignore_errors=True)


@pytest.mark.anyio
async def test_local_preview_does_not_inject_runtime_ai_context_without_requirement(monkeypatch):
    skill_dir = Path.cwd() / ".test-runtime-context" / uuid.uuid4().hex / "plain_skill"
    skill_dir.mkdir(parents=True)
    try:
        script_path = skill_dir / "skill.py"
        script_path.write_text(
            """
async def execute_skill(page, **kwargs):
    return {
        "has_model": "_model_config" in kwargs,
        "has_runtime": "_runtime_context" in kwargs,
        "query": kwargs.get("query"),
    }
""",
            encoding="utf-8",
        )
        (skill_dir / "skill.meta.json").write_text(
            json.dumps(
                {
                    "kind": "rpa-recording",
                    "runtime_requirements": {"runtime_ai": False},
                }
            ),
            encoding="utf-8",
        )

        context = _FakeContext()
        connector = _FakeConnector(_FakeBrowser(context))

        async def noop_async(*_args, **_kwargs):
            return None

        monkeypatch.setattr(
            "backend.deepagent.local_preview_backend.get_cdp_connector",
            lambda: connector,
        )
        monkeypatch.setattr(
            "backend.deepagent.local_preview_backend.browser_preview_registry.register",
            noop_async,
        )
        monkeypatch.setattr(
            "backend.deepagent.local_preview_backend.browser_preview_registry.unregister",
            noop_async,
        )
        monkeypatch.setattr(
            "backend.rpa.runtime_context.resolve_default_model_config",
            lambda _user_id: pytest.fail("plain skill should not resolve runtime AI model"),
        )

        backend = LocalPreviewShellBackend.__new__(LocalPreviewShellBackend)
        backend._session_id = "chat-session"
        backend._user_id = "user-1"
        backend._session_model_config = {
            "id": "chat-model",
            "is_system": False,
            "user_id": "user-1",
            "api_key": "sk-chat",
            "model_name": "chat-model",
        }

        async def no_credentials(_script_path: Path, kwargs: dict):
            return kwargs

        backend._inject_credentials = no_credentials

        response = await backend._run_skill_command(
            ParsedSkillCommand(script_path=script_path, kwargs={"query": "science"}),
            timeout=5,
        )

        assert response.exit_code == 0
        assert '"has_model": false' in response.output
        assert '"has_runtime": false' in response.output
        assert '"query": "science"' in response.output
    finally:
        shutil.rmtree(skill_dir.parent, ignore_errors=True)
