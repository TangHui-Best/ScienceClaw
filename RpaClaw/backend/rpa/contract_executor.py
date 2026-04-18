from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from .blackboard import Blackboard, resolve_template
from .contract_models import ArtifactKind, StepContract


RuntimeAIExecutor = Callable[[Any, StepContract, Dict[str, Any], Blackboard], Awaitable[Any]]


class ExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    output: Any = None
    evidence: Dict[str, Any] = field(default_factory=dict)


class ContractExecutor:
    def __init__(self, runtime_ai_executor: Optional[RuntimeAIExecutor] = None):
        self.runtime_ai_executor = runtime_ai_executor

    async def execute(
        self,
        contract: StepContract,
        artifact: Dict[str, Any],
        page: Any,
        board: Blackboard,
    ) -> ExecutionResult:
        kind = _artifact_kind(artifact)
        if kind == ArtifactKind.PRIMITIVE_ACTION.value:
            return await self._execute_primitive(contract, artifact, page, board)
        if kind == ArtifactKind.DETERMINISTIC_SCRIPT.value:
            return await self._execute_deterministic_script(contract, artifact, page, board)
        if kind == ArtifactKind.RUNTIME_AI.value:
            return await self._execute_runtime_ai(contract, artifact, page, board)
        raise ExecutionError(f"unknown artifact kind: {kind}")

    async def _execute_primitive(
        self,
        contract: StepContract,
        artifact: Dict[str, Any],
        page: Any,
        board: Blackboard,
    ) -> ExecutionResult:
        action = artifact.get("action")
        evidence: Dict[str, Any] = {"action": action}

        if action == "goto":
            template = artifact.get("target_url_template") or contract.target.url_template
            if not isinstance(template, str) or not template:
                raise ExecutionError("goto artifact requires target_url_template")
            url = resolve_template(template, board)
            await page.goto(url, wait_until="domcontentloaded")
            if hasattr(page, "wait_for_load_state"):
                await page.wait_for_load_state("domcontentloaded")
            evidence["url"] = url
            return ExecutionResult(success=True, output=url, evidence=evidence)

        locator_payload = artifact.get("locator")
        locator = _resolve_page_locator(page, locator_payload)
        if action == "click":
            await locator.click()
            evidence["action_performed"] = True
            return ExecutionResult(success=True, evidence=evidence)
        if action == "fill":
            value = resolve_template(str(artifact.get("value_template") or ""), board)
            await locator.fill(value)
            evidence["value"] = value
            evidence["action_performed"] = True
            return ExecutionResult(success=True, evidence=evidence)
        if action == "extract_text":
            value = await locator.inner_text()
            result_key = artifact.get("result_key") or contract.outputs.blackboard_key
            if result_key:
                board.write(result_key, value, schema=contract.outputs.schema_value)
            return ExecutionResult(success=True, output=value, evidence=evidence)

        raise ExecutionError(f"unsupported primitive action: {action}")

    async def _execute_deterministic_script(
        self,
        contract: StepContract,
        artifact: Dict[str, Any],
        page: Any,
        board: Blackboard,
    ) -> ExecutionResult:
        code = artifact.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ExecutionError("deterministic script artifact has no code")

        namespace: Dict[str, Any] = {}
        exec(code, namespace, namespace)
        runner = namespace.get("run")
        if not callable(runner):
            raise ExecutionError("deterministic script must define run(page, board)")

        output = runner(page, board)
        if inspect.isawaitable(output):
            output = await output

        result_key = artifact.get("result_key") or contract.outputs.blackboard_key
        if result_key:
            _validate_schema(output, contract.outputs.schema_value)
            board.write(result_key, output, schema=contract.outputs.schema_value)

        return ExecutionResult(
            success=True,
            output=output,
            evidence={"action": "deterministic_script", "result_key": result_key},
        )

    async def _execute_runtime_ai(
        self,
        contract: StepContract,
        artifact: Dict[str, Any],
        page: Any,
        board: Blackboard,
    ) -> ExecutionResult:
        if self.runtime_ai_executor is None:
            raise ExecutionError("runtime_ai executor is not configured")

        output = await self.runtime_ai_executor(page, contract, artifact, board)
        allow_side_effect = bool(artifact.get("allow_side_effect")) or contract.runtime_policy.allow_side_effect
        if not allow_side_effect and _has_side_effect_evidence(output):
            raise ExecutionError("runtime_ai returned side-effect evidence but side effects are not allowed")

        schema = artifact.get("output_schema") or contract.outputs.schema_value
        _validate_schema(output, schema)
        result_key = artifact.get("result_key") or contract.outputs.blackboard_key
        if result_key:
            board.write(result_key, output, schema=schema)

        return ExecutionResult(
            success=True,
            output=output,
            evidence={"action": "runtime_ai", "result_key": result_key},
        )


def _artifact_kind(artifact: Dict[str, Any]) -> str:
    kind = artifact.get("kind")
    if isinstance(kind, ArtifactKind):
        return kind.value
    return str(kind or "")


def _has_side_effect_evidence(output: Any) -> bool:
    if not isinstance(output, dict):
        return False
    return any(
        bool(output.get(key))
        for key in ("action_performed", "side_effect_performed", "navigation_performed")
    )


def _validate_schema(value: Any, schema: Any) -> None:
    if schema is None:
        return
    if not isinstance(schema, dict):
        return

    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            raise ExecutionError("output does not match object schema")
        for field in schema.get("required") or []:
            if field not in value:
                raise ExecutionError(f"output is missing required field: {field}")
    elif expected_type == "array":
        if not isinstance(value, list):
            raise ExecutionError("output does not match array schema")
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        required = item_schema.get("required") or []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise ExecutionError(f"array item {index} is not an object")
            for field in required:
                if field not in item:
                    raise ExecutionError(f"array item {index} is missing required field: {field}")


def _resolve_page_locator(page: Any, payload: Dict[str, Any]) -> Any:
    if not isinstance(payload, dict):
        raise ExecutionError("locator payload is required")
    method = payload.get("method")
    if method == "role" or (method is None and payload.get("role")):
        kwargs = {"name": payload.get("name")} if payload.get("name") else {}
        if "exact" in payload:
            kwargs["exact"] = payload.get("exact")
        return page.get_by_role(payload.get("role"), **kwargs)
    if method == "text":
        kwargs = {"exact": payload.get("exact")} if "exact" in payload else {}
        return page.get_by_text(payload.get("value", ""), **kwargs)
    if method == "nested":
        parent = _resolve_page_locator(page, payload.get("parent") or {})
        return _resolve_page_locator(parent, payload.get("child") or {})
    if hasattr(page, "locator"):
        return page.locator(payload.get("value", "body"))
    raise ExecutionError(f"unsupported locator payload: {payload}")
