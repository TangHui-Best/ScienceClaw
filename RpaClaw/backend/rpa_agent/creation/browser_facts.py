"""浏览器客观事实的因果锁定、顺序分配与有界缓冲。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import RLock
from collections.abc import Callable
from typing import Literal, Mapping

from pydantic import TypeAdapter

from ..contracts.models import BrowserFact
from .candidate_registry import ActiveCandidateRegistry, LockedCandidate


_FACT_ADAPTER = TypeAdapter(BrowserFact)


class FactBuffer:
    """创建会话内的有界事实缓冲。

    ``observed_order`` 只在事实真正进入缓冲时分配。TTL 只释放事实，既不
    参与 Candidate 关联，也不会把事实重挂到其他动作。
    """

    def __init__(self, *, capacity: int, ttl: timedelta) -> None:
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
            raise ValueError("browser_fact_buffer.capacity_invalid")
        if not isinstance(ttl, timedelta) or ttl <= timedelta(0):
            raise ValueError("browser_fact_buffer.ttl_invalid")
        self._capacity = capacity
        self._ttl = ttl
        self._next_order = 1
        self._facts: list[BrowserFact] = []
        self._mutex = RLock()

    @property
    def capacity(self) -> int:
        return self._capacity

    def _publish_resolved(
        self,
        payload: Mapping[str, object],
        resolve_candidate: Callable[[], str | None],
    ) -> BrowserFact:
        """先验证容量与事实形状，再且仅再解析一次 Candidate 锁。"""

        with self._mutex:
            if len(self._facts) >= self._capacity:
                raise ValueError("browser_fact_buffer.capacity_exceeded")
            order = self._next_order
            document = dict(payload)
            document["fact_id"] = f"fact_{order:06d}"
            document["observed_order"] = order
            document["candidate_id"] = None
            provisional = _FACT_ADAPTER.validate_python(document)
            candidate_id = resolve_candidate()
            fact = provisional.model_copy(update={"candidate_id": candidate_id})
            self._facts.append(fact)
            self._next_order += 1
            return fact

    def facts(self) -> tuple[BrowserFact, ...]:
        with self._mutex:
            return tuple(self._facts)

    def release_candidate(self, candidate_id: str) -> int:
        with self._mutex:
            retained = [fact for fact in self._facts if fact.candidate_id != candidate_id]
            released = len(self._facts) - len(retained)
            self._facts = retained
            return released

    def clear(self) -> int:
        """会话结束时释放全部短生命周期事实，不重置全局观察顺序。"""

        with self._mutex:
            released = len(self._facts)
            self._facts.clear()
            return released

    def expire(self, now: datetime) -> int:
        with self._mutex:
            try:
                retained = [
                    fact for fact in self._facts
                    if fact.observed_at + self._ttl > now
                ]
            except TypeError as exc:
                raise ValueError("browser_fact_buffer.timezone_mismatch") from exc
            released = len(self._facts) - len(retained)
            self._facts = retained
            return released


@dataclass(frozen=True, slots=True, eq=False)
class FactTrigger:
    """事件第一次触发时冻结的短生命周期凭据。"""

    trigger_id: int
    kind: Literal[
        "navigation", "new_page", "download", "dialog",
        "page_activated", "page_closed",
    ]
    source_page_runtime_ref: str
    source_frame_runtime_ref: str
    locked_candidate: LockedCandidate | None


class BrowserFactObserver:
    """将 Playwright/CDP 回调归一为六种正式 BrowserFact。"""

    def __init__(
        self,
        registry: ActiveCandidateRegistry,
        buffer: FactBuffer,
        *,
        max_pending: int | None = None,
    ) -> None:
        pending_limit = buffer.capacity if max_pending is None else max_pending
        if (
            not isinstance(pending_limit, int)
            or isinstance(pending_limit, bool)
            or pending_limit < 1
        ):
            raise ValueError("browser_fact.max_pending_invalid")
        self._registry = registry
        self._buffer = buffer
        self._max_pending = pending_limit
        self._next_trigger_id = 1
        self._pending: dict[int, FactTrigger] = {}
        self._mutex = RLock()

    @property
    def pending_count(self) -> int:
        with self._mutex:
            return len(self._pending)

    def cancel_trigger(self, trigger: FactTrigger) -> bool:
        return self._discard_trigger(trigger)

    def expire_trigger(self, trigger: FactTrigger) -> bool:
        return self._discard_trigger(trigger)

    def clear_pending(self) -> int:
        with self._mutex:
            pending = tuple(self._pending.values())
            self._pending.clear()
            for trigger in pending:
                self._registry.discard_fact_lock(trigger.locked_candidate)
            return len(pending)

    def expire_windows(self, window_ids: set[int]) -> int:
        """同步移除已经由 Registry 到期释放的窗口触发器。"""

        with self._mutex:
            expired = [
                trigger
                for trigger in self._pending.values()
                if trigger.locked_candidate is not None
                and trigger.locked_candidate.window_id in window_ids
            ]
            for trigger in expired:
                self._pending.pop(trigger.trigger_id, None)
                self._registry.discard_fact_lock(trigger.locked_candidate)
            return len(expired)

    def start_navigation(self, page_runtime_ref: str, frame_runtime_ref: str) -> FactTrigger:
        return self._start("navigation", page_runtime_ref, frame_runtime_ref)

    def start_new_page(self, opener_page_runtime_ref: str, opener_frame_runtime_ref: str) -> FactTrigger:
        return self._start("new_page", opener_page_runtime_ref, opener_frame_runtime_ref)

    def start_download(self, page_runtime_ref: str, frame_runtime_ref: str) -> FactTrigger:
        return self._start("download", page_runtime_ref, frame_runtime_ref)

    def start_dialog(self, page_runtime_ref: str, frame_runtime_ref: str) -> FactTrigger:
        return self._start("dialog", page_runtime_ref, frame_runtime_ref)

    def start_page_activated(
        self, source_page_runtime_ref: str, source_frame_runtime_ref: str
    ) -> FactTrigger:
        return self._start(
            "page_activated", source_page_runtime_ref, source_frame_runtime_ref
        )

    def start_page_closed(
        self, source_page_runtime_ref: str, source_frame_runtime_ref: str
    ) -> FactTrigger:
        return self._start(
            "page_closed", source_page_runtime_ref, source_frame_runtime_ref
        )

    def complete_navigation(
        self,
        trigger: FactTrigger,
        *,
        observed_at: datetime,
        page_runtime_ref: str,
        frame_runtime_ref: str,
        is_main_frame: bool,
        url: str,
    ) -> BrowserFact:
        return self._publish_trigger(trigger, "navigation", {
            "kind": "navigation",
            "observed_at": observed_at,
            "runtime_scope": {"page_runtime_ref": page_runtime_ref},
            "detail": {
                "frame_runtime_ref": frame_runtime_ref,
                "is_main_frame": is_main_frame,
                "url": url,
            },
        })

    def complete_new_page(
        self,
        trigger: FactTrigger,
        *,
        observed_at: datetime,
        new_page_runtime_ref: str,
        initial_url: str,
    ) -> BrowserFact:
        return self._publish_trigger(trigger, "new_page", {
            "kind": "new_page",
            "observed_at": observed_at,
            "runtime_scope": {"page_runtime_ref": new_page_runtime_ref},
            "detail": {"initial_url": initial_url},
        })

    def complete_download(
        self,
        trigger: FactTrigger,
        *,
        observed_at: datetime,
        page_runtime_ref: str,
        download_ref: str,
        status: Literal["completed", "failed"],
        suggested_filename: str | None,
        failure_reason: str | None = None,
    ) -> BrowserFact:
        return self._publish_trigger(trigger, "download", {
            "kind": "download",
            "observed_at": observed_at,
            "runtime_scope": {"page_runtime_ref": page_runtime_ref},
            "detail": {
                "download_ref": download_ref,
                "suggested_filename": suggested_filename,
                "status": status,
                "failure_reason": failure_reason,
            },
        })

    def complete_dialog(
        self,
        trigger: FactTrigger,
        *,
        observed_at: datetime,
        page_runtime_ref: str,
        dialog_type: Literal["alert", "confirm", "prompt", "beforeunload"],
        response: Literal["accept", "dismiss"],
        prompt_value: str | None = None,
    ) -> BrowserFact:
        return self._publish_trigger(trigger, "dialog", {
            "kind": "dialog",
            "observed_at": observed_at,
            "runtime_scope": {"page_runtime_ref": page_runtime_ref},
            "detail": {
                "dialog_type": dialog_type,
                "response": response,
                "prompt_value": prompt_value,
            },
        })

    def complete_page_activated(
        self,
        trigger: FactTrigger,
        *,
        observed_at: datetime,
        page_runtime_ref: str,
    ) -> BrowserFact:
        return self._publish_trigger(trigger, "page_activated", {
            "kind": "page_activated",
            "observed_at": observed_at,
            "runtime_scope": {"page_runtime_ref": page_runtime_ref},
        })

    def complete_page_closed(
        self,
        trigger: FactTrigger,
        *,
        observed_at: datetime,
        page_runtime_ref: str,
    ) -> BrowserFact:
        return self._publish_trigger(trigger, "page_closed", {
            "kind": "page_closed",
            "observed_at": observed_at,
            "runtime_scope": {"page_runtime_ref": page_runtime_ref},
        })

    def _start(
        self,
        kind: Literal[
            "navigation", "new_page", "download", "dialog",
            "page_activated", "page_closed",
        ],
        page_runtime_ref: str,
        frame_runtime_ref: str,
    ) -> FactTrigger:
        with self._mutex:
            if len(self._pending) >= self._max_pending:
                raise ValueError("browser_fact.pending_limit_exceeded")
            locked = self._registry.lock_fact(
                page_runtime_ref=page_runtime_ref,
                frame_runtime_ref=frame_runtime_ref,
            )
            trigger = FactTrigger(
                trigger_id=self._next_trigger_id,
                kind=kind,
                source_page_runtime_ref=page_runtime_ref,
                source_frame_runtime_ref=frame_runtime_ref,
                locked_candidate=locked,
            )
            self._next_trigger_id += 1
            self._pending[trigger.trigger_id] = trigger
            return trigger

    def _publish_trigger(
        self,
        trigger: FactTrigger,
        expected_kind: str,
        payload: Mapping[str, object],
    ) -> BrowserFact:
        with self._mutex:
            stored = self._pending.get(trigger.trigger_id)
            if stored is not trigger:
                raise ValueError("browser_fact.trigger_invalid_or_completed")
            if trigger.kind != expected_kind:
                raise ValueError("browser_fact.trigger_kind_mismatch")
            fact = self._buffer._publish_resolved(
                payload,
                lambda: self._registry.complete_fact(
                    trigger.locked_candidate,
                    observed_at=payload.get("observed_at"),
                ),
            )
            del self._pending[trigger.trigger_id]
            return fact

    def _discard_trigger(self, trigger: FactTrigger) -> bool:
        with self._mutex:
            stored = self._pending.get(trigger.trigger_id)
            if stored is not trigger:
                return False
            del self._pending[trigger.trigger_id]
            self._registry.discard_fact_lock(trigger.locked_candidate)
            return True
