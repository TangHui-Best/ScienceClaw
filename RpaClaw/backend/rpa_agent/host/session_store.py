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
from .browser_session import BrowserSession


class SessionState(str, Enum):
    RECORDING = "recording"
    STOPPED = "stopped"
    CONFIGURED = "configured"
    COMPILED = "compiled"
    TESTED = "tested"
    SAVED = "saved"


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
    cleanup_errors: list[str] = field(default_factory=list)
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
                await item.browser.aclose(at=current)
            except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
                raise
            except BaseException as exc:
                item.cleanup_errors.append(type(exc).__name__)
            finally:
                item.lock.release()
        return len(expired)

    async def discard(self, session_id: str, *, owner_id: str) -> bool:
        """Remove one owned session and release all of its short-lived resources."""

        async with self._lock:
            hosted = self._sessions.get(session_id)
            if hosted is None or hosted.owner_id != owner_id:
                return False
            await hosted.lock.acquire()
            if self._sessions.get(session_id) is not hosted:
                hosted.lock.release()
                return False
            self._sessions.pop(session_id, None)
        try:
            try:
                await hosted.browser.aclose(at=datetime.now(timezone.utc))
            except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
                raise
            except BaseException as exc:
                hosted.cleanup_errors.append(type(exc).__name__)
        finally:
            hosted.lock.release()
        return True

    async def close_all(self) -> None:
        async with self._lock:
            sessions = tuple(self._sessions.values())
            self._sessions.clear()
        primary: BaseException | None = None
        for item in sessions:
            async with item.lock:
                try:
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


__all__ = ["HostedSession", "SessionState", "SessionStore"]
