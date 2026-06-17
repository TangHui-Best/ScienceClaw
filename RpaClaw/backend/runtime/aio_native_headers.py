from __future__ import annotations

from typing import Any


def aio_native_platform_headers(settings: Any) -> dict[str, str]:
    """Headers required by the native AIO gateway lifecycle APIs."""
    headers: dict[str, str] = {}
    token = (getattr(settings, "aio_native_api_token", "") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    hw_id = (getattr(settings, "aio_native_hw_id", "") or "").strip()
    if hw_id:
        headers["X-HW-ID"] = hw_id
    appkey = (getattr(settings, "aio_native_appkey", "") or "").strip()
    if appkey:
        headers["X-HW-APPKEY"] = appkey
    return headers


def aio_native_sandbox_headers(settings: Any, sandbox_id: str | None) -> dict[str, str]:
    """Headers for native AIO in-sandbox APIs routed through the gateway."""
    headers = aio_native_platform_headers(settings)
    sandbox_id = (sandbox_id or "").strip()
    if sandbox_id:
        header_name = (
            getattr(settings, "aio_native_sandbox_header_name", "")
            or "x-livefunction-sandbox-id"
        ).strip()
        headers[header_name] = sandbox_id
    return headers
