from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path

import pytest


def test_parse_marker_wrapped_output_extracts_result_and_pre_output() -> None:
    from backend.deepagent.tool_execution import parse_marker_wrapped_output

    parsed = parse_marker_wrapped_output(
        "tool log line\n>>>TOOL_RESULT_JSON>>>\n"
        '{"message": "ok", "count": 2}\n'
        "<<<TOOL_RESULT_JSON<<<\n"
    )

    assert parsed.pre_output == "tool log line"
    assert parsed.result == {"message": "ok", "count": 2}


def test_local_tool_executor_runs_tool_runner_locally(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.deepagent.tool_execution import LocalToolExecutor

    helper_file = tmp_path / "helper.py"
    helper_file.write_text(
        """
def build_message(name: str) -> dict:
    return {"message": f"hello {name}"}
""".strip(),
        encoding="utf-8",
    )
    tool_file = tmp_path / "example_tool.py"
    tool_file.write_text(
        """
from langchain_core.tools import tool


@tool
def greet(name: str) -> dict:
    \"\"\"Return a greeting.\"\"\"
    from helper import build_message
    print("tool-stdout")
    return build_message(name)
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("SANDBOX_BASE_URL", "http://should-not-be-used.invalid")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.chdir(Path(__file__).resolve().parents[2])

    executor = LocalToolExecutor()
    result = executor.execute(
        tool_path=str(tool_file),
        function_name="greet",
        arguments={"name": "Ada"},
    )

    assert result["result"] == {"message": "hello Ada"}
    assert result["_sandbox_exec"]["output"] == "tool-stdout"
    assert "backend.deepagent.tool_execution" in result["_sandbox_exec"]["command"]
    assert str(tool_file) in result["_sandbox_exec"]["command"]


def test_sandbox_tool_executor_uses_sandbox_visible_path(tmp_path: Path) -> None:
    from backend.deepagent.tool_execution import SandboxToolExecutor

    tool_file = tmp_path / "sample tool.py"
    tool_file.write_text("", encoding="utf-8")
    captured: dict[str, str] = {}

    def fake_command_runner(command: str, timeout: int) -> str:
        captured["command"] = command
        captured["timeout"] = str(timeout)
        return "stdout\n>>>TOOL_RESULT_JSON>>>\n{\"ok\": true}\n<<<TOOL_RESULT_JSON<<<\n"

    executor = SandboxToolExecutor(
        sandbox_tools_dir="/configured/sandbox-tools",
        command_runner=fake_command_runner,
    )
    result = executor.execute(
        tool_path=str(tool_file),
        function_name="sample",
        arguments={"query": "cells"},
    )

    assert captured["command"].startswith("python3 /app/_tool_runner.py ")
    assert "'/configured/sandbox-tools/sample tool.py'" in captured["command"]
    assert result["result"] == {"ok": True}
    assert result["_sandbox_exec"]["output"] == "stdout"


def test_agent_uses_backend_owned_tool_loader_without_importing_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_tools_dir = tmp_path / "configured-tools"
    configured_tools_dir.mkdir()
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        if name == "Tools":
            raise AssertionError("agent runtime should not import the repo-root Tools package")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    sys.modules.pop("backend.deepagent.agent", None)
    agent_module = importlib.import_module("backend.deepagent.agent")

    calls: list[dict[str, object]] = []

    class FakeLocalToolExecutor:
        def __init__(self) -> None:
            calls.append({"executor": "local"})

    class FakeSandboxToolExecutor:
        def __init__(self, **kwargs) -> None:
            calls.append({"executor": "sandbox", **kwargs})

    class FakeLoader:
        def __init__(self, *, tools_dir, executor) -> None:
            calls.append({"tools_dir": Path(tools_dir), "executor_instance": executor})

        def reload(self, force: bool = False):
            calls.append({"reload_force": force})
            return [type("ToolStub", (), {"name": "demo_tool", "description": "demo"})()]

    protocol_calls: list[tuple[str, str, str]] = []

    class FakeProtocolManager:
        def __init__(self) -> None:
            self.extra_meta = {"demo_tool": {"sandbox": True}}

        def register_tool(self, name: str, category, icon: str, description: str) -> None:
            protocol_calls.append(("tool", name, description))
            self.extra_meta.setdefault(name, {})

        def register_sandbox_tool(self, name: str, description: str) -> None:
            protocol_calls.append(("sandbox", name, description))
            self.extra_meta[name] = {"sandbox": True}

    fake_protocol = FakeProtocolManager()

    monkeypatch.setattr(agent_module.settings, "storage_backend", "local")
    monkeypatch.setattr(agent_module.settings, "tools_dir", str(configured_tools_dir))
    monkeypatch.setattr(agent_module.settings, "sandbox_tools_dir", "/configured/sandbox-tools")
    monkeypatch.setattr(agent_module, "LocalToolExecutor", FakeLocalToolExecutor)
    monkeypatch.setattr(agent_module, "SandboxToolExecutor", FakeSandboxToolExecutor)
    monkeypatch.setattr(agent_module, "ExternalToolsLoader", FakeLoader)
    monkeypatch.setattr(agent_module, "_EXTERNAL_TOOLS_LOADER", None, raising=False)
    monkeypatch.setattr(agent_module, "_EXTERNAL_TOOLS_LOADER_KEY", None, raising=False)
    monkeypatch.setattr("backend.deepagent.sse_protocol.get_protocol_manager", lambda: fake_protocol)

    loader = agent_module._get_external_tools_loader()

    assert loader is not None
    assert calls[0] == {"executor": "local"}
    assert calls[1]["tools_dir"] == configured_tools_dir
    assert agent_module.reload_external_tools(force=True)[0].name == "demo_tool"
    assert protocol_calls == [("tool", "demo_tool", "demo")]
    assert fake_protocol.extra_meta.get("demo_tool") == {}


def test_agent_uses_runtime_scoped_sandbox_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_tools_dir = tmp_path / "configured-tools"
    configured_tools_dir.mkdir()
    sys.modules.pop("backend.deepagent.agent", None)
    agent_module = importlib.import_module("backend.deepagent.agent")

    calls: list[dict[str, object]] = []

    class FakeSandboxToolExecutor:
        def __init__(self, **kwargs) -> None:
            calls.append({"executor": "sandbox", **kwargs})

    class FakeLoader:
        def __init__(self, *, tools_dir, executor) -> None:
            calls.append({"tools_dir": Path(tools_dir), "executor_instance": executor})

        def reload(self, force: bool = False):
            calls.append({"reload_force": force})
            return []

    monkeypatch.setattr(agent_module.settings, "storage_backend", "docker")
    monkeypatch.setattr(agent_module.settings, "tools_dir", str(configured_tools_dir))
    monkeypatch.setattr(agent_module.settings, "sandbox_tools_dir", "/configured/sandbox-tools")
    monkeypatch.setattr(agent_module, "SandboxToolExecutor", FakeSandboxToolExecutor)
    monkeypatch.setattr(agent_module, "ExternalToolsLoader", FakeLoader)
    monkeypatch.setattr(agent_module, "_EXTERNAL_TOOLS_LOADER", None, raising=False)
    monkeypatch.setattr(agent_module, "_EXTERNAL_TOOLS_LOADER_KEY", None, raising=False)

    loader_one = agent_module._get_external_tools_loader(
        sandbox_base_url="http://shared-runtime",
        loader_cache_key="session-one",
    )
    loader_two = agent_module._get_external_tools_loader(
        sandbox_base_url="http://shared-runtime",
        loader_cache_key="session-two",
    )

    assert loader_one is not None
    assert loader_two is not None
    assert calls[0] == {
        "executor": "sandbox",
        "sandbox_base_url": "http://shared-runtime",
        "sandbox_tools_dir": "/configured/sandbox-tools",
    }
    assert calls[2] == {
        "executor": "sandbox",
        "sandbox_base_url": "http://shared-runtime",
        "sandbox_tools_dir": "/configured/sandbox-tools",
    }


def test_dir_watcher_logs_resolved_directory_details(tmp_path: Path) -> None:
    from backend.deepagent.dir_watcher import DirWatcher, logger as dir_logger

    watched_dir = tmp_path / "watched"
    watched_dir.mkdir()

    messages: list[str] = []
    sink_id = dir_logger.add(messages.append, format="{message}")
    try:
        watcher = DirWatcher()
        assert watcher.has_changed(str(watched_dir)) is False
        (watched_dir / "example.txt").write_text("content", encoding="utf-8")
        assert watcher.has_changed(str(watched_dir)) is True
    finally:
        dir_logger.remove(sink_id)

    assert any(str(watched_dir) in message for message in messages)
    assert any("added=" in message for message in messages)
