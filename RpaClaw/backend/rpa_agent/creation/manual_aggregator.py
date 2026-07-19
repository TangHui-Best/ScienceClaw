"""把人工低层 DOM 事件聚合为动作级 TraceCandidate。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ..contracts import TraceCandidate
from .candidate_registry import ActiveCandidateRegistry, CandidateReservation


class ManualEventKind(Enum):
    FOCUS = "focus"
    BEFORE_INPUT = "beforeinput"
    INPUT = "input"
    CHANGE = "change"
    BLUR = "blur"
    CLICK = "click"
    COMPOSITION_START = "compositionstart"
    COMPOSITION_END = "compositionend"


class InteractionKind(Enum):
    CLICK = "click"
    FILL = "fill"
    SET_CHECKED = "set_checked"


@dataclass(frozen=True, slots=True)
class ManualEvent:
    """仅存在于创建态 Adapter 内部的规范化事件载荷。"""

    kind: ManualEventKind
    page_runtime_ref: str
    frame_runtime_ref: str
    target_key: str
    target_name: str
    target_locators: tuple[Mapping[str, object], ...]
    interaction_kind: InteractionKind
    observed_at: datetime
    target_path: tuple[Mapping[str, object], ...] = ()
    binding_hints: tuple[Mapping[str, object], ...] = ()
    value: str | None = None
    checked: bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_locators",
            tuple(deepcopy(dict(locator)) for locator in self.target_locators),
        )
        object.__setattr__(
            self,
            "target_path",
            tuple(deepcopy(dict(step)) for step in self.target_path),
        )
        object.__setattr__(
            self,
            "binding_hints",
            tuple(deepcopy(dict(binding)) for binding in self.binding_hints),
        )


@dataclass(frozen=True, slots=True)
class _WindowKey:
    page_runtime_ref: str
    frame_runtime_ref: str
    target_key: str
    interaction_kind: InteractionKind


@dataclass(slots=True)
class _ManualWindow:
    key: _WindowKey
    reservation: CandidateReservation
    ordinal: int | None
    started_at: datetime
    last_observed_at: datetime
    target_name: str
    target_locators: tuple[Mapping[str, object], ...]
    target_path: tuple[Mapping[str, object], ...]
    binding_hints: tuple[Mapping[str, object], ...]
    composing: bool = False
    final_value: str | None = None
    checked: bool | None = None


class ManualInteractionAggregator:
    """按 Page + Frame + Target + InteractionKind 管理人工交互窗口。

    同一实例属于单个 SkillCreationSession，必须由该 Session 串行调用；跨监听器
    的并发先在宿主队列中排序。Reservation 的最终 expire 生命周期由 Session 托管。
    """

    def __init__(
        self,
        *,
        registry: ActiveCandidateRegistry,
        allocate_ordinal: Callable[[], int] | None = None,
    ) -> None:
        self._registry = registry
        self._ordinal = 0
        self._allocate_ordinal = allocate_ordinal or self._next_ordinal
        self._windows: dict[_WindowKey, _ManualWindow] = {}
        self._emitted_reservations: set[CandidateReservation] = set()

    def ingest(
        self, reservation: CandidateReservation, event: ManualEvent
    ) -> tuple[TraceCandidate, ...]:
        """验证活动凭据并接收事件；明确闭合时才返回 Candidate。"""

        self._registry.validate_active(
            reservation,
            page_runtime_ref=event.page_runtime_ref,
            frame_runtime_ref=event.frame_runtime_ref,
        )
        if reservation in self._emitted_reservations:
            raise ValueError("manual_window.already_emitted")
        key = self._key(event)
        if event.kind is ManualEventKind.FOCUS:
            self._window_for_event(
                reservation,
                event,
                key,
                allocate_ordinal=False,
            )
            return ()

        if event.interaction_kind is InteractionKind.CLICK:
            if any(
                window.reservation is reservation
                for window in self._windows.values()
            ):
                raise ValueError("manual_window.reservation_has_open_window")
            return self._ingest_click(reservation, event)

        if event.kind is ManualEventKind.COMPOSITION_START:
            window = self._window_for_event(
                reservation, event, key, allocate_ordinal=False
            )
            window.composing = True
            return ()

        if event.kind is ManualEventKind.BEFORE_INPUT:
            self._window_for_event(reservation, event, key, allocate_ordinal=True)
            return ()

        if event.interaction_kind is InteractionKind.FILL:
            return self._ingest_fill(reservation, event, key)
        if event.interaction_kind is InteractionKind.SET_CHECKED:
            return self._ingest_set_checked(reservation, event, key)
        raise ValueError(f"manual_event.interaction_unsupported:{event.interaction_kind.value}")

    def flush_all(self, ended_at: datetime) -> tuple[TraceCandidate, ...]:
        """原子闭合全部完整窗口；任一窗口不完整时不修改任何窗口。"""

        windows = sorted(
            self._windows.values(), key=lambda item: item.ordinal or 0
        )
        emitted: list[TraceCandidate] = []
        for window in windows:
            self._registry.validate_active(
                window.reservation,
                page_runtime_ref=window.key.page_runtime_ref,
                frame_runtime_ref=window.key.frame_runtime_ref,
            )
            emitted.append(self._succeeded_candidate(window, ended_at))
        self._windows.clear()
        self._emitted_reservations.update(window.reservation for window in windows)
        return tuple(emitted)

    def finalize_all(
        self,
        ended_at: datetime,
        *,
        reservations_to_close: Iterable[CandidateReservation] | None = None,
        tail_expires_at: datetime | None = None,
    ) -> tuple[TraceCandidate, ...]:
        """控制权切换时原子终态化全部窗口并关闭因果入口。

        完整窗口形成 succeeded Candidate；尚缺最终值、仍在输入法组合态等
        不完整窗口形成 cancelled Candidate。关闭只禁止新的事实锁，已经在浏览器
        回调首次触发时锁定的异步事实仍可在 Session 的有界尾部窗口内完成。
        """

        windows = sorted(
            self._windows.values(),
            key=lambda item: (
                item.ordinal is None,
                item.ordinal or 0,
                item.started_at,
            ),
        )
        for window in windows:
            self._registry.validate_active(
                window.reservation,
                page_runtime_ref=window.key.page_runtime_ref,
                frame_runtime_ref=window.key.frame_runtime_ref,
            )
            self._validate_end_time(window, ended_at)

        owned_reservations = tuple(
            reservations_to_close
            if reservations_to_close is not None
            else (window.reservation for window in windows)
        )
        self._registry.validate_reservations(owned_reservations)
        owned_ids = {reservation.window_id for reservation in owned_reservations}
        if any(window.reservation.window_id not in owned_ids for window in windows):
            raise ValueError("manual_window.reservation_not_owned")

        emitted: list[TraceCandidate] = []
        for window in windows:
            try:
                candidate = self._succeeded_candidate(window, ended_at)
            except ValueError as exc:
                if not str(exc).startswith("manual_window.incomplete:"):
                    raise
                ordinal = window.ordinal or self._new_ordinal()
                candidate = self._cancelled_candidate(
                    window, ended_at, ordinal=ordinal
                )
            emitted.append(candidate)

        self._registry.close_many(
            owned_reservations,
            expires_at=tail_expires_at,
        )
        self._windows.clear()
        self._emitted_reservations.update(window.reservation for window in windows)
        return tuple(sorted(emitted, key=lambda item: item.ordinal))

    def cancel(
        self,
        reservation: CandidateReservation,
        ended_at: datetime,
        *,
        tail_expires_at: datetime | None = None,
    ) -> TraceCandidate:
        """把一个未闭合人工窗口显式终止，并关闭其事实活动窗口。"""

        self._registry.validate_active(
            reservation,
            page_runtime_ref=reservation.page_runtime_ref,
            frame_runtime_ref=reservation.frame_runtime_ref,
        )
        matches = [
            (key, window)
            for key, window in self._windows.items()
            if window.reservation is reservation
        ]
        if len(matches) != 1:
            raise ValueError(
                "manual_window.not_found"
                if not matches
                else "manual_window.multiple_for_reservation"
            )
        key, window = matches[0]
        self._validate_end_time(window, ended_at)
        if window.ordinal is None:
            window.ordinal = self._new_ordinal()
        candidate = self._cancelled_candidate(window, ended_at)
        del self._windows[key]
        self._registry.close(reservation, expires_at=tail_expires_at)
        self._emitted_reservations.add(reservation)
        return candidate

    def fail(
        self,
        reservation: CandidateReservation,
        event: ManualEvent,
        *,
        ended_at: datetime,
        error_code: str,
        error_message: str,
    ) -> TraceCandidate:
        """Terminalize a reserved action whose browser dispatch raised.

        The Candidate is retained even when the browser already produced a
        causally locked side effect. Settlement, rather than this adapter,
        decides whether it is rejected or needs user confirmation.
        """

        self._registry.validate_active(
            reservation,
            page_runtime_ref=event.page_runtime_ref,
            frame_runtime_ref=event.frame_runtime_ref,
        )
        if reservation in self._emitted_reservations:
            raise ValueError("manual_window.already_emitted")
        matches = [
            (key, window)
            for key, window in self._windows.items()
            if window.reservation is reservation
        ]
        if len(matches) > 1:
            raise ValueError("manual_window.multiple_for_reservation")
        if matches:
            key, window = matches[0]
            if key != self._key(event):
                raise ValueError("manual_window.failure_target_mismatch")
            self._validate_end_time(window, ended_at)
            ordinal = window.ordinal or self._new_ordinal()
            started_at = window.started_at
            del self._windows[key]
        else:
            self._ensure_not_before(
                ended_at,
                event.observed_at,
                "manual_event.ended_at_regressed",
            )
            ordinal = self._new_ordinal()
            started_at = event.observed_at
        candidate = self._candidate(
            reservation=reservation,
            ordinal=ordinal,
            started_at=started_at,
            ended_at=ended_at,
            action_hint=self._failed_action_hint(event),
            binding_hints=[],
            status="failed",
            error_code=error_code,
            error_message=error_message,
        )
        self._emitted_reservations.add(reservation)
        return candidate

    def _ingest_click(
        self, reservation: CandidateReservation, event: ManualEvent
    ) -> tuple[TraceCandidate, ...]:
        if event.kind is not ManualEventKind.CLICK:
            raise ValueError(f"manual_event.click_event_unsupported:{event.kind.value}")
        ordinal = self._new_ordinal()
        candidate = self._candidate(
            reservation=reservation,
            ordinal=ordinal,
            started_at=event.observed_at,
            ended_at=event.observed_at,
            action_hint={
                "kind": "click",
                "target_hint": self._target(
                    event.target_name,
                    event.target_locators,
                    event.target_path,
                ),
                "button": "left",
                "count": 1,
            },
            binding_hints=[deepcopy(dict(binding)) for binding in event.binding_hints],
            status="succeeded",
        )
        self._emitted_reservations.add(reservation)
        return (candidate,)

    def _ingest_fill(
        self,
        reservation: CandidateReservation,
        event: ManualEvent,
        key: _WindowKey,
    ) -> tuple[TraceCandidate, ...]:
        window = self._windows.get(key)
        if event.kind is ManualEventKind.BLUR:
            if window is None:
                return ()
            self._require_same_reservation(window, reservation)
            self._observe(window, event.observed_at)
            candidate = self._succeeded_candidate(window, event.observed_at)
            del self._windows[key]
            self._emitted_reservations.add(reservation)
            return (candidate,)

        if event.kind not in {
            ManualEventKind.INPUT,
            ManualEventKind.CHANGE,
            ManualEventKind.COMPOSITION_END,
        }:
            raise ValueError(f"manual_event.fill_event_unsupported:{event.kind.value}")

        if event.value is None:
            raise ValueError(f"manual_event.value_missing:{event.kind.value}")

        window = self._window_for_event(
            reservation, event, key, allocate_ordinal=True
        )
        if event.kind is ManualEventKind.COMPOSITION_END:
            window.composing = False
            window.final_value = event.value
            return ()
        if not window.composing:
            window.final_value = event.value
        return ()

    def _ingest_set_checked(
        self,
        reservation: CandidateReservation,
        event: ManualEvent,
        key: _WindowKey,
    ) -> tuple[TraceCandidate, ...]:
        if event.kind is ManualEventKind.CLICK:
            self._window_for_event(reservation, event, key, allocate_ordinal=True)
            return ()
        if event.kind is not ManualEventKind.CHANGE:
            raise ValueError(f"manual_event.checkbox_event_unsupported:{event.kind.value}")
        if event.checked is None:
            raise ValueError("manual_event.checked_missing")
        window = self._window_for_event(
            reservation, event, key, allocate_ordinal=True
        )
        window.checked = event.checked
        candidate = self._succeeded_candidate(window, event.observed_at)
        del self._windows[key]
        self._emitted_reservations.add(reservation)
        return (candidate,)

    def _window_for_event(
        self,
        reservation: CandidateReservation,
        event: ManualEvent,
        key: _WindowKey,
        *,
        allocate_ordinal: bool,
    ) -> _ManualWindow:
        window = self._windows.get(key)
        if window is not None:
            self._require_same_reservation(window, reservation)
            self._observe(window, event.observed_at)
            if allocate_ordinal and window.ordinal is None:
                window.ordinal = self._new_ordinal()
            return window
        if any(item.reservation is reservation for item in self._windows.values()):
            raise ValueError("manual_window.target_changed_requires_close")
        window = _ManualWindow(
            key=key,
            reservation=reservation,
            ordinal=self._new_ordinal() if allocate_ordinal else None,
            started_at=event.observed_at,
            last_observed_at=event.observed_at,
            target_name=event.target_name,
            target_locators=tuple(deepcopy(dict(locator)) for locator in event.target_locators),
            target_path=tuple(deepcopy(dict(step)) for step in event.target_path),
            binding_hints=tuple(
                deepcopy(dict(binding)) for binding in event.binding_hints
            ),
        )
        self._windows[key] = window
        return window

    @staticmethod
    def _require_same_reservation(
        window: _ManualWindow, reservation: CandidateReservation
    ) -> None:
        if window.reservation is not reservation:
            raise ValueError("manual_window.reservation_mismatch")

    @staticmethod
    def _key(event: ManualEvent) -> _WindowKey:
        return _WindowKey(
            page_runtime_ref=event.page_runtime_ref,
            frame_runtime_ref=event.frame_runtime_ref,
            target_key=event.target_key,
            interaction_kind=event.interaction_kind,
        )

    def _succeeded_candidate(
        self, window: _ManualWindow, ended_at: datetime
    ) -> TraceCandidate:
        self._validate_end_time(window, ended_at)
        if window.composing:
            self._raise_incomplete(window, "composition_active")
        if window.ordinal is None:
            self._raise_incomplete(window, "ordinal_missing")
        target = self._target(
            window.target_name,
            window.target_locators,
            window.target_path,
        )
        if window.key.interaction_kind is InteractionKind.FILL:
            if window.final_value is None:
                self._raise_incomplete(window, "final_value_missing")
            action_hint: dict[str, object] = {
                "kind": "fill",
                "target_hint": target,
            }
            binding_hints = [
                {
                    "name": "value",
                    "direction": "input",
                    "kind_hint": "literal",
                    "value": window.final_value,
                    "sensitive": False,
                }
            ] + [deepcopy(dict(binding)) for binding in window.binding_hints]
        elif window.key.interaction_kind is InteractionKind.SET_CHECKED:
            if window.checked is None:
                self._raise_incomplete(window, "checked_missing")
            action_hint = {
                "kind": "set_checked",
                "target_hint": target,
                "checked": window.checked,
            }
            binding_hints = [
                deepcopy(dict(binding)) for binding in window.binding_hints
            ]
        else:
            raise ValueError("manual_window.interaction_unsupported")
        return self._candidate(
            reservation=window.reservation,
            ordinal=window.ordinal,
            started_at=window.started_at,
            ended_at=ended_at,
            action_hint=action_hint,
            binding_hints=binding_hints,
            status="succeeded",
        )

    def _cancelled_candidate(
        self,
        window: _ManualWindow,
        ended_at: datetime,
        *,
        ordinal: int | None = None,
    ) -> TraceCandidate:
        self._validate_end_time(window, ended_at)
        if window.key.interaction_kind is InteractionKind.FILL:
            action_hint: dict[str, object] = {
                "kind": "fill",
                "target_hint": self._target(
                    window.target_name,
                    window.target_locators,
                    window.target_path,
                ),
            }
        else:
            action_hint = {
                "kind": "unsupported",
                "unsupported_name": "manual_set_checked_incomplete",
            }
        return self._candidate(
            reservation=window.reservation,
            ordinal=window.ordinal if ordinal is None else ordinal,
            started_at=window.started_at,
            ended_at=ended_at,
            action_hint=action_hint,
            binding_hints=[],
            status="cancelled",
        )

    @staticmethod
    def _candidate(
        *,
        reservation: CandidateReservation,
        ordinal: int,
        started_at: datetime,
        ended_at: datetime,
        action_hint: Mapping[str, object],
        binding_hints: list[dict[str, object]],
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> TraceCandidate:
        ManualInteractionAggregator._ensure_not_before(
            ended_at,
            started_at,
            "manual_event.ended_at_regressed",
        )
        execution: dict[str, object] = {
            "status": status,
            "started_at": started_at,
            "ended_at": ended_at,
            "output": None,
            "error": None,
        }
        if status == "cancelled":
            execution["error"] = {
                "code": "manual_cancelled",
                "message": "Manual interaction window was explicitly cancelled",
            }
        elif status == "failed":
            if not error_code or not error_message:
                raise ValueError("manual_failure.error_missing")
            execution["error"] = {
                "code": error_code,
                "message": error_message,
            }
        return TraceCandidate.model_validate(
            {
                "candidate_id": reservation.candidate_id,
                "ordinal": ordinal,
                "origin": "human",
                "scope_hint": {"page_ref": None, "frame_path": None},
                "action_hint": dict(action_hint),
                "binding_hints": binding_hints,
                "execution": execution,
            }
        )

    @staticmethod
    def _failed_action_hint(event: ManualEvent) -> dict[str, object]:
        if event.interaction_kind is InteractionKind.CLICK:
            return {
                "kind": "click",
                "target_hint": ManualInteractionAggregator._target(
                    event.target_name,
                    event.target_locators,
                    event.target_path,
                ),
                "button": "left",
                "count": 1,
            }
        if event.interaction_kind is InteractionKind.FILL:
            return {
                "kind": "fill",
                "target_hint": ManualInteractionAggregator._target(
                    event.target_name,
                    event.target_locators,
                    event.target_path,
                ),
            }
        return {
            "kind": "unsupported",
            "unsupported_name": "manual_set_checked_dispatch_failed",
        }

    @staticmethod
    def _target(
        name: str,
        locators: tuple[Mapping[str, object], ...],
        path: tuple[Mapping[str, object], ...] = (),
    ) -> dict[str, object]:
        target: dict[str, object] = {
            "name": name,
            "locators": [deepcopy(dict(locator)) for locator in locators],
        }
        if path:
            target["path"] = [deepcopy(dict(step)) for step in path]
        return target

    @staticmethod
    def _raise_incomplete(window: _ManualWindow, reason: str) -> None:
        raise ValueError(
            f"manual_window.incomplete:{window.reservation.candidate_id}:{reason}"
        )

    @staticmethod
    def _observe(window: _ManualWindow, observed_at: datetime) -> None:
        ManualInteractionAggregator._ensure_not_before(
            observed_at,
            window.last_observed_at,
            "manual_event.observed_at_regressed",
        )
        window.last_observed_at = observed_at

    @staticmethod
    def _validate_end_time(window: _ManualWindow, ended_at: datetime) -> None:
        ManualInteractionAggregator._ensure_not_before(
            ended_at,
            window.last_observed_at,
            "manual_event.ended_at_regressed",
        )

    @staticmethod
    def _ensure_not_before(
        value: datetime, lower_bound: datetime, error_code: str
    ) -> None:
        try:
            regressed = value < lower_bound
        except TypeError as exc:
            raise ValueError(f"{error_code}:incomparable") from exc
        if regressed:
            raise ValueError(error_code)

    def _new_ordinal(self) -> int:
        ordinal = self._allocate_ordinal()
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
            raise ValueError("manual_event.ordinal_invalid")
        return ordinal

    def _next_ordinal(self) -> int:
        self._ordinal += 1
        return self._ordinal
