from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from backend.runtime.aio_native_lifecycle import (
    AioNativeLifecycleClient,
    AioNativeLifecycleConfig,
    AioNativeLifecycleError,
)
from backend.runtime.rpa_agent_next_aio_provider import AioNativeRuntimeProvider
from rpa_agent.platform import RuntimeLeaseError


def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
) -> AioNativeRuntimeProvider:
    client = AioNativeLifecycleClient(
        AioNativeLifecycleConfig(
            api_base_url="https://aio.example.test",
            template_id="browser-template",
            create_timeout_seconds=120,
            api_token="never-leak-this-token",
            hw_id="hw-test",
            app_key="app-test",
        ),
        transport=httpx.MockTransport(handler),
    )
    return AioNativeRuntimeProvider(client)


def test_acquire_creates_a_ready_sandbox_with_minimal_platform_payload() -> None:
    async def scenario() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            assert request.method == "POST"
            assert request.url.path == "/api/livefunction/sandboxes"
            assert request.headers["authorization"] == "Bearer never-leak-this-token"
            assert request.headers["x-hw-id"] == "hw-test"
            assert request.headers["x-hw-appkey"] == "app-test"
            assert json.loads(request.content) == {
                "templateId": "browser-template",
                "timeout": 120,
            }
            return httpx.Response(
                200,
                json={
                    "data": {
                        "sandboxId": "sandbox-1",
                        "status": "running",
                        "workspaceId": "workspace-1",
                    }
                },
            )

        provider = _provider(handler)
        lease = await provider.acquire("session-1", "user-1", "recording")

        assert len(requests) == 1
        assert lease.lease_id == "aio-native:sandbox-1"
        assert lease.workspace_id == "workspace-1"
        assert "token" not in repr(lease).lower()

    asyncio.run(scenario())


def test_acquire_reuses_only_a_ready_sandbox_and_fails_closed_for_owner_conflict() -> None:
    async def scenario() -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(f"{request.method} {request.url.path}")
            if request.method == "POST":
                return httpx.Response(
                    200,
                    json={"data": {"sandboxId": "sandbox-1", "status": "ready"}},
                )
            return httpx.Response(
                200,
                json={"data": {"sandboxId": "sandbox-1", "status": "ready"}},
            )

        provider = _provider(handler)
        first = await provider.acquire("session-1", "user-1", "recording")
        resumed = await provider.acquire("session-1", "user-1", "evaluation")

        assert resumed.lease_id == first.lease_id
        assert calls == [
            "POST /api/livefunction/sandboxes",
            "GET /api/livefunction/sandboxes/sandbox-1",
        ]
        with pytest.raises(RuntimeLeaseError, match="owner_conflict"):
            await provider.acquire("session-1", "other-user", "recording")
        assert len(calls) == 2

    asyncio.run(scenario())


def test_provisioning_sandbox_never_becomes_a_lease_until_it_is_ready() -> None:
    async def scenario() -> None:
        status = "creating"

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal status
            if request.method == "POST":
                return httpx.Response(
                    200,
                    json={"data": {"sandboxId": "sandbox-1", "status": status}},
                )
            assert request.method == "GET"
            status = "ready"
            return httpx.Response(
                200,
                json={"data": {"sandboxId": "sandbox-1", "status": status}},
            )

        provider = _provider(handler)
        with pytest.raises(RuntimeLeaseError, match="not_ready"):
            await provider.acquire("session-1", "user-1", "recording")

        lease = await provider.acquire("session-1", "user-1", "recording")
        assert lease.lease_id == "aio-native:sandbox-1"

    asyncio.run(scenario())


def test_release_deletes_once_and_makes_the_lease_unusable() -> None:
    async def scenario() -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(f"{request.method} {request.url.path}")
            if request.method == "POST":
                return httpx.Response(
                    200,
                    json={"data": {"sandboxId": "sandbox-1", "status": "ready"}},
                )
            return httpx.Response(204, content=b"")

        provider = _provider(handler)
        lease = await provider.acquire("session-1", "user-1", "replay")
        await provider.release(lease, "run_finished")

        assert calls == [
            "POST /api/livefunction/sandboxes",
            "DELETE /api/livefunction/sandboxes/sandbox-1",
        ]
        assert (await provider.health(lease)).state == "released"
        with pytest.raises(RuntimeLeaseError, match="invalid_release"):
            await provider.release(lease, "duplicate")

    asyncio.run(scenario())


def test_native_errors_are_stable_and_do_not_include_response_body_or_token() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="secret response body")

        client = AioNativeLifecycleClient(
            AioNativeLifecycleConfig(
                api_base_url="https://aio.example.test",
                template_id="browser-template",
                api_token="never-leak-this-token",
            ),
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(AioNativeLifecycleError) as error:
            await client.create()
        assert str(error.value) == "aio_native_create_http_failed"
        assert "secret" not in str(error.value)
        assert "token" not in str(error.value)

    asyncio.run(scenario())
