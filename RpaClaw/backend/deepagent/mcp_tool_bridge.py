from __future__ import annotations

from typing import Any, Mapping

from langchain_core.tools import StructuredTool
from pydantic import ConfigDict, create_model

from backend.deepagent.mcp_runtime import McpRuntime, McpToolDefinition, coerce_mcp_tool_definition
from backend.mcp.models import McpServerDefinition


def mcp_tool_name(server_id: str, tool_name: str) -> str:
    return f"mcp__{server_id}__{tool_name}"


def _build_args_schema(tool: McpToolDefinition) -> Any:
    schema = tool.input_schema or {}
    properties = schema.get("properties") if isinstance(schema, dict) else {}
    required = set(schema.get("required") or []) if isinstance(schema, dict) else set()

    if not isinstance(properties, dict) or not properties:
        return schema if isinstance(schema, dict) else {"type": "object"}

    fields: dict[str, tuple[Any, Any]] = {}
    for field_name, field_schema in properties.items():
        if not isinstance(field_name, str):
            continue
        field_schema = field_schema if isinstance(field_schema, dict) else {}
        annotation = _schema_to_annotation(field_schema)
        default = field_schema.get("default", None)
        if field_name in required:
            default = ...
        if default is None and annotation is not Any:
            annotation = annotation if _is_optional_annotation(annotation) else annotation | None
        fields[field_name] = (annotation, default)

    model_name = "".join(part.capitalize() for part in tool.name.split("_") if part) or "McpToolInput"
    model = create_model(  # type: ignore[call-overload]
        f"{model_name}Input",
        __config__=ConfigDict(extra="allow"),
        **fields,
    )
    return model


def _schema_to_annotation(schema: Mapping[str, Any]) -> Any:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        members = [_schema_to_annotation({"type": member}) for member in schema_type]
        return _combine_annotations(members)
    if schema_type == "string":
        return str
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        return list[Any]
    if schema_type == "object":
        return dict[str, Any]
    return Any


def _combine_annotations(members: list[Any]) -> Any:
    unique_members: list[Any] = []
    for member in members:
        if member not in unique_members:
            unique_members.append(member)
    if len(unique_members) == 1:
        return unique_members[0]
    return Any


def _is_optional_annotation(annotation: Any) -> bool:
    origin = getattr(annotation, "__origin__", None)
    if origin is None:
        return False
    return type(None) in getattr(annotation, "__args__", ())


def bridge_mcp_tool(
    *,
    server: McpServerDefinition,
    runtime: McpRuntime,
    tool: McpToolDefinition | Mapping[str, Any],
) -> StructuredTool:
    tool_def = coerce_mcp_tool_definition(tool)
    internal_name = mcp_tool_name(server.id, tool_def.name)
    args_schema = _build_args_schema(tool_def)
    tool_metadata = {
        "source": "mcp",
        "server_id": server.id,
        "server_key": f"{server.scope}:{server.id}",
        "server_name": server.name,
        "scope": server.scope,
        "transport": server.transport,
        "tool_name": tool_def.name,
        "tool_description": tool_def.description,
    }

    def _sync_call(**kwargs: Any) -> Any:
        raise RuntimeError("MCP bridged tools are async-only; use ainvoke()")

    async def _async_call(**kwargs: Any) -> Any:
        return await runtime.call_tool(tool_def.name, kwargs)

    return StructuredTool(
        name=internal_name,
        description=tool_def.description,
        func=_sync_call,
        coroutine=_async_call,
        args_schema=args_schema,
        metadata={"mcp": tool_metadata},
    )
