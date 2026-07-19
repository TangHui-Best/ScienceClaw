"""Generic ScienceClaw runtime lease used by the greenfield RPA host.

This module intentionally depends only on the generic runtime and preview
facilities.  It neither imports nor adapts any legacy RPA domain object.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from threading import RLock
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


def rewrite_cdp_url(cdp_url: str, *, rest_base_url: str) -> str:
    """Route an opaque CDP websocket path through the runtime REST host."""

    cdp = urlsplit(cdp_url)
    runtime = urlsplit(rest_base_url)
    if (
        cdp.scheme not in {"ws", "wss"}
        or not cdp.netloc
        or not cdp.path.startswith("/devtools/browser/")
        or runtime.scheme not in {"http", "https"}
        or not runtime.netloc
    ):
        raise ValueError("browser_runtime.cdp_url_invalid")
    public_scheme = "wss" if runtime.scheme == "https" else "ws"
    return urlunsplit(
        (public_scheme, runtime.netloc, cdp.path, cdp.query, cdp.fragment)
    )


async def fetch_runtime_cdp_url(rest_base_url: str) -> str:
    url = rest_base_url.rstrip("/") + "/v1/browser/info"
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise RuntimeError("browser_runtime.cdp_info_unavailable") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("browser_runtime.cdp_info_invalid")
    data = payload.get("data")
    raw = data.get("cdp_url") if isinstance(data, dict) else None
    if not isinstance(raw, str) or not raw:
        raise RuntimeError("browser_runtime.cdp_info_invalid")
    try:
        return rewrite_cdp_url(raw, rest_base_url=rest_base_url)
    except ValueError as exc:
        raise RuntimeError("browser_runtime.cdp_info_invalid") from exc


async def _connect_playwright(cdp_url: str) -> tuple[object, object]:
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
    except BaseException:
        await playwright.stop()
        raise
    return playwright, browser


@dataclass(slots=True)
class BrowserRuntimeLease:
    page: object
    cdp_url: str
    _cleanup: Callable[[], Awaitable[None]] | None = None
    _closed: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def aclose(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._cleanup is not None:
                await self._cleanup()


@dataclass(slots=True)
class _OwnedRuntimeResource:
    page: object
    cdp_url: str
    playwright: object
    created_context: object | None
    preview_registry: object
    ref_count: int = 1


_RESOURCE_MUTEX = RLock()
_ACQUIRE_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}
_OWNED_RESOURCES: dict[tuple[int, str], _OwnedRuntimeResource] = {}


def _acquire_lock(key: tuple[int, str]) -> asyncio.Lock:
    with _RESOURCE_MUTEX:
        return _ACQUIRE_LOCKS.setdefault(key, asyncio.Lock())


async def acquire_browser_runtime_lease(
    *,
    owner_id: str,
    browser_ref: str,
    preview_registry: object,
    ensure_runtime: Callable[[str, str], Awaitable[object]] | None = None,
    resolve_cdp_url: Callable[[str, str], Awaitable[str]] | None = None,
    fetch_cdp_url: Callable[[str], Awaitable[str]] = fetch_runtime_cdp_url,
    connect: Callable[[str], Awaitable[tuple[object, object]]] = _connect_playwright,
) -> BrowserRuntimeLease:
    """Ensure the generic runtime exposes one preview Page for both channels."""

    key = (id(preview_registry), browser_ref)
    async with _acquire_lock(key):
        if resolve_cdp_url is not None:
            cdp_url = await resolve_cdp_url(browser_ref, owner_id)
            parsed_cdp = urlsplit(cdp_url) if isinstance(cdp_url, str) else None
            if (
                parsed_cdp is None
                or parsed_cdp.scheme not in {"ws", "wss"}
                or not parsed_cdp.netloc
                or not parsed_cdp.path.startswith("/devtools/browser/")
            ):
                raise RuntimeError("browser_runtime.cdp_url_invalid")
        else:
            if ensure_runtime is None:
                from backend.runtime.session_runtime_manager import (
                    get_session_runtime_manager,
                )

                ensure_runtime = get_session_runtime_manager().ensure_runtime
            runtime = await ensure_runtime(browser_ref, owner_id)
            rest_base_url = getattr(runtime, "rest_base_url", None)
            if not isinstance(rest_base_url, str) or not rest_base_url:
                raise RuntimeError("browser_runtime.rest_base_url_invalid")
            cdp_url = await fetch_cdp_url(rest_base_url)

        owned = _OWNED_RESOURCES.get(key)
        if owned is not None:
            if owned.cdp_url != cdp_url:
                raise RuntimeError("browser_runtime.preview_cdp_mismatch")
            owned.ref_count += 1
            return BrowserRuntimeLease(
                page=owned.page,
                cdp_url=owned.cdp_url,
                _cleanup=lambda: _release_owned_resource(key),
            )

        existing = getattr(preview_registry, "get_active_page")(browser_ref)
        if existing is not None:
            registered_cdp = getattr(preview_registry, "get_cdp_url", lambda _ref: None)(
                browser_ref
            )
            if registered_cdp != cdp_url:
                raise RuntimeError("browser_runtime.preview_cdp_mismatch")
            return BrowserRuntimeLease(page=existing, cdp_url=cdp_url)

        playwright, browser = await connect(cdp_url)
        created_context: object | None = None
        try:
            contexts = tuple(getattr(browser, "contexts", ()) or ())
            if contexts:
                context = contexts[0]
            else:
                context = await getattr(browser, "new_context")()
                created_context = context
            pages = tuple(getattr(context, "pages", ()) or ())
            page = pages[-1] if pages else await getattr(context, "new_page")()
            await getattr(preview_registry, "register")(
                browser_ref, page, cdp_url=cdp_url
            )
        except BaseException:
            await _release_connection(playwright, created_context)
            raise
        _OWNED_RESOURCES[key] = _OwnedRuntimeResource(
            page=page,
            cdp_url=cdp_url,
            playwright=playwright,
            created_context=created_context,
            preview_registry=preview_registry,
        )
        return BrowserRuntimeLease(
            page=page,
            cdp_url=cdp_url,
            _cleanup=lambda: _release_owned_resource(key),
        )


async def _release_owned_resource(key: tuple[int, str]) -> None:
    lock = _acquire_lock(key)
    async with lock:
        owned = _OWNED_RESOURCES.get(key)
        if owned is None:
            return
        owned.ref_count -= 1
        if owned.ref_count > 0:
            return
        del _OWNED_RESOURCES[key]
        browser_ref = key[1]
        first: BaseException | None = None
        try:
            await getattr(owned.preview_registry, "unregister")(
                browser_ref, owned.page
            )
        except BaseException as exc:
            first = exc
        try:
            await _release_connection(owned.playwright, owned.created_context)
        except BaseException as exc:
            if first is None:
                first = exc
        with _RESOURCE_MUTEX:
            _ACQUIRE_LOCKS.pop(key, None)
        if first is not None:
            raise first


async def _release_connection(playwright: Any, created_context: object | None) -> None:
    first: BaseException | None = None
    if created_context is not None:
        try:
            await getattr(created_context, "close")()
        except BaseException as exc:
            first = exc
    try:
        await getattr(playwright, "stop")()
    except BaseException as exc:
        if first is None:
            first = exc
    if first is not None:
        raise first


__all__ = [
    "BrowserRuntimeLease",
    "acquire_browser_runtime_lease",
    "fetch_runtime_cdp_url",
    "rewrite_cdp_url",
]
