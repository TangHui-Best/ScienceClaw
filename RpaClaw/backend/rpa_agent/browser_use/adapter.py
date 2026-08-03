"""Browser-use 0.13.2 实际 Tools Action 到创建态 Candidate 的适配边界。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping as ABCMapping, Sequence as ABCSequence
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import importlib.metadata
import inspect
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import tomllib
from typing import Any, Awaitable, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from ..contracts import BindingHint, TargetHint, TraceCandidate
from ..contracts.models import ScopeHint
from ..creation import SkillCreationSession
from .classifiers import classify_candidate_action, classify_non_sop


BROWSER_USE_BASELINE_VERSION = "0.13.2"
BROWSER_USE_COMPATIBILITY_DISTRIBUTION_VERSION = "0.13.2+sciclaw.1"
_SUPPORTED_BROWSER_USE_DISTRIBUTIONS = frozenset(
    {BROWSER_USE_BASELINE_VERSION, BROWSER_USE_COMPATIBILITY_DISTRIBUTION_VERSION}
)
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")
_NON_SOP_ACTIONS = frozenset({
    "done", "wait", "observe", "search_page", "find_elements", "find_text",
    "dropdown_options", "get_dropdown_options",
})
_DETERMINISTIC_ACTIONS = frozenset({
    "navigate", "go_back", "click", "input", "select_dropdown", "scroll",
    "upload_file", "switch", "close", "extract", "send_keys",
})
_DENIED_ACTIONS = frozenset({
    "search", "read_file", "write_file", "replace_file",
    "screenshot", "save_pdf", "save_as_pdf", "analyze_image",
})
_ALLOWED_ACTIONS = _NON_SOP_ACTIONS | _DETERMINISTIC_ACTIONS | frozenset({"evaluate"})
_UUID = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_HIGH_ENTROPY_SEGMENT = re.compile(r"(?i)^[a-f0-9]{24,}$|^[A-Za-z0-9_-]{32,}$")

_EVIDENCE_KEYS = {
    "navigate": frozenset({"url_reached", "navigation_committed"}),
    "go_back": frozenset({"url_reached", "navigation_committed", "history_changed"}),
    "click": frozenset({"dispatched", "clicked", "enabled"}),
    "input": frozenset({"dom_value", "value_matched"}),
    "select_dropdown": frozenset({"selected", "selected_value", "value_matched"}),
    "scroll": frozenset({"completed", "scrolled", "position_changed"}),
    "upload_file": frozenset({"uploaded_asset_ref", "uploaded", "file_count"}),
    "switch": frozenset({"activated_page_ref", "page_active"}),
    "close": frozenset({"closed_page_ref", "page_closed"}),
    "extract": frozenset({"variables", "extracted"}),
    "send_keys": frozenset({"dispatched"}),
    "evaluate": frozenset({"completed", "dispatched", "variables"}),
    "done": frozenset(),
    "wait": frozenset(),
    "observe": frozenset(),
    "search_page": frozenset(),
    "find_elements": frozenset(),
    "find_text": frozenset(),
    "dropdown_options": frozenset(),
    "get_dropdown_options": frozenset(),
}


def _immutable(*_: Any, **__: Any) -> None:
    raise TypeError("browser_use_adapter.dto_immutable")


class _FrozenMapping(ABCMapping):
    """Tuple-backed Mapping with no mutable-container base descriptor."""

    __slots__ = ("_items",)
    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def __init__(self, items: Sequence[tuple[str, Any]]) -> None:
        object.__setattr__(self, "_items", tuple(items))

    def __getitem__(self, key: str) -> Any:
        for current, value in self._items:
            if current == key:
                return value
        raise KeyError(key)

    def __iter__(self):
        return (key for key, _ in self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return repr(_deep_thaw(self))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ABCMapping):
            return _deep_thaw(self) == _deep_thaw(other)
        return False

    def __deepcopy__(self, memo: dict[int, Any]) -> "_FrozenMapping":
        copied = _FrozenMapping(tuple(
            (deepcopy(key, memo), deepcopy(value, memo))
            for key, value in self._items
        ))
        memo[id(self)] = copied
        return copied


class _FrozenSequence(ABCSequence):
    """Tuple-backed Sequence companion for JSON array values."""

    __slots__ = ("_values",)
    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable

    def __init__(self, values: Sequence[Any]) -> None:
        object.__setattr__(self, "_values", tuple(values))

    def __getitem__(self, index):
        returned = self._values[index]
        return _FrozenSequence(returned) if isinstance(index, slice) else returned

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return repr(_deep_thaw(self))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ABCSequence) and not isinstance(other, (str, bytes)):
            return list(self) == list(other)
        return False

    def __deepcopy__(self, memo: dict[int, Any]) -> "_FrozenSequence":
        copied = _FrozenSequence(tuple(deepcopy(value, memo) for value in self._values))
        memo[id(self)] = copied
        return copied


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenMapping(tuple(
            (key, _deep_freeze(item)) for key, item in value.items()
        ))
    if isinstance(value, list):
        return _FrozenSequence(tuple(_deep_freeze(item) for item in value))
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, ABCMapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, ABCSequence) and not isinstance(value, (str, bytes)):
        return [_deep_thaw(item) for item in value]
    return value


def thaw_browser_use_value(value: Any) -> Any:
    """Return an independent JSON/Pydantic-ready copy of a frozen DTO value."""

    return _deep_thaw(value)


def _json_copy(value: Any) -> Any:
    try:
        copied = json.loads(json.dumps(
            _deep_thaw(value), ensure_ascii=False, allow_nan=False
        ))
    except (TypeError, ValueError) as exc:
        raise ValueError("browser_use_adapter.not_json_safe") from exc
    return _deep_freeze(copied)


@dataclass(frozen=True, slots=True)
class ActualToolAction:
    """宿主在实际 Tools 调用边界提供的规范化、短生命周期 DTO。"""

    action_name: str
    candidate_id: str
    params: Mapping[str, Any]
    business_intent: str
    runtime_page_ref: str
    runtime_frame_ref: str
    page_ref: str
    frame_path: tuple[Mapping[str, Any], ...]
    target_hint: Mapping[str, Any] | None
    binding_hints: tuple[Mapping[str, Any], ...]
    source_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_name, str) or not self.action_name.strip():
            raise ValueError("browser_use_adapter.action_name_invalid")
        for field_name in ("candidate_id", "runtime_page_ref", "runtime_frame_ref", "page_ref"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"browser_use_adapter.{field_name}_invalid")
        if not isinstance(self.business_intent, str) or not self.business_intent.strip():
            raise ValueError("browser_use_adapter.business_intent_invalid")
        params = _json_copy(dict(self.params))
        if self.action_name == "upload_file" and any(
            isinstance(params.get(key), str)
            and (
                PureWindowsPath(params[key]).is_absolute()
                or PurePosixPath(params[key]).is_absolute()
            )
            for key in ("path", "file_path")
        ):
            raise ValueError("browser_use_adapter.local_asset_path_forbidden")
        frame_path = tuple(_json_copy(dict(item)) for item in self.frame_path)
        target = None if self.target_hint is None else _json_copy(dict(self.target_hint))
        bindings = tuple(_json_copy(dict(item)) for item in self.binding_hints)
        for binding in bindings:
            BindingHint.model_validate(_deep_thaw(binding))
        ScopeHint.model_validate({
            "page_ref": self.page_ref,
            "frame_path": _deep_thaw(frame_path),
        })
        object.__setattr__(self, "action_name", self.action_name.strip())
        object.__setattr__(self, "business_intent", self.business_intent.strip())
        object.__setattr__(self, "params", params)
        object.__setattr__(self, "frame_path", frame_path)
        object.__setattr__(self, "target_hint", target)
        object.__setattr__(self, "binding_hints", bindings)


@dataclass(frozen=True, slots=True)
class NormalizedActionResult:
    """只包含 0.13.2 ActionResult 判定字段和宿主可信后置证据。"""

    error: str | None = None
    success: bool | None = None
    is_done: bool | None = None
    data: Mapping[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.error is not None and (not isinstance(self.error, str) or not self.error):
            raise ValueError("browser_use_adapter.result_error_invalid")
        if self.success is not None and not isinstance(self.success, bool):
            raise ValueError("browser_use_adapter.result_success_invalid")
        if self.is_done is not None and not isinstance(self.is_done, bool):
            raise ValueError("browser_use_adapter.result_is_done_invalid")
        object.__setattr__(self, "data", _json_copy(dict(self.data or {})))


def normalize_action_result(
    action_name: str,
    result: object,
    *,
    evidence: Mapping[str, Any] | None,
) -> NormalizedActionResult:
    """Normalize a 0.13.2 ActionResult without trusting its private payloads."""

    allowed = _EVIDENCE_KEYS.get(
        action_name,
        frozenset({"completed", "dispatched", "variables"}),
    )
    # A named tool can still become an agent Candidate when its locator or
    # deterministic parameter contract cannot be proven.  ``completed`` is
    # trusted host evidence for that downgrade, never Browser-use payload.
    if action_name not in _NON_SOP_ACTIONS:
        allowed = allowed | frozenset({"completed"})
    copied_evidence = _json_copy(dict(evidence or {}))
    forbidden = set(copied_evidence) - allowed
    if forbidden:
        raise ValueError(
            "browser_use_result.evidence_key_forbidden:"
            + ",".join(sorted(forbidden))
        )

    def field(name: str) -> Any:
        if isinstance(result, Mapping):
            return result.get(name)
        return getattr(result, name, None)

    return NormalizedActionResult(
        error=field("error"),
        success=field("success"),
        is_done=field("is_done"),
        data=copied_evidence,
    )


@dataclass(frozen=True, slots=True)
class NonSopActionClassification:
    action_name: str
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class RecordingRoundReport:
    actual_action_count: int
    candidate_ids: tuple[str, ...]
    non_sop: tuple[NonSopActionClassification, ...]
    invocation_count: int = 0
    blocked: tuple[NonSopActionClassification, ...] = ()


@dataclass(frozen=True, slots=True)
class TargetResolution:
    target_hint: Mapping[str, Any] | None
    match_count: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.match_count, int)
            or isinstance(self.match_count, bool)
            or self.match_count < 0
        ):
            raise ValueError("browser_use_adapter.target_match_count_invalid")
        target = None if self.target_hint is None else _json_copy(dict(self.target_hint))
        object.__setattr__(self, "target_hint", target)


class RecordingCancelledError(asyncio.CancelledError):
    def __init__(self, partial_report: RecordingRoundReport) -> None:
        super().__init__("browser_use round cancelled")
        self.partial_report = partial_report


ActionExecutor = Callable[[ActualToolAction], object | Awaitable[object]]


class BrowserUseRecordingAdapter:
    """逐个消费实际 Action；不接受或解释 Browser-use History。"""

    def __init__(
        self,
        *,
        session: SkillCreationSession,
        executor: ActionExecutor,
        evidence_provider: Callable[[ActualToolAction, object], Mapping[str, Any] | Awaitable[Mapping[str, Any]]],
        target_resolver: Callable[[ActualToolAction], TargetResolution | Awaitable[TargetResolution]],
        version_provider: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        allowed_extension_actions: frozenset[str] = frozenset(),
    ) -> None:
        assert_browser_use_version(version_provider=version_provider)
        self._session = session
        self._executor = executor
        self._evidence_provider = evidence_provider
        self._target_resolver = target_resolver
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        invalid_extensions = allowed_extension_actions & _DENIED_ACTIONS
        if invalid_extensions:
            raise ValueError("browser_use_adapter.denied_extension_action")
        self._allowed_extension_actions = frozenset(allowed_extension_actions)

    async def record_round(
        self,
        actions: Sequence[ActualToolAction],
        *,
        planning_metadata: Mapping[str, Any] | None = None,
        completed_at: datetime | None = None,
    ) -> RecordingRoundReport:
        del planning_metadata
        snapshot = tuple(actions)
        self._validate_completed_at(completed_at)
        candidate_ids: list[str] = []
        non_sop: list[NonSopActionClassification] = []
        blocked: list[NonSopActionClassification] = []
        invocation_count = 0
        for action in snapshot:
            invocation_count += 1
            if not self._is_allowed(action.action_name):
                blocked.append(NonSopActionClassification(
                    action_name=action.action_name,
                    status="blocked",
                    reason=(
                        "action_denied"
                        if action.action_name in _DENIED_ACTIONS
                        else "action_unknown"
                    ),
                ))
                continue
            self._validate_host_page_scope(action)
            if self._is_non_sop(action):
                try:
                    non_sop.append(await self._execute_non_sop(action))
                except asyncio.CancelledError:
                    non_sop.append(NonSopActionClassification(
                        action_name=action.action_name,
                        status="cancelled",
                        reason="action_cancelled",
                    ))
                    raise RecordingCancelledError(self._report(
                        invocation_count, candidate_ids, non_sop, blocked
                    )) from None
                except BaseException as exc:
                    non_sop.append(NonSopActionClassification(
                        action_name=action.action_name,
                        status="failed",
                        reason="tool_execution_interrupted",
                    ))
                    setattr(
                        exc,
                        "browser_use_partial_report",
                        self._report(invocation_count, candidate_ids, non_sop, blocked),
                    )
                    raise
                continue
            try:
                await self._record_candidate(action, completed_at=completed_at)
            except asyncio.CancelledError:
                candidate_ids.append(action.candidate_id)
                raise RecordingCancelledError(self._report(
                    invocation_count, candidate_ids, non_sop, blocked
                )) from None
            candidate_ids.append(action.candidate_id)
        return self._report(invocation_count, candidate_ids, non_sop, blocked)

    @staticmethod
    def _report(
        invocation_count: int,
        candidate_ids: Sequence[str],
        non_sop: Sequence[NonSopActionClassification],
        blocked: Sequence[NonSopActionClassification],
    ) -> RecordingRoundReport:
        return RecordingRoundReport(
            invocation_count=invocation_count,
            actual_action_count=len(candidate_ids) + len(non_sop),
            candidate_ids=tuple(candidate_ids),
            non_sop=tuple(non_sop),
            blocked=tuple(blocked),
        )

    def _validate_completed_at(self, completed_at: datetime | None) -> None:
        if completed_at is None:
            return
        now = self._clock()
        if not self._aware(now):
            raise ValueError("browser_use_adapter.clock_naive")
        if not self._aware(completed_at):
            raise ValueError("browser_use_adapter.completed_at_naive")
        if completed_at < now:
            raise ValueError("browser_use_adapter.completed_at_regressed")

    @staticmethod
    def _aware(value: datetime) -> bool:
        return isinstance(value, datetime) and value.utcoffset() is not None

    def _is_allowed(self, action_name: str) -> bool:
        return action_name in _ALLOWED_ACTIONS or action_name in self._allowed_extension_actions

    def _validate_host_page_scope(self, action: ActualToolAction) -> None:
        try:
            registered = self._session.pages.resolve(action.runtime_page_ref)
        except ValueError as exc:
            raise ValueError("browser_use_adapter.runtime_page_unknown") from exc
        if registered != action.page_ref:
            raise ValueError("browser_use_adapter.page_ref_mismatch")

    @staticmethod
    def _is_non_sop(action: ActualToolAction) -> bool:
        return (
            action.action_name in _NON_SOP_ACTIONS
            or action.action_name == "scroll"
            and action.params.get("business_required") is False
        )

    async def _execute_non_sop(
        self, action: ActualToolAction
    ) -> NonSopActionClassification:
        try:
            result = await self._execute_and_normalize(action)
            judgement = classify_non_sop(action.action_name, action.params, result)
        except asyncio.CancelledError:
            raise
        except Exception:
            return NonSopActionClassification(
                action_name=action.action_name,
                status="failed",
                reason="tool_execution_exception",
            )
        return NonSopActionClassification(
            action_name=action.action_name,
            status="succeeded" if judgement.succeeded else "failed",
            reason=judgement.reason,
        )

    async def _record_candidate(
        self,
        action: ActualToolAction,
        *,
        completed_at: datetime | None,
    ) -> None:
        started_at = self._clock()
        if not self._aware(started_at):
            raise ValueError("browser_use_adapter.clock_naive")
        if completed_at is not None and completed_at < started_at:
            raise ValueError("browser_use_adapter.completed_at_regressed")
        resolution = await self._resolve_target(action)
        resolved_action = replace(
            action,
            target_hint=(
                resolution.target_hint if resolution.match_count == 1 else None
            ),
        )
        action_hint, bindings, deterministic, params_for_judgement = self._prepare_mapping(
            resolved_action,
            started_at=started_at,
        )
        reservation = self._session.reserve_agent(
            action.candidate_id,
            page_runtime_ref=action.runtime_page_ref,
            frame_runtime_ref=action.runtime_frame_ref,
        )
        try:
            result = await self._execute_and_normalize(action)
            finished_at = completed_at or self._clock()
            if not self._aware(finished_at):
                raise ValueError("browser_use_adapter.clock_naive")
            if finished_at < started_at:
                raise ValueError("browser_use_adapter.completed_at_regressed")
            has_side_effect = self._session.candidate_has_side_effect(action.candidate_id)
            if action.action_name == "switch" and isinstance(action.params.get("page_ref"), str):
                page_ref = action.params["page_ref"]
                params_for_judgement["page_registered"] = self._session.pages.has_page_ref(page_ref)
                params_for_judgement["page_active"] = self._session.pages.active_page_ref == page_ref
                params_for_judgement["activation_fact"] = self._session.candidate_has_fact(
                    action.candidate_id, "page_activated"
                )
            if action.action_name == "close":
                params_for_judgement["page_closed"] = (
                    self._session.pages.has_page_ref(action.page_ref, include_closed=True)
                    and self._session.pages.is_closed(action.page_ref)
                )
                params_for_judgement["closure_fact"] = self._session.candidate_has_fact(
                    action.candidate_id, "page_closed"
                )
            judgement = classify_candidate_action(
                action.action_name,
                params_for_judgement,
                result,
                deterministic=deterministic,
            )
            succeeded = judgement.succeeded
            failure_reason = judgement.reason
            execution = self._execution(
                started_at=started_at,
                finished_at=finished_at,
                succeeded=succeeded,
                has_side_effect=has_side_effect,
                error_code=failure_reason,
                cancelled=False,
            )
            candidate = self._candidate(
                action=resolved_action,
                ordinal=reservation.ordinal,
                action_hint=action_hint,
                bindings=bindings,
                execution=execution,
            )
            variable_outputs = (
                self._declared_variable_outputs(bindings, result) if succeeded else {}
            )
            try:
                self._session.register_candidate(
                    reservation,
                    candidate,
                    completed_at=finished_at,
                    variable_outputs=variable_outputs,
                )
            except ValueError as exc:
                if not variable_outputs or not str(exc).startswith("session_variable_store."):
                    raise
                failed = self._candidate(
                    action=resolved_action,
                    ordinal=reservation.ordinal,
                    action_hint=action_hint,
                    bindings=bindings,
                    execution=self._execution(
                        started_at=started_at,
                        finished_at=finished_at,
                        succeeded=False,
                        has_side_effect=has_side_effect,
                        error_code="variable_output_commit_failed",
                        cancelled=False,
                    ),
                )
                self._session.register_candidate(
                    reservation,
                    failed,
                    completed_at=finished_at,
                )
        except BaseException as exc:
            # Once reserved, every exit path must consume the reservation.  A
            # bad host clock is itself execution-boundary failure; started_at
            # is the last trusted aware timestamp and is safe for terminal use.
            if action.candidate_id not in self._session.candidates:
                try:
                    has_side_effect = self._session.candidate_has_side_effect(
                        action.candidate_id
                    )
                except BaseException:
                    has_side_effect = False
                cancelled = isinstance(exc, asyncio.CancelledError)
                failed = self._candidate(
                    action=resolved_action,
                    ordinal=reservation.ordinal,
                    action_hint=action_hint,
                    bindings=bindings,
                    execution=self._execution(
                        started_at=started_at,
                        finished_at=started_at,
                        succeeded=False,
                        has_side_effect=has_side_effect,
                        error_code=(
                            "action_cancelled" if cancelled else "tool_execution_exception"
                        ),
                        cancelled=cancelled,
                    ),
                )
                self._session.register_candidate(
                    reservation,
                    failed,
                    completed_at=started_at,
                )
            raise

    async def _execute_and_normalize(self, action: ActualToolAction) -> NormalizedActionResult:
        returned = self._executor(action)
        if inspect.isawaitable(returned):
            returned = await returned
        evidence = self._evidence_provider(action, returned)
        if inspect.isawaitable(evidence):
            evidence = await evidence
        if not isinstance(evidence, Mapping):
            raise TypeError("browser_use_adapter.evidence_invalid")
        return normalize_action_result(action.action_name, returned, evidence=evidence)

    async def _resolve_target(self, action: ActualToolAction) -> TargetResolution:
        if action.target_hint is None and action.source_index is None:
            return TargetResolution(target_hint=None, match_count=0)
        returned = self._target_resolver(action)
        if inspect.isawaitable(returned):
            returned = await returned
        if not isinstance(returned, TargetResolution):
            raise TypeError("browser_use_adapter.target_resolution_invalid")
        return returned

    @staticmethod
    def _execution(
        *,
        started_at: datetime,
        finished_at: datetime,
        succeeded: bool,
        has_side_effect: bool,
        error_code: str,
        cancelled: bool,
    ) -> dict[str, Any]:
        if cancelled:
            return {
                "status": "cancelled",
                "started_at": started_at,
                "ended_at": finished_at,
                "output": None,
                "error": {
                    "code": "action_cancelled",
                    "message": "Browser action was cancelled.",
                },
            }
        if not succeeded and has_side_effect:
            return {
                "status": "running",
                "started_at": started_at,
                "ended_at": None,
                "output": None,
                "error": None,
            }
        if succeeded:
            return {
                "status": "succeeded",
                "started_at": started_at,
                "ended_at": finished_at,
                "output": None,
                "error": None,
            }
        return {
            "status": "failed",
            "started_at": started_at,
            "ended_at": finished_at,
            "output": None,
            "error": {
                "code": error_code,
                "message": "Browser action execution failed.",
            },
        }

    @classmethod
    def _prepare_mapping(
        cls,
        action: ActualToolAction,
        *,
        started_at: datetime,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], bool, dict[str, Any]]:
        mapped = cls._mapping(action)
        action_hint, bindings, _, params = mapped
        try:
            cls._candidate(
                action=action,
                ordinal=1,
                action_hint=action_hint,
                bindings=bindings,
                execution={
                    "status": "running",
                    "started_at": started_at,
                    "ended_at": None,
                    "output": None,
                    "error": None,
                },
            )
            return mapped
        except ValueError:
            fallback_params = _deep_thaw(action.params)
            declared_outputs = cls._declared_output_refs(bindings)
            if declared_outputs:
                fallback_params["declared_output_refs"] = declared_outputs
            fallback = (
                {"kind": "agent", "instruction": action.business_intent},
                bindings,
                False,
                fallback_params,
            )
            cls._candidate(
                action=action,
                ordinal=1,
                action_hint=fallback[0],
                bindings=bindings,
                execution={
                    "status": "running",
                    "started_at": started_at,
                    "ended_at": None,
                    "output": None,
                    "error": None,
                },
            )
            return fallback

    @staticmethod
    def _candidate(
        *,
        action: ActualToolAction,
        ordinal: int,
        action_hint: Mapping[str, Any],
        bindings: Sequence[Mapping[str, Any]],
        execution: Mapping[str, Any],
    ) -> TraceCandidate:
        return TraceCandidate.model_validate({
            "candidate_id": action.candidate_id,
            "ordinal": ordinal,
            "origin": "agent",
            "scope_hint": {
                "page_ref": action.page_ref,
                "frame_path": _deep_thaw(action.frame_path),
            },
            "action_hint": _deep_thaw(action_hint),
            "binding_hints": _deep_thaw(bindings),
            "execution": _deep_thaw(execution),
        })

    @classmethod
    def _mapping(
        cls, action: ActualToolAction
    ) -> tuple[dict[str, Any], list[dict[str, Any]], bool, dict[str, Any]]:
        name = action.action_name
        target = cls._stable_target(action.target_hint)
        bindings = _deep_thaw(action.binding_hints)
        params = _deep_thaw(action.params)
        deterministic = name in _DETERMINISTIC_ACTIONS
        if name == "navigate":
            if cls._dynamic_literal_url(params.get("url"), bindings):
                safe_bindings = [item for item in bindings if item.get("name") != "url"]
                return (
                    {"kind": "agent", "instruction": action.business_intent},
                    safe_bindings,
                    False,
                    {},
                )
            cls._ensure_literal_binding(bindings, "url", params.get("url"))
            return {"kind": "navigate", "mode": "url"}, bindings, True, params
        if name == "go_back":
            return {"kind": "navigate", "mode": "back"}, bindings, True, params
        if name == "click" and target is not None:
            return {"kind": "click", "target_hint": target}, bindings, True, params
        if name == "input" and target is not None:
            cls._ensure_literal_binding(bindings, "value", params.get("text"))
            return {"kind": "fill", "target_hint": target}, bindings, True, params
        if name == "select_dropdown" and target is not None:
            cls._ensure_literal_binding(bindings, "option", params.get("option"))
            return {"kind": "select", "target_hint": target}, bindings, True, params
        if (
            name == "scroll"
            and (action.source_index is None or target is not None)
            and params.get("direction", "down") in {"up", "down", "left", "right"}
            and isinstance(params.get("amount", 1), int)
            and not isinstance(params.get("amount", 1), bool)
            and params.get("amount", 1) >= 1
            and params.get("unit", "viewport") in {"pixel", "viewport"}
        ):
            hint = {
                "kind": "scroll",
                "direction": params.get("direction", "down"),
                "amount": params.get("amount", 1),
                "unit": params.get("unit", "viewport"),
            }
            if target is not None:
                hint["target_hint"] = target
            return hint, bindings, True, params
        if name == "upload_file" and target is not None and isinstance(params.get("asset_ref"), str):
            cls._ensure_asset_binding(bindings, params["asset_ref"])
            return {"kind": "upload", "target_hint": target}, bindings, True, params
        if name == "switch" and isinstance(params.get("page_ref"), str):
            return {"kind": "switch_page", "page_ref": params["page_ref"]}, bindings, True, params
        if name == "close":
            params["scope_page_ref"] = action.page_ref
            return {"kind": "close_page"}, bindings, True, params
        if (
            name == "extract"
            and target is not None
            and params.get("mode", "text") in {"text", "attribute", "table"}
        ):
            output_ref = cls._declared_output_ref(bindings)
            params["declared_output_ref"] = output_ref
            hint: dict[str, Any] = {
                "kind": "extract",
                "mode": params.get("mode", "text"),
                "target_hint": target,
            }
            if hint["mode"] == "attribute" and isinstance(params.get("attribute"), str):
                hint["attribute"] = params["attribute"]
            if hint["mode"] == "table" and isinstance(params.get("columns"), list):
                hint["columns"] = params["columns"]
            return hint, bindings, True, params
        if name == "send_keys" and target is not None:
            cls._ensure_literal_binding(bindings, "keys", params.get("keys"))
            return {"kind": "press", "target_hint": target}, bindings, True, params
        hint = {"kind": "agent", "instruction": action.business_intent}
        if target is not None and name not in {"evaluate"}:
            hint["target_hint"] = target
        declared_outputs = cls._declared_output_refs(bindings)
        if declared_outputs:
            params["declared_output_refs"] = declared_outputs
        return hint, bindings, False, params

    @staticmethod
    def _stable_target(target: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if target is None:
            return None
        name = target.get("name")
        locators = target.get("locators")
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(locators, ABCSequence)
            or isinstance(locators, (str, bytes))
            or not locators
        ):
            return None
        cleaned: dict[str, Any] = {
            "name": name,
            "locators": BrowserUseRecordingAdapter._without_private_indexes(locators),
        }
        path = target.get("path")
        if (
            isinstance(path, ABCSequence)
            and not isinstance(path, (str, bytes))
            and path
        ):
            cleaned["path"] = BrowserUseRecordingAdapter._without_private_indexes(path)
        try:
            validated = TargetHint.model_validate(cleaned)
        except ValueError:
            return None
        return validated.model_dump(exclude_none=True, exclude={"index"})

    @staticmethod
    def _without_private_indexes(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: BrowserUseRecordingAdapter._without_private_indexes(item)
                for key, item in value.items()
                if key != "index"
            }
        if isinstance(value, ABCSequence) and not isinstance(value, (str, bytes)):
            return [BrowserUseRecordingAdapter._without_private_indexes(item) for item in value]
        return deepcopy(value)

    @staticmethod
    def _dynamic_literal_url(url: Any, bindings: Sequence[Mapping[str, Any]]) -> bool:
        explicit = any(
            item.get("name") == "url" and item.get("kind_hint") != "literal"
            for item in bindings
        )
        if explicit:
            return False
        if not isinstance(url, str) or not url.strip():
            return False
        parsed = urlsplit(url)
        if parsed.query or parsed.fragment:
            return True
        return any(
            _UUID.fullmatch(segment) is not None
            or _HIGH_ENTROPY_SEGMENT.fullmatch(segment) is not None
            for segment in parsed.path.split("/")
            if segment
        )

    @staticmethod
    def _ensure_literal_binding(
        bindings: list[dict[str, Any]], name: str, value: Any
    ) -> None:
        if any(item.get("name") == name for item in bindings):
            return
        bindings.append({
            "name": name,
            "direction": "input",
            "kind_hint": "literal",
            "value": value,
            "sensitive": False,
        })

    @staticmethod
    def _ensure_asset_binding(bindings: list[dict[str, Any]], asset_ref: str) -> None:
        if any(item.get("name") == "file" for item in bindings):
            return
        bindings.append({
            "name": "file",
            "direction": "input",
            "kind_hint": "data_asset",
            "ref_hint": asset_ref,
            "sensitive": False,
        })

    @staticmethod
    def _declared_output_ref(bindings: list[dict[str, Any]]) -> str | None:
        matches = [
            item.get("ref_hint")
            for item in bindings
            if item.get("name") == "result"
            and item.get("direction") == "output"
            and item.get("kind_hint") == "variable"
            and isinstance(item.get("ref_hint"), str)
        ]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _declared_output_refs(bindings: list[dict[str, Any]]) -> list[str]:
        return sorted({
            item["ref_hint"]
            for item in bindings
            if item.get("direction") == "output"
            and item.get("kind_hint") == "variable"
            and isinstance(item.get("ref_hint"), str)
        })

    @staticmethod
    def _declared_variable_outputs(
        bindings: list[dict[str, Any]],
        result: NormalizedActionResult,
    ) -> dict[str, Any]:
        variables = result.data.get("variables")
        if not isinstance(variables, ABCMapping):
            return {}
        declared_refs = {
            item["ref_hint"]
            for item in bindings
            if item.get("direction") == "output"
            and item.get("kind_hint") == "variable"
            and isinstance(item.get("ref_hint"), str)
        }
        return {
            ref: _deep_thaw(variables[ref])
            for ref in sorted(declared_refs)
            if ref in variables
        }


def assert_browser_use_version(
    repo_path: str | Path | None = None,
    *,
    version_provider: object | None = None,
) -> str:
    """Accept the upstream API baseline or the audited ScienceClaw distribution."""

    configured = repo_path if repo_path is not None else os.environ.get("BROWSER_USE_REPO_PATH")
    if configured is not None:
        path = Path(configured)
        metadata = path / "pyproject.toml"
        if not metadata.is_file():
            raise ValueError("browser_use.version_metadata_missing")
        with metadata.open("rb") as handle:
            document = tomllib.load(handle)
        version = document.get("project", {}).get("version")
    elif version_provider is not None:
        if not callable(version_provider):
            raise TypeError("browser_use.version_provider_invalid")
        version = version_provider()
    else:
        try:
            version = importlib.metadata.version("browser-use")
        except importlib.metadata.PackageNotFoundError as exc:
            raise ValueError("browser_use.version_distribution_missing") from exc
    if version not in _SUPPORTED_BROWSER_USE_DISTRIBUTIONS:
        raise ValueError(f"browser_use.version_unsupported:{version}")
    return version
