from __future__ import annotations

import asyncio
import importlib
import json
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.rpa.manager import RPASession, RPASessionManager
from backend.rpa.region_context import (
    RPARegionAnalyzeRequest,
    RPARegionContext,
    RPARegionEvidence,
    RPARegionRect,
    RPARegionViewport,
    analyze_region_on_page,
    classify_region_evidence,
    prune_region_evidence,
)


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


def test_region_evidence_model_preserves_scope_locator_hierarchy():
    evidence = RPARegionEvidence(
        url="https://example.test/orders",
        title="Orders",
        rect={"x": 10, "y": 20, "width": 200, "height": 80},
        scope_candidates=[
            {
                "kind": "text",
                "locator": {"method": "text", "value": "Order A"},
                "source": "dominant_scope",
            }
        ],
        intersecting_elements=[
            {
                "tag": "span",
                "text": "Paid",
                "ancestor_chain": [
                    {
                        "tag": "article",
                        "role": "article",
                        "text": "Order A Paid",
                        "locator_candidates": [
                            {"kind": "text", "locator": {"method": "text", "value": "Order A"}}
                        ],
                    }
                ],
                "nested_locator_candidates": [
                    {
                        "kind": "nested",
                        "locator": {
                            "method": "nested",
                            "parent": {"method": "text", "value": "Order A"},
                            "child": {"method": "text", "value": "Paid"},
                        },
                        "source": "region_ancestor_scope",
                    }
                ],
            }
        ],
    )

    dumped = evidence.model_dump(mode="json")

    assert dumped["scope_candidates"] == [
        {
            "kind": "text",
            "locator": {"method": "text", "value": "Order A"},
            "source": "dominant_scope",
        }
    ]
    assert dumped["intersecting_elements"][0]["ancestor_chain"][0]["locator_candidates"] == [
        {"kind": "text", "locator": {"method": "text", "value": "Order A"}}
    ]
    assert dumped["intersecting_elements"][0]["nested_locator_candidates"] == [
        {
            "kind": "nested",
            "locator": {
                "method": "nested",
                "parent": {"method": "text", "value": "Order A"},
                "child": {"method": "text", "value": "Paid"},
            },
            "source": "region_ancestor_scope",
        }
    ]


def test_region_evidence_pruning_drops_oversized_ancestor_text():
    oversized_text = " ".join(["Oversized checkout content"] * 12)
    raw = {
        "rect": {"x": 100, "y": 100, "width": 200, "height": 100},
        "intersecting_elements": [
            {
                "tag": "main",
                "text": oversized_text,
                "rect": {"x": 0, "y": 0, "width": 1200, "height": 800},
            },
            {
                "tag": "span",
                "text": "Selected Price",
                "rect": {"x": 120, "y": 120, "width": 90, "height": 20},
            },
        ],
        "local_text": [oversized_text, "Selected Price"],
        "dominant_container": {
            "tag": "main",
            "text": oversized_text,
            "rect": {"x": 0, "y": 0, "width": 1200, "height": 800},
        },
        "scope_candidates": [
            {
                "kind": "css",
                "locator": {"method": "css", "value": "article.order-card"},
            }
        ],
    }

    pruned = prune_region_evidence(raw)

    assert [item.get("text") for item in pruned["intersecting_elements"]] == ["Selected Price"]
    assert pruned["local_text"] == ["Selected Price"]
    assert pruned["dominant_container"]["tag"] == "span"
    assert pruned["scope_candidates"][0]["locator"]["value"] == "article.order-card"


def test_region_evidence_pruning_keeps_semantic_table_container():
    raw = {
        "rect": {"x": 0, "y": 0, "width": 500, "height": 250},
        "intersecting_elements": [
            {
                "tag": "table",
                "role": "table",
                "text": "Name Price A 10",
                "rect": {"x": 0, "y": 0, "width": 1000, "height": 600},
            },
            {
                "tag": "td",
                "text": "A",
                "rect": {"x": 20, "y": 40, "width": 80, "height": 30},
            },
        ],
        "dominant_container": {
            "tag": "table",
            "role": "table",
            "text": "Name Price A 10",
            "rect": {"x": 0, "y": 0, "width": 1000, "height": 600},
        },
        "local_text": ["Name Price A 10", "A"],
    }

    pruned = prune_region_evidence(raw)

    assert pruned["dominant_container"]["tag"] == "table"
    assert pruned["local_text"][0] == "Name Price A 10"


async def _collect_sse_events(response):
    events = []
    chunks = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, dict):
            events.append(chunk)
        else:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk))
    body = "".join(chunks)
    current_event = None
    for line in body.splitlines():
        if line.startswith("event:"):
            current_event = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            events.append(
                {
                    "event": current_event or "message",
                    "data": line.removeprefix("data:").strip(),
                }
            )
            current_event = None
    return events


class _FakeFrameElement:
    def __init__(self, bbox):
        self._bbox = bbox

    async def bounding_box(self):
        return self._bbox


class _FakeFrame:
    def __init__(self, name, *, result=None, bbox=None, parent_frame=None):
        self.name = name
        self.result = result or {}
        self.parent_frame = parent_frame
        self.page = None
        self.evaluated_rect = None
        self._frame_element = _FakeFrameElement(bbox) if bbox else None

    async def evaluate(self, script, arg):
        assert "__rpaPlaywrightRecorder" in script
        self.evaluated_rect = arg
        return self.result

    async def frame_element(self):
        if self._frame_element is None:
            raise RuntimeError("main frame has no frame element")
        return self._frame_element


class _FakePage:
    def __init__(self, *, main_result=None, child_result=None):
        self.url = "https://example.test/region"
        self.main_frame = _FakeFrame("main", result=main_result or {})
        self.child_frame = _FakeFrame(
            "child",
            result=child_result or {},
            bbox={"x": 90, "y": 70, "width": 200, "height": 200},
            parent_frame=self.main_frame,
        )
        self.main_frame.page = self
        self.child_frame.page = self
        self.frames = [self.main_frame, self.child_frame]

    async def title(self):
        return "Region Page"

    async def evaluate(self, script, arg):
        return await self.main_frame.evaluate(script, arg)


class _FakeNestedPage:
    def __init__(self, *, outer_result=None, inner_result=None):
        self.url = "https://example.test/nested-region"
        self.main_frame = _FakeFrame("main", result={})
        self.outer_frame = _FakeFrame(
            "outer",
            result=outer_result or {},
            bbox={"x": 90, "y": 70, "width": 240, "height": 180},
            parent_frame=self.main_frame,
        )
        self.inner_frame = _FakeFrame(
            "inner",
            result=inner_result or {},
            bbox={"x": 120, "y": 100, "width": 80, "height": 60},
            parent_frame=self.outer_frame,
        )
        for frame in (self.main_frame, self.outer_frame, self.inner_frame):
            frame.page = self
        self.frames = [self.main_frame, self.outer_frame, self.inner_frame]

    async def title(self):
        return "Nested Region Page"

    async def evaluate(self, script, arg):
        return await self.main_frame.evaluate(script, arg)


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


def test_region_rect_and_viewport_reject_non_positive_dimensions():
    with pytest.raises(ValidationError):
        RPARegionRect(x=0, y=0, width=0, height=10)

    with pytest.raises(ValidationError):
        RPARegionRect(x=0, y=0, width=10, height=-1)

    with pytest.raises(ValidationError):
        RPARegionViewport(width=1280, height=0)


def test_classify_region_evidence_prefers_table_headers():
    raw = {
        "table_summary": {"headers": ["Name"]},
        "list_summary": {"item_count": 3},
        "action_summary": {"controls": [{"label": "Save"}]},
        "local_text": ["Name"],
    }

    assert classify_region_evidence(raw) == "table_region"


@pytest.mark.anyio
async def test_analyze_region_on_page_collects_frame_local_evidence(monkeypatch):
    child_result = {
        "rect": {"x": 10, "y": 10, "width": 50, "height": 40},
        "intersecting_elements": [{"tag": "table", "text": "Name Price"}],
        "dominant_container": {"tag": "table", "text": "Name Price"},
        "locator_candidates": [{"kind": "role", "playwright_locator": "page.get_by_role('table')"}],
        "local_text": ["Name", "Price", "A", "$1"],
        "table_summary": {
            "headers": ["Name", "Price"],
            "sample_rows": [["A", "$1"]],
            "row_count": 1,
            "locator_candidates": [{"kind": "css", "selector": "table"}],
        },
        "list_summary": {
            "item_count": 2,
            "item_selector": "li",
            "sample_items": ["First", "Second"],
            "container_locator_candidates": [{"kind": "css", "selector": "ul"}],
        },
        "action_summary": {
            "controls": [
                {
                    "tag": "button",
                    "text": "Save",
                    "locator_candidates": [{"kind": "text", "playwright_locator": "page.get_by_text('Save')"}],
                }
            ]
        },
        "warnings": [],
    }
    page = _FakePage(child_result=child_result)

    async def fake_build_frame_path(frame):
        assert frame.name == "child"
        return ["iframe[title='workspace']"]

    monkeypatch.setattr("backend.rpa.region_context.build_frame_path", fake_build_frame_path)

    evidence = await analyze_region_on_page(
        page,
        RPARegionAnalyzeRequest(
            tab_id="tab-1",
            rect=RPARegionRect(x=100, y=80, width=50, height=40),
            viewport=RPARegionViewport(width=1280, height=720),
        ),
    )

    assert page.child_frame.evaluated_rect == {"x": 10, "y": 10, "width": 50, "height": 40}
    assert evidence["url"] == "https://example.test/region"
    assert evidence["title"] == "Region Page"
    assert evidence["frame_path"] == ["iframe[title='workspace']"]
    assert evidence["inferred_kind"] == "table_region"
    assert evidence["table_summary"]["headers"] == ["Name", "Price"]
    assert evidence["table_summary"]["sample_rows"] == [["A", "$1"]]
    assert evidence["list_summary"]["item_count"] == 2
    assert evidence["action_summary"]["controls"][0]["text"] == "Save"


@pytest.mark.anyio
async def test_analyze_region_on_page_keeps_main_frame_when_iframe_overlap_is_minor(monkeypatch):
    main_result = {
        "intersecting_elements": [{"tag": "section", "text": "Main content"}],
        "dominant_container": {"tag": "section", "text": "Main content"},
        "local_text": ["Main content"],
        "warnings": [],
    }
    page = _FakePage(main_result=main_result, child_result={"local_text": ["Iframe content"]})

    async def fail_if_frame_path_requested(_frame):
        raise AssertionError("minor iframe overlap should not resolve a frame path")

    monkeypatch.setattr("backend.rpa.region_context.build_frame_path", fail_if_frame_path_requested)

    evidence = await analyze_region_on_page(
        page,
        RPARegionAnalyzeRequest(
            tab_id="tab-1",
            rect=RPARegionRect(x=0, y=0, width=100, height=80),
            viewport=RPARegionViewport(width=1280, height=720),
        ),
    )

    assert page.main_frame.evaluated_rect == {"x": 0, "y": 0, "width": 100, "height": 80}
    assert page.child_frame.evaluated_rect is None
    assert evidence["frame_path"] == []
    assert evidence["rect"] == {"x": 0, "y": 0, "width": 100, "height": 80}
    assert evidence["local_text"] == ["Main content"]


@pytest.mark.anyio
async def test_analyze_region_on_page_prefers_deeper_frame_when_overlap_ties(monkeypatch):
    page = _FakeNestedPage(
        outer_result={"local_text": ["Outer frame"]},
        inner_result={
            "intersecting_elements": [{"tag": "table", "text": "Nested table"}],
            "dominant_container": {"tag": "table", "text": "Nested table"},
            "local_text": ["Nested table"],
            "warnings": [],
        },
    )

    async def fake_build_frame_path(frame):
        if frame.name == "inner":
            return ["iframe[title='outer']", "iframe[title='inner']"]
        if frame.name == "outer":
            return ["iframe[title='outer']"]
        return []

    monkeypatch.setattr("backend.rpa.region_context.build_frame_path", fake_build_frame_path)

    evidence = await analyze_region_on_page(
        page,
        RPARegionAnalyzeRequest(
            tab_id="tab-1",
            rect=RPARegionRect(x=120, y=100, width=80, height=60),
            viewport=RPARegionViewport(width=1280, height=720),
        ),
    )

    assert page.outer_frame.evaluated_rect is None
    assert page.inner_frame.evaluated_rect == {"x": 0, "y": 0, "width": 80, "height": 60}
    assert evidence["frame_path"] == ["iframe[title='outer']", "iframe[title='inner']"]
    assert evidence["rect"] == {"x": 0, "y": 0, "width": 80, "height": 60}
    assert evidence["local_text"] == ["Nested table"]


def test_manager_get_page_for_tab_uses_active_or_requested_tab():
    manager = RPASessionManager()
    session = _session()
    manager.sessions["session-1"] = session
    active_page = object()
    other_page = object()
    manager._tabs["session-1"] = {"tab-1": active_page, "tab-2": other_page}
    manager._pages["session-1"] = active_page

    assert manager.get_page_for_tab("session-1", None) is active_page
    assert manager.get_page_for_tab("session-1", "tab-2") is other_page
    assert manager.get_page_for_tab("session-1", "missing") is None


@pytest.mark.anyio
async def test_analyze_region_route_stores_context(monkeypatch):
    route_module = importlib.import_module("backend.route.rpa")
    manager = route_module.rpa_manager
    session = RPASession(
        id="session-route",
        user_id="user-1",
        sandbox_session_id="sandbox-1",
        active_tab_id="tab-1",
    )
    page = object()
    stored = {}

    async def fake_get_session(session_id):
        assert session_id == "session-route"
        return session

    async def fake_analyze_region_on_page(page_arg, request_arg):
        assert page_arg is page
        assert request_arg.tab_id == "tab-1"
        return {
            "url": "https://example.test/region",
            "title": "Region Page",
            "frame_path": [],
            "rect": request_arg.rect.model_dump(),
            "dominant_container": {"tag": "table"},
            "intersecting_elements": [{"tag": "table"}],
            "locator_candidates": [{"kind": "css", "selector": "table"}],
            "local_text": ["Name"],
            "inferred_kind": "table_region",
            "table_summary": {"headers": ["Name"], "sample_rows": [["A"]], "row_count": 1},
            "list_summary": None,
            "action_summary": {"controls": []},
            "warnings": [],
        }

    def fake_get_page_for_tab(session_id, tab_id):
        assert session_id == "session-route"
        assert tab_id == "tab-1"
        return page

    def fake_store_region_context(session_id, context):
        stored["session_id"] = session_id
        stored["context"] = context
        return context

    monkeypatch.setattr(manager, "get_session", fake_get_session)
    monkeypatch.setattr(manager, "get_page_for_tab", fake_get_page_for_tab)
    monkeypatch.setattr(manager, "store_region_context", fake_store_region_context)
    monkeypatch.setattr(route_module, "analyze_region_on_page", fake_analyze_region_on_page)

    response = await route_module.analyze_rpa_region(
        "session-route",
        RPARegionAnalyzeRequest(
            tab_id="tab-1",
            rect=RPARegionRect(x=1, y=2, width=100, height=80),
            viewport=RPARegionViewport(width=1280, height=720),
        ),
        type("User", (), {"id": "user-1"})(),
    )

    assert stored["session_id"] == "session-route"
    assert stored["context"].tab_id == "tab-1"
    assert response.region_id == stored["context"].region_id
    assert response.inferred_kind == "table_region"


@pytest.mark.anyio
async def test_analyze_region_route_rejects_missing_tab_page(monkeypatch):
    route_module = importlib.import_module("backend.route.rpa")
    session = RPASession(
        id="session-route",
        user_id="user-1",
        sandbox_session_id="sandbox-1",
        active_tab_id="tab-1",
    )

    async def fake_get_session(_session_id):
        return session

    monkeypatch.setattr(route_module.rpa_manager, "get_session", fake_get_session)
    monkeypatch.setattr(route_module.rpa_manager, "get_page_for_tab", lambda _session_id, _tab_id: None)

    with pytest.raises(route_module.HTTPException) as exc_info:
        await route_module.analyze_rpa_region(
            "session-route",
            RPARegionAnalyzeRequest(
                tab_id="missing",
                rect=RPARegionRect(x=1, y=2, width=100, height=80),
                viewport=RPARegionViewport(width=1280, height=720),
            ),
            type("User", (), {"id": "user-1"})(),
        )

    assert exc_info.value.status_code == 404


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


def test_resolve_chat_region_context_returns_model_dump(monkeypatch):
    route_module = importlib.import_module("backend.route.rpa")
    context = _context("region-route", url="https://example.test/a")

    def fake_resolve_region_context(session_id, region_id, *, current_url=None):
        assert session_id == "session-1"
        assert region_id == "region-route"
        assert current_url == "https://example.test/a"
        return context

    monkeypatch.setattr(route_module.rpa_manager, "resolve_region_context", fake_resolve_region_context)

    assert route_module._resolve_chat_region_context(
        "session-1",
        "region-route",
        "https://example.test/a",
    ) == context.model_dump(mode="json")


def test_resolve_chat_region_context_rejects_missing_or_stale_region(monkeypatch):
    route_module = importlib.import_module("backend.route.rpa")
    calls = []

    def fake_resolve_region_context(session_id, region_id, *, current_url=None):
        calls.append((session_id, region_id, current_url))
        return None

    monkeypatch.setattr(route_module.rpa_manager, "resolve_region_context", fake_resolve_region_context)

    assert route_module._resolve_chat_region_context(
        "session-1",
        None,
        "https://example.test/a",
    ) is None
    assert calls == []

    with pytest.raises(route_module.HTTPException) as exc_info:
        route_module._resolve_chat_region_context(
            "session-1",
            "missing-region",
            "https://example.test/a",
        )

    assert exc_info.value.status_code == 400
    assert "reselect" in str(exc_info.value.detail).lower()


@pytest.mark.anyio
async def test_chat_resolves_region_before_agent_streams_preview_and_clears_on_success(monkeypatch):
    route_module = importlib.import_module("backend.route.rpa")
    manager = route_module.rpa_manager
    session = RPASession(
        id="session-chat-region",
        user_id="user-1",
        sandbox_session_id="sandbox-1",
        active_tab_id="tab-1",
    )
    manager.sessions[session.id] = session
    page = type("Page", (), {"url": "https://example.test/a"})()
    context = _context("region-chat", url="https://example.test/a")
    calls = []

    def fake_get_page(session_id):
        assert session_id == session.id
        return page

    def fake_resolve_chat_region_context(session_id, region_id, current_url):
        calls.append(("resolve", session_id, region_id, current_url))
        return context.model_dump(mode="json")

    class FakeRecordingRuntimeAgent:
        def __init__(self, *args, **kwargs):
            calls.append(("agent_init", kwargs))

        async def run(self, **kwargs):
            calls.append(("agent_run", kwargs))
            return route_module.RecordingAgentResult(
                success=True,
                message="completed",
            )

    def fake_clear_region_context(session_id, region_id=None):
        calls.append(("clear", session_id, region_id))

    async def fake_resolve_user_model_config(*args, **kwargs):
        return None

    monkeypatch.setattr(manager, "get_page", fake_get_page)
    monkeypatch.setattr(route_module, "_resolve_chat_region_context", fake_resolve_chat_region_context)
    monkeypatch.setattr(route_module, "RecordingRuntimeAgent", FakeRecordingRuntimeAgent)
    monkeypatch.setattr(manager, "clear_region_context", fake_clear_region_context)
    monkeypatch.setattr(route_module, "_resolve_user_model_config", fake_resolve_user_model_config)

    try:
        response = await route_module.chat_with_assistant(
            session.id,
            route_module.ChatRequest(message="read selected table", region_id="region-chat"),
            type("User", (), {"id": "user-1"})(),
        )
        events = await _collect_sse_events(response)
    finally:
        manager.sessions.pop(session.id, None)

    call_names = [call[0] for call in calls]
    assert call_names.index("resolve") < call_names.index("agent_run")
    assert calls[0] == ("resolve", session.id, "region-chat", "https://example.test/a")
    agent_run = next(call for call in calls if call[0] == "agent_run")[1]
    assert agent_run["region_context"] == context.model_dump(mode="json")
    assert ("clear", session.id, "region-chat") in calls

    event_names = [event["event"] for event in events]
    assert event_names.index("region_context") < event_names.index("agent_thought")
    region_event = next(event for event in events if event["event"] == "region_context")
    region_payload = json.loads(region_event["data"])
    assert region_payload == context.preview()
    assert "evidence" not in region_payload
    assert "intersecting_elements" not in region_payload
    assert "local_text" not in region_payload


@pytest.mark.anyio
async def test_chat_agent_aborted_includes_region_preview(monkeypatch):
    route_module = importlib.import_module("backend.route.rpa")
    manager = route_module.rpa_manager
    session = RPASession(
        id="session-chat-region-abort",
        user_id="user-1",
        sandbox_session_id="sandbox-1",
        active_tab_id="tab-1",
    )
    manager.sessions[session.id] = session
    page = type("Page", (), {"url": "https://example.test/a"})()
    context = _context("region-chat", url="https://example.test/a")

    class FakeRecordingRuntimeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, **kwargs):
            return route_module.RecordingAgentResult(
                success=False,
                message="could not complete",
            )

    async def fake_resolve_user_model_config(*args, **kwargs):
        return None

    monkeypatch.setattr(manager, "get_page", lambda _session_id: page)
    monkeypatch.setattr(
        route_module,
        "_resolve_chat_region_context",
        lambda _session_id, _region_id, _current_url: context.model_dump(mode="json"),
    )
    monkeypatch.setattr(route_module, "RecordingRuntimeAgent", FakeRecordingRuntimeAgent)
    monkeypatch.setattr(route_module, "_resolve_user_model_config", fake_resolve_user_model_config)

    try:
        response = await route_module.chat_with_assistant(
            session.id,
            route_module.ChatRequest(message="read selected table", region_id="region-chat"),
            type("User", (), {"id": "user-1"})(),
        )
        events = await _collect_sse_events(response)
    finally:
        manager.sessions.pop(session.id, None)

    aborted_event = next(event for event in events if event["event"] == "agent_aborted")
    aborted_payload = json.loads(aborted_event["data"])
    assert aborted_payload["region"] == context.preview()
