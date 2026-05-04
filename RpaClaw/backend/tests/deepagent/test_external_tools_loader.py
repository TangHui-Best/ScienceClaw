from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any
from typing import get_args, get_origin

from backend.deepagent.external_tools_loader import ExternalToolsLoader, parse_tool_file


class DummyExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute(self, *, tool_path: str, function_name: str, arguments: dict[str, Any]) -> Any:
        call = {
            "tool_path": tool_path,
            "function_name": function_name,
            "arguments": arguments,
        }
        self.calls.append(call)
        return call


def test_parse_tool_file_extracts_metadata(tmp_path: Path) -> None:
    tool_file = tmp_path / "example_tool.py"
    tool_file.write_text(
        """
from typing import Optional
from langchain_core.tools import tool


@tool
def summarize(topic: str, max_items: int = 3, verbose: bool = False, note: Optional[str] = None) -> str:
    \"\"\"Summarize a topic.\"\"\"
    return topic
""".strip(),
        encoding="utf-8",
    )

    metadata = parse_tool_file(tool_file)

    assert metadata is not None
    assert metadata.function_name == "summarize"
    assert metadata.description == "Summarize a topic."
    assert metadata.file_path == tool_file
    assert [parameter.name for parameter in metadata.parameters] == [
        "topic",
        "max_items",
        "verbose",
        "note",
    ]
    assert metadata.parameters[0].annotation is str
    assert metadata.parameters[0].default is ...
    assert metadata.parameters[1].annotation is int
    assert metadata.parameters[1].default == 3
    assert metadata.parameters[2].annotation is bool
    assert metadata.parameters[2].default is False
    assert metadata.parameters[3].default is None


def test_parse_tool_file_supports_keyword_only_and_pep604_optional(tmp_path: Path) -> None:
    tool_file = tmp_path / "advanced_tool.py"
    tool_file.write_text(
        """
from langchain_core.tools import tool


@tool
def summarize(topic: str, *, note: str | None = None, limit: int = 10) -> str:
    \"\"\"Summarize with options.\"\"\"
    return topic
""".strip(),
        encoding="utf-8",
    )

    metadata = parse_tool_file(tool_file)

    assert metadata is not None
    assert [parameter.name for parameter in metadata.parameters] == ["topic", "note", "limit"]
    note_annotation = metadata.parameters[1].annotation
    assert type(None) in get_args(note_annotation)
    assert str in get_args(note_annotation)
    assert metadata.parameters[1].default is None
    assert metadata.parameters[2].annotation is int
    assert metadata.parameters[2].default == 10


def test_external_tools_loader_skips_tools_with_positional_only_parameters(tmp_path: Path) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "positional_only.py").write_text(
        """
from langchain_core.tools import tool


@tool
def positional_only(query: str, /, limit: int = 5) -> str:
    \"\"\"Cannot be called via keyword proxy.\"\"\"
    return query
""".strip(),
        encoding="utf-8",
    )

    assert parse_tool_file(tools_dir / "positional_only.py") is None

    executor = DummyExecutor()
    loader = ExternalToolsLoader(tools_dir=tools_dir, executor=executor)

    assert loader.reload(force=True) == []


def test_external_tools_loader_skips_tools_with_varargs_or_kwargs(tmp_path: Path) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "variadic.py").write_text(
        """
from langchain_core.tools import tool


@tool
def variadic(*parts: str, **options: str) -> str:
    \"\"\"Cannot be called via keyword-only proxy.\"\"\"
    return ",".join(parts)
""".strip(),
        encoding="utf-8",
    )

    assert parse_tool_file(tools_dir / "variadic.py") is None

    executor = DummyExecutor()
    loader = ExternalToolsLoader(tools_dir=tools_dir, executor=executor)

    assert loader.reload(force=True) == []


def test_parse_tool_file_ignores_non_module_level_tools(tmp_path: Path) -> None:
    tool_file = tmp_path / "nested_tool.py"
    tool_file.write_text(
        """
from langchain_core.tools import tool


class ToolBox:
    @tool
    def nested(self, query: str) -> str:
        \"\"\"Should not be exposed.\"\"\"
        return query
""".strip(),
        encoding="utf-8",
    )

    assert parse_tool_file(tool_file) is None


def test_external_tools_loader_scans_and_builds_proxy_tools(tmp_path: Path) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "alpha.py").write_text(
        """
from langchain_core.tools import tool


@tool
def alpha(query: str, limit: int = 5) -> str:
    \"\"\"Run alpha lookup.\"\"\"
    return query
""".strip(),
        encoding="utf-8",
    )
    (tools_dir / "ignored.py").write_text("def noop() -> None:\n    pass\n", encoding="utf-8")

    executor = DummyExecutor()
    loader = ExternalToolsLoader(tools_dir=tools_dir, executor=executor)

    tools = loader.reload(force=True)

    assert [tool.name for tool in tools] == ["alpha"]
    alpha_tool = tools[0]
    result = alpha_tool.invoke({"query": "cells", "limit": 2})

    assert result == {
        "tool_path": str(tools_dir / "alpha.py"),
        "function_name": "alpha",
        "arguments": {"query": "cells", "limit": 2},
    }
    assert executor.calls == [result]

    schema = alpha_tool.args_schema.model_fields
    assert schema["query"].is_required()
    assert schema["limit"].default == 5


def test_external_tools_loader_includes_keyword_only_parameters(tmp_path: Path) -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "advanced.py").write_text(
        """
from langchain_core.tools import tool


@tool
def advanced(query: str, *, note: str | None = None, limit: int = 10) -> str:
    \"\"\"Advanced lookup.\"\"\"
    return query
""".strip(),
        encoding="utf-8",
    )

    executor = DummyExecutor()
    loader = ExternalToolsLoader(tools_dir=tools_dir, executor=executor)

    tools = loader.reload(force=True)

    assert [tool.name for tool in tools] == ["advanced"]
    advanced_tool = tools[0]
    schema = advanced_tool.args_schema.model_fields
    assert schema["query"].is_required()
    assert schema["note"].default is None
    assert schema["limit"].default == 10

    result = advanced_tool.invoke({"query": "cells", "note": "brief", "limit": 2})

    assert result["arguments"] == {"query": "cells", "note": "brief", "limit": 2}


def test_tools_compat_loader_uses_configured_tools_dir(tmp_path: Path, monkeypatch) -> None:
    configured_tools_dir = tmp_path / "configured-tools"
    configured_tools_dir.mkdir()
    repo_root = Path(__file__).resolve().parents[4]
    configured_sandbox_tools_dir = "/configured/sandbox-tools"

    import backend.config as backend_config
    import backend.deepagent.external_tools_loader as loader_module

    calls: list[dict[str, Any]] = []

    class FakeLoader:
        def __init__(self, *, tools_dir: str | Path, executor: Any) -> None:
            calls.append({"tools_dir": Path(tools_dir), "executor": executor})

        def reload(self, force: bool = False) -> list[Any]:
            calls.append({"force": force})
            return []

    monkeypatch.setattr(backend_config.settings, "tools_dir", str(configured_tools_dir))
    monkeypatch.setattr(backend_config.settings, "sandbox_tools_dir", configured_sandbox_tools_dir)
    monkeypatch.setattr(loader_module, "ExternalToolsLoader", FakeLoader)
    monkeypatch.syspath_prepend(str(repo_root))
    sys.modules.pop("Tools", None)

    tools_module = importlib.import_module("Tools")

    assert calls[0]["tools_dir"] == configured_tools_dir
    assert calls[1] == {"force": True}
    assert tools_module.external_tools == []
    captured: dict[str, Any] = {}

    def fake_execute_in_sandbox(command: str, timeout: int = 120) -> str:
        captured["command"] = command
        return "stdout\n>>>TOOL_RESULT_JSON>>>\n{\"ok\": true}\n<<<TOOL_RESULT_JSON<<<\n"

    monkeypatch.setattr(tools_module, "_execute_in_sandbox", fake_execute_in_sandbox)
    spaced_tool_path = configured_tools_dir / "sample tool.py"
    result = calls[0]["executor"].execute(
        tool_path=str(spaced_tool_path),
        function_name="sample",
        arguments={"query": "cells"},
    )

    assert "'/configured/sandbox-tools/sample tool.py'" in captured["command"]
    assert result["result"] == {"ok": True}
    sys.modules.pop("Tools", None)
