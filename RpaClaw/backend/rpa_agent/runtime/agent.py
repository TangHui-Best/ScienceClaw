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
        asset_output_refs: Mapping[str, str] | None = None,
        required_paths: Mapping[str, tuple[str, ...]],
        variables: Mapping[str, object] | None = None,
        sensitive_data: Mapping[str, ResolvedSecret] | None = None,
        data_assets: Mapping[str, object] | None = None,
        step_id: str = "legacy_agent_step",
        scope_hint: Mapping[str, object] | None = None,
        expected_effects: tuple[Mapping[str, object], ...] = (),
        model_policy: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if self._backend is None:
            raise AgentExecutionError("agent.unavailable", "当前宿主未配置 AgentExecutor")
        if _contains_secret(inputs):
            raise AgentExecutionError("agent.secret_input_forbidden", "Secret 不得进入 Agent 上下文")
        secrets = dict(sensitive_data or {})
        if any(not isinstance(value, ResolvedSecret) for value in secrets.values()):
            raise AgentExecutionError("agent.sensitive_data_invalid", "Secret 必须由受控解析器提供")
        try:
            outputs = await self._backend(
                scope=scope,
                target=target,
                instruction=instruction,
                inputs=dict(inputs),
                output_names=tuple(output_names),
                asset_output_refs=dict(asset_output_refs or {}),
                required_paths={key: tuple(value) for key, value in required_paths.items()},
                variables=dict(variables or {}),
                sensitive_data=secrets,
                data_assets=dict(data_assets or {}),
                step_id=step_id,
                scope_hint=dict(scope_hint or {}),
                expected_effects=tuple(dict(item) for item in expected_effects),
                model_policy=dict(model_policy or {"mode": "runtime_default", "model_ref": None}),
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
