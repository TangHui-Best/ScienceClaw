"""RPA Core's provider-neutral runtime-session contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


RuntimePurpose = Literal["recording", "replay", "evaluation"]
RuntimeState = Literal["ready", "released"]


@dataclass(frozen=True)
class RuntimeLease:
    lease_id: str
    session_id: str
    user_id: str
    workspace_id: str
    purpose: RuntimePurpose
    expires_at: int | None = None


@dataclass(frozen=True)
class RuntimeHealth:
    state: RuntimeState


@dataclass(frozen=True)
class FilePolicy:
    workspace_id: str
    allow_network: bool = False
    allow_secrets: bool = False


class RuntimeLeaseError(ValueError):
    pass


class RuntimeProviderPort(Protocol):
    async def acquire(
        self, session_id: str, user_id: str, purpose: RuntimePurpose
    ) -> RuntimeLease: ...

    async def release(self, lease: RuntimeLease, reason: str) -> None: ...

    async def health(self, lease: RuntimeLease) -> RuntimeHealth: ...

    async def resolve_file_policy(self, lease: RuntimeLease) -> FilePolicy: ...


class FakeRuntimeProvider:
    """Deterministic provider for S0 tests; it never creates a real sandbox."""

    def __init__(self) -> None:
        self._leases_by_session: dict[str, RuntimeLease] = {}
        self._released: set[str] = set()
        self.release_reasons: list[tuple[str, str]] = []

    async def acquire(
        self, session_id: str, user_id: str, purpose: RuntimePurpose
    ) -> RuntimeLease:
        existing = self._leases_by_session.get(session_id)
        if existing is not None:
            if existing.user_id != user_id:
                raise RuntimeLeaseError("runtime_lease_owner_conflict")
            if existing.lease_id in self._released:
                raise RuntimeLeaseError("runtime_lease_released")
            return existing

        lease = RuntimeLease(
            lease_id=f"lease:{session_id}",
            session_id=session_id,
            user_id=user_id,
            workspace_id=f"workspace:{session_id}",
            purpose=purpose,
        )
        self._leases_by_session[session_id] = lease
        return lease

    async def release(self, lease: RuntimeLease, reason: str) -> None:
        current = self._leases_by_session.get(lease.session_id)
        if current != lease or lease.lease_id in self._released:
            raise RuntimeLeaseError("runtime_lease_invalid_release")
        self._released.add(lease.lease_id)
        self.release_reasons.append((lease.lease_id, reason))

    async def health(self, lease: RuntimeLease) -> RuntimeHealth:
        return RuntimeHealth(
            state="released" if lease.lease_id in self._released else "ready"
        )

    async def resolve_file_policy(self, lease: RuntimeLease) -> FilePolicy:
        if lease.lease_id in self._released:
            raise RuntimeLeaseError("runtime_lease_released")
        return FilePolicy(workspace_id=lease.workspace_id)
