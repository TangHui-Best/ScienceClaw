from __future__ import annotations

import inspect
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Dict, Optional

from .blackboard import Blackboard
from .contract_compiler import ContractCompiler
from .contract_executor import ContractExecutor
from .contract_models import StepContract
from .contract_pipeline import ContractPipeline
from .contract_planner import plan_step_contract
from .contract_validator import validate_recording_step
from .snapshot_views import build_base_snapshot_from_legacy


class RPAContractAgent:
    """Contract-first agent wrapper around the plan/compile/execute/validate pipeline."""

    def __init__(
        self,
        planner: Optional[Callable[[str, Any, Blackboard], Any]] = None,
        compiler: Optional[Callable[[StepContract], Dict[str, Any]]] = None,
        executor: Optional[Callable[[StepContract, Dict[str, Any], Any, Blackboard], Any]] = None,
        validator: Optional[Callable[..., Any]] = None,
        snapshot_builder: Optional[Callable[[Any], Any]] = None,
    ):
        self.planner = planner
        self.compiler = compiler
        self.executor = executor
        self.validator = validator
        self.snapshot_builder = snapshot_builder

    async def run(
        self,
        session_id: str,
        page: Any,
        goal: str,
        board: Optional[Blackboard] = None,
        model_config: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        board = board or Blackboard()
        snapshot = await self._build_snapshot(page)
        planner = self.planner or self._default_planner(model_config)
        compiler = self.compiler or ContractCompiler().compile
        executor = self.executor or ContractExecutor(
            runtime_ai_executor=self._default_runtime_ai_executor(model_config)
        ).execute
        validator = self.validator or validate_recording_step

        pipeline = ContractPipeline(
            planner=planner,
            compiler=compiler,
            executor=executor,
            validator=validator,
        )

        yield {"event": "agent_message", "data": {"message": "Planning contract-first RPA step"}}
        result = await pipeline.run_step(goal, page=page, snapshot=snapshot, board=board)
        if not result.success or result.committed_step is None:
            yield {
                "event": "agent_aborted",
                "data": {
                    "message": result.message or "Contract-first RPA step failed",
                    "failure_class": result.failure_class.value if result.failure_class else None,
                    "failure_type": result.failure_type,
                    "recapture_required": result.recapture_required,
                },
            }
            return

        committed = result.committed_step
        yield {
            "event": "agent_contract_committed_steps",
            "data": {
                "contract_steps": [_committed_step_payload(committed)],
                "display_steps": [_display_step_payload(committed)],
                "blackboard": board.values,
            },
        }
        yield {
            "event": "agent_done",
            "data": {
                "message": "Contract-first RPA step committed",
                "step_count": 1,
            },
        }

    async def _build_snapshot(self, page: Any) -> Dict[str, Any]:
        if self.snapshot_builder:
            return await _maybe_await(self.snapshot_builder(page))

        from .assistant_runtime import build_frame_path_from_frame, build_page_snapshot

        legacy_snapshot = await build_page_snapshot(page, build_frame_path_from_frame)
        return build_base_snapshot_from_legacy(legacy_snapshot).semantic_view()

    @staticmethod
    def _default_planner(model_config: Optional[Dict[str, Any]]):
        async def planner(goal: str, snapshot: Any, board: Blackboard) -> StepContract:
            return await plan_step_contract(goal, snapshot, board.values, model_config=model_config)

        return planner

    @staticmethod
    def _default_runtime_ai_executor(model_config: Optional[Dict[str, Any]]):
        async def runtime_ai_executor(page: Any, contract: StepContract, artifact: Dict[str, Any], board: Blackboard) -> Any:
            from .runtime_ai_instruction import execute_ai_instruction

            runtime_step = {
                "action": "ai_instruction",
                "description": artifact.get("description") or contract.description,
                "prompt": artifact.get("prompt") or contract.description,
                "instruction_kind": artifact.get("instruction_kind") or contract.operator.type,
                "input_scope": artifact.get("input_scope") or {"mode": "current_page"},
                "output_expectation": {"mode": "extract", "schema": artifact.get("output_schema")},
                "execution_hint": {
                    "requires_dom_snapshot": True,
                    "allow_navigation": bool(artifact.get("allow_side_effect")),
                },
                "result_key": artifact.get("result_key") or contract.outputs.blackboard_key,
            }
            result = await execute_ai_instruction(
                page,
                runtime_step,
                results=board.values,
                model_config=model_config,
            )
            if isinstance(result, dict) and "output" in result:
                return result["output"]
            return result

        return runtime_ai_executor


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _committed_step_payload(committed_step) -> Dict[str, Any]:
    return {
        "contract": _jsonable(committed_step.contract.model_dump(by_alias=True)),
        "artifact": _jsonable(committed_step.artifact),
        "validation_evidence": _jsonable(committed_step.validation_evidence),
    }


def _display_step_payload(committed_step) -> Dict[str, Any]:
    contract = committed_step.contract
    return {
        "action": "contract_step",
        "source": "ai",
        "description": contract.description or contract.intent.goal,
        "tag": contract.operator.execution_strategy.value,
        "assistant_diagnostics": {
            "contract_id": contract.id,
            "execution_strategy": contract.operator.execution_strategy.value,
            "operator_type": contract.operator.type,
            "validation_evidence": _jsonable(committed_step.validation_evidence),
        },
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value
