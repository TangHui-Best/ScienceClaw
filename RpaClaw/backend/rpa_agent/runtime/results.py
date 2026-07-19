"""运行结果与可安全返回的结构化错误。"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


ALLOWED_PHASES = frozenset(
    {"scope", "input", "target", "effect_prepare", "action", "effect_commit", "output", "wait"}
)


class RuntimeServiceError(RuntimeError):
    def __init__(self, *, phase: str, code: str, safe_message: str) -> None:
        if phase not in ALLOWED_PHASES:
            raise ValueError("runtime.phase_invalid")
        self.phase = phase
        self.code = code
        self.safe_message = safe_message
        super().__init__(f"{code}: {safe_message}")


class StepExecutionError(RuntimeError):
    def __init__(
        self,
        *,
        run_id: str,
        trace_id: str,
        sequence: int,
        action_kind: str,
        phase: str,
        code: str,
        safe_message: str,
    ) -> None:
        if phase not in ALLOWED_PHASES:
            raise ValueError("runtime.phase_invalid")
        self.run_id = run_id
        self.trace_id = trace_id
        self.sequence = sequence
        self.action_kind = action_kind
        self.phase = phase
        self.code = code
        self.safe_message = safe_message
        super().__init__(f"{code}: {safe_message}")


@dataclass(frozen=True, slots=True)
class StepRecord:
    trace_id: str
    sequence: int
    action_kind: str
    status: str


@dataclass(frozen=True, slots=True)
class SkillRunResult:
    run_id: str
    status: str
    outputs: Mapping[str, Any]
    data_assets: Mapping[str, Any]
    steps: tuple[StepRecord, ...]
    error: Mapping[str, Any] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "outputs", _deep_freeze(self.outputs))
        object.__setattr__(self, "data_assets", _deep_freeze(self.data_assets))
        if self.error is not None:
            object.__setattr__(self, "error", _deep_freeze(self.error))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "outputs": _deep_thaw(self.outputs),
            "data_assets": _deep_thaw(self.data_assets),
            "steps": [
                {
                    "trace_id": item.trace_id,
                    "sequence": item.sequence,
                    "action_kind": item.action_kind,
                    "status": item.status,
                }
                for item in self.steps
            ],
            "error": _deep_thaw(self.error) if self.error is not None else None,
        }


class ResultBuilder:
    def __init__(
        self,
        run_id: str,
        *,
        output_refs: set[str] | None = None,
        asset_refs: set[str] | None = None,
    ) -> None:
        self._run_id = run_id
        self._steps: list[StepRecord] = []
        self._output_refs = set(output_refs or ())
        self._asset_refs = set(asset_refs or ())

    def record_step(self, trace_id: str, sequence: int, action_kind: str, status: str) -> None:
        self._steps.append(StepRecord(trace_id, sequence, action_kind, status))

    def succeeded(self, *, outputs: Mapping[str, Any], data_assets: Mapping[str, Any]) -> SkillRunResult:
        if _contains_secret(outputs) or _contains_secret(data_assets):
            raise ValueError("result.secret_forbidden")
        if set(outputs) - self._output_refs:
            raise ValueError("result.output_not_declared")
        if set(data_assets) - self._asset_refs:
            raise ValueError("result.asset_not_declared")
        return SkillRunResult(
            run_id=self._run_id,
            status="succeeded",
            outputs=MappingProxyType(dict(outputs)),
            data_assets=MappingProxyType(dict(data_assets)),
            steps=tuple(self._steps),
        )


def _contains_secret(value: object) -> bool:
    if getattr(value, "_rpa_secret", False) is True:
        return True
    if isinstance(value, Mapping):
        return any(_contains_secret(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_contains_secret(item) for item in value)
    return False


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_deep_freeze(item) for item in value)
    return copy.deepcopy(value)


def _deep_thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return [_deep_thaw(item) for item in value]
    return copy.deepcopy(value)
