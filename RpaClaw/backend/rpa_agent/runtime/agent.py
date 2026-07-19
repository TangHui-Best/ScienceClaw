"""受控 Agent Action 执行边界。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from .results import RuntimeServiceError
from .variables import ResolvedSecret


class AgentExecutionError(RuntimeServiceError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(phase="action", code=code, safe_message=message)


class AgentExecutor:
    def __init__(self, backend: Callable[..., Awaitable[Mapping[str, object]]] | None) -> None:
        self._backend = backend

    async def execute(
        self,
        *,
        scope: object,
        target: object | None,
        instruction: str,
        inputs: Mapping[str, object],
        output_names: tuple[str, ...],
        required_paths: Mapping[str, tuple[str, ...]],
    ) -> dict[str, object]:
        if self._backend is None:
            raise AgentExecutionError("agent.unavailable", "当前宿主未配置 AgentExecutor")
        if _contains_secret(inputs):
            raise AgentExecutionError("agent.secret_input_forbidden", "Secret 不得进入 Agent 上下文")
        try:
            outputs = await self._backend(
                scope=scope,
                target=target,
                instruction=instruction,
                inputs=dict(inputs),
                output_names=tuple(output_names),
                required_paths={key: tuple(value) for key, value in required_paths.items()},
            )
        except Exception as exc:
            raise AgentExecutionError("agent.execution_failed", "Agent Action 执行失败") from exc
        if not isinstance(outputs, Mapping):
            raise AgentExecutionError("agent.result_invalid", "Agent 输出必须是对象")
        declared = set(output_names)
        actual = set(outputs)
        if actual - declared:
            raise AgentExecutionError("agent.output_undeclared", "Agent 返回了未声明输出")
        if declared - actual:
            raise AgentExecutionError("agent.output_missing", "Agent 未返回全部声明输出")
        result = dict(outputs)
        for output_name, paths in required_paths.items():
            if output_name not in declared:
                raise AgentExecutionError("agent.required_path_invalid", "required_paths 引用了未声明输出")
            for path in paths:
                if not _has_leaf(result[output_name], path):
                    raise AgentExecutionError("agent.required_path_missing", "Agent 输出缺少必需叶路径")
        return result


def _has_leaf(value: object, path: str) -> bool:
    current: object = value
    for segment in path.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return False
        current = current[segment]
    return True


def _contains_secret(value: object) -> bool:
    if isinstance(value, ResolvedSecret):
        return True
    if isinstance(value, Mapping):
        return any(_contains_secret(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_contains_secret(item) for item in value)
    return False
