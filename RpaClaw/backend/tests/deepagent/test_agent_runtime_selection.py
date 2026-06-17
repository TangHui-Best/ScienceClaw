from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.runtime.models import SessionRuntimeRecord


@pytest.mark.asyncio
async def test_deep_agent_uses_session_runtime_when_aio_native_overrides_local_storage(
    monkeypatch,
):
    from backend.deepagent import agent as agent_module

    runtime = SessionRuntimeRecord(
        session_id="chat-1",
        user_id="user-1",
        namespace="aio-native",
        pod_name="aio-sandbox",
        service_name="aio-sandbox",
        rest_base_url="http://aio-runtime.local",
        route_base_url="http://aio-runtime.local",
        status="ready",
        sandbox_id="aio-sandbox",
        metadata={"home_dir": "/home/gem"},
    )
    calls: dict[str, object] = {}

    class FakeRuntimeManager:
        async def ensure_runtime(self, session_id: str, user_id: str):
            calls["ensure_runtime"] = (session_id, user_id)
            return runtime

    class FakeFullSandboxBackend:
        def __init__(self, **kwargs):
            calls["full_sandbox_kwargs"] = kwargs
            self.workspace = f"/home/rpaclaw/{kwargs['session_id']}"

        async def get_context(self):
            self.workspace = "/home/gem/workspace/chat-1"
            return {"success": True, "data": {"env": "aio"}}

        async def awrite(self, file_path: str, content: str):
            return SimpleNamespace(path=file_path, error=None)

    class ForbiddenLocalPreviewShellBackend:
        def __init__(self, *args, **kwargs):
            raise AssertionError("aio_native chat execution must not use local shell backend")

    def fake_create_agent(*, use_local_filesystem_paths, **kwargs):
        calls["use_local_filesystem_paths"] = use_local_filesystem_paths
        calls["agent_kwargs"] = kwargs
        return SimpleNamespace(name="fake-agent")

    def fake_collect_tools(**kwargs):
        calls["collect_tools_kwargs"] = kwargs
        return []

    monkeypatch.setattr(agent_module.settings, "storage_backend", "local")
    monkeypatch.setattr(agent_module.settings, "runtime_mode", "aio_native")
    monkeypatch.setattr(agent_module.settings, "aio_native_hw_id", "com.huawei.pass.roma.event")
    monkeypatch.setattr(agent_module.settings, "aio_native_appkey", "configured-appkey")
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        monkeypatch.setattr(agent_module, "_WORKSPACE_DIR", str(temp_path / "workspace"))
        monkeypatch.setattr(agent_module, "_BUILTIN_SKILLS_DIR", str(temp_path / "missing-builtin"))
        monkeypatch.setattr(agent_module.settings, "external_skills_dir", str(temp_path / "missing-skills"))
        monkeypatch.setattr(
            agent_module,
            "get_llm_model",
            lambda *args, **kwargs: SimpleNamespace(profile={"max_input_tokens": 8192}),
        )
        monkeypatch.setattr(agent_module, "get_blocked_skills", lambda user_id: _async_set())
        monkeypatch.setattr(agent_module, "get_blocked_tools", lambda user_id: _async_set())
        monkeypatch.setattr(agent_module, "_load_mcp_tools_for_session", lambda *args: _async_list())
        monkeypatch.setattr(agent_module, "get_session_runtime_manager", lambda: FakeRuntimeManager())
        monkeypatch.setattr(agent_module, "FullSandboxBackend", FakeFullSandboxBackend)
        monkeypatch.setattr(agent_module, "LocalPreviewShellBackend", ForbiddenLocalPreviewShellBackend)
        monkeypatch.setattr(agent_module, "_collect_tools", fake_collect_tools)
        monkeypatch.setattr(agent_module, "create_rpaclaw_deep_agent", fake_create_agent)

        agent, _, _, _ = await agent_module.deep_agent(
            "chat-1",
            user_id="user-1",
            model_config={},
        )

    assert agent.name == "fake-agent"
    assert calls["ensure_runtime"] == ("chat-1", "user-1")
    assert calls["full_sandbox_kwargs"]["sandbox_url"] == "http://aio-runtime.local"
    assert calls["full_sandbox_kwargs"]["runtime_home_dir"] == "/home/gem"
    assert calls["full_sandbox_kwargs"]["runtime_headers"] == {
        "X-HW-ID": "com.huawei.pass.roma.event",
        "X-HW-APPKEY": "configured-appkey",
        "x-livefunction-sandbox-id": "aio-sandbox",
    }
    assert calls["collect_tools_kwargs"]["sandbox_base_url"] == "http://aio-runtime.local"
    assert calls["collect_tools_kwargs"]["sandbox_headers"] == {
        "X-HW-ID": "com.huawei.pass.roma.event",
        "X-HW-APPKEY": "configured-appkey",
        "x-livefunction-sandbox-id": "aio-sandbox",
    }
    assert calls["use_local_filesystem_paths"] is False
    assert "memory" not in calls["agent_kwargs"]
    assert "/home/gem/workspace/chat-1" in calls["agent_kwargs"]["system_prompt"]


@pytest.mark.asyncio
async def test_local_skill_injection_aborts_after_first_remote_write_failure():
    from backend.deepagent import agent as agent_module

    calls: list[tuple[str, str]] = []

    class FailingSandbox:
        async def awrite(self, file_path: str, content: str):
            calls.append((file_path, content))
            return SimpleNamespace(error="remote file api unavailable")

    with tempfile.TemporaryDirectory() as temp_dir:
        skill_dir = Path(temp_dir) / "sample_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: sample_skill\ndescription: sample\n---\n",
            encoding="utf-8",
        )
        (skill_dir / "skill.py").write_text("print('should not upload')\n", encoding="utf-8")

        injected = await agent_module._inject_local_skills_to_sandbox(
            FailingSandbox(),
            "/home/rpaclaw/workspace/chat-1",
            temp_dir,
            set(),
        )

    assert injected == 0
    assert len(calls) == 1
    assert calls[0][0].endswith("/.skills/sample_skill/SKILL.md")


def test_external_tool_executor_uses_sandbox_when_runtime_base_is_provided(
    monkeypatch,
):
    from backend.deepagent import agent as agent_module

    calls: list[dict[str, object]] = []

    class FakeLocalToolExecutor:
        def __init__(self):
            calls.append({"executor": "local"})

    class FakeSandboxToolExecutor:
        def __init__(self, **kwargs):
            calls.append({"executor": "sandbox", **kwargs})

    monkeypatch.setattr(agent_module.settings, "storage_backend", "local")
    monkeypatch.setattr(agent_module.settings, "sandbox_tools_dir", "/app/Tools")
    monkeypatch.setattr(agent_module, "LocalToolExecutor", FakeLocalToolExecutor)
    monkeypatch.setattr(agent_module, "SandboxToolExecutor", FakeSandboxToolExecutor)

    agent_module._build_external_tool_executor(
        sandbox_base_url="http://aio-runtime.local",
    )

    assert calls == [
            {
                "executor": "sandbox",
                "sandbox_base_url": "http://aio-runtime.local",
                "sandbox_tools_dir": "/app/Tools",
                "sandbox_headers": None,
            }
        ]


@pytest.mark.asyncio
async def test_deep_agent_eval_uses_session_runtime_when_aio_native(
    monkeypatch,
):
    from backend.deepagent import agent as agent_module

    runtime = SessionRuntimeRecord(
        session_id="eval-1",
        user_id="eval_runner",
        namespace="aio-native",
        pod_name="aio-sandbox",
        service_name="aio-sandbox",
        rest_base_url="http://aio-runtime.local",
        route_base_url="http://aio-runtime.local",
        status="ready",
        sandbox_id="aio-sandbox",
        metadata={"home_dir": "/home/gem"},
    )
    calls: dict[str, object] = {}

    class FakeRuntimeManager:
        async def ensure_runtime(self, session_id: str, user_id: str):
            calls["ensure_runtime"] = (session_id, user_id)
            return runtime

    class FakeFullSandboxBackend:
        def __init__(self, **kwargs):
            calls["full_sandbox_kwargs"] = kwargs
            self.workspace = "/home/rpaclaw/eval-1"

        async def get_context(self):
            self.workspace = "/home/gem/workspace/eval-1"
            return {"success": True, "data": {"env": "aio"}}

    def fake_create_agent(*, use_local_filesystem_paths, **kwargs):
        calls["use_local_filesystem_paths"] = use_local_filesystem_paths
        calls["agent_kwargs"] = kwargs
        return SimpleNamespace(name="fake-eval-agent")

    monkeypatch.setattr(agent_module.settings, "storage_backend", "local")
    monkeypatch.setattr(agent_module.settings, "runtime_mode", "aio_native")
    monkeypatch.setattr(
        agent_module,
        "get_llm_model",
        lambda *args, **kwargs: SimpleNamespace(profile={"max_input_tokens": 8192}),
    )
    monkeypatch.setattr(agent_module, "get_session_runtime_manager", lambda: FakeRuntimeManager())
    monkeypatch.setattr(agent_module, "FullSandboxBackend", FakeFullSandboxBackend)
    monkeypatch.setattr(agent_module, "create_rpaclaw_deep_agent", fake_create_agent)

    agent, _ = await agent_module.deep_agent_eval(
        "eval-1",
        model_config={},
        skill_sources=[],
    )

    assert agent.name == "fake-eval-agent"
    assert calls["ensure_runtime"] == ("eval-1", "eval_runner")
    assert calls["full_sandbox_kwargs"]["sandbox_url"] == "http://aio-runtime.local"
    assert calls["full_sandbox_kwargs"]["runtime_home_dir"] == "/home/gem"
    assert calls["use_local_filesystem_paths"] is False
    assert "/home/gem/workspace/eval-1" in calls["agent_kwargs"]["system_prompt"]


async def _async_set():
    return set()


async def _async_list():
    return []
