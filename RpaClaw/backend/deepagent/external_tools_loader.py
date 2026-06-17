from __future__ import annotations

import ast
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from types import NoneType
from typing import Any, Optional, Protocol, Union

from langchain_core.tools import StructuredTool
from pydantic import Field, create_model

logger = logging.getLogger(__name__)


class ToolExecutor(Protocol):
    def execute(self, *, tool_path: str, function_name: str, arguments: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class ToolParameterMetadata:
    name: str
    annotation: Any
    default: Any = ...


@dataclass(frozen=True)
class ToolMetadata:
    function_name: str
    description: str
    file_path: Path
    parameters: list[ToolParameterMetadata]


_SIMPLE_TYPES: dict[str, Any] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "dict": dict,
    "list": list,
    "Dict": dict,
    "List": list,
    "Any": Any,
}


def _resolve_type(node: ast.expr | None) -> Any:
    if node is None:
        return str
    if isinstance(node, ast.Name):
        return _SIMPLE_TYPES.get(node.id, Any)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _resolve_type(node.left)
        right = _resolve_type(node.right)
        if left is Any or right is Any:
            return Any
        members = _flatten_union_members(left) + _flatten_union_members(right)
        return _build_union_type(members)
    if isinstance(node, ast.Subscript):
        if isinstance(node.value, ast.Name):
            base = node.value.id
            if base in {"Dict", "dict"}:
                return dict
            if base in {"List", "list"}:
                return list
            if base == "Optional":
                return Optional[_resolve_type(node.slice)]
        return Any
    if isinstance(node, ast.Attribute):
        return Any
    if isinstance(node, ast.Constant):
        return type(node.value)
    return Any


def _flatten_union_members(annotation: Any) -> list[Any]:
    args = getattr(annotation, "__args__", None)
    if args:
        return [member for arg in args for member in _flatten_union_members(arg)]
    return [annotation]


def _build_union_type(members: list[Any]) -> Any:
    unique_members: list[Any] = []
    for member in members:
        if member not in unique_members:
            unique_members.append(member)

    if len(unique_members) == 1:
        return unique_members[0]

    non_none_members = [member for member in unique_members if member is not NoneType]
    has_none = len(non_none_members) != len(unique_members)
    if has_none and len(non_none_members) == 1:
        return Optional[non_none_members[0]]

    return Union[tuple(unique_members)]


def _resolve_default(node: ast.expr) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id == "None":
        return None
    if isinstance(node, ast.List):
        return []
    if isinstance(node, ast.Dict):
        return {}
    return ...


def parse_tool_file(file_path: str | Path) -> ToolMetadata | None:
    path = Path(file_path)
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except Exception as exc:
        logger.warning("[ExternalToolsLoader] AST parse failed for %s: %s", path, exc)
        return None

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue

        has_tool_decorator = any(
            (isinstance(decorator, ast.Name) and decorator.id == "tool")
            or (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
                and decorator.func.id == "tool"
            )
            for decorator in node.decorator_list
        )
        if not has_tool_decorator:
            continue

        if node.args.posonlyargs or node.args.vararg is not None or node.args.kwarg is not None:
            logger.warning(
                "[ExternalToolsLoader] Skipping %s in %s because variadic or positional-only parameters are unsupported",
                node.name,
                path,
            )
            return None

        parameters: list[ToolParameterMetadata] = []
        positional_args = list(node.args.args)
        total_args = len(positional_args)
        total_defaults = len(node.args.defaults)
        for index, arg in enumerate(positional_args):
            if arg.arg == "self":
                continue
            default_index = index - (total_args - total_defaults)
            default = _resolve_default(node.args.defaults[default_index]) if default_index >= 0 else ...
            parameters.append(
                ToolParameterMetadata(
                    name=arg.arg,
                    annotation=_resolve_type(arg.annotation),
                    default=default,
                )
            )
        for arg, default_node in zip(node.args.kwonlyargs, node.args.kw_defaults):
            if arg.arg == "self":
                continue
            default = _resolve_default(default_node) if default_node is not None else ...
            parameters.append(
                ToolParameterMetadata(
                    name=arg.arg,
                    annotation=_resolve_type(arg.annotation),
                    default=default,
                )
            )

        return ToolMetadata(
            function_name=node.name,
            description=ast.get_docstring(node) or f"Tool: {node.name}",
            file_path=path,
            parameters=parameters,
        )

    return None


class ExternalToolsLoader:
    def __init__(self, *, tools_dir: str | Path, executor: ToolExecutor) -> None:
        self._tools_dir = Path(tools_dir)
        self._executor = executor
        self._lock = threading.Lock()
        self._cached_tools: list[StructuredTool] = []

    def reload(self, force: bool = False) -> list[StructuredTool]:
        changed = True
        try:
            from backend.deepagent.dir_watcher import watcher

            changed = watcher.has_changed(str(self._tools_dir))
        except ImportError:
            changed = True

        if not force and not changed and self._cached_tools:
            return self._cached_tools

        with self._lock:
            if not force and not changed and self._cached_tools:
                return self._cached_tools
            self._cached_tools = self._scan()
            logger.info(
                "[ExternalToolsLoader] Loaded %s tools from %s: %s",
                len(self._cached_tools),
                self._tools_dir,
                [tool.name for tool in self._cached_tools],
            )
            return self._cached_tools

    def _scan(self) -> list[StructuredTool]:
        tools: list[StructuredTool] = []
        if not self._tools_dir.is_dir():
            return tools

        for py_file in sorted(self._tools_dir.glob("*.py")):
            if py_file.name.startswith("_") or py_file.name == "__init__.py":
                continue

            metadata = parse_tool_file(py_file)
            if metadata is None:
                logger.warning("[ExternalToolsLoader] No @tool found in %s, skipping", py_file.name)
                continue

            try:
                tools.append(self._build_proxy_tool(metadata))
            except Exception as exc:
                logger.warning(
                    "[ExternalToolsLoader] Proxy creation failed for %s: %s",
                    py_file.name,
                    exc,
                )
        return tools

    def _build_proxy_tool(self, metadata: ToolMetadata) -> StructuredTool:
        fields: dict[str, tuple[Any, Any]] = {}
        for parameter in metadata.parameters:
            if parameter.default is ...:
                fields[parameter.name] = (parameter.annotation, ...)
            elif parameter.default is None:
                fields[parameter.name] = (Optional[parameter.annotation], Field(default=None))
            else:
                fields[parameter.name] = (parameter.annotation, Field(default=parameter.default))

        input_model = create_model(f"{metadata.function_name}_input", **fields)

        def _proxy_run(**kwargs: Any) -> Any:
            return self._executor.execute(
                tool_path=str(metadata.file_path),
                function_name=metadata.function_name,
                arguments=kwargs,
            )

        return StructuredTool(
            name=metadata.function_name,
            description=metadata.description,
            func=_proxy_run,
            args_schema=input_model,
        )
