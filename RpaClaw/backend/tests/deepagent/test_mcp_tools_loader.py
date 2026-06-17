from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from backend.deepagent.mcp_tool_bridge import bridge_mcp_tool, mcp_tool_name
from backend.deepagent.mcp_tools_loader import load_mcp_tools
from backend.deepagent.mcp_runtime import McpToolDefinition
from backend.mcp.models import McpServerDefinition, McpToolPolicy


@dataclass
class FakeRuntime:
    tools: list[McpToolDefinition | dict[str, Any]] = field(default_factory=list)
    call_result: Any = None
    discovery_error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    bound_loop: asyncio.AbstractEventLoop | None = None

    async def list_tools(self):
        if self.discovery_error is not None:
            raise self.discovery_error
        self.bound_loop = asyncio.get_running_loop()
        return self.tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        current_loop = asyncio.get_running_loop()
        if self.bound_loop is None:
            self.bound_loop = current_loop
        assert current_loop is self.bound_loop
        self.calls.append({"tool_name": tool_name, "arguments": arguments})
        return self.call_result


class FakeRuntimeFactory:
    def __init__(self, runtimes: dict[str, FakeRuntime]) -> None:
        self.runtimes = runtimes
        self.requests: list[str] = []

    def create_runtime(self, server: McpServerDefinition) -> FakeRuntime:
        self.requests.append(server.id)
        return self.runtimes[server.id]


def test_bridge_maps_tool_name_and_preserves_metadata():
    server = McpServerDefinition(
        id="pubmed",
        name="PubMed",
        transport="streamable_http",
        scope="system",
        url="https://example.test/mcp",
    )
    runtime = FakeRuntime(
        tools=[
            McpToolDefinition(
                name="search",
                description="Search PubMed",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )
        ],
        call_result={"ok": True},
    )

    tool = bridge_mcp_tool(server=server, runtime=runtime, tool=runtime.tools[0])

    assert tool.name == mcp_tool_name("pubmed", "search")
    assert tool.metadata["mcp"] == {
        "source": "mcp",
        "server_id": "pubmed",
        "server_key": "system:pubmed",
        "server_name": "PubMed",
        "scope": "system",
        "transport": "streamable_http",
        "tool_name": "search",
        "tool_description": "Search PubMed",
    }


def test_bridge_preserves_raw_payload_for_propertyless_object_schema():
    server = McpServerDefinition(
        id="pubmed",
        name="PubMed",
        transport="streamable_http",
        scope="system",
        url="https://example.test/mcp",
    )
    runtime = FakeRuntime(
        tools=[
            McpToolDefinition(
                name="search",
                description="Search PubMed",
                input_schema={
                    "type": "object",
                    "additionalProperties": True,
                },
            )
        ],
        call_result={"ok": True},
    )

    tool = bridge_mcp_tool(server=server, runtime=runtime, tool=runtime.tools[0])
    result = asyncio.run(tool.ainvoke({"query": "cells", "limit": 2}))

    assert result == {"ok": True}
    assert runtime.calls == [
        {
            "tool_name": "search",
            "arguments": {"query": "cells", "limit": 2},
        }
    ]


def test_loader_applies_tool_policy_filtering():
    server = McpServerDefinition(
        id="pubmed",
        name="PubMed",
        transport="streamable_http",
        scope="system",
        url="https://example.test/mcp",
        tool_policy=McpToolPolicy(
            allowed_tools=["search", "lookup"],
            blocked_tools=["lookup"],
        ),
    )
    runtime = FakeRuntime(
        tools=[
            McpToolDefinition(
                name="search",
                description="Search",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            ),
            McpToolDefinition(
                name="lookup",
                description="Lookup",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            ),
            McpToolDefinition(
                name="delete",
                description="Delete",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            ),
        ]
    )

    tools = asyncio.run(load_mcp_tools([server], runtime_factory=FakeRuntimeFactory({server.id: runtime})))

    assert [tool.name for tool in tools] == [mcp_tool_name("pubmed", "search")]


def test_loader_is_fail_soft_when_one_server_breaks():
    broken_server = McpServerDefinition(
        id="broken",
        name="Broken",
        transport="sse",
        scope="system",
        url="https://example.test/broken",
    )
    healthy_server = McpServerDefinition(
        id="healthy",
        name="Healthy",
        transport="streamable_http",
        scope="system",
        url="https://example.test/healthy",
    )
    runtimes = {
        "broken": FakeRuntime(discovery_error=RuntimeError("boom")),
        "healthy": FakeRuntime(
            tools=[
                McpToolDefinition(
                    name="search",
                    description="Search",
                    input_schema={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                )
            ]
        ),
    }

    tools = asyncio.run(
        load_mcp_tools(
            [broken_server, healthy_server],
            runtime_factory=FakeRuntimeFactory(runtimes),
        )
    )

    assert [tool.name for tool in tools] == [mcp_tool_name("healthy", "search")]


def test_loader_logs_redacted_context_without_exception_text(caplog):
    failing_server = McpServerDefinition(
        id="broken",
        name="Broken",
        transport="sse",
        scope="system",
        url="https://example.test/broken",
    )

    class ExplodingFactory:
        def create_runtime(self, server: McpServerDefinition):
            raise RuntimeError("secret-token-123")

    caplog.set_level("WARNING")

    tools = asyncio.run(load_mcp_tools([failing_server], runtime_factory=ExplodingFactory()))

    assert tools == []
    assert "secret-token-123" not in caplog.text
    assert "Discovery failed for server broken (sse)" in caplog.text


def test_loader_logs_redacted_bridge_failures_without_exception_text(caplog, monkeypatch):
    server = McpServerDefinition(
        id="pubmed",
        name="PubMed",
        transport="streamable_http",
        scope="system",
        url="https://example.test/mcp",
    )
    runtime = FakeRuntime(
        tools=[{"name": "search", "description": "Search"}],
    )

    def exploding_bridge(*, server: McpServerDefinition, runtime: FakeRuntime, tool: Any):
        raise RuntimeError("secret-query-value")

    caplog.set_level("WARNING")
    monkeypatch.setattr("backend.deepagent.mcp_tools_loader.bridge_mcp_tool", exploding_bridge)

    tools = asyncio.run(load_mcp_tools([server], runtime_factory=FakeRuntimeFactory({server.id: runtime})))

    assert tools == []
    assert "secret-query-value" not in caplog.text
    assert "Tool bridge failed for server pubmed tool 'search'" in caplog.text


def test_bridged_tool_rejects_sync_invocation():
    server = McpServerDefinition(
        id="pubmed",
        name="PubMed",
        transport="streamable_http",
        scope="system",
        url="https://example.test/mcp",
    )
    runtime = FakeRuntime(
        tools=[
            McpToolDefinition(
                name="search",
                description="Search PubMed",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            )
        ],
        call_result={"hits": 3},
    )

    tool = bridge_mcp_tool(server=server, runtime=runtime, tool=runtime.tools[0])

    with pytest.raises(RuntimeError, match="async-only"):
        tool.invoke({"query": "cancer", "limit": 5})

    assert runtime.calls == []


def test_bridged_tool_forwards_arguments_and_result():
    server = McpServerDefinition(
        id="pubmed",
        name="PubMed",
        transport="streamable_http",
        scope="system",
        url="https://example.test/mcp",
    )
    runtime = FakeRuntime(
        tools=[
            McpToolDefinition(
                name="search",
                description="Search PubMed",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            )
        ],
        call_result={"hits": 3},
    )

    async def run_flow():
        tools = await load_mcp_tools([server], runtime_factory=FakeRuntimeFactory({server.id: runtime}))
        tool = tools[0]
        return await tool.ainvoke({"query": "cancer", "limit": 5})

    result = asyncio.run(run_flow())

    assert result == {"hits": 3}
    assert runtime.calls == [
        {
            "tool_name": "search",
            "arguments": {"query": "cancer", "limit": 5},
        }
    ]
