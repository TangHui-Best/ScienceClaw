from __future__ import annotations

import asyncio

import pytest

from rpa_agent.platform import FakeRuntimeProvider, RuntimeLeaseError


def test_provider_reuses_a_session_lease_and_isolates_other_sessions() -> None:
    async def scenario() -> None:
        provider = FakeRuntimeProvider()
        first = await provider.acquire("session-a", "user-a", "recording")
        resumed = await provider.acquire("session-a", "user-a", "replay")
        other = await provider.acquire("session-b", "user-a", "recording")

        assert resumed == first
        assert other.lease_id != first.lease_id
        assert other.workspace_id != first.workspace_id

    asyncio.run(scenario())


def test_provider_rejects_owner_conflicts_and_releases_once() -> None:
    async def scenario() -> None:
        provider = FakeRuntimeProvider()
        lease = await provider.acquire("session-a", "user-a", "recording")
        with pytest.raises(RuntimeLeaseError, match="owner_conflict"):
            await provider.acquire("session-a", "user-b", "recording")

        await provider.release(lease, "scenario_failed")
        assert (await provider.health(lease)).state == "released"
        assert provider.release_reasons == [(lease.lease_id, "scenario_failed")]
        with pytest.raises(RuntimeLeaseError, match="invalid_release"):
            await provider.release(lease, "duplicate")

    asyncio.run(scenario())
