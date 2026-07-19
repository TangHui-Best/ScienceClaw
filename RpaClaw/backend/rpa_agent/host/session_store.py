"""Concurrent, identity-scoped lifecycle store for creation API sessions."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
import secrets
from typing import Any, AsyncIterator

from ..compiler import CompileResult
from ..configuration import ConfigurationResult, SkillConfigurationDraft
from ..contracts import (
    AgentStepConfiguration,
    CompiledSkillPlan,
    RecordingTimeline,
    ReplayAssessment,
    ManualFallbackInstruction,
)
from .browser_session import BrowserSession


class SessionState(str, Enum):
    RECORDING = "recording"
    STOPPED = "stopped"
    CONFIGURED = "configured"
    COMPILED = "compiled"
    TESTED = "tested"
    SAVED = "saved"


@dataclass(frozen=True, slots=True)
class AgentIdempotencyRecord:
    request_hash: str
    step_id: str


@dataclass(slots=True)
class ManualIdempotencyRecord:
    request_hash: str
    draft_id: str
    capture_status: str


@dataclass(slots=True)
class HostedSession:
    session_id: str
    owner_id: str
    browser_session_ref: str
    browser: BrowserSession
    artifact_dir: Path
    state: SessionState = SessionState.RECORDING
    configuration_draft: SkillConfigurationDraft | None = None
    configuration: ConfigurationResult | None = None
    compile_result: CompileResult | None = None
    artifact_hash: str | None = None
    run_result: dict[str, Any] | None = None
    test_passed: bool = False
    saved_ref: str | None = None
    test_browser_host: Any | None = field(default=None, repr=False)
    cleanup_errors: list[str] = field(default_factory=list)
    admission_closed: bool = False
    active_operation_id: str | None = None
    active_operation_kind: str | None = None
    agent_idempotency: dict[str, AgentIdempotencyRecord] = field(default_factory=dict)
    manual_idempotency: dict[str, ManualIdempotencyRecord] = field(default_factory=dict)
    agent_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict, repr=False)
    agent_step_configurations: dict[str, AgentStepConfiguration] = field(default_factory=dict)
    manual_fallbacks: dict[str, ManualFallbackInstruction] = field(default_factory=dict)
    recording_timeline: RecordingTimeline | None = None
    replay_assessments: tuple[ReplayAssessment, ...] = ()
    compiled_plan: CompiledSkillPlan | None = None
    last_accessed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def touch(self, now: datetime | None = None) -> None:
        self.last_accessed_at = now or datetime.now(timezone.utc)

    def require_state(self, *allowed: SessionState) -> None:
        if self.state not in allowed:
            expected = ",".join(item.value for item in allowed)
            raise ValueError(
                f"api.state_conflict:{self.state.value}:expected:{expected}"
            )

    def reserve_operation(self, *, operation_id: str, kind: str) -> None:
        if self.admission_closed:
            raise ValueError("session_admission_closed")
        if self.active_operation_id is not None:
            code = (
                "agent_instruction_in_progress"
                if self.active_operation_kind == "agent"
                else "session_operation_in_progress"
            )
            raise ValueError(code)
        self.active_operation_id = operation_id
        self.active_operation_kind = kind

    def release_operation(self, *, operation_id: str) -> None:
        if self.active_operation_id != operation_id:
            raise ValueError("session_operation_lease_mismatch")
        self.active_operation_id = None
        self.active_operation_kind = None


class SessionStore:
    def __init__(self, *, ttl: timedelta = timedelta(hours=2)) -> None:
        if ttl <= timedelta(0):
            raise ValueError("session_store.ttl_invalid")
        self._ttl = ttl
        self._sessions: dict[str, HostedSession] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        owner_id: str,
        browser_session_ref: str,
        browser: BrowserSession,
        artifact_dir: Path,
    ) -> HostedSession:
        async with self._lock:
            while True:
                session_id = "rca_" + secrets.token_hex(12)
                if session_id not in self._sessions:
                    break
            hosted = HostedSession(
                session_id=session_id,
                owner_id=owner_id,
                browser_session_ref=browser_session_ref,
                browser=browser,
                artifact_dir=artifact_dir / session_id,
            )
            self._sessions[session_id] = hosted
            return hosted

    @asynccontextmanager
    async def use(self, session_id: str, *, owner_id: str) -> AsyncIterator[HostedSession]:
        await self._lock.acquire()
        hosted: HostedSession | None = None
        try:
            hosted = self._sessions.get(session_id)
            if hosted is None or hosted.owner_id != owner_id:
                raise KeyError("session_store.not_found")
            await hosted.lock.acquire()
        finally:
            self._lock.release()
        assert hosted is not None
        try:
            hosted.touch()
            yield hosted
        finally:
            hosted.touch()
            hosted.lock.release()

    async def cleanup_expired(self, *, now: datetime | None = None) -> int:
        current = now or datetime.now(timezone.utc)
        expired: list[HostedSession] = []
        async with self._lock:
            for item in tuple(self._sessions.values()):
                if item.last_accessed_at + self._ttl > current:
                    continue
                if item.lock.locked():
                    continue
                if item.active_operation_id is not None:
                    continue
                await item.lock.acquire()
                if (
                    self._sessions.get(item.session_id) is not item
                    or item.last_accessed_at + self._ttl > current
                ):
                    item.lock.release()
                    continue
                self._sessions.pop(item.session_id, None)
                expired.append(item)
        for item in expired:
            try:
                if item.test_browser_host is not None:
                    await item.test_browser_host.aclose()
                    item.test_browser_host = None
                await item.browser.aclose(at=current)
            except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
                raise
            except BaseException as exc:
                item.cleanup_errors.append(type(exc).__name__)
            finally:
                item.lock.release()
        return len(expired)

    async def pop(self, session_id: str, *, owner_id: str) -> HostedSession:
        async with self._lock:
            hosted = self._sessions.get(session_id)
            if hosted is None or hosted.owner_id != owner_id:
                raise KeyError("session_store.not_found")
            await hosted.lock.acquire()
            self._sessions.pop(session_id, None)
        hosted.touch()
        hosted.lock.release()
        return hosted

    async def close_all(self) -> None:
        async with self._lock:
            sessions = tuple(self._sessions.values())
            self._sessions.clear()
        primary: BaseException | None = None
        for item in sessions:
            tasks = tuple(item.agent_tasks.values())
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            async with item.lock:
                try:
                    if item.test_browser_host is not None:
                        await item.test_browser_host.aclose()
                        item.test_browser_host = None
                    await item.browser.aclose(
                        at=datetime.now(timezone.utc), primary=primary
                    )
                except (KeyboardInterrupt, SystemExit, asyncio.CancelledError) as exc:
                    if primary is None:
                        primary = exc
                except BaseException as exc:
                    item.cleanup_errors.append(type(exc).__name__)
        if primary is not None:
            raise primary


__all__ = [
    "AgentIdempotencyRecord",
    "HostedSession",
    "ManualIdempotencyRecord",
    "SessionState",
    "SessionStore",
]
