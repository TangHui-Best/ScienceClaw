import importlib
import sys
import types

import pytest

from backend.runtime.models import SessionRuntimeRecord


def _install_fake_playwright_modules():
    playwright_module = types.ModuleType("playwright")
    async_api_module = types.ModuleType("playwright.async_api")
    async_api_module.async_playwright = lambda: None
    async_api_module.Browser = object
    async_api_module.Playwright = object
    async_api_module.Page = object
    async_api_module.BrowserContext = object
    sys.modules["playwright"] = playwright_module
    sys.modules["playwright.async_api"] = async_api_module


class _FakeManager:
    async def ensure_runtime(self, session_id: str, user_id: str) -> SessionRuntimeRecord:
        return SessionRuntimeRecord(
            session_id=session_id,
            user_id=user_id,
            namespace="beta",
            pod_name="rpaclaw-sess-sess-1",
            service_name="rpaclaw-sess-sess-1-svc",
            rest_base_url="http://rpaclaw-sess-sess-1-svc:8080",
            status="ready",
        )


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "data": {
                "cdp_url": "ws://127.0.0.1:9222/devtools/browser/test-id",
            }
        }


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        self.calls.append(url)
        return _FakeResponse()


class _FakeChromium:
    def __init__(self):
        self.connect_calls = []
        self.launch_calls = []

    async def connect_over_cdp(self, cdp_url):
        self.connect_calls.append(cdp_url)
        return object()

    async def launch(self, **kwargs):
        self.launch_calls.append(kwargs)
        return object()


class _FakePlaywrightHandle:
    def __init__(self):
        self.chromium = _FakeChromium()


class _FakeAsyncPlaywrightFactory:
    def __init__(self, handle):
        self.handle = handle

    async def start(self):
        return self.handle


@pytest.mark.anyio
async def test_fetch_cdp_url_uses_runtime_endpoint_for_session(monkeypatch):
    _install_fake_playwright_modules()
    sys.modules.pop("backend.rpa.cdp_connector", None)
    cdp_connector = importlib.import_module("backend.rpa.cdp_connector")

    fake_client = _FakeAsyncClient()
    monkeypatch.setattr(cdp_connector, "get_session_runtime_manager", lambda: _FakeManager())
    monkeypatch.setattr(cdp_connector.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)

    connector = cdp_connector.CDPConnector()

    cdp_url = await connector._fetch_cdp_url(session_id="sess-1", user_id="user-1")

    assert fake_client.calls == ["http://rpaclaw-sess-sess-1-svc:8080/v1/browser/info"]
    assert cdp_url == "ws://rpaclaw-sess-sess-1-svc:8080/devtools/browser/test-id"


@pytest.mark.anyio
async def test_local_launch_uses_relaxed_security_browser_args(monkeypatch):
    _install_fake_playwright_modules()
    sys.modules.pop("backend.rpa.cdp_connector", None)
    cdp_connector = importlib.import_module("backend.rpa.cdp_connector")

    fake_playwright = _FakePlaywrightHandle()
    monkeypatch.setattr(
        cdp_connector,
        "async_playwright",
        lambda: _FakeAsyncPlaywrightFactory(fake_playwright),
    )

    _pw, _browser = await cdp_connector.LocalCDPConnector._launch()

    assert fake_playwright.chromium.launch_calls == [
        {
            "headless": False,
            "args": [
                "--ignore-certificate-errors",
                "--allow-insecure-localhost",
                "--allow-running-insecure-content",
                "--test-type",
                "--disable-notifications",
            ],
        }
    ]
