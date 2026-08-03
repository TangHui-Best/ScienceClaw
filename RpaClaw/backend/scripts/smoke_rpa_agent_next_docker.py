"""Run the opt-in RPA Agent Next Docker edge-runtime smoke test.

Run this inside the Compose backend container started with
``docker-compose-edge-runtime.yml``.  The script creates one transient session
container, resolves its CDP endpoint, opens a fresh Playwright context, then
closes both the browser context and the session container.
"""

from __future__ import annotations

import asyncio
import time

from backend.browser_preview import BrowserPreviewRegistry
from backend.config import settings
from backend.rpa_agent.host.scienceclaw_browser import acquire_browser_runtime_lease
from backend.rpa_agent.platform import DockerBrowserHostFactory
from backend.runtime.docker_runtime_provider import DockerRuntimeProvider as GenericDockerProvider
from backend.runtime.rpa_agent_next_docker_provider import DockerRuntimeProvider


class _SmokeRuntimeManager:
    """Minimal ephemeral record store so the smoke never requires MongoDB state."""

    def __init__(self, provider: GenericDockerProvider) -> None:
        self._provider = provider
        self._records: dict[str, object] = {}

    async def ensure_runtime(self, session_id: str, user_id: str):
        record = self._records.get(session_id)
        if record is None:
            record = await self._provider.create_runtime(session_id, user_id)
            self._records[session_id] = record
        return record

    async def get_runtime(self, session_id: str, refresh: bool = False):
        record = self._records.get(session_id)
        if record is None or not refresh:
            return record
        return await self._provider.refresh_runtime(record)

    async def destroy_runtime(self, session_id: str) -> bool:
        record = self._records.pop(session_id, None)
        if record is None:
            return False
        await self._provider.delete_runtime(record)
        return True


async def _run() -> None:
    session_id = f"rpa-agent-next-smoke-{int(time.time())}"
    user_id = "rpa-agent-next-smoke"
    manager = _SmokeRuntimeManager(GenericDockerProvider(settings))
    runtime_provider = DockerRuntimeProvider(manager)
    lease = None
    host = None

    try:
        lease = await runtime_provider.acquire(session_id, user_id, "recording")
        assert (await runtime_provider.health(lease)).state == "ready"
        cdp_url = await runtime_provider.resolve_cdp_url(lease)
        assert cdp_url.startswith(("ws://", "wss://"))

        host_factory = DockerBrowserHostFactory(
            resolve_cdp_url=runtime_provider.resolve_cdp_url,
            preview_registry=BrowserPreviewRegistry(),
            acquire_runtime_lease=acquire_browser_runtime_lease,
        )
        host = await host_factory.create_recording(owner_id=user_id, lease=lease)
        assert host.port.browser_use_cdp_url == cdp_url
        print("RPA_AGENT_NEXT_DOCKER_SMOKE=passed")
    finally:
        if host is not None:
            await host.aclose()
        if lease is not None:
            await runtime_provider.release(lease, "smoke_complete")
            assert (await runtime_provider.health(lease)).state == "released"
            print("RPA_AGENT_NEXT_DOCKER_RELEASE=passed")


if __name__ == "__main__":
    asyncio.run(_run())
