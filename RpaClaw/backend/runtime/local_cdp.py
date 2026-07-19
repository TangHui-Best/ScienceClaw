from __future__ import annotations

import asyncio
import logging
import socket
import sys
import threading
from typing import Optional

import httpx
from playwright.async_api import Browser, Playwright, async_playwright

from backend.runtime.playwright_security import get_chromium_launch_kwargs


logger = logging.getLogger(__name__)


class LocalCDPConnector:
    """Own the process-wide local Chromium and expose its exact CDP endpoint."""

    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._cdp_port: Optional[int] = None
        self._cdp_url: Optional[str] = None
        self._lock = asyncio.Lock()
        self._pw_loop: Optional[asyncio.AbstractEventLoop] = None
        self._pw_thread: Optional[threading.Thread] = None

    def _ensure_pw_loop(self) -> None:
        if self._pw_thread and self._pw_thread.is_alive():
            return
        self._pw_loop = asyncio.new_event_loop()
        if sys.platform == "win32":
            self._pw_loop = asyncio.ProactorEventLoop()
        self._pw_thread = threading.Thread(
            target=self._pw_loop.run_forever,
            daemon=True,
            name="playwright-local-loop",
        )
        self._pw_thread.start()

    async def _run_in_pw_loop(self, coro):
        self._ensure_pw_loop()
        assert self._pw_loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._pw_loop)
        return await asyncio.wrap_future(future)

    async def run_in_pw_loop(self, coro):
        return await self._run_in_pw_loop(coro)

    async def _ensure_browser(self) -> None:
        if self._browser and self._browser.is_connected() and self._cdp_url:
            return
        logger.info("Launching local Playwright Chromium (headful)")
        cdp_port = _find_free_local_port()
        playwright, browser = await self._run_in_pw_loop(self._launch(cdp_port))
        try:
            cdp_url = await _fetch_local_cdp_url(cdp_port)
        except BaseException:
            await self._close_handles(playwright, browser)
            raise
        self._cdp_port = cdp_port
        self._playwright = playwright
        self._browser = browser
        self._cdp_url = cdp_url
        logger.info("Local browser launched")

    async def get_browser(
        self,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Browser:
        del session_id, user_id
        async with self._lock:
            await self._ensure_browser()
            if self._browser is None:
                raise RuntimeError("local_browser.unavailable")
            return self._browser

    async def get_cdp_url(self) -> str:
        async with self._lock:
            await self._ensure_browser()
            if not self._cdp_url:
                raise RuntimeError("local_browser.cdp_url_unavailable")
            return self._cdp_url

    @staticmethod
    async def _launch(cdp_port: Optional[int] = None):
        playwright = await async_playwright().start()
        launch_kwargs = get_chromium_launch_kwargs(headless=False)
        if cdp_port:
            launch_kwargs["args"] = list(launch_kwargs.get("args") or []) + [
                f"--remote-debugging-port={cdp_port}",
            ]
        browser = await playwright.chromium.launch(**launch_kwargs)
        return playwright, browser

    async def _close_handles(self, playwright, browser) -> None:
        if self._pw_loop and self._pw_loop.is_running():
            if browser is not None:
                future = asyncio.run_coroutine_threadsafe(
                    browser.close(), self._pw_loop
                )
                await asyncio.wrap_future(future)
            if playwright is not None:
                future = asyncio.run_coroutine_threadsafe(
                    playwright.stop(), self._pw_loop
                )
                await asyncio.wrap_future(future)

    async def close(self) -> None:
        async with self._lock:
            browser = self._browser
            playwright = self._playwright
            self._browser = None
            self._playwright = None
            self._cdp_url = None
            self._cdp_port = None
        try:
            await self._close_handles(playwright, browser)
        finally:
            if self._pw_loop:
                self._pw_loop.call_soon_threadsafe(self._pw_loop.stop)
            self._pw_loop = None
            self._pw_thread = None


def _find_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _fetch_local_cdp_url(port: int) -> str:
    url = f"http://127.0.0.1:{port}/json/version"
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=1.0, trust_env=False) as client:
        for _ in range(50):
            try:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
                cdp_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
                if cdp_url:
                    return cdp_url
            except Exception as exc:
                last_error = exc
            await asyncio.sleep(0.1)
    raise RuntimeError(
        f"Local browser CDP endpoint did not become ready at {url}: {last_error}"
    )


local_cdp_connector = LocalCDPConnector()


__all__ = ["LocalCDPConnector", "local_cdp_connector"]
