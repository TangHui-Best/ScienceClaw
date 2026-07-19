"""Server-authored manual browser input for Skill creation.

The producer owns the reserve-before-default ordering.  Callers provide only
an opaque input id and browser input coordinates/text; Page/Frame scope and
locator candidates always come from the attached browser port.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import secrets
from typing import AsyncContextManager, Literal, Protocol, runtime_checkable

from ..creation import InteractionKind, ManualEvent, ManualEventKind


ManualInteraction = Literal["click", "fill", "set_checked"]


@dataclass(frozen=True, slots=True)
class ManualTarget:
    page_runtime_ref: str
    frame_runtime_ref: str
    target_key: str
    target_name: str
    target_locators: tuple[Mapping[str, object], ...]
    interaction_kind: ManualInteraction
    handle: object
    target_path: tuple[Mapping[str, object], ...] = ()
    page: object | None = None
    frame: object | None = None


@dataclass(frozen=True, slots=True)
class ManualInputCommand:
    input_id: str
    kind: Literal["click", "text", "paste"]
    draft_id: str | None = None
    x: float | None = None
    y: float | None = None
    text: str | None = None

    def __post_init__(self) -> None:
        if not self.input_id or len(self.input_id) > 128:
            raise ValueError("manual_input.input_id_invalid")
        if self.kind == "click":
            if self.x is None or self.y is None:
                raise ValueError("manual_input.coordinates_required")
            if self.text is not None:
                raise ValueError("manual_input.text_forbidden")
        else:
            if not isinstance(self.text, str) or not self.text:
                raise ValueError("manual_input.text_required")
            if self.x is not None or self.y is not None:
                raise ValueError("manual_input.coordinates_forbidden")


@dataclass(frozen=True, slots=True)
class ManualInputResult:
    input_id: str
    candidate_id: str
    candidate_ids: tuple[str, ...]


@runtime_checkable
class ManualInputPort(Protocol):
    async def resolve_pointer_target(self, *, x: float, y: float) -> ManualTarget: ...

    async def resolve_focused_target(self) -> ManualTarget: ...

    def action_dispatch_scope(
        self, target: ManualTarget
    ) -> AsyncContextManager[None]: ...

    async def click(self, target: ManualTarget) -> None: ...

    async def insert_text(self, target: ManualTarget, text: str) -> None: ...

    async def read_value(self, target: ManualTarget) -> str: ...

    async def read_checked(self, target: ManualTarget) -> bool: ...


@dataclass(slots=True)
class _ActiveFill:
    candidate_id: str
    token: str
    target: ManualTarget
    has_input: bool = False


class ManualInputProducer:
    """Translate atomic host input into the existing manual aggregation path."""

    def __init__(self, *, browser: object, port: ManualInputPort) -> None:
        self._browser = browser
        self._port = port
        self._results: dict[str, tuple[ManualInputCommand, ManualInputResult]] = {}
        self._failures: dict[str, tuple[ManualInputCommand, str]] = {}
        self._active_fill: _ActiveFill | None = None

    async def dispatch(self, command: ManualInputCommand) -> ManualInputResult:
        previous = self._results.get(command.input_id)
        if previous is not None:
            if previous[0] != command:
                raise ValueError("manual_input.id_payload_conflict")
            return previous[1]
        previous_failure = self._failures.get(command.input_id)
        if previous_failure is not None:
            if previous_failure[0] != command:
                raise ValueError("manual_input.id_payload_conflict")
            raise ValueError(previous_failure[1])

        try:
            if command.kind == "click":
                assert command.x is not None and command.y is not None
                target = await self._port.resolve_pointer_target(x=command.x, y=command.y)
                await self._flush_if_target_changed(target)
                result = await self._dispatch_click(command, target)
            else:
                target = await self._port.resolve_focused_target()
                if target.interaction_kind != "fill":
                    raise ValueError("manual_input.focused_target_not_editable")
                await self._flush_if_target_changed(target)
                result = await self._dispatch_text(command, target)
        except ValueError as exc:
            if str(exc).split(":", 1)[0] == "manual_input.dispatch_failed":
                self._failures[command.input_id] = (
                    command,
                    "manual_input.dispatch_failed",
                )
            raise

        self._results[command.input_id] = (command, result)
        return result

    def flush(self) -> tuple[str, ...]:
        if self._active_fill is None:
            return ()
        candidate_id = self._active_fill.candidate_id
        if self._active_fill.has_input:
            self._finish_active_fill()
        else:
            self._cancel_active_fill()
        return (candidate_id,)

    async def _dispatch_click(
        self, command: ManualInputCommand, target: ManualTarget
    ) -> ManualInputResult:
        if target.interaction_kind == "fill":
            candidate_id, token = self._reserve(target, candidate_id=command.draft_id)
            active = _ActiveFill(
                candidate_id=candidate_id,
                token=token,
                target=target,
            )
            self._active_fill = active
            focus_event = _event(
                target,
                kind=ManualEventKind.FOCUS,
                interaction=InteractionKind.FILL,
                observed_at=_now(),
            )
            try:
                self._browser.ingest_manual(
                    token=token,
                    event=focus_event,
                    finish=False,
                )
                async with self._port.action_dispatch_scope(target):
                    await self._port.click(target)
            except Exception as exc:
                self._active_fill = None
                self._record_dispatch_failure(
                    token=token,
                    event=focus_event,
                    error=exc,
                )
            return ManualInputResult(
                input_id=command.input_id,
                candidate_id=candidate_id,
                candidate_ids=(),
            )

        candidate_id, token = self._reserve(target, candidate_id=command.draft_id)
        failure_event = _event(
            target,
            kind=ManualEventKind.CLICK,
            interaction=(
                InteractionKind.SET_CHECKED
                if target.interaction_kind == "set_checked"
                else InteractionKind.CLICK
            ),
            observed_at=_now(),
        )
        try:
            async with self._port.action_dispatch_scope(target):
                await self._port.click(target)
        except Exception as exc:
            self._record_dispatch_failure(
                token=token,
                event=failure_event,
                error=exc,
            )
        try:
            observed_at = _now()
            if target.interaction_kind == "set_checked":
                self._browser.ingest_manual(
                    token=token,
                    event=_event(
                        target,
                        kind=ManualEventKind.CLICK,
                        interaction=InteractionKind.SET_CHECKED,
                        observed_at=observed_at,
                    ),
                    finish=False,
                )
                checked = await self._port.read_checked(target)
                emitted = self._browser.ingest_manual(
                    token=token,
                    event=_event(
                        target,
                        kind=ManualEventKind.CHANGE,
                        interaction=InteractionKind.SET_CHECKED,
                        observed_at=_now(),
                        checked=checked,
                    ),
                    finish=True,
                )
            elif target.interaction_kind == "click":
                emitted = self._browser.ingest_manual(
                    token=token,
                    event=_event(
                        target,
                        kind=ManualEventKind.CLICK,
                        interaction=InteractionKind.CLICK,
                        observed_at=observed_at,
                    ),
                    finish=True,
                )
            else:
                raise ValueError("manual_input.pointer_interaction_unsupported")
        except Exception as exc:
            self._record_dispatch_failure(
                token=token,
                event=failure_event,
                error=exc,
            )
        return ManualInputResult(
            input_id=command.input_id,
            candidate_id=candidate_id,
            candidate_ids=tuple(emitted),
        )

    async def _dispatch_text(
        self, command: ManualInputCommand, target: ManualTarget
    ) -> ManualInputResult:
        active = self._active_fill
        if active is None:
            candidate_id, token = self._reserve(target, candidate_id=command.draft_id)
            active = _ActiveFill(candidate_id=candidate_id, token=token, target=target)
            self._active_fill = active
        before_event = _event(
            target,
            kind=ManualEventKind.BEFORE_INPUT,
            interaction=InteractionKind.FILL,
            observed_at=_now(),
        )
        assert command.text is not None
        try:
            self._browser.ingest_manual(
                token=active.token,
                event=before_event,
                finish=False,
            )
            async with self._port.action_dispatch_scope(target):
                await self._port.insert_text(target, command.text)
            value = await self._port.read_value(target)
            self._browser.ingest_manual(
                token=active.token,
                event=_event(
                    target,
                    kind=ManualEventKind.INPUT,
                    interaction=InteractionKind.FILL,
                    observed_at=_now(),
                    value=value,
                ),
                finish=False,
            )
        except Exception as exc:
            self._active_fill = None
            self._record_dispatch_failure(
                token=active.token,
                event=before_event,
                error=exc,
            )
        active.has_input = True
        return ManualInputResult(
            input_id=command.input_id,
            candidate_id=active.candidate_id,
            candidate_ids=(),
        )

    async def _flush_if_target_changed(self, target: ManualTarget) -> None:
        active = self._active_fill
        if active is None:
            return
        if _target_identity(active.target) == _target_identity(target):
            return
        if active.has_input:
            self._finish_active_fill()
        else:
            self._cancel_active_fill()

    def _finish_active_fill(self) -> None:
        active = self._active_fill
        if active is None:
            return
        self._browser.ingest_manual(
            token=active.token,
            event=_event(
                active.target,
                kind=ManualEventKind.BLUR,
                interaction=InteractionKind.FILL,
                observed_at=_now(),
            ),
            finish=True,
        )
        self._active_fill = None

    def _cancel_active_fill(self) -> None:
        active = self._active_fill
        if active is None:
            return
        self._browser.cancel_manual(token=active.token, at=_now())
        self._active_fill = None

    def _record_dispatch_failure(
        self,
        *,
        token: str,
        event: ManualEvent,
        error: Exception,
    ) -> None:
        self._browser.fail_manual(
            token=token,
            event=event,
            at=_now(),
            error_code="manual_input.dispatch_failed",
            error_message=f"{type(error).__name__}: browser default action failed",
        )
        raise ValueError("manual_input.dispatch_failed") from error

    def _reserve(
        self, target: ManualTarget, *, candidate_id: str | None = None
    ) -> tuple[str, str]:
        candidate_id = candidate_id or "manual_" + secrets.token_hex(12)
        token = self._browser.reserve_manual(
            candidate_id=candidate_id,
            page_runtime_ref=target.page_runtime_ref,
            frame_runtime_ref=target.frame_runtime_ref,
        )
        return candidate_id, token


def _target_identity(target: ManualTarget) -> tuple[str, str, str, ManualInteraction]:
    return (
        target.page_runtime_ref,
        target.frame_runtime_ref,
        target.target_key,
        target.interaction_kind,
    )


def _event(
    target: ManualTarget,
    *,
    kind: ManualEventKind,
    interaction: InteractionKind,
    observed_at: datetime,
    value: str | None = None,
    checked: bool | None = None,
) -> ManualEvent:
    return ManualEvent(
        kind=kind,
        page_runtime_ref=target.page_runtime_ref,
        frame_runtime_ref=target.frame_runtime_ref,
        target_key=target.target_key,
        target_name=target.target_name,
        target_locators=target.target_locators,
        interaction_kind=interaction,
        observed_at=observed_at,
        target_path=target.target_path,
        value=value,
        checked=checked,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "ManualInputCommand",
    "ManualInputPort",
    "ManualInputProducer",
    "ManualInputResult",
    "ManualTarget",
]
