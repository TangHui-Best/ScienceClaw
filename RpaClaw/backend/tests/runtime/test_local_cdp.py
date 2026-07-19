from __future__ import annotations

import importlib

import pytest

from backend.runtime.local_cdp import LocalCDPConnector, local_cdp_connector


def test_legacy_local_connector_reexports_neutral_singleton() -> None:
    cdp_connector = importlib.import_module("backend.rpa.cdp_connector")

    assert cdp_connector.LocalCDPConnector is LocalCDPConnector
    assert cdp_connector.local_cdp_connector is local_cdp_connector


@pytest.mark.asyncio
async def test_local_connector_exposes_public_cdp_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = LocalCDPConnector()

    async def fake_ensure_browser() -> None:
        connector._cdp_url = (
            "ws://127.0.0.1:19222/devtools/browser/local-runtime"
        )

    monkeypatch.setattr(connector, "_ensure_browser", fake_ensure_browser)

    assert await connector.get_cdp_url() == (
        "ws://127.0.0.1:19222/devtools/browser/local-runtime"
    )
