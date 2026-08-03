"""Narrow AIO native sandbox lifecycle client for RPA Agent Next.

This module is deliberately a platform implementation.  It must not expose
credentials, raw responses, or AIO endpoint details through RPA contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx


SandboxState = Literal["ready", "provisioning", "released"]


class AioNativeLifecycleError(ValueError):
    """A stable, response-body-free error suitable for higher layers."""

    def __init__(self, operation: str, reason: str) -> None:
        self.operation = operation
        self.reason = reason
        super().__init__(f"aio_native_{operation}_{reason}")


@dataclass(frozen=True)
class AioNativeLifecycleConfig:
    api_base_url: str
    template_id: str
    create_timeout_seconds: int = 600
    api_token: str | None = None
    hw_id: str | None = None
    app_key: str | None = None
    sandbox_header_name: str = "x-livefunction-sandbox-id"
    sandbox_base_url: str | None = None

    def __post_init__(self) -> None:
        if not self.api_base_url:
            raise ValueError("aio_native_config_api_base_url_required")
        if not self.template_id:
            raise ValueError("aio_native_config_template_id_required")
        if self.create_timeout_seconds <= 0:
            raise ValueError("aio_native_config_create_timeout_invalid")
        if not self.sandbox_header_name:
            raise ValueError("aio_native_config_sandbox_header_required")


@dataclass(frozen=True)
class AioNativeSandbox:
    sandbox_id: str
    state: SandboxState
    workspace_id: str | None = None


class AioNativeLifecycleClient:
    """Calls only the four documented native sandbox lifecycle endpoints."""

    def __init__(
        self,
        config: AioNativeLifecycleConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport

    async def create(self) -> AioNativeSandbox:
        payload = await self._request(
            "create",
            "POST",
            "/api/livefunction/sandboxes",
            json={
                "templateId": self._config.template_id,
                "timeout": self._config.create_timeout_seconds,
            },
        )
        return self._parse_sandbox("create", payload, require_state=False)

    async def status(self, sandbox_id: str) -> AioNativeSandbox:
        try:
            payload = await self._request(
                "status", "GET", f"/api/livefunction/sandboxes/{sandbox_id}"
            )
        except AioNativeLifecycleError as exc:
            if exc.reason == "not_found":
                return AioNativeSandbox(sandbox_id=sandbox_id, state="released")
            raise
        return self._parse_sandbox("status", payload, fallback_sandbox_id=sandbox_id)

    async def refresh(self, sandbox_id: str) -> AioNativeSandbox:
        try:
            payload = await self._request(
                "refresh",
                "POST",
                f"/api/livefunction/sandboxes/refresh/{sandbox_id}",
            )
        except AioNativeLifecycleError as exc:
            if exc.reason == "not_found":
                return AioNativeSandbox(sandbox_id=sandbox_id, state="released")
            raise
        return self._parse_sandbox("refresh", payload, fallback_sandbox_id=sandbox_id)

    async def delete(self, sandbox_id: str) -> bool:
        try:
            await self._request(
                "delete",
                "DELETE",
                f"/api/livefunction/sandboxes/{sandbox_id}",
                expect_body=False,
            )
        except AioNativeLifecycleError as exc:
            if exc.reason == "not_found":
                return False
            raise
        return True

    async def _request(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        expect_body: bool = True,
    ) -> Any:
        try:
            async with httpx.AsyncClient(
                base_url=self._config.api_base_url,
                headers=self._platform_headers(),
                timeout=httpx.Timeout(self._config.create_timeout_seconds),
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = await client.request(method, path, json=json)
        except httpx.HTTPError as exc:
            raise AioNativeLifecycleError(operation, "transport_failed") from exc

        if response.status_code == 404:
            raise AioNativeLifecycleError(operation, "not_found")
        if response.is_error:
            raise AioNativeLifecycleError(operation, "http_failed")
        if not expect_body:
            return None
        try:
            payload = response.json()
        except ValueError as exc:
            raise AioNativeLifecycleError(operation, "response_invalid") from exc
        return payload.get("data", payload) if isinstance(payload, dict) else payload

    def _platform_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._config.api_token:
            headers["Authorization"] = f"Bearer {self._config.api_token}"
        if self._config.hw_id:
            headers["X-HW-ID"] = self._config.hw_id
        if self._config.app_key:
            headers["X-HW-APPKEY"] = self._config.app_key
        return headers

    @staticmethod
    def _parse_sandbox(
        operation: str,
        payload: Any,
        *,
        fallback_sandbox_id: str | None = None,
        require_state: bool = True,
    ) -> AioNativeSandbox:
        if not isinstance(payload, dict):
            raise AioNativeLifecycleError(operation, "response_invalid")
        sandbox_id = (
            payload.get("sandboxId")
            or payload.get("sandbox_id")
            or payload.get("id")
            or fallback_sandbox_id
        )
        if not isinstance(sandbox_id, str) or not sandbox_id:
            raise AioNativeLifecycleError(operation, "sandbox_id_missing")
        raw_state = payload.get("status") or payload.get("state")
        if raw_state is None and not require_state:
            state: SandboxState = "provisioning"
        elif isinstance(raw_state, str) and raw_state.lower() in {"running", "ready", "ok"}:
            state = "ready"
        elif isinstance(raw_state, str) and raw_state.lower() in {
            "creating",
            "pending",
            "provisioning",
            "starting",
        }:
            state = "provisioning"
        elif isinstance(raw_state, str) and raw_state.lower() in {
            "deleted",
            "missing",
            "released",
            "stopped",
            "failed",
        }:
            state = "released"
        else:
            raise AioNativeLifecycleError(operation, "sandbox_state_invalid")
        workspace_id = payload.get("workspaceId") or payload.get("workspace_id")
        if workspace_id is not None and not isinstance(workspace_id, str):
            raise AioNativeLifecycleError(operation, "workspace_invalid")
        return AioNativeSandbox(
            sandbox_id=sandbox_id, state=state, workspace_id=workspace_id
        )
