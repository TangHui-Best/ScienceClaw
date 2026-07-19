from __future__ import annotations

import os

from fastapi import FastAPI
import httpx
import pytest

from backend import browser_preview
from backend.config import settings
from backend.route.rpa_agent import (
    RpaAgentApiServices,
    _scienceclaw_browser_provider,
    build_router,
)
from backend.runtime import ownership
from backend.runtime.local_cdp import local_cdp_connector
from backend.user.dependencies import User, require_user


pytestmark = pytest.mark.skipif(
    os.environ.get("RPA_AGENT_LOCAL_LIVE") != "1",
    reason="set RPA_AGENT_LOCAL_LIVE=1 to launch real local Chromium",
)


@pytest.mark.asyncio
async def test_local_mode_starts_rpa_agent_session_on_real_local_chromium(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    browser_ref = "live-local-rpa-agent"

    async def owned(_browser_ref: str, _owner_id: str) -> bool:
        return True

    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(ownership, "user_owns_runtime_session", owned)
    await browser_preview.browser_preview_registry.unregister(browser_ref)

    services = RpaAgentApiServices(
        artifact_root=tmp_path / "artifacts",
        browser_provider=_scienceclaw_browser_provider,
    )
    app = FastAPI()
    app.include_router(build_router(services), prefix="/api/v1/rpa-agent")
    app.dependency_overrides[require_user] = lambda: User(
        id="live-owner",
        username="live-tester",
        role="user",
    )

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/rpa-agent/sessions",
                json={"browser_session_ref": browser_ref},
            )

        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["session_id"].startswith("rca_")
        assert payload["main_scope"]["page_runtime_ref"].startswith("host_page_")
        assert payload["main_scope"]["frame_runtime_ref"].startswith("host_frame_")
        assert browser_preview.browser_preview_registry.get_active_page(browser_ref)
        assert browser_preview.browser_preview_registry.get_cdp_url(browser_ref).startswith(
            "ws://127.0.0.1:"
        )
    finally:
        assert services.store is not None
        await services.store.close_all()
        await browser_preview.browser_preview_registry.unregister(browser_ref)
        await local_cdp_connector.close()
