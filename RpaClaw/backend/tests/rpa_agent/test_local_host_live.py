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
async def test_local_mode_isolates_consecutive_recording_contexts_on_real_chromium(
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
            first_response = await client.post(
                "/api/v1/rpa-agent/sessions",
                json={"browser_session_ref": browser_ref},
            )
            assert first_response.status_code == 201, first_response.text
            first_payload = first_response.json()
            first_page = browser_preview.browser_preview_registry.get_active_page(
                browser_ref
            )
            assert first_page is not None
            first_context = first_page.context
            await first_context.add_cookies(
                [
                    {
                        "name": "old_recording",
                        "value": "must-not-cross",
                        "url": "https://isolation.test",
                    }
                ]
            )
            first_cdp_url = browser_preview.browser_preview_registry.get_cdp_url(
                browser_ref
            )

            stopped = await client.post(
                f"/api/v1/rpa-agent/sessions/{first_payload['session_id']}/stop"
            )
            assert stopped.status_code == 200, stopped.text
            assert first_page.is_closed()
            assert browser_preview.browser_preview_registry.get_active_page(browser_ref) is None

            second_response = await client.post(
                "/api/v1/rpa-agent/sessions",
                json={"browser_session_ref": browser_ref},
            )
            assert second_response.status_code == 201, second_response.text
            second_payload = second_response.json()
            second_page = browser_preview.browser_preview_registry.get_active_page(
                browser_ref
            )
            assert second_page is not None
            second_context = second_page.context

            assert first_payload["session_id"] != second_payload["session_id"]
            assert first_context is not second_context
            assert first_page is not second_page
            assert await second_context.cookies("https://isolation.test") == []
            assert browser_preview.browser_preview_registry.get_cdp_url(
                browser_ref
            ) == first_cdp_url

            discarded = await client.delete(
                f"/api/v1/rpa-agent/sessions/{second_payload['session_id']}"
            )
            assert discarded.status_code == 200, discarded.text
            assert second_page.is_closed()
    finally:
        assert services.store is not None
        await services.store.close_all()
        await browser_preview.browser_preview_registry.unregister(browser_ref)
        await local_cdp_connector.close()
