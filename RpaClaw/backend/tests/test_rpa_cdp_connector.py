import unittest
from unittest.mock import AsyncMock, patch

from backend.rpa.cdp_connector import LocalCDPConnector


class _FakeContext:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, *, stale=False):
        self.stale = stale
        self.contexts_created = 0

    def is_connected(self):
        return True

    async def new_context(self, **_kwargs):
        self.contexts_created += 1
        if self.stale:
            raise RuntimeError("Connection closed while reading from the driver")
        return _FakeContext()


class LocalCDPConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_browser_relaunches_when_cached_browser_cannot_create_context(self):
        connector = LocalCDPConnector()
        stale_browser = _FakeBrowser(stale=True)
        fresh_browser = _FakeBrowser()
        connector._browser = stale_browser
        connector._playwright = object()

        async def run_inline(coro):
            return await coro

        connector._run_in_pw_loop = run_inline

        with patch.object(
            LocalCDPConnector,
            "_launch",
            new=AsyncMock(return_value=(object(), fresh_browser)),
        ) as launch:
            browser = await connector.get_browser()

        self.assertIs(browser, fresh_browser)
        self.assertIs(connector._browser, fresh_browser)
        self.assertEqual(stale_browser.contexts_created, 1)
        launch.assert_awaited_once()

    async def test_get_browser_reuses_cached_browser_when_context_probe_succeeds(self):
        connector = LocalCDPConnector()
        cached_browser = _FakeBrowser()
        connector._browser = cached_browser
        connector._playwright = object()

        async def run_inline(coro):
            return await coro

        connector._run_in_pw_loop = run_inline

        with patch.object(
            LocalCDPConnector,
            "_launch",
            new=AsyncMock(),
        ) as launch:
            browser = await connector.get_browser()

        self.assertIs(browser, cached_browser)
        self.assertEqual(cached_browser.contexts_created, 1)
        launch.assert_not_awaited()
