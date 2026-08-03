from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.runtime.models import SessionRuntimeRecord
from backend.runtime.rpa_agent_next_docker_provider import DockerRuntimeProvider
from route.rpa_agent_next import build_default_services
from backend.rpa_agent.platform.docker_browser_host import DockerBrowserHostFactory
from backend.rpa_agent.platform import RuntimeLease, RuntimeLeaseError


class _RuntimeManager:
    def __init__(self) -> None:
        self.records: dict[str, SessionRuntimeRecord] = {}
        self.destroyed: list[str] = []

    async def ensure_runtime(self, session_id: str, user_id: str) -> SessionRuntimeRecord:
        existing = self.records.get(session_id)
        if existing is not None:
            return existing
        record = SessionRuntimeRecord(
            session_id=session_id,
            user_id=user_id,
            namespace="local",
            pod_name="pod_" + session_id,
            service_name="service_" + session_id,
            rest_base_url="http://" + session_id + ".example.test",
            status="ready",
        )
        self.records[session_id] = record
        return record

    async def get_runtime(self, session_id: str, refresh: bool = False):
        del refresh
        return self.records.get(session_id)

    async def destroy_runtime(self, session_id: str) -> bool:
        self.destroyed.append(session_id)
        return self.records.pop(session_id, None) is not None


def test_docker_runtime_provider_enforces_owner_and_releases_container_runtime() -> None:
    async def scenario() -> None:
        manager = _RuntimeManager()
        cdp_urls: list[str] = []

        async def fetcher(rest_base_url: str) -> str:
            cdp_urls.append(rest_base_url)
            return "ws://runtime.example.test/devtools/browser/next"

        provider = DockerRuntimeProvider(manager, cdp_fetcher=fetcher)
        lease = await provider.acquire("next_session_1", "user_1", "recording")
        assert lease.lease_id == "docker-runtime:next_session_1"
        assert (await provider.health(lease)).state == "ready"
        assert await provider.resolve_cdp_url(lease) == "ws://runtime.example.test/devtools/browser/next"
        assert cdp_urls == ["http://next_session_1.example.test"]
        await provider.release(lease, "test")
        assert manager.destroyed == ["next_session_1"]
        assert (await provider.health(lease)).state == "released"

        await provider.acquire("next_session_2", "user_1", "recording")
        with pytest.raises(RuntimeLeaseError, match="runtime_lease_owner_conflict"):
            await provider.acquire("next_session_2", "user_2", "recording")

    asyncio.run(scenario())


class _Frame:
    def __init__(self, *, name: str = "", parent_frame=None) -> None:
        self.name = name
        self.parent_frame = parent_frame


class _Page:
    def __init__(self) -> None:
        self.context = object()
        self.main_frame = _Frame()


class _BrowserLease:
    def __init__(self) -> None:
        self.page = _Page()
        self.cdp_url = "ws://runtime.example.test/devtools/browser/next"
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


def test_docker_host_factory_uses_only_supplied_lease_and_creates_fresh_host() -> None:
    async def scenario() -> None:
        calls: list[dict[str, object]] = []
        browser_lease = _BrowserLease()

        async def resolve_cdp(lease: RuntimeLease) -> str:
            assert lease.lease_id == "docker-runtime:next_session_3"
            return browser_lease.cdp_url

        async def acquire(**kwargs):
            calls.append(kwargs)
            assert await kwargs["resolve_cdp_url"]("ignored", "ignored") == browser_lease.cdp_url
            return browser_lease

        factory = DockerBrowserHostFactory(
            resolve_cdp_url=resolve_cdp,
            preview_registry=object(),
            acquire_runtime_lease=acquire,
        )
        lease = RuntimeLease(
            lease_id="docker-runtime:next_session_3",
            session_id="next_session_3",
            user_id="user_1",
            workspace_id="runtime-workspace:next_session_3",
            purpose="recording",
        )
        host = await factory.create_recording(owner_id="user_1", lease=lease)
        assert host.browser_session_ref.startswith("rpa_agent_next_recording_")
        assert host.port.browser_use_cdp_url == browser_lease.cdp_url
        assert len(calls) == 1
        await host.aclose()
        assert browser_lease.closed == 1

        with pytest.raises(RuntimeLeaseError, match="runtime_lease_owner_conflict"):
            await factory.create_recording(owner_id="other_user", lease=lease)

    asyncio.run(scenario())


def test_default_services_enable_docker_only_by_explicit_next_mode() -> None:
    manager = _RuntimeManager()
    disabled = build_default_services(
        next_settings=SimpleNamespace(rpa_agent_next_runtime_mode="disabled")
    )
    assert disabled.runtime_provider is None

    docker = build_default_services(
        next_settings=SimpleNamespace(rpa_agent_next_runtime_mode="docker"),
        runtime_manager=manager,
        preview_registry=object(),
    )
    assert isinstance(docker.runtime_provider, DockerRuntimeProvider)
    assert docker.host_factory.__class__.__name__ == "DockerBrowserHostFactory"
    assert docker.runner_factory("user_1").__class__.__name__ == "NativeBrowserUseRunner"
