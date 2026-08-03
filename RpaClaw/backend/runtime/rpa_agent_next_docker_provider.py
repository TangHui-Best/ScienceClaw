"""Adapt the generic per-session Docker runtime to the vNext RPA port."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from backend.rpa_agent.platform import (
    FilePolicy,
    RuntimeHealth,
    RuntimeLease,
    RuntimeLeaseError,
    RuntimePurpose,
)

from backend.rpa_agent.host.scienceclaw_browser import fetch_runtime_cdp_url
from backend.runtime.models import SessionRuntimeRecord


class DockerRuntimeProvider:
    """One vNext lease owns exactly one generic Docker session runtime.

    This adapter deliberately retains no RPA payload.  It only remembers the
    runtime record needed to validate ownership and resolve the CDP endpoint.
    """

    def __init__(
        self,
        runtime_manager: object,
        *,
        cdp_fetcher: Callable[[str], Awaitable[str]] = fetch_runtime_cdp_url,
    ) -> None:
        self._runtime_manager = runtime_manager
        self._cdp_fetcher = cdp_fetcher
        self._records: dict[str, SessionRuntimeRecord] = {}

    async def acquire(
        self, session_id: str, user_id: str, purpose: RuntimePurpose
    ) -> RuntimeLease:
        record = await self._runtime_manager.ensure_runtime(session_id, user_id)
        if not isinstance(record, SessionRuntimeRecord):
            raise RuntimeLeaseError("rpa_agent_next.runtime_record_invalid")
        if record.user_id != user_id:
            raise RuntimeLeaseError("runtime_lease_owner_conflict")
        if record.status != "ready":
            raise RuntimeLeaseError("runtime_lease_not_ready")
        lease = RuntimeLease(
            lease_id="docker-runtime:" + record.session_id,
            session_id=record.session_id,
            user_id=record.user_id,
            workspace_id="runtime-workspace:" + record.session_id,
            purpose=purpose,
            expires_at=record.expires_at,
        )
        self._records[lease.lease_id] = record
        return lease

    async def release(self, lease: RuntimeLease, reason: str) -> None:
        del reason
        record = self._require(lease)
        current = await self._runtime_manager.get_runtime(record.session_id)
        if not isinstance(current, SessionRuntimeRecord) or not self._same_record(
            current, record
        ):
            raise RuntimeLeaseError("runtime_lease_invalid_release")
        await self._runtime_manager.destroy_runtime(record.session_id)
        self._records.pop(lease.lease_id, None)

    async def health(self, lease: RuntimeLease) -> RuntimeHealth:
        record = self._records.get(lease.lease_id)
        if record is None or not self._same_record(record, lease):
            return RuntimeHealth(state="released")
        current = await self._runtime_manager.get_runtime(record.session_id, refresh=True)
        if not isinstance(current, SessionRuntimeRecord) or not self._same_record(
            current, record
        ):
            return RuntimeHealth(state="released")
        return RuntimeHealth(state="ready" if current.status == "ready" else "released")

    async def resolve_file_policy(self, lease: RuntimeLease) -> FilePolicy:
        if (await self.health(lease)).state != "ready":
            raise RuntimeLeaseError("runtime_lease_released")
        return FilePolicy(workspace_id=lease.workspace_id, allow_network=False)

    async def resolve_cdp_url(self, lease: RuntimeLease) -> str:
        record = self._require(lease)
        if (await self.health(lease)).state != "ready":
            raise RuntimeLeaseError("runtime_lease_released")
        return await self._cdp_fetcher(record.rest_base_url)

    def _require(self, lease: RuntimeLease) -> SessionRuntimeRecord:
        record = self._records.get(lease.lease_id)
        if record is None or not self._same_record(record, lease):
            raise RuntimeLeaseError("runtime_lease_invalid")
        return record

    @staticmethod
    def _same_record(record: SessionRuntimeRecord, other: object) -> bool:
        return (
            getattr(other, "session_id", None) == record.session_id
            and getattr(other, "user_id", None) == record.user_id
            and getattr(other, "workspace_id", "runtime-workspace:" + record.session_id)
            == "runtime-workspace:" + record.session_id
        )


__all__ = ["DockerRuntimeProvider"]
