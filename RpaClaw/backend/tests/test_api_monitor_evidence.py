"""Tests for evidence collection: request-id keyed storage and frame-to-page mapping."""
import time
from datetime import datetime
from collections import defaultdict
from unittest.mock import MagicMock

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
