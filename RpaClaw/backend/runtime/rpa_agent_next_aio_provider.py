"""AIO-native implementation of the RPA Agent Next runtime provider port."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from rpa_agent.platform import (
    FilePolicy,
    RuntimeHealth,
    RuntimeLease,
    RuntimeLeaseError,
    RuntimePurpose,
)

from backend.runtime.aio_native_lifecycle import (
    AioNativeLifecycleClient,
    AioNativeLifecycleError,
    AioNativeSandbox,
)


@dataclass(frozen=True)
class RuntimeLeaseRecord:
    session_id: str
    user_id: str
    sandbox_id: str
    workspace_id: str


class RuntimeLeaseRegistryPort(Protocol):
    async def get(self, session_id: str) -> RuntimeLeaseRecord | None: ...

    async def put(self, record: RuntimeLeaseRecord) -> None: ...

    async def remove(self, session_id: str) -> None: ...


class InMemoryRuntimeLeaseRegistry:
    """A deterministic test implementation; it is not a multi-instance store."""

    def __init__(self) -> None:
        self._records: dict[str, RuntimeLeaseRecord] = {}

    async def get(self, session_id: str) -> RuntimeLeaseRecord | None:
        return self._records.get(session_id)

    async def put(self, record: RuntimeLeaseRecord) -> None:
        self._records[record.session_id] = record

    async def remove(self, session_id: str) -> None:
        self._records.pop(session_id, None)


class AioNativeRuntimeProvider:
    """Session-isolated provider; it only issues a lease for a ready sandbox."""

    def __init__(
        self,
        client: AioNativeLifecycleClient,
        registry: RuntimeLeaseRegistryPort | None = None,
    ) -> None:
        self._client = client
        self._registry = registry or InMemoryRuntimeLeaseRegistry()
        self._session_locks: dict[str, asyncio.Lock] = {}

    async def acquire(
        self, session_id: str, user_id: str, purpose: RuntimePurpose
    ) -> RuntimeLease:
        async with self._lock_for(session_id):
            record = await self._registry.get(session_id)
            if record is not None:
                if record.user_id != user_id:
                    raise RuntimeLeaseError("runtime_lease_owner_conflict")
                sandbox = await self._client.status(record.sandbox_id)
                if sandbox.state == "ready":
                    return self._lease(record, purpose)
                if sandbox.state == "released":
                    await self._registry.remove(session_id)
                else:
                    raise RuntimeLeaseError("runtime_lease_not_ready")

            sandbox = await self._client.create()
            record = self._record_from_sandbox(session_id, user_id, sandbox)
            await self._registry.put(record)
            if sandbox.state != "ready":
                raise RuntimeLeaseError("runtime_lease_not_ready")
            return self._lease(record, purpose)

    async def release(self, lease: RuntimeLease, reason: str) -> None:
        del reason  # The platform records only lifecycle authority, never RPA payload.
        async with self._lock_for(lease.session_id):
            record = await self._registry.get(lease.session_id)
            if record is None or not self._matches(record, lease):
                raise RuntimeLeaseError("runtime_lease_invalid_release")
            try:
                await self._client.delete(record.sandbox_id)
            except AioNativeLifecycleError as exc:
                raise RuntimeLeaseError(str(exc)) from exc
            await self._registry.remove(lease.session_id)

    async def health(self, lease: RuntimeLease) -> RuntimeHealth:
        record = await self._registry.get(lease.session_id)
        if record is None or not self._matches(record, lease):
            return RuntimeHealth(state="released")
        try:
            sandbox = await self._client.status(record.sandbox_id)
        except AioNativeLifecycleError as exc:
            raise RuntimeLeaseError(str(exc)) from exc
        return RuntimeHealth(state="ready" if sandbox.state == "ready" else "released")

    async def resolve_file_policy(self, lease: RuntimeLease) -> FilePolicy:
        health = await self.health(lease)
        if health.state != "ready":
            raise RuntimeLeaseError("runtime_lease_released")
        return FilePolicy(workspace_id=lease.workspace_id)

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        return self._session_locks.setdefault(session_id, asyncio.Lock())

    @staticmethod
    def _record_from_sandbox(
        session_id: str, user_id: str, sandbox: AioNativeSandbox
    ) -> RuntimeLeaseRecord:
        return RuntimeLeaseRecord(
            session_id=session_id,
            user_id=user_id,
            sandbox_id=sandbox.sandbox_id,
            workspace_id=sandbox.workspace_id or f"workspace:{sandbox.sandbox_id}",
        )

    @staticmethod
    def _lease(record: RuntimeLeaseRecord, purpose: RuntimePurpose) -> RuntimeLease:
        return RuntimeLease(
            lease_id=f"aio-native:{record.sandbox_id}",
            session_id=record.session_id,
            user_id=record.user_id,
            workspace_id=record.workspace_id,
            purpose=purpose,
        )

    @staticmethod
    def _matches(record: RuntimeLeaseRecord, lease: RuntimeLease) -> bool:
        return (
            record.session_id == lease.session_id
            and record.user_id == lease.user_id
            and record.workspace_id == lease.workspace_id
            and lease.lease_id == f"aio-native:{record.sandbox_id}"
        )
