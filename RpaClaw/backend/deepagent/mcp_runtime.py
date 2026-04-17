from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from backend.mcp.models import McpServerDefinition


@dataclass(frozen=True)
class McpToolDefinition:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class McpRuntime(Protocol):
    async def list_tools(self) -> Sequence[McpToolDefinition | Mapping[str, Any]]: ...

    async def call_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> Any: ...


class McpRuntimeFactory(Protocol):
    def create_runtime(self, server: McpServerDefinition) -> McpRuntime: ...


class UnsupportedMcpRuntimeFactory:
    def create_runtime(self, server: McpServerDefinition) -> McpRuntime:
        raise RuntimeError(
            f"No MCP runtime factory is configured for server '{server.id}' "
            f"(transport={server.transport})"
        )


def coerce_mcp_tool_definition(tool: McpToolDefinition | Mapping[str, Any]) -> McpToolDefinition:
    if isinstance(tool, McpToolDefinition):
        return tool

    name = str(tool.get("name", "")).strip()
    description = str(tool.get("description", "") or "")
    input_schema = tool.get("input_schema") or tool.get("inputSchema") or {}
    if not isinstance(input_schema, dict):
        input_schema = {}

    return McpToolDefinition(
        name=name,
        description=description,
        input_schema=input_schema,
    )
