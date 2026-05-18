from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from backend.rpa.manager import RPASession, RPASessionManager
from backend.rpa.region_context import RPARegionContext, RPARegionEvidence


def _session() -> RPASession:
    return RPASession(
        id="session-1",
        user_id="user-1",
        sandbox_session_id="sandbox-1",
        active_tab_id="tab-1",
    )


def _context(
    region_id: str = "region-1",
    url: str = "https://example.test/a",
) -> RPARegionContext:
    return RPARegionContext(
        region_id=region_id,
        session_id="session-1",
        tab_id="tab-1",
        page_url=url,
        page_title="Example",
        created_at=datetime.now(),
        evidence=RPARegionEvidence(
            url=url,
            title="Example",
            frame_path=[],
            rect={"x": 10, "y": 20, "width": 100, "height": 50},
            local_text=["SKU", "Price"],
            inferred_kind="table_region",
            warnings=[],
        ),
    )


def test_region_context_storage_replaces_prior_context_for_session():
    manager = RPASessionManager()
    manager.sessions["session-1"] = _session()

    first = manager.store_region_context("session-1", _context("region-1"))
    second = manager.store_region_context("session-1", _context("region-2"))

    assert first.region_id == "region-1"
    assert second.region_id == "region-2"
    assert manager.resolve_region_context("session-1", "region-1") is None
    assert manager.resolve_region_context("session-1", "region-2") == second


def test_region_context_resolution_rejects_stale_page_url():
    manager = RPASessionManager()
    session = _session()
    manager.sessions["session-1"] = session
    manager.store_region_context(
        "session-1",
        _context("region-1", url="https://example.test/old"),
    )

    resolved = manager.resolve_region_context(
        "session-1",
        "region-1",
        current_url="https://example.test/new",
    )

    assert resolved is None


def test_region_context_preview_returns_readable_summary():
    context = _context()
    context.evidence.intersecting_elements = [{"tag": "th"}, {"tag": "td"}]

    preview = context.preview()

    assert preview == {
        "region_id": "region-1",
        "tab_id": "tab-1",
        "summary": "区域 100x50，包含 2 个元素",
        "inferred_kind": "table_region",
        "page_url": "https://example.test/a",
        "page_title": "Example",
        "warnings": [],
    }


def test_region_context_clear_supports_region_and_session_scope():
    manager = RPASessionManager()
    manager.sessions["session-1"] = _session()
    context = manager.store_region_context("session-1", _context("region-1"))

    manager.clear_region_context("session-1", "missing-region")
    assert manager.resolve_region_context("session-1", "region-1") == context

    manager.clear_region_context("session-1", "region-1")
    assert manager.resolve_region_context("session-1", "region-1") is None

    manager.store_region_context("session-1", _context("region-2"))
    manager.clear_region_context("session-1")
    assert manager.resolve_region_context("session-1", "region-2") is None


def test_region_context_detach_clears_pending_contexts():
    manager = RPASessionManager()
    manager.sessions["session-1"] = _session()
    manager.store_region_context("session-1", _context("region-1"))

    manager.detach_context("session-1")

    assert manager.resolve_region_context("session-1", "region-1") is None


def test_region_context_expired_cleanup_clears_pending_contexts():
    manager = RPASessionManager()
    session = _session()
    session.last_activity_at = datetime.now() - timedelta(seconds=120)
    manager.sessions["session-1"] = session
    manager.store_region_context("session-1", _context("region-1"))

    removed = asyncio.run(manager.cleanup_expired_sessions(max_idle_seconds=60))

    assert removed == ["session-1"]
    assert manager.resolve_region_context("session-1", "region-1") is None
