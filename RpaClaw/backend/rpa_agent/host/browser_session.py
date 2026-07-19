"""Browser-context reuse boundary for a greenfield Skill creation session.

This module deliberately knows only a current context/page and normalized
browser events.  It never imports the legacy RPA manager, trace, session, or
compiler.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import inspect
import json
import secrets
from threading import RLock
from typing import Any, Literal, Protocol, runtime_checkable

from ..contracts import BrowserScope
from ..creation import (
    InteractionKind,
    ManualEvent,
    ManualEventKind,
    SkillCreationSession,
)
from ..creation.candidate_registry import CandidateReservation
from ..creation.browser_facts import FactTrigger


@dataclass(frozen=True, slots=True)
class HostBrowserEvent:
    kind: Literal[
        "navigation", "new_page", "download", "page_activated", "page_closed"
    ]
    observed_at: datetime
    source_page_runtime_ref: str
    source_frame_runtime_ref: str
    runtime_page_ref: str
    detail: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HostDownloadEvent:
    """A download whose causal lock is acquired before completion is awaited."""

    observed_at: datetime
    source_page_runtime_ref: str
    source_frame_runtime_ref: str
    runtime_page_ref: str
    download_ref: str
    suggested_filename: str | None
    failure: Awaitable[str | None]


@dataclass(slots=True)
class _ActionDispatchCausalScope:
    source_page_runtime_ref: str
    source_frame_runtime_ref: str
    page_ids: set[int] = field(default_factory=set)


@runtime_checkable
class BrowserSessionPort(Protocol):
    """The only browser capabilities the new creation domain may consume."""

    context: object
    main_page: object
    main_page_runtime_ref: str
    main_frame_runtime_ref: str

    def subscribe(
        self,
        kind: str,
        callback: Callable[[HostBrowserEvent | HostDownloadEvent], None],
    ) -> Callable[[], None]: ...


class BrowserSession:
    """Owns listener and opaque manual-reservation lifecycles for one session."""

    _LISTENER_KINDS = ("navigation", "new_page", "download")

    def __init__(self, *, port: BrowserSessionPort, creation: SkillCreationSession) -> None:
        self.port = port
        self.creation = creation
        self._releases: list[Callable[[], None]] = []
        self._reservations: dict[str, CandidateReservation] = {}
        self._attached = False
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._background_failures: list[BaseException] = []
        self._pending_fact_counts: dict[str, int] = {}
        self._deferred_scopes: dict[str, BrowserScope] = {}
        self._fact_state_lock = RLock()
        self.cleanup_errors: list[str] = []
        from .manual_input import ManualInputPort, ManualInputProducer

        self._manual_input = (
            ManualInputProducer(browser=self, port=port)
            if isinstance(port, ManualInputPort)
            else None
        )

    @property
    def context(self) -> object:
        return self.port.context

    @property
    def main_page(self) -> object:
        return self.port.main_page

    @property
    def background_task_count(self) -> int:
        return len(self._background_tasks)

    def attach(self) -> None:
        if self._attached:
            raise ValueError("browser_session.already_attached")
        installed: list[Callable[[], None]] = []
        try:
            for kind in self._LISTENER_KINDS:
                installed.append(self.port.subscribe(kind, self.handle_event))
        except BaseException as primary:
            self._release_callbacks(installed, primary=primary)
            raise
        self._releases = installed
        self._attached = True

    def reserve_manual(
        self,
        *,
        candidate_id: str,
        page_runtime_ref: str,
        frame_runtime_ref: str,
    ) -> str:
        reservation = self.creation.reserve_manual(
            candidate_id=candidate_id,
            page_runtime_ref=page_runtime_ref,
            frame_runtime_ref=frame_runtime_ref,
        )
        token = secrets.token_urlsafe(32)
        self._reservations[token] = reservation
        return token

    def ingest_manual(
        self,
        *,
        token: str,
        event: ManualEvent,
        finish: bool,
    ) -> tuple[str, ...]:
        reservation = self._reservations.get(token)
        if reservation is None:
            raise ValueError("manual_reservation.invalid")
        if (
            event.page_runtime_ref != reservation.page_runtime_ref
            or event.frame_runtime_ref != reservation.frame_runtime_ref
        ):
            raise ValueError("manual_reservation.scope_mismatch")
        emitted = self.creation.ingest_manual(reservation, event)
        if finish:
            self.creation.finish_manual_candidate(reservation, at=event.observed_at)
            del self._reservations[token]
            for candidate in emitted:
                scope = self._scope_for(
                    event.page_runtime_ref,
                    event.frame_runtime_ref,
                )
                self._settle_or_defer(candidate.candidate_id, scope=scope)
        return tuple(item.candidate_id for item in emitted)

    def fail_manual(
        self,
        *,
        token: str,
        event: ManualEvent,
        at: datetime,
        error_code: str,
        error_message: str,
    ) -> str:
        reservation = self._reservation_for_event(token=token, event=event)
        candidate = self.creation.fail_manual_candidate(
            reservation,
            event,
            at=at,
            error_code=error_code,
            error_message=error_message,
        )
        del self._reservations[token]
        self._settle_or_defer(
            candidate.candidate_id,
            scope=self._scope_for(
                reservation.page_runtime_ref,
                reservation.frame_runtime_ref,
            ),
        )
        return candidate.candidate_id

    def cancel_manual(self, *, token: str, at: datetime) -> str:
        reservation = self._reservations.get(token)
        if reservation is None:
            raise ValueError("manual_reservation.invalid")
        candidate = self.creation.cancel_manual_candidate(reservation, at=at)
        del self._reservations[token]
        self._settle_or_defer(
            candidate.candidate_id,
            scope=self._scope_for(
                reservation.page_runtime_ref,
                reservation.frame_runtime_ref,
            ),
        )
        return candidate.candidate_id

    def _reservation_for_event(
        self, *, token: str, event: ManualEvent
    ) -> CandidateReservation:
        reservation = self._reservations.get(token)
        if reservation is None:
            raise ValueError("manual_reservation.invalid")
        if (
            event.page_runtime_ref != reservation.page_runtime_ref
            or event.frame_runtime_ref != reservation.frame_runtime_ref
        ):
            raise ValueError("manual_reservation.scope_mismatch")
        return reservation

    def finalize_recording(self, *, at: datetime) -> tuple[str, ...]:
        """Finalize open human windows without destroying the CoreTrace state."""

        flushed = self._manual_input.flush() if self._manual_input is not None else ()
        finalized = self._finalize_manual_for_agent(at=at)
        return tuple(dict.fromkeys((*flushed, *finalized)))

    def enter_agent_control(self, *, at: datetime) -> tuple[str, ...]:
        """Finalize and settle open manual candidates before Agent actions start."""

        from ..creation import ControlMode

        if self.creation.control_mode is ControlMode.AGENT:
            return ()
        flushed = self._manual_input.flush() if self._manual_input is not None else ()
        finalized = self._finalize_manual_for_agent(at=at)
        return tuple(dict.fromkeys((*flushed, *finalized)))

    async def dispatch_manual_input(self, command: object) -> object:
        if self._manual_input is None:
            raise RuntimeError("browser_session.manual_input_unavailable")
        return await self._manual_input.dispatch(command)

    def _finalize_manual_for_agent(self, *, at: datetime) -> tuple[str, ...]:
        from ..creation import ControlMode

        emitted = self.creation.switch_control(ControlMode.AGENT, at=at)
        by_candidate = {
            reservation.candidate_id: reservation
            for reservation in self._reservations.values()
        }
        for candidate in emitted:
            reservation = by_candidate.get(candidate.candidate_id)
            if reservation is None:
                raise ValueError("manual_reservation.finalize_scope_missing")
            self._settle_or_defer(
                candidate.candidate_id,
                scope=self._scope_for(
                    reservation.page_runtime_ref,
                    reservation.frame_runtime_ref,
                ),
            )
        self._reservations.clear()
        return tuple(candidate.candidate_id for candidate in emitted)

    def manual_event_from_payload(self, payload: object) -> ManualEvent:
        return ManualEvent(
            kind=ManualEventKind(getattr(payload, "kind")),
            page_runtime_ref=getattr(payload, "page_runtime_ref"),
            frame_runtime_ref=getattr(payload, "frame_runtime_ref"),
            target_key=getattr(payload, "target_key"),
            target_name=getattr(payload, "target_name"),
            target_locators=tuple(getattr(payload, "target_locators")),
            interaction_kind=InteractionKind(getattr(payload, "interaction_kind")),
            observed_at=getattr(payload, "observed_at"),
            target_path=tuple(getattr(payload, "target_path")),
            binding_hints=tuple(getattr(payload, "binding_hints")),
            value=getattr(payload, "value"),
            checked=getattr(payload, "checked"),
        )

    def _scope_for(self, page_runtime_ref: str, frame_runtime_ref: str) -> BrowserScope:
        page_ref = self.creation.pages.resolve(page_runtime_ref)
        resolver = getattr(self.port, "resolve_frame_path", None)
        if callable(resolver):
            frame_path = resolver(page_runtime_ref, frame_runtime_ref)
        elif frame_runtime_ref == self.port.main_frame_runtime_ref:
            frame_path = ()
        else:
            raise ValueError("browser_session.frame_path_unavailable")
        return BrowserScope.model_validate(
            {"page_ref": page_ref, "frame_path": list(frame_path)}
        )

    def handle_event(
        self,
        event: HostBrowserEvent | HostDownloadEvent | Mapping[str, object],
    ) -> None:
        if isinstance(event, HostDownloadEvent):
            trigger = self.creation.observer.start_download(
                event.source_page_runtime_ref,
                event.source_frame_runtime_ref,
            )
            candidate_id = (
                trigger.locked_candidate.candidate_id
                if trigger.locked_candidate is not None
                else None
            )
            if candidate_id is not None:
                with self._fact_state_lock:
                    self._pending_fact_counts[candidate_id] = (
                        self._pending_fact_counts.get(candidate_id, 0) + 1
                    )
            task = asyncio.create_task(self._complete_download(event, trigger))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_task_done)
            return
        if not isinstance(event, HostBrowserEvent):
            event = HostBrowserEvent(**event)  # type: ignore[arg-type]
        if event.observed_at.utcoffset() is None:
            raise ValueError("browser_session.event_time_naive")
        observer = self.creation.observer
        if event.kind == "navigation":
            trigger = observer.start_navigation(
                event.source_page_runtime_ref, event.source_frame_runtime_ref
            )
            fact = observer.complete_navigation(
                trigger,
                observed_at=event.observed_at,
                page_runtime_ref=event.runtime_page_ref,
                frame_runtime_ref=str(
                    event.detail.get("frame_runtime_ref", event.source_frame_runtime_ref)
                ),
                is_main_frame=bool(event.detail.get("is_main_frame", True)),
                url=str(event.detail.get("url", "")),
            )
            self.creation.pages.apply(fact)
            return
        if event.kind == "new_page":
            trigger = observer.start_new_page(
                event.source_page_runtime_ref, event.source_frame_runtime_ref
            )
            fact = observer.complete_new_page(
                trigger,
                observed_at=event.observed_at,
                new_page_runtime_ref=event.runtime_page_ref,
                initial_url=str(event.detail.get("initial_url", "")),
            )
            self.creation.pages.apply(fact)
            return
        if event.kind == "page_activated":
            trigger = observer.start_page_activated(
                event.source_page_runtime_ref, event.source_frame_runtime_ref
            )
            fact = observer.complete_page_activated(
                trigger,
                observed_at=event.observed_at,
                page_runtime_ref=event.runtime_page_ref,
            )
            self.creation.pages.apply(fact)
            return
        if event.kind == "page_closed":
            trigger = observer.start_page_closed(
                event.source_page_runtime_ref, event.source_frame_runtime_ref
            )
            fact = observer.complete_page_closed(
                trigger,
                observed_at=event.observed_at,
                page_runtime_ref=event.runtime_page_ref,
            )
            self.creation.pages.apply(fact)
            return
        trigger = observer.start_download(
            event.source_page_runtime_ref, event.source_frame_runtime_ref
        )
        observer.complete_download(
            trigger,
            observed_at=event.observed_at,
            page_runtime_ref=event.runtime_page_ref,
            download_ref=str(event.detail["download_ref"]),
            status=str(event.detail["status"]),  # type: ignore[arg-type]
            suggested_filename=(
                str(event.detail["suggested_filename"])
                if event.detail.get("suggested_filename") is not None
                else None
            ),
            failure_reason=(
                str(event.detail["failure_reason"])
                if event.detail.get("failure_reason") is not None
                else None
            ),
        )

    async def _complete_download(
        self,
        event: HostDownloadEvent,
        trigger: FactTrigger,
    ) -> None:
        observer = self.creation.observer
        try:
            failure = await event.failure
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            observer.cancel_trigger(trigger)
            raise
        except BaseException as exc:
            failure = f"failure_check_error:{type(exc).__name__}"
        observer.complete_download(
            trigger,
            observed_at=datetime.now(timezone.utc),
            page_runtime_ref=event.runtime_page_ref,
            download_ref=event.download_ref,
            status="failed" if failure else "completed",
            suggested_filename=event.suggested_filename,
            failure_reason=failure,
        )
        self._complete_pending_candidate(trigger)

    def _complete_pending_candidate(self, trigger: FactTrigger) -> None:
        locked = trigger.locked_candidate
        if locked is None:
            return
        candidate_id = locked.candidate_id
        deferred_scope: BrowserScope | None = None
        with self._fact_state_lock:
            count = self._pending_fact_counts.get(candidate_id, 0)
            if count <= 1:
                self._pending_fact_counts.pop(candidate_id, None)
                deferred_scope = self._deferred_scopes.pop(candidate_id, None)
            else:
                self._pending_fact_counts[candidate_id] = count - 1
        if deferred_scope is not None:
            self._settle_now(candidate_id, scope=deferred_scope)

    def _settle_or_defer(self, candidate_id: str, *, scope: BrowserScope) -> None:
        with self._fact_state_lock:
            if self._pending_fact_counts.get(candidate_id, 0):
                if candidate_id in self._deferred_scopes:
                    raise ValueError("browser_session.settlement_already_deferred")
                self._deferred_scopes[candidate_id] = scope
                return
        self._settle_now(candidate_id, scope=scope)

    def _settle_now(self, candidate_id: str, *, scope: BrowserScope) -> None:
        candidate = self.creation.candidates[candidate_id]
        asset_refs = {
            hint.ref_hint
            for hint in candidate.binding_hints
            if hint.direction == "output"
            and hint.kind_hint == "data_asset"
            and hint.ref_hint is not None
        }
        completed_download_refs = {
            fact.detail.download_ref
            for fact in self.creation.fact_buffer.facts()
            if fact.candidate_id == candidate_id
            and fact.kind == "download"
            and fact.detail.status == "completed"
        }
        resolved_assets: dict[str, str] = {}
        if len(asset_refs) == 1:
            asset_ref = next(iter(asset_refs))
            resolved_assets = {
                download_ref: asset_ref
                for download_ref in completed_download_refs
            }
        self.creation.settle_candidate(
            candidate_id,
            scope=scope,
            resolved_assets=resolved_assets,
        )

    async def drain_pending_facts(self, *, timeout: float) -> None:
        if timeout <= 0:
            raise ValueError("browser_session.drain_timeout_invalid")
        tasks = tuple(self._background_tasks)
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=timeout)
            if pending:
                raise ValueError("browser_session.pending_fact_timeout")
            for task in done:
                if not task.cancelled() and task.exception() is not None:
                    raise ValueError("browser_session.background_fact_failed")
        with self._fact_state_lock:
            if self._pending_fact_counts or self._deferred_scopes:
                raise ValueError("browser_session.pending_fact_incomplete")
        if self._background_failures:
            raise ValueError("browser_session.background_fact_failed")

    def _background_task_done(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self.cleanup_errors.append(type(error).__name__)
            self._background_failures.append(error)

    def detach(self, *, primary: BaseException | None = None) -> None:
        releases, self._releases = self._releases, []
        self._attached = False
        self._release_callbacks(releases, primary=primary)

    def close(self, *, at: datetime, primary: BaseException | None = None) -> None:
        if self._background_tasks:
            raise RuntimeError("browser_session.async_close_required")
        self._close_without_background_tasks(at=at, primary=primary)

    async def aclose(
        self,
        *,
        at: datetime,
        primary: BaseException | None = None,
    ) -> None:
        try:
            self.detach(primary=primary)
        except BaseException:
            if primary is None:
                raise
        tasks = tuple(self._background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.difference_update(tasks)
        with self._fact_state_lock:
            self._pending_fact_counts.clear()
            self._deferred_scopes.clear()
        self._background_failures.clear()
        try:
            self._close_without_background_tasks(
                at=at,
                primary=primary,
                already_detached=True,
            )
        finally:
            close_port = getattr(self.port, "aclose", None)
            if callable(close_port):
                try:
                    result = close_port()
                    if inspect.isawaitable(result):
                        await result
                except BaseException as cleanup:
                    if primary is None:
                        raise
                    self.cleanup_errors.append(type(cleanup).__name__)

    def _close_without_background_tasks(
        self,
        *,
        at: datetime,
        primary: BaseException | None,
        already_detached: bool = False,
    ) -> None:
        try:
            if not already_detached:
                self.detach(primary=primary)
        finally:
            self._reservations.clear()
            if not self.creation.closed:
                try:
                    self.creation.close(at=at)
                except BaseException as cleanup:
                    if primary is None:
                        raise
                    self.cleanup_errors.append(type(cleanup).__name__)

    def _release_callbacks(
        self,
        callbacks: Sequence[Callable[[], None]],
        *,
        primary: BaseException | None,
    ) -> None:
        first: BaseException | None = None
        for release in reversed(tuple(callbacks)):
            try:
                release()
            except BaseException as cleanup:
                self.cleanup_errors.append(type(cleanup).__name__)
                if first is None:
                    first = cleanup
        if primary is None and first is not None:
            raise first


class PlaywrightBrowserSessionPort:
    """Thin normalized event adapter around an already-owned Playwright context."""

    def __init__(
        self,
        *,
        context: object,
        main_page: object,
        main_page_runtime_ref: str,
        main_frame_runtime_ref: str,
        page_runtime_ref: Callable[[object], str],
        frame_runtime_ref: Callable[[object], str],
        frame_path: Callable[[str, str], Sequence[Mapping[str, object]]],
        page_main_frame_runtime_ref: Callable[[object], str],
        active_page: Callable[[], object | None] | None = None,
        browser_use_cdp_url: str | None = None,
        cleanup: Callable[[], Awaitable[None] | None] | None = None,
    ) -> None:
        self.context = context
        self.main_page = main_page
        self.main_page_runtime_ref = main_page_runtime_ref
        self.main_frame_runtime_ref = main_frame_runtime_ref
        self._page_runtime_ref = page_runtime_ref
        self._frame_runtime_ref = frame_runtime_ref
        self._frame_path = frame_path
        self._page_main_frame_runtime_ref = page_main_frame_runtime_ref
        self._active_page = active_page or (lambda: self.main_page)
        self.browser_use_cdp_url = browser_use_cdp_url
        self._cleanup = cleanup
        self._cleanup_complete = False
        self._cleanup_lock = asyncio.Lock()
        self._page_subscriptions: list[dict[str, Any]] = []
        self._dispatch_scopes: dict[int, _ActionDispatchCausalScope] = {}
        self._validated_frame_paths: dict[
            tuple[str, str], tuple[Mapping[str, object], ...]
        ] = {}

    async def aclose(self) -> None:
        """Release only resources explicitly owned by this host port."""

        async with self._cleanup_lock:
            if self._cleanup_complete:
                return
            self._cleanup_complete = True
            if self._cleanup is None:
                return
            result = self._cleanup()
            if inspect.isawaitable(result):
                await result

    async def active_page_object(self) -> object:
        page = self._active_page()
        page = await page if inspect.isawaitable(page) else page
        if page is None:
            raise ValueError("browser_session.active_page_unavailable")
        return page

    def page_runtime_ref(self, page: object) -> str:
        return self._page_runtime_ref(page)

    def frame_runtime_ref(self, frame: object) -> str:
        return self._frame_runtime_ref(frame)

    def page_main_frame_runtime_ref(self, page: object) -> str:
        return self._page_main_frame_runtime_ref(page)

    async def validate_semantic_target(
        self,
        *,
        page: object,
        frame_path: Sequence[Mapping[str, object]],
        target_hint: Mapping[str, object],
    ) -> int:
        """Validate stable candidates without using nth/first or DOM order."""

        locator = await self._resolve_semantic_locator(
            page=page,
            frame_path=frame_path,
            target_hint=target_hint,
        )
        return 1 if locator is not None else 0

    async def semantic_action_evidence(
        self,
        *,
        action_name: str,
        page: object,
        frame_path: Sequence[Mapping[str, object]],
        target_hint: Mapping[str, object],
        expected: object | None = None,
    ) -> Mapping[str, object]:
        """Read action-specific evidence from one uniquely resolved locator."""

        locator = await self._resolve_semantic_locator(
            page=page,
            frame_path=frame_path,
            target_hint=target_hint,
        )
        if locator is None:
            raise ValueError("browser_session.semantic_target_not_unique")
        if action_name == "click":
            return {"dispatched": True}
        if action_name == "input":
            value = await self._await_call(getattr(locator, "input_value"))
            return {"dom_value": str(value)}
        if action_name == "select_dropdown":
            selected = await self._await_call(
                getattr(locator, "evaluate"),
                """node => {
                    const option = node.selectedOptions && node.selectedOptions[0];
                    return option ? {value: String(option.value), label: String(option.label)} : null;
                }""",
            )
            if not isinstance(selected, Mapping):
                raise ValueError("browser_session.selected_option_unavailable")
            value = str(selected.get("value", ""))
            label = str(selected.get("label", ""))
            matched = expected if expected in {value, label} else value
            return {"selected": matched, "selected_value": value}
        raise ValueError("browser_session.semantic_evidence_action_unsupported")

    async def _resolve_semantic_locator(
        self,
        *,
        page: object,
        frame_path: Sequence[Mapping[str, object]],
        target_hint: Mapping[str, object],
    ) -> object | None:
        scope = page
        for step in frame_path:
            locator = await self._first_unique_locator(scope, step.get("locators", ()))
            if locator is None:
                return None
            element = await self._await_call(getattr(locator, "element_handle"))
            if element is None:
                return None
            content_frame = await self._await_call(getattr(element, "content_frame"))
            if content_frame is None:
                return None
            scope = content_frame
        return await self._first_unique_locator(
            scope, target_hint.get("locators", ())
        )

    async def _first_unique_locator(
        self, scope: object, specs: object
    ) -> object | None:
        if not isinstance(specs, Sequence) or isinstance(specs, (str, bytes)):
            return None
        for raw in specs:
            if not isinstance(raw, Mapping):
                continue
            locator = self._locator_from_spec(scope, raw)
            count = await self._await_call(getattr(locator, "count"))
            if count == 1:
                return locator
        return None

    def resolve_frame_path(
        self, page_runtime_ref: str, frame_runtime_ref: str
    ) -> Sequence[Mapping[str, object]]:
        cached = self._validated_frame_paths.get(
            (page_runtime_ref, frame_runtime_ref)
        )
        if cached is not None:
            return tuple(dict(step) for step in cached)
        return self._frame_path(page_runtime_ref, frame_runtime_ref)

    async def resolve_pointer_target(self, *, x: float, y: float):
        page = self._active_page()
        page = await page if inspect.isawaitable(page) else page
        if page is None:
            raise ValueError("manual_input.active_page_unavailable")
        main_frame = getattr(page, "main_frame", None)
        if main_frame is None:
            raise ValueError("manual_input.main_frame_unavailable")
        frame, element = await self._hit_test(main_frame, x=x, y=y)
        return await self._manual_target(page=page, frame=frame, element=element)

    async def resolve_focused_target(self):
        page = self._active_page()
        page = await page if inspect.isawaitable(page) else page
        if page is None:
            raise ValueError("manual_input.active_page_unavailable")
        frames = tuple(getattr(page, "frames", ()) or (getattr(page, "main_frame"),))
        ordered = sorted(frames, key=self._frame_depth, reverse=True)
        for frame in ordered:
            raw = await self._await_call(
                getattr(frame, "evaluate_handle"),
                "() => document.activeElement",
            )
            element = self._as_element(raw)
            if element is None:
                continue
            snapshot = await self._snapshot(element)
            if snapshot["tag"] in {"body", "html", "iframe"}:
                continue
            actionable = await self._actionable_element(element)
            try:
                return await self._manual_target(
                    page=page,
                    frame=frame,
                    element=actionable,
                )
            except ValueError as exc:
                if str(exc) != "manual_input.target_locator_unavailable":
                    raise
        raise ValueError("manual_input.focused_target_unavailable")

    @asynccontextmanager
    async def action_dispatch_scope(self, target):
        page = getattr(target, "page", None)
        if page is None:
            raise ValueError("manual_input.target_page_unavailable")
        page_id = id(page)
        if page_id in self._dispatch_scopes:
            raise ValueError("manual_input.action_scope_occupied")
        scope = _ActionDispatchCausalScope(
            source_page_runtime_ref=target.page_runtime_ref,
            source_frame_runtime_ref=target.frame_runtime_ref,
        )
        self._bind_page_to_dispatch_scope(page, scope)
        try:
            yield
        finally:
            for bound_page_id in tuple(scope.page_ids):
                if self._dispatch_scopes.get(bound_page_id) is scope:
                    del self._dispatch_scopes[bound_page_id]
            scope.page_ids.clear()

    async def click(self, target) -> None:
        await self._await_call(getattr(target.handle, "click"))

    async def insert_text(self, target, text: str) -> None:
        method = getattr(target.handle, "press_sequentially", None)
        if not callable(method):
            method = getattr(target.handle, "type", None)
        if not callable(method):
            raise ValueError("manual_input.text_dispatch_unavailable")
        await self._await_call(method, text)

    async def read_value(self, target) -> str:
        value = await self._await_call(
            getattr(target.handle, "evaluate"),
            "(node) => String(node.value ?? node.textContent ?? '')",
        )
        return str(value)

    async def read_checked(self, target) -> bool:
        value = await self._await_call(
            getattr(target.handle, "evaluate"),
            "(node) => Boolean(node.checked)",
        )
        if not isinstance(value, bool):
            raise ValueError("manual_input.checked_state_invalid")
        return value

    async def _hit_test(
        self, frame: object, *, x: float, y: float
    ) -> tuple[object, object]:
        raw = await self._await_call(
            getattr(frame, "evaluate_handle"),
            "([x, y]) => document.elementFromPoint(x, y)",
            [x, y],
        )
        element = self._as_element(raw)
        if element is None:
            raise ValueError("manual_input.pointer_target_unavailable")
        snapshot = await self._snapshot(element)
        if snapshot["tag"] == "iframe":
            content_frame = await self._await_call(getattr(element, "content_frame"))
            box = await self._await_call(
                getattr(element, "evaluate"),
                """(node) => {
                    const rect = node.getBoundingClientRect();
                    return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
                }""",
            )
            if content_frame is not None and isinstance(box, Mapping):
                return await self._hit_test(
                    content_frame,
                    x=x - float(box["x"]),
                    y=y - float(box["y"]),
                )
        return frame, await self._actionable_element(element)

    async def _actionable_element(self, element: object) -> object:
        raw = await self._await_call(
            getattr(element, "evaluate_handle"),
            """(node) => {
                if (node instanceof HTMLLabelElement && node.control) return node.control;
                return node.closest('button,a,input,textarea,select,[role],[contenteditable="true"]') || node;
            }""",
        )
        actionable = self._as_element(raw)
        if actionable is None:
            raise ValueError("manual_input.actionable_target_unavailable")
        return actionable

    async def _manual_target(self, *, page: object, frame: object, element: object):
        from .manual_input import ManualTarget

        snapshot = await self._snapshot(element)
        if snapshot["tag"] == "select":
            raise ValueError("manual_input.native_select_unsupported")
        locators = await self._unique_locators(frame, element, snapshot)
        if not locators:
            raise ValueError("manual_input.target_locator_unavailable")
        page_ref = self._page_runtime_ref(page)
        frame_ref = self._frame_runtime_ref(frame)
        frame_path = await self._validated_frame_path(page, frame)
        self._validated_frame_paths[(page_ref, frame_ref)] = frame_path
        interaction_kind = self._interaction_kind(snapshot)
        name = self._target_name(snapshot)
        stable_key = json.dumps(locators, ensure_ascii=False, sort_keys=True)
        target_key = "target_" + hashlib.sha256(
            f"{page_ref}|{frame_ref}|{stable_key}".encode("utf-8")
        ).hexdigest()[:24]
        return ManualTarget(
            page_runtime_ref=page_ref,
            frame_runtime_ref=frame_ref,
            target_key=target_key,
            target_name=name,
            target_locators=locators,
            interaction_kind=interaction_kind,
            handle=element,
            page=page,
            frame=frame,
        )

    async def _validated_frame_path(
        self, page: object, frame: object
    ) -> tuple[Mapping[str, object], ...]:
        main_frame = getattr(page, "main_frame", None)
        if frame is main_frame:
            return ()
        reversed_steps: list[Mapping[str, object]] = []
        current = frame
        while current is not main_frame:
            parent = getattr(current, "parent_frame", None)
            if parent is None:
                raise ValueError("manual_input.frame_parent_chain_invalid")
            frame_element = await self._await_call(getattr(current, "frame_element"))
            snapshot = await self._snapshot(frame_element)
            locators = await self._unique_locators(parent, frame_element, snapshot)
            if not locators:
                raise ValueError("manual_input.frame_locator_unavailable")
            name = str(snapshot.get("name_attr") or getattr(current, "name", "")).strip()
            if not name:
                name = self._target_name(snapshot)
            reversed_steps.append({"name": name, "locators": list(locators)})
            current = parent
        return tuple(reversed(reversed_steps))

    async def _unique_locators(
        self,
        frame: object,
        element: object,
        snapshot: Mapping[str, object],
    ) -> tuple[Mapping[str, object], ...]:
        candidates = self._locator_candidates(snapshot)
        unique: list[Mapping[str, object]] = []
        seen: set[str] = set()
        for spec in candidates:
            fingerprint = json.dumps(spec, ensure_ascii=False, sort_keys=True)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            locator = self._locator_from_spec(frame, spec)
            count = await self._await_call(getattr(locator, "count"))
            if count != 1:
                continue
            candidate = await self._await_call(getattr(locator, "element_handle"))
            if candidate is None:
                continue
            identical = await self._await_call(
                getattr(element, "evaluate"),
                "(node, candidate) => node === candidate",
                candidate,
            )
            if identical is True:
                unique.append(dict(spec))
        return tuple(unique)

    @staticmethod
    def _locator_candidates(
        snapshot: Mapping[str, object]
    ) -> tuple[Mapping[str, object], ...]:
        candidates: list[Mapping[str, object]] = []
        test_id = str(snapshot.get("test_id", "")).strip()
        if test_id:
            candidates.append({"strategy": "test_id", "value": test_id, "exact": True})
        role = str(snapshot.get("role", "")).strip()
        accessible_name = PlaywrightBrowserSessionPort._accessible_name(snapshot)
        if role:
            role_locator: dict[str, object] = {
                "strategy": "role",
                "role": role,
                "exact": True,
            }
            if accessible_name:
                role_locator["name"] = accessible_name
            candidates.append(role_locator)
        for strategy, key in (
            ("label", "label"),
            ("placeholder", "placeholder"),
            ("title", "title"),
            ("alt_text", "alt"),
        ):
            value = str(snapshot.get(key, "")).strip()
            if value:
                candidates.append(
                    {"strategy": strategy, "value": value, "exact": True}
                )
        if not bool(snapshot.get("editable", False)):
            text = str(snapshot.get("text", "")).strip()
            if text:
                candidates.append(
                    {"strategy": "text", "value": text, "exact": True}
                )
        if str(snapshot.get("tag", "")) == "iframe":
            name_attr = str(snapshot.get("name_attr", "")).strip()
            if name_attr:
                candidates.append(
                    {
                        "strategy": "css",
                        "value": "iframe[name=" + json.dumps(name_attr) + "]",
                    }
                )
        return tuple(candidates)

    @staticmethod
    def _locator_from_spec(frame: object, spec: Mapping[str, object]) -> object:
        strategy = spec["strategy"]
        if strategy == "role":
            kwargs: dict[str, object] = {"exact": bool(spec.get("exact", True))}
            if "name" in spec:
                kwargs["name"] = spec["name"]
            return getattr(frame, "get_by_role")(spec["role"], **kwargs)
        method_names = {
            "test_id": "get_by_test_id",
            "label": "get_by_label",
            "placeholder": "get_by_placeholder",
            "text": "get_by_text",
            "title": "get_by_title",
            "alt_text": "get_by_alt_text",
        }
        if strategy in method_names:
            method = getattr(frame, method_names[strategy])
            if strategy == "test_id":
                return method(spec["value"])
            return method(spec["value"], exact=bool(spec.get("exact", True)))
        return getattr(frame, "locator")(spec["value"])

    @staticmethod
    async def _snapshot(element: object) -> Mapping[str, object]:
        snapshot = await PlaywrightBrowserSessionPort._await_call(
            getattr(element, "evaluate"),
            """(node) => {
                const tag = node.tagName.toLowerCase();
                const implicitRole = tag === 'button' ? 'button'
                    : tag === 'a' && node.hasAttribute('href') ? 'link'
                    : tag === 'textarea' ? 'textbox'
                    : tag === 'select' ? 'combobox'
                    : tag === 'input' && ['checkbox', 'radio'].includes(node.type) ? node.type
                    : tag === 'input' ? 'textbox' : '';
                const labels = node.labels ? Array.from(node.labels)
                    .map((label) => label.innerText.trim()).filter(Boolean) : [];
                return {
                    tag,
                    role: node.getAttribute('role') || implicitRole,
                    text: (node.innerText || node.textContent || '').trim(),
                    aria_label: (node.getAttribute('aria-label') || '').trim(),
                    label: labels.join(' ').trim(),
                    placeholder: (node.getAttribute('placeholder') || '').trim(),
                    title: (node.getAttribute('title') || '').trim(),
                    alt: (node.getAttribute('alt') || '').trim(),
                    test_id: (node.getAttribute('data-testid') || '').trim(),
                    name_attr: (node.getAttribute('name') || '').trim(),
                    input_type: (node.getAttribute('type') || '').toLowerCase(),
                    editable: tag === 'input' || tag === 'textarea' || node.isContentEditable,
                    checked: Boolean(node.checked),
                };
            }""",
        )
        if not isinstance(snapshot, Mapping) or not snapshot.get("tag"):
            raise ValueError("manual_input.target_snapshot_invalid")
        return snapshot

    @staticmethod
    def _interaction_kind(snapshot: Mapping[str, object]) -> str:
        if str(snapshot.get("input_type", "")) in {"checkbox", "radio"}:
            return "set_checked"
        if bool(snapshot.get("editable", False)):
            return "fill"
        return "click"

    @staticmethod
    def _target_name(snapshot: Mapping[str, object]) -> str:
        for key in (
            "aria_label",
            "label",
            "text",
            "placeholder",
            "title",
            "alt",
            "name_attr",
            "role",
            "tag",
        ):
            value = " ".join(str(snapshot.get(key, "")).split())
            if value:
                return value[:256]
        raise ValueError("manual_input.target_name_unavailable")

    @staticmethod
    def _accessible_name(snapshot: Mapping[str, object]) -> str:
        for key in (
            "aria_label",
            "label",
            "text",
            "placeholder",
            "title",
            "alt",
        ):
            value = " ".join(str(snapshot.get(key, "")).split())
            if value:
                return value[:256]
        return ""

    @staticmethod
    def _as_element(handle: object) -> object | None:
        method = getattr(handle, "as_element", None)
        return method() if callable(method) else handle

    @staticmethod
    def _frame_depth(frame: object) -> int:
        depth = 0
        current = getattr(frame, "parent_frame", None)
        while current is not None:
            depth += 1
            current = getattr(current, "parent_frame", None)
        return depth

    @staticmethod
    async def _await_call(method: Callable[..., object], *args: object) -> object:
        result = method(*args)
        return await result if inspect.isawaitable(result) else result

    def _bind_page_to_dispatch_scope(
        self, page: object, scope: _ActionDispatchCausalScope
    ) -> None:
        page_id = id(page)
        current = self._dispatch_scopes.get(page_id)
        if current is not None and current is not scope:
            raise ValueError("manual_input.action_scope_occupied")
        self._dispatch_scopes[page_id] = scope
        scope.page_ids.add(page_id)

    def subscribe(
        self,
        kind: str,
        callback: Callable[[HostBrowserEvent | HostDownloadEvent], None],
    ) -> Callable[[], None]:
        if kind not in {"navigation", "new_page", "download"}:
            raise ValueError("browser_session.listener_kind_unsupported")
        registration: dict[str, Any] = {
            "kind": kind,
            "callback": callback,
            "bindings": [],
            "page_ids": set(),
            "active": True,
        }
        self._page_subscriptions.append(registration)
        pages = tuple(getattr(self.context, "pages", ()) or (self.main_page,))
        for page in pages:
            self._attach_page_subscription(registration, page)

        def release() -> None:
            registration["active"] = False
            if registration in self._page_subscriptions:
                self._page_subscriptions.remove(registration)
            first: BaseException | None = None
            for page, event_name, handler in reversed(registration["bindings"]):
                try:
                    self._remove_listener(page, event_name, handler)
                except BaseException as exc:
                    if first is None:
                        first = exc
            registration["bindings"].clear()
            registration["page_ids"].clear()
            if first is not None:
                raise first

        return release

    def _attach_page_subscription(
        self, registration: dict[str, Any], page: object
    ) -> None:
        if id(page) in registration["page_ids"]:
            return
        callback = registration["callback"]
        runtime_page_ref = self._page_runtime_ref(page)
        if registration["kind"] == "new_page":
            event_name = "popup"

            def handler(new_page: object) -> None:
                dispatch_scope = self._dispatch_scopes.get(id(page))
                if dispatch_scope is not None:
                    self._bind_page_to_dispatch_scope(new_page, dispatch_scope)
                for active in tuple(self._page_subscriptions):
                    if active["active"]:
                        self._attach_page_subscription(active, new_page)
                callback(
                    HostBrowserEvent(
                        kind="new_page",
                        observed_at=datetime.now(timezone.utc),
                        source_page_runtime_ref=(
                            dispatch_scope.source_page_runtime_ref
                            if dispatch_scope is not None
                            else runtime_page_ref
                        ),
                        source_frame_runtime_ref=(
                            dispatch_scope.source_frame_runtime_ref
                            if dispatch_scope is not None
                            else self._page_main_frame_runtime_ref(page)
                        ),
                        runtime_page_ref=self._page_runtime_ref(new_page),
                        detail={"initial_url": str(getattr(new_page, "url", ""))},
                    )
                )
        elif registration["kind"] == "navigation":
            event_name = "framenavigated"

            def handler(frame: object) -> None:
                runtime_frame_ref = self._frame_runtime_ref(frame)
                dispatch_scope = self._dispatch_scopes.get(id(page))
                callback(
                    HostBrowserEvent(
                        kind="navigation",
                        observed_at=datetime.now(timezone.utc),
                        source_page_runtime_ref=(
                            dispatch_scope.source_page_runtime_ref
                            if dispatch_scope is not None
                            else runtime_page_ref
                        ),
                        source_frame_runtime_ref=(
                            dispatch_scope.source_frame_runtime_ref
                            if dispatch_scope is not None
                            else runtime_frame_ref
                        ),
                        runtime_page_ref=runtime_page_ref,
                        detail={
                            "frame_runtime_ref": runtime_frame_ref,
                            "is_main_frame": getattr(frame, "parent_frame", None) is None,
                            "url": str(getattr(frame, "url", "")),
                        },
                    )
                )

        else:
            event_name = "download"

            def handler(download: object) -> None:
                dispatch_scope = self._dispatch_scopes.get(id(page))
                async def failure() -> str | None:
                    failure_method = getattr(download, "failure", None)
                    result = await failure_method() if callable(failure_method) else None
                    return str(result) if result else None

                callback(
                    HostDownloadEvent(
                        observed_at=datetime.now(timezone.utc),
                        source_page_runtime_ref=(
                            dispatch_scope.source_page_runtime_ref
                            if dispatch_scope is not None
                            else runtime_page_ref
                        ),
                        source_frame_runtime_ref=(
                            dispatch_scope.source_frame_runtime_ref
                            if dispatch_scope is not None
                            else self._page_main_frame_runtime_ref(page)
                        ),
                        runtime_page_ref=runtime_page_ref,
                        download_ref="download_" + secrets.token_hex(12),
                        suggested_filename=getattr(download, "suggested_filename", None),
                        failure=failure(),
                    )
                )

        getattr(page, "on")(event_name, handler)
        registration["page_ids"].add(id(page))
        registration["bindings"].append((page, event_name, handler))

    @staticmethod
    def _remove_listener(source: object, event_name: str, handler: object) -> None:
        remove = getattr(source, "remove_listener", None) or getattr(source, "off")
        result = remove(event_name, handler)
        if inspect.isawaitable(result):
            raise RuntimeError("browser_session.async_listener_release_unsupported")


__all__ = [
    "BrowserSession",
    "BrowserSessionPort",
    "HostBrowserEvent",
    "HostDownloadEvent",
    "PlaywrightBrowserSessionPort",
]
