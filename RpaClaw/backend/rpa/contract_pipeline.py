from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .blackboard import Blackboard
from .contract_executor import ExecutionResult
from .contract_models import FailureClass, StepContract
from .contract_validator import ValidationResult


Planner = Callable[[str, Any, Blackboard], StepContract]
Compiler = Callable[[StepContract], Dict[str, Any]]
Executor = Callable[[StepContract, Dict[str, Any], Any, Blackboard], Any]
Validator = Callable[[StepContract, Dict[str, Any], ExecutionResult, Blackboard, Any], ValidationResult]


@dataclass(frozen=True)
class AttemptRecord:
    goal: str
    contract: Optional[StepContract] = None
    artifact: Optional[Dict[str, Any]] = None
    success: bool = False
    failure_class: Optional[FailureClass] = None
    failure_type: Optional[str] = None
    message: str = ""
    validation_evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CommittedStep:
    contract: StepContract
    artifact: Dict[str, Any]
    validation_evidence: Dict[str, Any]


@dataclass(frozen=True)
class PipelineRunResult:
    success: bool
    committed_step: Optional[CommittedStep] = None
    attempt: Optional[AttemptRecord] = None
    failure_class: Optional[FailureClass] = None
    failure_type: Optional[str] = None
    message: str = ""
    recapture_required: bool = False


class ContractPipeline:
    def __init__(
        self,
        planner: Planner,
        compiler: Compiler,
        executor: Optional[Executor],
        validator: Optional[Validator],
    ):
        self.planner = planner
        self.compiler = compiler
        self.executor = executor
        self.validator = validator
        self.attempts: List[AttemptRecord] = []
        self.committed_steps: List[CommittedStep] = []

    async def run_step(
        self,
        goal: str,
        page: Any,
        snapshot: Any,
        board: Blackboard,
    ) -> PipelineRunResult:
        contract: Optional[StepContract] = None
        artifact: Optional[Dict[str, Any]] = None

        try:
            contract = await _maybe_await(self.planner(goal, snapshot, board))
        except Exception as exc:
            return self._record_failure(
                goal,
                contract=None,
                artifact=None,
                failure_class=FailureClass.CONTRACT_INVALID,
                failure_type="planner_failed",
                message=str(exc),
            )

        try:
            artifact = await _maybe_await(self.compiler(contract))
        except Exception as exc:
            return self._record_failure(
                goal,
                contract=contract,
                artifact=None,
                failure_class=FailureClass.ARTIFACT_FAILED,
                failure_type="compiler_failed",
                message=str(exc),
            )

        if self.executor is None:
            return self._record_failure(
                goal,
                contract=contract,
                artifact=artifact,
                failure_class=FailureClass.ARTIFACT_FAILED,
                failure_type="executor_missing",
                message="Contract pipeline executor is not configured.",
            )

        try:
            execution_result = await _maybe_await(self.executor(contract, artifact, page, board))
        except Exception as exc:
            return self._record_failure(
                goal,
                contract=contract,
                artifact=artifact,
                failure_class=FailureClass.ARTIFACT_FAILED,
                failure_type="execution_failed",
                message=str(exc),
            )

        if self.validator is None:
            return self._record_failure(
                goal,
                contract=contract,
                artifact=artifact,
                failure_class=FailureClass.VALIDATION_FAILED,
                failure_type="validator_missing",
                message="Contract pipeline validator is not configured.",
            )

        validation_result = await _maybe_await(
            self.validator(contract, artifact, execution_result, board, snapshot)
        )
        if not validation_result.passed:
            failure_class = validation_result.failure_class or FailureClass.VALIDATION_FAILED
            return self._record_failure(
                goal,
                contract=contract,
                artifact=artifact,
                failure_class=failure_class,
                failure_type=validation_result.failure_type,
                message=validation_result.message,
                recapture_required=failure_class == FailureClass.SNAPSHOT_STALE,
            )

        committed = CommittedStep(
            contract=contract,
            artifact=artifact,
            validation_evidence={
                **dict(validation_result.evidence),
                "committed_at_ms": int(time.time() * 1000),
            },
        )
        self.committed_steps.append(committed)
        attempt = AttemptRecord(
            goal=goal,
            contract=contract,
            artifact=artifact,
            success=True,
            validation_evidence=dict(validation_result.evidence),
        )
        self.attempts.append(attempt)
        return PipelineRunResult(success=True, committed_step=committed, attempt=attempt)

    def _record_failure(
        self,
        goal: str,
        contract: Optional[StepContract],
        artifact: Optional[Dict[str, Any]],
        failure_class: FailureClass,
        failure_type: Optional[str],
        message: str,
        recapture_required: bool = False,
    ) -> PipelineRunResult:
        attempt = AttemptRecord(
            goal=goal,
            contract=contract,
            artifact=artifact,
            success=False,
            failure_class=failure_class,
            failure_type=failure_type,
            message=message,
        )
        self.attempts.append(attempt)
        return PipelineRunResult(
            success=False,
            attempt=attempt,
            failure_class=failure_class,
            failure_type=failure_type,
            message=message,
            recapture_required=recapture_required,
        )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
