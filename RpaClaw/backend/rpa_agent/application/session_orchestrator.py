"""Compose only vNext recording sessions with their isolated runtime resources."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import secrets
from typing import Protocol

from ..host import BrowserHostSession, ManualRecordingListenerGate
from ..platform import RuntimeLease, RuntimeProviderPort
from ..recording import BrowserUseInstructionCoordinator, RecordingSession
from ..recording.ai_execution import BrowserUseExecutionPort
from ..recording.contracts import RecordingTimeline


class NextRecordingHostFactory(Protocol):
    """Create a host bound to the lease already acquired for this Next session."""

    async def create_recording(
        self, *, owner_id: str, lease: RuntimeLease
    ) -> BrowserHostSession: ...


class SessionNotFoundError(ValueError):
    code = "rpa_agent_next.session_not_found"


class SessionOwnerError(ValueError):
    code = "rpa_agent_next.session_not_owned"


@dataclass(slots=True)
class _ActiveSession:
    session_id: str
    owner_id: str
    lease: RuntimeLease
    host: BrowserHostSession
    recording: RecordingSession
    listener_gate: ManualRecordingListenerGate


class RpaAgentNextSessionOrchestrator:
    """Own the composition and reverse-order cleanup of a vNext session.

    The in-memory registry is intentionally process-local.  It makes the API
    and lifecycle contract testable, but is not a production multi-instance
    session store.  It never falls back to the legacy RPA session store.
    """

    def __init__(
        self,
        *,
        runtime_provider: RuntimeProviderPort,
        host_factory: NextRecordingHostFactory,
        runner_factory: Callable[[str], BrowserUseExecutionPort],
    ) -> None:
        self._runtime_provider = runtime_provider
        self._host_factory = host_factory
        self._runner_factory = runner_factory
        self._sessions: dict[str, _ActiveSession] = {}
        self._mutex = asyncio.Lock()

    async def start(self, *, session_id: str, owner_id: str) -> RecordingSession:
        async with self._mutex:
            existing = self._sessions.get(session_id)
            if existing is not None:
                self._require_owner(existing, owner_id)
                return existing.recording

            lease = await self._runtime_provider.acquire(
                session_id, owner_id, "recording"
            )
            host: BrowserHostSession | None = None
            gate: ManualRecordingListenerGate | None = None
            try:
                host = await self._host_factory.create_recording(
                    owner_id=owner_id, lease=lease
                )
                gate = ManualRecordingListenerGate(
                    port=host.port,
                    event_sink=lambda _event: None,
                )
                gate.attach()
                recording = RecordingSession(session_id=session_id)
                self._sessions[session_id] = _ActiveSession(
                    session_id=session_id,
                    owner_id=owner_id,
                    lease=lease,
                    host=host,
                    recording=recording,
                    listener_gate=gate,
                )
                return recording
            except BaseException:
                await self._cleanup_unregistered(lease=lease, host=host, gate=gate)
                raise

    async def projection(self, *, session_id: str, owner_id: str) -> dict[str, object]:
        active = await self._get(session_id=session_id, owner_id=owner_id)
        return {
            "session_id": active.session_id,
            "items": [
                item.model_dump(mode="json", exclude_none=True)
                for item in active.recording.projection_items()
            ],
            "timeline": active.recording.timeline().model_dump(
                mode="json", exclude_none=True
            ),
        }

    async def timeline(
        self, *, session_id: str, owner_id: str
    ) -> RecordingTimeline:
        """Expose only the vNext timeline for downstream build services."""

        active = await self._get(session_id=session_id, owner_id=owner_id)
        return active.recording.timeline()

    async def execute_instruction(
        self,
        *,
        session_id: str,
        owner_id: str,
        instruction: str,
        model_ref: str,
    ) -> dict[str, object]:
        active = await self._get(session_id=session_id, owner_id=owner_id)
        step_id = "ais_" + secrets.token_hex(12)
        now = datetime.now(timezone.utc)
        step, ordinal = active.recording.queue_ai_instruction(
            step_id=step_id,
            instruction=instruction,
            model_ref=model_ref,
            context_snapshot_ref="ctx_" + secrets.token_hex(12),
            created_at=now,
        )
        coordinator = BrowserUseInstructionCoordinator(
            session=active.recording,
            manual_control=active.listener_gate,
            runner=self._runner_factory(owner_id),
        )
        await coordinator.execute(step_id=step.step_id, host=active.host)
        completed = next(
            item
            for item in active.recording.timeline().items
            if getattr(item, "step_id", None) == step.step_id
        )
        return {
            "step_id": step.step_id,
            "ordinal": ordinal,
            "execution": completed.execution.model_dump(
                mode="json", exclude_none=True
            ),
        }

    async def close(self, *, session_id: str, owner_id: str) -> bool:
        async with self._mutex:
            active = self._sessions.get(session_id)
            if active is None:
                return False
            self._require_owner(active, owner_id)
            self._sessions.pop(session_id)
        await self._cleanup_unregistered(
            lease=active.lease,
            host=active.host,
            gate=active.listener_gate,
        )
        return True

    async def _get(self, *, session_id: str, owner_id: str) -> _ActiveSession:
        async with self._mutex:
            active = self._sessions.get(session_id)
            if active is None:
                raise SessionNotFoundError(session_id)
            self._require_owner(active, owner_id)
            return active

    async def _cleanup_unregistered(
        self,
        *,
        lease: RuntimeLease,
        host: BrowserHostSession | None,
        gate: ManualRecordingListenerGate | None,
    ) -> None:
        first_error: BaseException | None = None
        if gate is not None:
            try:
                await gate.aclose()
            except BaseException as error:
                first_error = error
        if host is not None:
            try:
                await host.aclose()
            except BaseException as error:
                if first_error is None:
                    first_error = error
        try:
            await self._runtime_provider.release(lease, "rpa_agent_next.session_closed")
        except BaseException as error:
            if first_error is None:
                first_error = error
        if first_error is not None:
            raise first_error

    @staticmethod
    def _require_owner(active: _ActiveSession, owner_id: str) -> None:
        if active.owner_id != owner_id:
            raise SessionOwnerError(active.session_id)
