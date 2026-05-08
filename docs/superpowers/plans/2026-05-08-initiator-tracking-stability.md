# Initiator Tracking Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix intermittent initiator tracking failures caused by CDP/Playwright event ordering race conditions.

**Architecture:** Add a deferred re-lookup in `on_response` (CDP evidence must have arrived by then), a JS stack query retry, diagnostic logging at all evidence lookup points, and evidence cleanup to prevent unbounded memory growth.

**Tech Stack:** Python 3.13, asyncio, Playwright, CDP, pytest + pytest-anyio

---

### Task 1: Add `_retry_sync_evidence` method to manager.py

**Files:**
- Modify: `backend/rpa/api_monitor/manager.py:2493-2497` (after `_evidence_for_request`, before `_cleanup_request_evidence`)
- Test: `backend/tests/test_api_monitor_evidence.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api_monitor_evidence.py` at the end of the file:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py::TestRetrySyncEvidence -v`
Expected: FAIL — `AttributeError: 'ApiMonitorSessionManager' object has no attribute '_retry_sync_evidence'`

- [ ] **Step 3: Implement `_retry_sync_evidence`**

In `backend/rpa/api_monitor/manager.py`, add the following method right after `_evidence_for_request` (after line 2493, before `_cleanup_request_evidence`):

```python
    def _retry_sync_evidence(
        self,
        session_id: str,
        request_url: str,
        request_method: str,
        frame_url: str = "",
    ) -> Dict:
        """Second-chance lookup of CDP evidence for requests where the initial
        _evidence_for_request call missed because CDP event arrived late."""
        by_cdp = self._request_evidence.get(session_id, {})
        if not by_cdp:
            logger.debug("[ApiMonitor] Retry evidence: no CDP evidence for session=%s", session_id)
            return {}

        cdp_map = self._cdp_to_pw.get(session_id, {})
        method_upper = request_method.upper()
        for cdp_id, cdp_ev in by_cdp.items():
            if cdp_id in cdp_map:
                continue
            if (cdp_ev.get("_cdp_url") == request_url
                    and cdp_ev.get("_cdp_method") == method_upper):
                if frame_url and cdp_ev.get("frame_url") != frame_url:
                    logger.debug(
                        "[ApiMonitor] Retry evidence: frame_url mismatch for %s (expected=%s got=%s)",
                        request_url[:80], frame_url[:60], cdp_ev.get("frame_url", "")[:60],
                    )
                    continue
                cdp_map[cdp_id] = 0
                result = dict(cdp_ev)
                result.pop("_cdp_url", None)
                result.pop("_cdp_method", None)
                result.pop("_stored_at", None)
                logger.info(
                    "[ApiMonitor] Retry evidence: HIT session=%s url=%s initiator=%s",
                    session_id, request_url[:80], cdp_ev.get("initiator_type", "?"),
                )
                return result
        logger.debug(
            "[ApiMonitor] Retry evidence: MISS session=%s url=%s method=%s (checked %d entries)",
            session_id, request_url[:80], method_upper, len(by_cdp),
        )
        return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py::TestRetrySyncEvidence -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_evidence.py
git commit -m "feat: add _retry_sync_evidence for deferred CDP evidence lookup"
```

---

### Task 2: Wire retry callback into NetworkCaptureEngine

**Files:**
- Modify: `backend/rpa/api_monitor/network_capture.py:163-177` (constructor)
- Modify: `backend/rpa/api_monitor/network_capture.py:309-318` (`on_response` evidence merge)
- Modify: `backend/rpa/api_monitor/manager.py:539` (engine instantiation)
- Test: `backend/tests/test_api_monitor_evidence.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api_monitor_evidence.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py::TestNetworkCaptureRetryEvidence -v`
Expected: FAIL — `TypeError: __init__ got an unexpected keyword argument`

- [ ] **Step 3: Modify NetworkCaptureEngine constructor**

In `backend/rpa/api_monitor/network_capture.py`, replace the `__init__` method (lines 163-177):

```python
    def __init__(
        self,
        page_url_provider: Optional[Callable[[], str]] = None,
        evidence_provider: Optional[Callable[[object], Dict]] = None,
        async_evidence_provider: Optional[Callable[[object], Awaitable[Dict]]] = None,
        evidence_retry_provider: Optional[Callable[[str, str, str], Dict]] = None,
        evidence_cleanup_provider: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._in_flight: Dict[int, Dict] = {}
        self._captured_calls: List[CapturedApiCall] = []
        self._page_url_provider = page_url_provider
        self._evidence_provider = evidence_provider
        self._async_evidence_provider = async_evidence_provider
        self._evidence_retry_provider = evidence_retry_provider
        self._evidence_cleanup_provider = evidence_cleanup_provider
        # Optional callback invoked when a request/response is captured or skipped.
        # Signature: (level: str, message: str) -> None
        self.on_log: Optional[Callable[[str, str], None]] = None
```

- [ ] **Step 4: Run constructor test**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py::TestNetworkCaptureRetryEvidence -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Modify `on_response` to call retry provider and cleanup provider**

In `backend/rpa/api_monitor/network_capture.py`, replace the evidence merge block in `on_response` (lines 309-318). Replace:

```python
        source_evidence: Dict = dict(info.get("source_evidence") or {})
        async_evidence = await self._async_source_evidence(req)
        for key, value in async_evidence.items():
            if key in ("initiator_urls", "js_stack_urls"):
                source_evidence[key] = list(dict.fromkeys([
                    *source_evidence.get(key, []),
                    *value,
                ]))
            elif value and not source_evidence.get(key):
                source_evidence[key] = value
```

with:

```python
        source_evidence: Dict = dict(info.get("source_evidence") or {})

        # Retry CDP evidence lookup if initiator info was missed during on_request
        if not source_evidence.get("initiator_urls") and self._evidence_retry_provider:
            try:
                retry = self._evidence_retry_provider(
                    captured_req.url,
                    captured_req.method,
                    captured_req.frame_url or "",
                )
                if retry.get("initiator_urls"):
                    source_evidence.update(retry)
                    logger.debug(
                        "[ApiMonitor] Retry evidence filled initiator_urls for %s %s",
                        captured_req.method,
                        captured_req.url[:80],
                    )
            except Exception as exc:
                logger.debug("[ApiMonitor] Retry evidence lookup failed: %s", exc)

        async_evidence = await self._async_source_evidence(req)
        for key, value in async_evidence.items():
            if key in ("initiator_urls", "js_stack_urls"):
                source_evidence[key] = list(dict.fromkeys([
                    *source_evidence.get(key, []),
                    *value,
                ]))
            elif value and not source_evidence.get(key):
                source_evidence[key] = value

        # Clean up CDP evidence for this request
        if self._evidence_cleanup_provider:
            try:
                self._evidence_cleanup_provider(captured_req.request_id)
            except Exception:
                pass
```

- [ ] **Step 6: Wire callbacks in manager.py engine instantiation**

In `backend/rpa/api_monitor/manager.py`, replace the `NetworkCaptureEngine` instantiation (around line 539):

```python
        capture = NetworkCaptureEngine(
            page_url_provider=_capture_page_url,
            evidence_provider=lambda request: self._evidence_for_request(session_id, request),
            async_evidence_provider=lambda request: self._async_evidence_for_request(session_id, request),
            evidence_retry_provider=lambda url, method, frame_url="": self._retry_sync_evidence(
                session_id, url, method, frame_url,
            ),
            evidence_cleanup_provider=lambda request_id: self._cleanup_evidence_by_request_id(
                session_id, request_id,
            ),
        )
```

- [ ] **Step 7: Add `_cleanup_evidence_by_request_id` helper to manager.py**

Add right after `_cleanup_request_evidence` in `backend/rpa/api_monitor/manager.py` (after line 2497):

```python
    def _cleanup_evidence_by_request_id(self, session_id: str, pw_request_id: str) -> None:
        """Clean up CDP evidence linked to a Playwright request ID (string form of id())."""
        cdp_map = self._cdp_to_pw.get(session_id, {})
        # Find CDP IDs linked to this pw_request_id
        cdp_ids = [cdp_id for cdp_id, stored_pw_id in cdp_map.items()
                    if str(stored_pw_id) == pw_request_id]
        for cdp_id in cdp_ids:
            self._cleanup_request_evidence(session_id, cdp_id)
```

- [ ] **Step 8: Run all evidence tests**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py -v`
Expected: PASS (all tests)

- [ ] **Step 9: Commit**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/rpa/api_monitor/network_capture.py RpaClaw/backend/tests/test_api_monitor_evidence.py
git commit -m "feat: wire CDP evidence retry lookup and cleanup into capture engine"
```

---

### Task 3: Add JS call stack retry in `_async_evidence_for_request`

**Files:**
- Modify: `backend/rpa/api_monitor/manager.py:2525-2548` (`_async_evidence_for_request`)
- Test: `backend/tests/test_api_monitor_evidence.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api_monitor_evidence.py`:

```python
class TestAsyncEvidenceRetry:
    @pytest.mark.anyio
    async def test_retries_js_stack_on_first_miss(self):
        """When JS stack is empty on first try, should retry once after delay."""
        import asyncio
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()

        page = MagicMock()
        page.url = "https://example.com/page"
        # First call returns None, second returns data
        page.evaluate = AsyncMock(side_effect=[
            None,
            {"stack": "Error\n    at https://example.com/app.js:10:5", "frameUrl": "https://example.com/page"},
        ])
        manager._pages[session_id] = page

        request = MagicMock()
        request.url = "https://example.com/api/data"
        request.method = "GET"
        request.frame = None

        result = await manager._async_evidence_for_request(session_id, request)

        assert page.evaluate.call_count == 2
        assert result["js_stack_urls"] == ["https://example.com/app.js"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py::TestAsyncEvidenceRetry -v`
Expected: FAIL — `page.evaluate.call_count` is 1, not 2 (no retry yet)

- [ ] **Step 3: Implement JS stack retry**

In `backend/rpa/api_monitor/manager.py`, replace `_async_evidence_for_request` (lines 2525-2548):

```python
    async def _async_evidence_for_request(self, session_id: str, request) -> Dict:
        # Resolve the correct page from request's frame, not the active page
        frame = getattr(request, 'frame', None)
        page = self._frame_to_page.get(id(frame)) if frame else None
        page = page or self._pages.get(session_id)
        if not page:
            logger.debug("[ApiMonitor] Async evidence: no page for session=%s", session_id)
            return {}

        js_code = """({url, method}) => {
          const records = window.__apiMonitorStacks || [];
          for (let i = records.length - 1; i >= 0; i--) {
            const item = records[i];
            if (item.url === url && item.method === method.toUpperCase()) return item;
          }
          return null;
        }"""
        args = {"url": request.url, "method": request.method}

        stack_record = None
        for attempt in range(2):
            try:
                stack_record = await page.evaluate(js_code, args)
            except Exception as exc:
                logger.debug("[ApiMonitor] Async evidence: page.evaluate failed (attempt %d): %s", attempt + 1, exc)
                break
            if stack_record:
                break
            if attempt == 0:
                logger.debug(
                    "[ApiMonitor] Async evidence: no stack record for %s %s, retrying in 50ms",
                    request.method, request.url[:80],
                )
                await asyncio.sleep(0.05)

        if not stack_record:
            logger.debug(
                "[ApiMonitor] Async evidence: no stack found for %s %s after retry",
                request.method, request.url[:80],
            )
            return {}
        return {
            "js_stack_urls": _stack_to_urls(stack_record.get("stack") or ""),
            "frame_url": stack_record.get("frameUrl") or page.url,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py::TestAsyncEvidenceRetry -v`
Expected: PASS

- [ ] **Step 5: Run existing async evidence test to confirm no regression**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py::TestAsyncEvidenceCorrectPage -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_evidence.py
git commit -m "feat: add JS stack query retry in _async_evidence_for_request"
```

---

### Task 4: Add diagnostic logging to evidence functions

**Files:**
- Modify: `backend/rpa/api_monitor/manager.py:2466-2493` (`_evidence_for_request`)
- Modify: `backend/rpa/api_monitor/manager.py:2499-2523` (`_install_source_evidence_capture`)

- [ ] **Step 1: Add logging to `_evidence_for_request`**

In `backend/rpa/api_monitor/manager.py`, replace `_evidence_for_request` (lines 2466-2493):

```python
    def _evidence_for_request(self, session_id: str, request) -> Dict:
        pw_id = id(request)
        by_cdp = self._request_evidence.get(session_id, {})
        evidence: Dict = {}

        # Try to find CDP evidence by matching linked request ID
        cdp_map = self._cdp_to_pw.get(session_id, {})
        match_path = "miss"
        for cdp_id, stored_pw_id in cdp_map.items():
            if stored_pw_id == pw_id:
                evidence = dict(by_cdp.get(cdp_id, {}))
                match_path = "linked"
                break

        # Fallback: find by URL+method match among unlinked CDP evidence
        if not evidence:
            request_url = getattr(request, "url", "")
            request_method = (getattr(request, "method", "GET") or "GET").upper()
            for cdp_id, cdp_ev in by_cdp.items():
                if (cdp_ev.get("_cdp_url") == request_url
                        and cdp_ev.get("_cdp_method") == request_method
                        and cdp_id not in cdp_map):
                    evidence = dict(cdp_ev)
                    # Link this CDP entry to the current Playwright request
                    cdp_map[cdp_id] = pw_id
                    match_path = "fallback"
                    break

        evidence.setdefault("frame_url", self.sessions.get(session_id).target_url if self.sessions.get(session_id) else "")
        evidence["action_window_matched"] = self._action_window_matched(session_id)
        logger.debug(
            "[ApiMonitor] Evidence lookup: session=%s path=%s cdp_entries=%d initiator=%s url=%s",
            session_id, match_path, len(by_cdp),
            "found" if evidence.get("initiator_urls") else "empty",
            getattr(request, "url", "")[:80],
        )
        return evidence
```

- [ ] **Step 2: Upgrade logging in `_install_source_evidence_capture`**

In `backend/rpa/api_monitor/manager.py`, replace `_install_source_evidence_capture` (lines 2499-2523):

```python
    async def _install_source_evidence_capture(self, session_id: str, context, page: Page) -> None:
        try:
            cdp = await context.new_cdp_session(page)
            await cdp.send("Network.enable")
            logger.info(
                "[ApiMonitor] CDP evidence capture installed: session=%s page=%s",
                session_id, page.url[:80],
            )

            def on_request_will_be_sent(event: Dict) -> None:
                request = event.get("request") or {}
                url = request.get("url") or ""
                cdp_req_id = event.get("requestId") or ""
                if not url:
                    return
                evidence = _initiator_to_evidence(event.get("initiator") or {})
                evidence["frame_url"] = page.url
                evidence["_cdp_url"] = url
                evidence["_cdp_method"] = (request.get("method") or "GET").upper()
                evidence["_stored_at"] = time.monotonic()
                self._request_evidence.setdefault(session_id, {})[cdp_req_id] = evidence
                logger.debug(
                    "[ApiMonitor] CDP evidence stored: session=%s cdp_id=%s url=%s initiator=%s",
                    session_id, cdp_req_id[:16], url[:80], evidence.get("initiator_type", "?"),
                )

            cdp.on("Network.requestWillBeSent", on_request_will_be_sent)
        except Exception as exc:
            logger.warning(
                "[ApiMonitor] CDP source evidence capture unavailable: session=%s %s",
                session_id, exc,
            )

        try:
            await page.add_init_script(_FETCH_XHR_STACK_CAPTURE_JS)
        except Exception as exc:
            logger.warning(
                "[ApiMonitor] Fetch/XHR stack capture injection failed: session=%s %s",
                session_id, exc,
            )
```

Note: This adds `_stored_at` timestamp to CDP evidence, needed by Task 5 for stale cleanup.

- [ ] **Step 3: Add import for `time` if not already present**

Check the top of `manager.py` for `import time`. If not present, add it. It should already be there (used by `_mark_action` and others).

- [ ] **Step 4: Run all evidence and realtime tests**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py tests/test_api_monitor_realtime_generation.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add RpaClaw/backend/rpa/api_monitor/manager.py
git commit -m "feat: add diagnostic logging to evidence tracking functions"
```

---

### Task 5: Add stale evidence cleanup

**Files:**
- Modify: `backend/rpa/api_monitor/manager.py` (add `_cleanup_stale_evidence`)
- Modify: `backend/rpa/api_monitor/manager.py:757-784` (`_recording_drain_loop`)
- Test: `backend/tests/test_api_monitor_evidence.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api_monitor_evidence.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py::TestStaleEvidenceCleanup -v`
Expected: FAIL — `AttributeError: 'ApiMonitorSessionManager' object has no attribute '_cleanup_stale_evidence'`

- [ ] **Step 3: Implement `_cleanup_stale_evidence`**

Add to `backend/rpa/api_monitor/manager.py`, right after `_cleanup_evidence_by_request_id`:

```python
    def _cleanup_stale_evidence(self, session_id: str, max_age_seconds: float = 30) -> int:
        """Remove CDP evidence entries older than max_age_seconds. Returns count removed."""
        by_cdp = self._request_evidence.get(session_id, {})
        if not by_cdp:
            return 0
        now = time.monotonic()
        stale_ids = [
            cdp_id for cdp_id, ev in by_cdp.items()
            if ev.get("_stored_at") and (now - ev["_stored_at"]) > max_age_seconds
        ]
        for cdp_id in stale_ids:
            self._cleanup_request_evidence(session_id, cdp_id)
        if stale_ids:
            logger.debug(
                "[ApiMonitor] Cleaned %d stale evidence entries for session=%s",
                len(stale_ids), session_id,
            )
        return len(stale_ids)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py::TestStaleEvidenceCleanup -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Wire stale cleanup into `_recording_drain_loop`**

In `backend/rpa/api_monitor/manager.py`, in `_recording_drain_loop`, add the stale cleanup right after `calls = capture.drain_new_calls()` and before `if calls:`. Find this block (around line 773):

```python
            calls = capture.drain_new_calls()
            if calls:
```

Replace with:

```python
            calls = capture.drain_new_calls()
            self._cleanup_stale_evidence(session_id, max_age_seconds=30)
            if calls:
```

- [ ] **Step 6: Run all tests**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py tests/test_api_monitor_realtime_generation.py tests/test_api_monitor_confidence.py tests/test_api_monitor_user_action.py -v`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_evidence.py
git commit -m "feat: add stale evidence cleanup with timeout in drain loop"
```

---

### Task 6: Add on_response evidence summary logging

**Files:**
- Modify: `backend/rpa/api_monitor/network_capture.py:329-341` (end of `on_response`)

- [ ] **Step 1: Add summary log to `on_response`**

In `backend/rpa/api_monitor/network_capture.py`, in `on_response`, after the `self._captured_calls.append(call)` line (around line 329), replace the existing `logger.info` block:

```python
        self._captured_calls.append(call)
        init_count = len(source_evidence.get("initiator_urls", []))
        stack_count = len(source_evidence.get("js_stack_urls", []))
        logger.info(
            "[ApiMonitor] Captured %s %s -> %d (%.0fms) evidence:init=%d,stack=%d",
            captured_req.method,
            captured_req.url[:80],
            response.status,
            duration_ms,
            init_count,
            stack_count,
        )
```

- [ ] **Step 2: Run realtime generation tests**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_realtime_generation.py -v`
Expected: PASS (all tests)

- [ ] **Step 3: Commit**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add RpaClaw/backend/rpa/api_monitor/network_capture.py
git commit -m "feat: add evidence summary to on_response capture log"
```

---

### Task 7: Final integration test and full suite verification

**Files:**
- Test: `backend/tests/test_api_monitor_evidence.py`

- [ ] **Step 1: Write end-to-end retry integration test**

Add to `backend/tests/test_api_monitor_evidence.py`:

```python
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
```

- [ ] **Step 2: Run the full test suite**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py tests/test_api_monitor_realtime_generation.py tests/test_api_monitor_confidence.py tests/test_api_monitor_user_action.py -v`
Expected: PASS (all tests)

- [ ] **Step 3: Commit**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add RpaClaw/backend/tests/test_api_monitor_evidence.py
git commit -m "test: add end-to-end retry integration test for evidence tracking"
```
