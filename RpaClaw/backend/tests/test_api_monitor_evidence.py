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


class TestRetrySyncEvidence:
    def test_retry_finds_unlinked_cdp_evidence_by_url_method(self):
        """Re-lookup should find unlinked CDP evidence matching URL+method."""
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()

        # Store CDP evidence without linking to any Playwright request
        cdp_evidence_store = manager._request_evidence.setdefault(session_id, {})
        cdp_evidence_store["cdp.123"] = {
            "initiator_type": "script",
            "initiator_urls": ["https://example.com/app.js"],
            "frame_url": "https://example.com/page",
            "_cdp_url": "https://example.com/api/data",
            "_cdp_method": "GET",
        }

        result = manager._retry_sync_evidence(
            session_id,
            request_url="https://example.com/api/data",
            request_method="GET",
            frame_url="https://example.com/page",
        )

        assert result["initiator_urls"] == ["https://example.com/app.js"]
        assert "_cdp_url" not in result
        assert "_cdp_method" not in result
        # Should be marked as linked now
        assert "cdp.123" in manager._cdp_to_pw[session_id]

    def test_retry_skips_linked_evidence(self):
        """Re-lookup should skip CDP evidence already linked to a Playwright request."""
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()

        cdp_evidence_store = manager._request_evidence.setdefault(session_id, {})
        cdp_evidence_store["cdp.456"] = {
            "initiator_type": "script",
            "initiator_urls": ["https://example.com/app.js"],
            "frame_url": "https://example.com/page",
            "_cdp_url": "https://example.com/api/data",
            "_cdp_method": "GET",
        }
        # Already linked
        manager._cdp_to_pw[session_id]["cdp.456"] = 9999

        result = manager._retry_sync_evidence(
            session_id,
            request_url="https://example.com/api/data",
            request_method="GET",
            frame_url="https://example.com/page",
        )

        assert result == {}

    def test_retry_filters_by_frame_url(self):
        """Re-lookup should not match evidence from a different page."""
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()

        cdp_evidence_store = manager._request_evidence.setdefault(session_id, {})
        cdp_evidence_store["cdp.789"] = {
            "initiator_type": "script",
            "initiator_urls": ["https://other.com/app.js"],
            "frame_url": "https://other.com/page",
            "_cdp_url": "https://example.com/api/data",
            "_cdp_method": "GET",
        }

        result = manager._retry_sync_evidence(
            session_id,
            request_url="https://example.com/api/data",
            request_method="GET",
            frame_url="https://example.com/my-page",
        )

        assert result == {}

    def test_retry_returns_empty_when_no_evidence(self):
        """Re-lookup should return empty dict when no CDP evidence exists."""
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()

        result = manager._retry_sync_evidence(
            session_id,
            request_url="https://example.com/api/data",
            request_method="GET",
        )

        assert result == {}


class TestAsyncEvidenceRetry:
    @pytest.mark.anyio
    async def test_retries_js_stack_on_first_miss(self):
        """When JS stack is empty on first try, should retry once after delay."""
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()

        page = MagicMock()
        page.url = "https://example.com/page"
        # First call returns None, second returns data
        page.evaluate = AsyncMock(side_effect=[
            None,
            {"stack": "Error\n    at https://example.com/app.js)", "frameUrl": "https://example.com/page"},
        ])
        manager._pages[session_id] = page

        request = MagicMock()
        request.url = "https://example.com/api/data"
        request.method = "GET"
        request.frame = None

        result = await manager._async_evidence_for_request(session_id, request)

        assert page.evaluate.call_count == 2
        print(f"Result: {result}")
        # The second call returned: {"stack": "Error\n    at https://example.com/app.js:10:5", "frameUrl": "https://example.com/page"}
        # So stack_to_urls should extract "https://example.com/app.js"
        assert result["js_stack_urls"] == ["https://example.com/app.js"]


class TestNetworkCaptureRetryEvidence:
    def test_engine_accepts_retry_provider(self):
        """NetworkCaptureEngine should accept evidence_retry_provider."""
        from backend.rpa.api_monitor.network_capture import NetworkCaptureEngine

        retry_called = []

        def mock_retry(url, method, frame_url=""):
            retry_called.append((url, method, frame_url))
            return {"initiator_urls": ["https://app.js"]}

        engine = NetworkCaptureEngine(
            evidence_retry_provider=mock_retry,
        )
        assert engine._evidence_retry_provider is mock_retry

    def test_engine_accepts_cleanup_provider(self):
        """NetworkCaptureEngine should accept evidence_cleanup_provider."""
        from backend.rpa.api_monitor.network_capture import NetworkCaptureEngine

        cleanup_called = []

        def mock_cleanup(request_id):
            cleanup_called.append(request_id)

        engine = NetworkCaptureEngine(
            evidence_cleanup_provider=mock_cleanup,
        )
        assert engine._evidence_cleanup_provider is mock_cleanup


class TestStaleEvidenceCleanup:
    def test_cleanup_removes_old_entries(self):
        """Entries older than max_age should be removed."""
        import time as _time

        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()

        cdp_evidence_store = manager._request_evidence.setdefault(session_id, {})
        now = _time.monotonic()

        # Old entry (60 seconds ago)
        cdp_evidence_store["old.1"] = {
            "initiator_type": "script",
            "_stored_at": now - 60,
        }
        # Recent entry (5 seconds ago)
        cdp_evidence_store["new.1"] = {
            "initiator_type": "script",
            "_stored_at": now - 5,
        }

        removed = manager._cleanup_stale_evidence(session_id, max_age_seconds=30)

        assert removed == 1
        assert "old.1" not in cdp_evidence_store
        assert "new.1" in cdp_evidence_store

    def test_cleanup_handles_missing_timestamp(self):
        """Entries without _stored_at should be kept (backward compat)."""
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()

        cdp_evidence_store = manager._request_evidence.setdefault(session_id, {})
        cdp_evidence_store["no_ts"] = {
            "initiator_type": "script",
        }

        removed = manager._cleanup_stale_evidence(session_id, max_age_seconds=30)

        assert removed == 0
        assert "no_ts" in cdp_evidence_store


class TestEndToEndRetryIntegration:
    def test_evidence_for_request_miss_then_retry_hits(self):
        """Simulates the race: on_request misses, on_response retry finds it."""
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()
        manager.sessions[session_id].target_url = "https://example.com"

        # No CDP evidence yet when on_request fires
        request = MagicMock()
        request.url = "https://example.com/api/data"
        request.method = "GET"
        result1 = manager._evidence_for_request(session_id, request)

        # Should be empty (no initiator_urls)
        assert not result1.get("initiator_urls")

        # Now CDP evidence arrives (late)
        cdp_evidence_store = manager._request_evidence.setdefault(session_id, {})
        cdp_evidence_store["cdp.late"] = {
            "initiator_type": "script",
            "initiator_urls": ["https://example.com/app.js"],
            "frame_url": "https://example.com/page",
            "_cdp_url": "https://example.com/api/data",
            "_cdp_method": "GET",
            "_stored_at": time.monotonic(),
        }

        # on_response retry should find it
        result2 = manager._retry_sync_evidence(
            session_id,
            request_url="https://example.com/api/data",
            request_method="GET",
            frame_url="https://example.com/page",
        )

        assert result2["initiator_urls"] == ["https://example.com/app.js"]
