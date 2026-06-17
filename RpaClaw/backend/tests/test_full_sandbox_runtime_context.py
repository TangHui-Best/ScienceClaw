import json
import asyncio

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


def test_full_sandbox_client_injects_runtime_token_header(monkeypatch):
    calls = []

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.is_closed = False

    monkeypatch.setattr("backend.deepagent.full_sandbox_backend.httpx.AsyncClient", FakeAsyncClient)

    backend = FullSandboxBackend(
        session_id="session-1",
        user_id="user-1",
        sandbox_url="http://aio-runtime.local",
        runtime_token="runtime-secret",
    )

    assert backend._get_client() is backend._client
    assert calls == [
        {
            "base_url": "http://aio-runtime.local",
            "timeout": calls[0]["timeout"],
            "headers": {"Authorization": "Bearer runtime-secret"},
            "trust_env": False,
        }
    ]


def test_full_sandbox_client_prefers_runtime_headers_for_native_aio(monkeypatch):
    calls = []

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.is_closed = False

    monkeypatch.setattr("backend.deepagent.full_sandbox_backend.httpx.AsyncClient", FakeAsyncClient)

    backend = FullSandboxBackend(
        session_id="session-1",
        user_id="user-1",
        sandbox_url="http://apig.internal/api/rpa-sandbox",
        runtime_token="legacy-token",
        runtime_headers={
            "X-HW-ID": "com.huawei.pass.roma.event",
            "X-HW-APPKEY": "configured-appkey",
            "x-livefunction-sandbox-id": "sb-123",
        },
    )

    assert backend._get_client() is backend._client
    assert calls == [
        {
            "base_url": "http://apig.internal/api/rpa-sandbox",
            "timeout": calls[0]["timeout"],
            "headers": {
                "X-HW-ID": "com.huawei.pass.roma.event",
                "X-HW-APPKEY": "configured-appkey",
                "x-livefunction-sandbox-id": "sb-123",
                "Authorization": "Bearer legacy-token",
            },
            "trust_env": False,
        }
    ]


@pytest.mark.anyio
async def test_full_sandbox_rebases_workspace_to_runtime_home_dir(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "success": True,
                "home_dir": "/home/gem",
                "data": "runtime context",
            }

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            self.is_closed = False

        async def get(self, path, timeout=None):
            assert path == "/v1/sandbox"
            return FakeResponse()

    monkeypatch.setattr("backend.deepagent.full_sandbox_backend.httpx.AsyncClient", FakeAsyncClient)

    backend = FullSandboxBackend(
        session_id="chat-1",
        user_id="user-1",
        sandbox_url="http://aio-runtime.local",
        sandbox_base_dir="\\home\\rpaclaw\\workspace",
        use_runtime_home_workspace=True,
    )

    await backend.get_context()

    assert backend.workspace == "/home/gem/workspace/chat-1"


@pytest.mark.anyio
async def test_full_sandbox_uses_runtime_home_dir_when_context_temporarily_unavailable(monkeypatch):
    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            self.is_closed = False

        async def get(self, path, timeout=None):
            raise RuntimeError("temporary sandbox context outage")

    monkeypatch.setattr("backend.deepagent.full_sandbox_backend.httpx.AsyncClient", FakeAsyncClient)

    backend = FullSandboxBackend(
        session_id="chat-1",
        user_id="user-1",
        sandbox_url="http://aio-runtime.local",
        sandbox_base_dir="/home/rpaclaw/workspace",
        runtime_home_dir="/home/gem",
        use_runtime_home_workspace=True,
    )

    context = await backend.get_context()

    assert context["success"] is False
    assert backend.workspace == "/home/gem/workspace/chat-1"


@pytest.mark.anyio
async def test_full_sandbox_rewrites_legacy_workspace_paths_for_file_tools(monkeypatch):
    posts = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"success": True, "data": {"files": []}}

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            self.is_closed = False

        async def post(self, path, json=None, **_kwargs):
            posts.append((path, json))
            return FakeResponse()

    monkeypatch.setattr("backend.deepagent.full_sandbox_backend.httpx.AsyncClient", FakeAsyncClient)

    backend = FullSandboxBackend(
        session_id="chat-1",
        user_id="user-1",
        sandbox_url="http://aio-runtime.local",
        sandbox_base_dir="/home/rpaclaw/workspace",
        runtime_home_dir="/home/gem",
        use_runtime_home_workspace=True,
    )

    result = await backend.awrite("/home/rpaclaw/workspace/chat-1/hello.txt", "hello aio")
    await backend.als_info("/home/rpaclaw/workspace/chat-1")

    assert result.error is None
    assert result.path == "/home/gem/workspace/chat-1/hello.txt"
    assert posts == [
        (
            "/v1/file/write",
            {"file": "/home/gem/workspace/chat-1/hello.txt", "content": "hello aio"},
        ),
        (
            "/v1/file/list",
            {"path": "/home/gem/workspace/chat-1", "recursive": False},
        ),
    ]


@pytest.mark.anyio
async def test_full_sandbox_rewrites_legacy_workspace_paths_inside_shell_commands(monkeypatch):
    posts = []

    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            self.is_closed = False

        async def get(self, path, timeout=None):
            assert path == "/v1/sandbox"
            return FakeResponse({"success": True, "home_dir": "/home/gem"})

        async def post(self, path, json=None, **_kwargs):
            posts.append((path, json))
            if path == "/v1/shell/sessions/create":
                return FakeResponse({"success": True, "data": {"session_id": "shell-1"}})
            if path == "/v1/shell/exec":
                return FakeResponse({"success": True, "data": {"output": "hello aio", "exit_code": 0}})
            raise AssertionError(path)

    monkeypatch.setattr("backend.deepagent.full_sandbox_backend.httpx.AsyncClient", FakeAsyncClient)

    backend = FullSandboxBackend(
        session_id="chat-1",
        user_id="user-1",
        sandbox_url="http://aio-runtime.local",
        sandbox_base_dir="/home/rpaclaw/workspace",
        runtime_home_dir="/home/gem",
        use_runtime_home_workspace=True,
    )

    result = await backend.aexecute(
        'echo "hello aio" > /home/rpaclaw/workspace/chat-1/hello.txt '
        "&& cat /home/rpaclaw/workspace/chat-1/hello.txt"
    )

    assert result.exit_code == 0
    assert posts == [
        (
            "/v1/shell/sessions/create",
            {"id": "chat-1", "exec_dir": "/home/gem/workspace/chat-1"},
        ),
        (
            "/v1/shell/exec",
            {
                "id": "shell-1",
                "command": (
                    'echo "hello aio" > /home/gem/workspace/chat-1/hello.txt '
                    "&& cat /home/gem/workspace/chat-1/hello.txt"
                ),
                "async_mode": False,
                "exec_dir": "/home/gem/workspace/chat-1",
            },
        ),
    ]


@pytest.mark.anyio
async def test_full_sandbox_serializes_concurrent_shell_exec_calls(monkeypatch):
    active_execs = 0
    max_active_execs = 0
    exec_commands = []

    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            self.is_closed = False

        async def get(self, path, timeout=None):
            assert path == "/v1/sandbox"
            return FakeResponse({"success": True, "home_dir": "/home/gem"})

        async def post(self, path, json=None, **_kwargs):
            nonlocal active_execs, max_active_execs
            if path == "/v1/shell/sessions/create":
                return FakeResponse({"success": True, "data": {"session_id": "shell-1"}})
            if path == "/v1/shell/exec":
                active_execs += 1
                max_active_execs = max(max_active_execs, active_execs)
                exec_commands.append(json["command"])
                await asyncio.sleep(0.01)
                active_execs -= 1
                return FakeResponse(
                    {
                        "success": True,
                        "data": {"output": json["command"], "exit_code": 0},
                    }
                )
            raise AssertionError(path)

    monkeypatch.setattr("backend.deepagent.full_sandbox_backend.httpx.AsyncClient", FakeAsyncClient)

    backend = FullSandboxBackend(
        session_id="chat-1",
        user_id="user-1",
        sandbox_url="http://aio-runtime.local",
        runtime_home_dir="/home/gem",
        use_runtime_home_workspace=True,
    )

    await asyncio.gather(
        backend.aexecute("pwd"),
        backend.aexecute("cat /home/gem/workspace/chat-1/hello2.txt"),
    )

    assert max_active_execs == 1
    assert exec_commands == ["pwd", "cat /home/gem/workspace/chat-1/hello2.txt"]


@pytest.mark.anyio
async def test_full_sandbox_rewrites_virtual_skill_paths_inside_shell_commands(monkeypatch):
    posts = []

    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            self.is_closed = False

        async def get(self, path, timeout=None):
            assert path == "/v1/sandbox"
            return FakeResponse({"success": True, "home_dir": "/home/gem"})

        async def post(self, path, json=None, **_kwargs):
            posts.append((path, json))
            if path == "/v1/shell/sessions/create":
                return FakeResponse({"success": True, "data": {"session_id": "shell-1"}})
            if path == "/v1/shell/exec":
                return FakeResponse(
                    {
                        "success": True,
                        "data": {"output": json["command"], "exit_code": 0},
                    }
                )
            raise AssertionError(path)

    monkeypatch.setattr("backend.deepagent.full_sandbox_backend.httpx.AsyncClient", FakeAsyncClient)

    backend = FullSandboxBackend(
        session_id="chat-1",
        user_id="user-1",
        sandbox_url="http://aio-runtime.local",
        runtime_home_dir="/home/gem",
        use_runtime_home_workspace=True,
    )

    result = await backend.aexecute(
        'cd /skills/打开和agent最相关的项目 && python3 /skills/打开和agent最相关的项目/skill.py'
    )

    assert result.exit_code == 0
    assert posts[-1] == (
        "/v1/shell/exec",
        {
            "id": "shell-1",
            "command": (
                "cd /home/gem/workspace/chat-1/.skills/打开和agent最相关的项目 "
                "&& python3 /home/gem/workspace/chat-1/.skills/打开和agent最相关的项目/skill.py"
                " --_downloads_dir=/home/gem/workspace/chat-1/downloads"
            ),
            "async_mode": False,
            "exec_dir": "/home/gem/workspace/chat-1",
        },
    )
