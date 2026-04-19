from __future__ import annotations

import inspect
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Dict, Optional

from .blackboard import Blackboard
from .contract_compiler import ContractCompiler
from .contract_executor import ContractExecutor
from .contract_models import PlannerEnvelope, PlannerStatus, StepContract
from .contract_pipeline import ContractPipeline
from .contract_planner import plan_next_step_envelope
from .contract_validator import validate_recording_step
from .snapshot_views import build_base_snapshot_from_legacy


MAX_PLANNER_REPAIR_ATTEMPTS = 2


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

        committed_steps = []
        while True:
            repair_feedback = ""
            envelope = None
            pipeline_result = None
            for attempt_index in range(MAX_PLANNER_REPAIR_ATTEMPTS):
                yield {
                    "event": "agent_message",
                    "data": {
                        "message": (
                            "Planning contract-first RPA step"
                            if attempt_index == 0
                            else "Repairing contract-first RPA step after invalid planner/compiler output"
                        )
                    },
                }
                planner_goal = _goal_with_repair_feedback(goal, repair_feedback)
                try:
                    planned = await _maybe_await(planner(planner_goal, snapshot, board))
                    envelope = _normalize_planner_envelope(planned)
                except Exception as exc:
                    if attempt_index + 1 < MAX_PLANNER_REPAIR_ATTEMPTS:
                        repair_feedback = str(exc)
                        continue
                    yield {
                        "event": "agent_aborted",
                        "data": {
                            "message": str(exc) or "Planner failed to produce a valid contract",
                            "failure_class": None,
                            "failure_type": "planner_failed",
                            "recapture_required": False,
                        },
                    }
                    return

                if envelope.status == PlannerStatus.DONE:
                    yield {
                        "event": "agent_done",
                        "data": {
                            "message": envelope.message or "Contract-first RPA step committed",
                            "step_count": len(committed_steps),
                            "total_steps": len(committed_steps),
                        },
                    }
                    return

                if envelope.status == PlannerStatus.NEED_USER:
                    yield {
                        "event": "agent_need_user",
                        "data": {
                            "message": envelope.message or "Manual browser action is required to continue.",
                            "step_count": len(committed_steps),
                            "total_steps": len(committed_steps),
                        },
                    }
                    return

                contract = envelope.current_step
                if contract is None:
                    if attempt_index + 1 < MAX_PLANNER_REPAIR_ATTEMPTS:
                        repair_feedback = "Planner returned next_step without current_step"
                        continue
                    yield {
                        "event": "agent_aborted",
                        "data": {
                            "message": "Planner returned next_step without a contract",
                            "failure_class": None,
                            "failure_type": "planner_failed",
                            "recapture_required": False,
                        },
                    }
                    return

                yield {
                    "event": "agent_thought",
                    "data": {
                        "text": _contract_thought_text(contract),
                        "contract_id": contract.id,
                        "execution_strategy": contract.operator.execution_strategy.value,
                        "operator_type": contract.operator.type,
                    },
                }
                pipeline = ContractPipeline(
                    planner=lambda _goal, _snapshot, _board, planned_contract=contract: planned_contract,
                    compiler=compiler,
                    executor=executor,
                    validator=validator,
                )
                try:
                    preview_artifact = await _maybe_await(compiler(contract))
                    yield {
                        "event": "agent_action",
                        "data": {
                            "description": contract.description or contract.intent.goal,
                            "code": _artifact_preview(preview_artifact),
                            "execution_strategy": contract.operator.execution_strategy.value,
                            "operator_type": contract.operator.type,
                        },
                    }
                except Exception:
                    pass
                pipeline_result = await pipeline.run_step(goal, page=page, snapshot=snapshot, board=board)
                if pipeline_result.success and pipeline_result.committed_step is not None:
                    break
                if (
                    attempt_index + 1 < MAX_PLANNER_REPAIR_ATTEMPTS
                    and (
                        pipeline_result.failure_type in {"compiler_failed", "planner_failed"}
                        or _is_repairable_execution_failure(pipeline_result)
                    )
                ):
                    repair_feedback = _build_pipeline_repair_feedback(pipeline_result)
                    continue
                yield {
                    "event": "agent_aborted",
                    "data": {
                        "message": pipeline_result.message or "Contract-first RPA step failed",
                        "failure_class": pipeline_result.failure_class.value if pipeline_result.failure_class else None,
                        "failure_type": pipeline_result.failure_type,
                        "recapture_required": pipeline_result.recapture_required,
                        "attempt": _attempt_payload(pipeline_result.attempt),
                    },
                }
                return

            if pipeline_result is None or not pipeline_result.success or pipeline_result.committed_step is None:
                yield {
                    "event": "agent_aborted",
                    "data": {
                        "message": "Planner repair attempts were exhausted",
                        "failure_class": None,
                        "failure_type": "planner_failed",
                        "recapture_required": False,
                    },
                }
                return

            committed_steps = _merge_committed_step(committed_steps, pipeline_result.committed_step)
            yield {
                "event": "agent_step_done",
                "data": {
                    "output": _step_done_output(pipeline_result),
                    "contract_id": pipeline_result.committed_step.contract.id,
                    "step_count": len(committed_steps),
                    "total_steps": len(committed_steps),
                },
            }
            yield {
                "event": "agent_contract_committed_steps",
                "data": {
                    "contract_steps": [_committed_step_payload(step) for step in committed_steps],
                    "display_steps": [_display_step_payload(step) for step in committed_steps],
                    "blackboard": board.values,
                    "committed_step_count": len(committed_steps),
                    "total_steps": len(committed_steps),
                },
            }
            snapshot = await self._build_snapshot(page)

    async def _build_snapshot(self, page: Any) -> Dict[str, Any]:
        if self.snapshot_builder:
            return await _maybe_await(self.snapshot_builder(page))

        from .assistant_runtime import build_frame_path_from_frame, build_page_snapshot

        legacy_snapshot = await build_page_snapshot(page, build_frame_path_from_frame)
        return build_base_snapshot_from_legacy(legacy_snapshot).semantic_view()

    @staticmethod
    def _default_planner(model_config: Optional[Dict[str, Any]]):
        async def planner(goal: str, snapshot: Any, board: Blackboard) -> PlannerEnvelope:
            return await plan_next_step_envelope(goal, snapshot, board.values, model_config=model_config)

        return planner

    @staticmethod
    def _default_runtime_ai_executor(model_config: Optional[Dict[str, Any]]):
        async def runtime_ai_executor(page: Any, contract: StepContract, artifact: Dict[str, Any], board: Blackboard) -> Any:
            from .runtime_ai_instruction import execute_ai_instruction

            runtime_step = {
                "action": "ai_instruction",
                "description": artifact.get("description") or contract.description,
                "prompt": artifact.get("prompt") or contract.description,
                "global_goal": artifact.get("global_goal") or contract.intent.goal,
                "instruction_kind": artifact.get("instruction_kind") or contract.operator.type,
                "input_scope": artifact.get("input_scope") or {"mode": "current_page"},
                "input_refs": artifact.get("input_refs") or list(contract.inputs.refs),
                "output_expectation": {
                    "mode": artifact.get("output_mode")
                    or ("act" if artifact.get("allow_side_effect") or contract.runtime_policy.allow_side_effect else "extract"),
                    "schema": artifact.get("output_schema"),
                },
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
            result_key = artifact.get("result_key") or contract.outputs.blackboard_key
            if result_key and result_key in board.values:
                return board.values[result_key]
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
    event_timestamp_ms = _committed_step_event_timestamp_ms(committed_step)
    return {
        "action": "contract_step",
        "source": "ai",
        "description": contract.description or contract.intent.goal,
        "tag": contract.operator.execution_strategy.value,
        "event_timestamp_ms": event_timestamp_ms,
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


def _committed_step_event_timestamp_ms(committed_step) -> int | None:
    evidence = getattr(committed_step, "validation_evidence", {}) or {}
    value = evidence.get("committed_at_ms") if isinstance(evidence, dict) else None
    try:
        timestamp_ms = int(value)
    except Exception:
        return None
    return timestamp_ms if timestamp_ms >= 946684800000 else None


def _merge_committed_step(committed_steps: list[Any], new_step: Any) -> list[Any]:
    identity = _committed_step_identity(new_step)
    merged = list(committed_steps)
    if identity:
        for index, existing in enumerate(merged):
            if _committed_step_identity(existing) == identity:
                merged[index] = new_step
                return merged
    merged.append(new_step)
    return merged


def _committed_step_identity(committed_step: Any) -> str:
    contract = getattr(committed_step, "contract", None)
    if contract is None:
        return ""
    output_key = getattr(getattr(contract, "outputs", None), "blackboard_key", None)
    if isinstance(output_key, str) and output_key.strip():
        return f"output:{output_key.strip()}"
    contract_id = getattr(contract, "id", "")
    if isinstance(contract_id, str) and contract_id.strip():
        return f"id:{contract_id.strip()}"
    return ""


def _contract_thought_text(contract: StepContract) -> str:
    strategy = contract.operator.execution_strategy.value
    goal = contract.intent.goal or contract.description or contract.id
    if strategy == "primitive_action":
        return f"Use a stable browser action for: {goal}"
    if strategy == "deterministic_script":
        return f"Use deterministic Playwright logic for: {goal}"
    if strategy == "runtime_ai":
        return f"Use runtime AI semantic reasoning for: {goal}"
    return f"Plan next contract step: {goal}"


def _artifact_preview(artifact: Dict[str, Any]) -> str:
    kind = str(getattr(artifact.get("kind"), "value", artifact.get("kind")) or "")
    if kind == "deterministic_script":
        return str(artifact.get("code") or "")
    if kind == "runtime_ai":
        return str(artifact.get("prompt") or artifact.get("description") or "")
    if kind == "primitive_action":
        return _jsonable(artifact).__repr__()
    return _jsonable(artifact).__repr__()


def _step_done_output(pipeline_result: Any) -> str:
    attempt = getattr(pipeline_result, "attempt", None)
    evidence = getattr(attempt, "validation_evidence", {}) or {}
    execution = evidence.get("execution_evidence") if isinstance(evidence, dict) else None
    if isinstance(execution, dict):
        result_key = execution.get("result_key")
        if result_key:
            return f"{result_key} updated"
        url = execution.get("url")
        if url:
            return str(url)
        action = execution.get("action")
        if action:
            return str(action)
    return ""


def _attempt_payload(attempt: Any) -> Any:
    if attempt is None:
        return None
    return {
        "goal": getattr(attempt, "goal", ""),
        "success": getattr(attempt, "success", False),
        "failure_class": (
            getattr(attempt, "failure_class", None).value
            if getattr(attempt, "failure_class", None) is not None
            else None
        ),
        "failure_type": getattr(attempt, "failure_type", None),
        "message": getattr(attempt, "message", ""),
        "contract": _jsonable(getattr(getattr(attempt, "contract", None), "model_dump", lambda **_: None)(by_alias=True))
        if getattr(attempt, "contract", None) is not None
        else None,
        "artifact": _jsonable(getattr(attempt, "artifact", None)),
        "validation_evidence": _jsonable(getattr(attempt, "validation_evidence", {})),
    }


def _normalize_planned_contracts(planned: Any) -> list[StepContract]:
    if isinstance(planned, StepContract):
        return [planned]
    if isinstance(planned, list) and all(isinstance(item, StepContract) for item in planned):
        return planned
    raise ValueError("contract planner must return StepContract or list[StepContract]")


def _normalize_planner_envelope(planned: Any) -> PlannerEnvelope:
    if isinstance(planned, PlannerEnvelope):
        return planned
    if isinstance(planned, StepContract):
        return PlannerEnvelope(status=PlannerStatus.NEXT_STEP, current_step=planned)
    if isinstance(planned, list) and all(isinstance(item, StepContract) for item in planned):
        if not planned:
            return PlannerEnvelope(status=PlannerStatus.DONE)
        return PlannerEnvelope(status=PlannerStatus.NEXT_STEP, current_step=planned[0])
    raise ValueError("contract planner must return PlannerEnvelope, StepContract, or list[StepContract]")


def _goal_with_repair_feedback(goal: str, repair_feedback: str) -> str:
    feedback = str(repair_feedback or "").strip()
    if not feedback:
        return goal
    return (
        f"{goal}\n\n"
        "Previous planner/compiler failure:\n"
        f"{feedback}\n\n"
        "Repair requirements:\n"
        "- Return exactly one next-step contract for the current page only.\n"
        "- Use only supported primitive_action operator.type values: navigate, click, fill, press, extract_text.\n"
        "- Use only supported deterministic_script operator.type values: rank_collection_numeric_max, extract_repeated_records.\n"
        "- Do not invent operator names.\n"
        "- If you choose rank_collection_numeric_max, include selection_rule.collection_selector, "
        "selection_rule.value_selector, selection_rule.link_selector, and outputs.blackboard_key.\n"
        "- If you choose extract_repeated_records, include selection_rule.row_selector, selection_rule.fields, "
        "and outputs.blackboard_key.\n"
        "- Keep description and intent.goal local to the next step.\n"
    )


def _is_repairable_execution_failure(pipeline_result: Any) -> bool:
    if getattr(pipeline_result, "failure_type", None) != "execution_failed":
        return False
    message = str(getattr(pipeline_result, "message", "") or "").strip().lower()
    if not message:
        return False
    repairable_fragments = (
        "output does not match",
        "unsupported input_scope",
        "missing blackboard",
        "blackboard ref",
        "non-json response",
        "empty json response",
        "strict mode violation",
        "resolved to",
        "locator.click",
        "waiting for get_by_text",
    )
    return any(fragment in message for fragment in repairable_fragments)


def _build_pipeline_repair_feedback(pipeline_result: Any) -> str:
    if _is_repairable_execution_failure(pipeline_result):
        return (
            "Previous step execution failed:\n"
            f"{str(getattr(pipeline_result, 'message', '') or '').strip()}\n\n"
            "Repair guidance:\n"
            '- If the step reasons over previously extracted structured data, set target.type to "blackboard_ref" '
            "and populate inputs.refs with the required dotted blackboard refs.\n"
            "- Do not re-extract the same visible list if the needed records are already in blackboard.\n"
            "- Ensure runtime_ai outputs match outputs.schema exactly.\n"
            "- Return one corrected next-step contract for the current state only."
        )
    message = str(getattr(pipeline_result, "message", "") or "").strip()
    if "strict mode violation" in message.lower():
        return (
            "Previous step execution failed:\n"
            f"{message}\n\n"
            "Repair guidance:\n"
            "- The previous locator was ambiguous.\n"
            "- Prefer a role-based locator with an exact accessible name over a broad text locator.\n"
            "- If the destination URL is deterministically derivable from blackboard data, prefer a navigate step "
            "instead of retrying the same ambiguous click.\n"
            "- Return one corrected next-step contract for the current state only."
        )
    return message or "planner/compiler failed"
