from __future__ import annotations

import logging
from typing import Sequence

from langchain_core.tools import StructuredTool

from backend.deepagent.mcp_runtime import (
    McpRuntime,
    McpRuntimeFactory,
    McpToolDefinition,
    UnsupportedMcpRuntimeFactory,
    coerce_mcp_tool_definition,
)
from backend.deepagent.mcp_tool_bridge import bridge_mcp_tool
from backend.mcp.models import McpServerDefinition

logger = logging.getLogger(__name__)


def _tool_allowed(server: McpServerDefinition, tool_name: str) -> bool:
    policy = server.tool_policy
    allowed = set(policy.allowed_tools or [])
    blocked = set(policy.blocked_tools or [])

    if allowed and tool_name not in allowed:
        return False
    if tool_name in blocked:
        return False
    return True


async def load_mcp_tools(
    servers: Sequence[McpServerDefinition],
    *,
    runtime_factory: McpRuntimeFactory | None = None,
) -> list[StructuredTool]:
    factory = runtime_factory or UnsupportedMcpRuntimeFactory()
    bridged_tools: list[StructuredTool] = []

    for server in servers:
        try:
            runtime = factory.create_runtime(server)
            discovered_tools = await runtime.list_tools()
        except Exception:
            logger.warning(
                "[MCPToolsLoader] Discovery failed for server %s (%s)",
                server.id,
                server.transport,
            )
            continue

        for raw_tool in discovered_tools:
            try:
                tool_def = coerce_mcp_tool_definition(raw_tool)
                if not tool_def.name:
                    raise ValueError("tool name is required")
                if not _tool_allowed(server, tool_def.name):
                    continue
                bridged_tools.append(
                    bridge_mcp_tool(
                        server=server,
                        runtime=runtime,
                        tool=tool_def,
                    )
                )
            except Exception:
                logger.warning(
                    "[MCPToolsLoader] Tool bridge failed for server %s tool %r",
                    server.id,
                    getattr(raw_tool, "name", None) if not isinstance(raw_tool, dict) else raw_tool.get("name"),
                )
                continue

    return bridged_tools
