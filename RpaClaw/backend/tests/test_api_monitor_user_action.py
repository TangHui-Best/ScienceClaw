"""Tests for user action capture JS and handler."""
import asyncio
import json
import time
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

import pytest

from backend.rpa.api_monitor.manager import ApiMonitorSessionManager, _USER_ACTION_CAPTURE_JS
from backend.rpa.api_monitor.models import CapturedApiCall, CapturedRequest


class TestUserActionCaptureJS:
    def test_js_contains_binding_name(self):
        assert "__apiMonitorAction" in _USER_ACTION_CAPTURE_JS

    def test_js_captures_click(self):
        assert "click" in _USER_ACTION_CAPTURE_JS
        assert "describeElement" in _USER_ACTION_CAPTURE_JS

    def test_js_captures_submit(self):
        assert "submit" in _USER_ACTION_CAPTURE_JS

    def test_js_captures_navigate(self):
        assert "pushState" in _USER_ACTION_CAPTURE_JS
        assert "popstate" in _USER_ACTION_CAPTURE_JS

    def test_js_guards_against_double_install(self):
        assert "__apiMonitorActionInstalled" in _USER_ACTION_CAPTURE_JS


class TestHandleUserAction:
    def test_click_action_calls_mark_action(self):
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()

        # _last_action_at should be empty before
        assert session_id not in manager._last_action_at

        evt = json.dumps({
            "action": "click",
            "target": {"tag": "button", "text": "Search", "role": "", "type": ""},
            "url": "https://example.com/list",
            "timestamp": int(time.time() * 1000),
        })
        asyncio.run(manager._handle_user_action(session_id, evt))

        # Should have called _mark_action
        assert session_id in manager._last_action_at

    def test_creates_action_anchor(self):
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()

        evt = json.dumps({
            "action": "click",
            "target": {"tag": "button", "text": "Search", "role": "", "type": ""},
            "url": "https://example.com/list",
            "timestamp": int(time.time() * 1000),
        })
        asyncio.run(manager._handle_user_action(session_id, evt))

        anchors = manager._action_anchors.get(session_id, [])
        assert len(anchors) == 1
        assert anchors[0]["action"] == "click"
        assert anchors[0]["description"] == "Search"
        assert anchors[0]["page_url"] == "https://example.com/list"
        assert anchors[0]["call_ids"] == []

    def test_ignores_irrelevant_actions(self):
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()

        evt = json.dumps({
            "action": "scroll",
            "url": "https://example.com/list",
            "timestamp": int(time.time() * 1000),
        })
        asyncio.run(manager._handle_user_action(session_id, evt))

        assert session_id not in manager._last_action_at
        assert not manager._action_anchors.get(session_id, [])


class TestRecordingDrainWithAnchors:
    def test_drain_links_calls_to_last_anchor(self):
        async def _run():
            manager = ApiMonitorSessionManager()
            session_id = "test_session"

            # Set up session with recording status
            session = MagicMock()
            session.status = "recording"
            manager.sessions[session_id] = session

            # Pre-create an action anchor
            manager._action_anchors[session_id] = [{
                "action": "click",
                "description": "Search",
                "timestamp": time.monotonic(),
                "page_url": "https://example.com/list",
                "call_ids": [],
            }]

            # Create mock capture with one call
            call = CapturedApiCall(
                request=CapturedRequest(
                    request_id="test",
                    url="https://example.com/api/search?q=test",
                    method="GET",
                    headers={},
                    timestamp=datetime(2026, 1, 1),
                    resource_type="fetch",
                ),
            )
            capture = MagicMock()
            capture.drain_new_calls = MagicMock(return_value=[call])
            manager._captures[session_id] = capture

            # Mock _process_captured_calls_for_generation to avoid LLM calls
            async def mock_process(sid, calls, **kwargs):
                return []

            manager._process_captured_calls_for_generation = mock_process

            # Run one iteration of drain loop
            task = asyncio.create_task(manager._recording_drain_loop(session_id, interval_s=0.05))
            await asyncio.sleep(0.15)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            # Verify call was linked to the anchor
            anchors = manager._action_anchors[session_id]
            assert len(anchors) == 1
            assert call.id in anchors[0]["call_ids"]

        asyncio.run(_run())
