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


class TestCumulativeDomContext:
    def test_dom_context_merges_across_upserts(self):
        from backend.rpa.api_monitor.models import ApiMonitorSession, CapturedApiCall, CapturedRequest
        from backend.rpa.api_monitor.manager import ApiMonitorSessionManager

        manager = ApiMonitorSessionManager()
        session = ApiMonitorSession(id="s1", user_id="u1", sandbox_session_id="sb1")
        manager.sessions[session.id] = session

        call = CapturedApiCall(
            request=CapturedRequest(
                request_id="r1", url="https://example.com/api/orders", method="GET",
                headers={}, timestamp=datetime(2026, 1, 1), resource_type="fetch",
            ),
            url_pattern="/api/orders",
        )

        # First upsert with DOM context from page A
        candidate, _ = manager._upsert_generation_candidate(
            session.id, call,
            dom_context={"forms": [{"action": "/search", "inputs": [{"name": "q"}]}], "inputs": [], "buttons": []},
            page_url="https://example.com/list",
            title="List Page",
        )
        assert candidate.capture_page_url == "https://example.com/list"

        # Second upsert with DOM context from page B (same dedup key, new call)
        call2 = CapturedApiCall(
            request=CapturedRequest(
                request_id="r2", url="https://example.com/api/orders", method="GET",
                headers={}, timestamp=datetime(2026, 1, 1), resource_type="fetch",
            ),
            url_pattern="/api/orders",
        )
        candidate2, _ = manager._upsert_generation_candidate(
            session.id, call2,
            dom_context={"forms": [], "inputs": [{"name": "status"}], "buttons": [{"text": "Export"}]},
            page_url="https://example.com/detail",
            title="Detail Page",
        )

        # DOM context should contain merged data
        ctx = candidate2.capture_dom_context
        assert any(f.get("action") == "/search" for f in ctx.get("forms", []))
        assert any(i.get("name") == "status" for i in ctx.get("inputs", []))
        assert any(b.get("text") == "Export" for b in ctx.get("buttons", []))
        # Page URL updated to latest
        assert candidate2.capture_page_url == "https://example.com/detail"


class TestStepMetadata:
    def test_step_metadata_field_exists_and_appends(self):
        from backend.rpa.api_monitor.models import ApiToolGenerationCandidate

        candidate = ApiToolGenerationCandidate(
            session_id="s1",
            dedup_key="GET /api/orders",
            method="GET",
            url_pattern="/api/orders",
        )
        assert candidate.step_metadata == []

        candidate.step_metadata.append({
            "step": 1,
            "action_description": "click Search",
            "page_url": "https://example.com/list",
            "call_count": 2,
            "call_ids": ["c1", "c2"],
        })
        assert len(candidate.step_metadata) == 1
        assert candidate.step_metadata[0]["action_description"] == "click Search"
