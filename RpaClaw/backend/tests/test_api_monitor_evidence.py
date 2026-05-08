"""Tests for evidence collection: request-id keyed storage and frame-to-page mapping."""
import time
from datetime import datetime
from collections import defaultdict
from unittest.mock import MagicMock, AsyncMock
import pytest

from backend.rpa.api_monitor.models import CapturedApiCall, CapturedRequest, CapturedResponse
from backend.rpa.api_monitor.manager import ApiMonitorSessionManager


class TestRequestIdKeyedEvidence:
    def test_same_url_different_requests_keep_separate_evidence(self):
        """Two requests to the same URL from different CDP events should not overwrite each other."""
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()

        # Simulate CDP events for two requests to the same URL
        cdp_evidence_store = manager._request_evidence.setdefault(session_id, {})

        # First CDP request
        cdp_req_id_1 = "cdp_req_001"
        manager._cdp_to_pw[session_id][cdp_req_id_1] = 1001
        cdp_evidence_store[cdp_req_id_1] = {
            "initiator_type": "script",
            "initiator_urls": ["https://page-a.com/app.js"],
            "frame_url": "https://page-a.com/list",
        }

        # Second CDP request (same URL, different tab)
        cdp_req_id_2 = "cdp_req_002"
        manager._cdp_to_pw[session_id][cdp_req_id_2] = 1002
        cdp_evidence_store[cdp_req_id_2] = {
            "initiator_type": "script",
            "initiator_urls": ["https://page-b.com/app.js"],
            "frame_url": "https://page-b.com/detail",
        }

        # Evidence for request 1001 should still have page-a info
        assert cdp_evidence_store[cdp_req_id_1]["frame_url"] == "https://page-a.com/list"
        # Evidence for request 1002 should have page-b info
        assert cdp_evidence_store[cdp_req_id_2]["frame_url"] == "https://page-b.com/detail"

    def test_evidence_cleanup_on_response(self):
        """Evidence for a completed request should be cleaned up."""
        manager = ApiMonitorSessionManager()
        session_id = "test_session"

        cdp_evidence_store = manager._request_evidence.setdefault(session_id, {})
        cdp_req_id = "cdp_req_003"
        cdp_evidence_store[cdp_req_id] = {"initiator_type": "script", "initiator_urls": []}
        manager._cdp_to_pw[session_id][cdp_req_id] = 2001

        # Simulate cleanup after response
        manager._cleanup_request_evidence(session_id, cdp_req_id)

        assert cdp_req_id not in cdp_evidence_store
        assert cdp_req_id not in manager._cdp_to_pw.get(session_id, {})


class TestAsyncEvidenceCorrectPage:
    @pytest.mark.anyio
    async def test_queries_correct_page_not_active_page(self):
        """When request comes from frame_b, should query page_b's stacks, not active page_a."""
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()
        manager.sessions[session_id].target_url = "https://active.com"

        page_a = MagicMock()
        page_a.url = "https://active.com/list"
        page_a.evaluate = AsyncMock(return_value=None)

        page_b = MagicMock()
        page_b.url = "https://other.com/detail"
        page_b.evaluate = AsyncMock(return_value={
            "stack": "Error\n    at https://other.com/app.js:10:5",
            "frameUrl": "https://other.com/detail",
        })

        frame_b = MagicMock()
        manager._pages[session_id] = page_a
        manager._frame_to_page[id(frame_b)] = page_b

        request = MagicMock()
        request.url = "https://other.com/api/data"
        request.method = "GET"
        request.frame = frame_b

        result = await manager._async_evidence_for_request(session_id, request)

        # Should have queried page_b, not page_a
        page_b.evaluate.assert_called_once()
        page_a.evaluate.assert_not_called()
        assert result["frame_url"] == "https://other.com/detail"
