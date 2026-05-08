# API Monitor Evidence Awareness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix recording flow's inaccurate initiator identification and action window detection by unifying evidence collection, adding user operation awareness, and enhancing confidence scoring.

**Architecture:** Three-phase approach — first refactor shared evidence infrastructure (request-id keyed storage, frame-to-page mapping), then add JS-injected user action capture for recording flow, finally enhance confidence scoring with action context and cumulative DOM merging.

**Tech Stack:** Python 3.13, Playwright (expose_binding / CDP), Pydantic v2, pytest

**Spec:** `docs/superpowers/specs/2026-05-08-api-monitor-evidence-awareness-design.md`

---

## Phase 1: Unified Evidence Collection Layer

### Task 1: Add `frame_url` to `CapturedRequest` model

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/models.py:20-29`
- Test: `RpaClaw/backend/tests/test_api_monitor_capture.py`

- [ ] **Step 1: Write the failing test**

Add to `RpaClaw/backend/tests/test_api_monitor_capture.py`:

```python
def test_captured_request_has_optional_frame_url():
    from backend.rpa.api_monitor.models import CapturedRequest

    req = CapturedRequest(
        request_id="test",
        url="https://example.com/api/data",
        method="GET",
        headers={},
        timestamp=datetime(2026, 1, 1),
        resource_type="fetch",
        frame_url="https://example.com/page",
    )
    assert req.frame_url == "https://example.com/page"

    req_default = CapturedRequest(
        request_id="test",
        url="https://example.com/api/data",
        method="GET",
        headers={},
        timestamp=datetime(2026, 1, 1),
        resource_type="fetch",
    )
    assert req_default.frame_url is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_capture.py::test_captured_request_has_optional_frame_url -v`
Expected: FAIL — `CapturedRequest` does not have field `frame_url`

- [ ] **Step 3: Add `frame_url` field to `CapturedRequest`**

In `RpaClaw/backend/rpa/api_monitor/models.py`, add `frame_url` field after `resource_type`:

```python
class CapturedRequest(BaseModel):
    request_id: str
    url: str
    method: str
    headers: Dict[str, str]
    body: Optional[str] = None
    content_type: Optional[str] = None
    timestamp: datetime
    resource_type: str  # "xhr" or "fetch"
    frame_url: Optional[str] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_capture.py::test_captured_request_has_optional_frame_url -v`
Expected: PASS

- [ ] **Step 5: Populate `frame_url` in `NetworkCaptureEngine.on_request`**

In `RpaClaw/backend/rpa/api_monitor/network_capture.py`, modify `on_request` to pass `page_url` into `CapturedRequest`:

```python
        captured_req = CapturedRequest(
            request_id=str(id(request)),
            url=request.url,
            method=request.method,
            headers=dict(request.headers),
            body=body,
            content_type=content_type,
            timestamp=datetime.now(),
            resource_type=request.resource_type,
            frame_url=page_url,
        )
```

- [ ] **Step 6: Run all capture tests to check no regressions**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_capture.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/models.py RpaClaw/backend/rpa/api_monitor/network_capture.py RpaClaw/backend/tests/test_api_monitor_capture.py
git commit -m "feat(api-monitor): add frame_url to CapturedRequest, populated at capture time"
```

---

### Task 2: Change `_request_evidence` to CDP-request-ID keyed storage

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:323-331` (__init__)
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:2231-2253` (_install_source_evidence_capture)
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:2224-2229` (_evidence_for_request)
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:456-484` (stop_session cleanup)
- Test: `RpaClaw/backend/tests/test_api_monitor_evidence.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `RpaClaw/backend/tests/test_api_monitor_evidence.py`:

```python
"""Tests for evidence collection: request-id keyed storage and frame-to-page mapping."""
import time
from datetime import datetime
from unittest.mock import MagicMock

from backend.rpa.api_monitor.models import CapturedApiCall, CapturedRequest, CapturedResponse
from backend.rpa.api_monitor.manager import ApiMonitorSessionManager


def _make_request(url: str, method: str = "GET", frame_url: str = ""):
    req = MagicMock()
    req.url = url
    req.method = method
    req.resource_type = "fetch"
    req.headers = {}
    req.post_data = None
    frame = MagicMock()
    frame.url = frame_url
    req.frame = frame
    return req


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


class TestFrameToPageMapping:
    def test_frame_to_page_returns_correct_page(self):
        """_async_evidence_for_request should use frame-to-page mapping."""
        manager = ApiMonitorSessionManager()
        session_id = "test_session"

        page_a = MagicMock()
        page_a.url = "https://page-a.com/list"
        page_b = MagicMock()
        page_b.url = "https://page-b.com/detail"

        frame_a = MagicMock()
        frame_b = MagicMock()

        manager._pages[session_id] = page_a  # active page
        manager._frame_to_page[id(frame_a)] = page_a
        manager._frame_to_page[id(frame_b)] = page_b

        # Request from frame_b should resolve to page_b
        result_page = manager._frame_to_page.get(id(frame_b))
        assert result_page is page_b
        assert result_page.url == "https://page-b.com/detail"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py -v`
Expected: FAIL — `ApiMonitorSessionManager` does not have `_cdp_to_pw` or `_cleanup_request_evidence`

- [ ] **Step 3: Add new instance variables to `__init__`**

In `RpaClaw/backend/rpa/api_monitor/manager.py`, add to `__init__` after `self._request_evidence`:

```python
        self._request_evidence: Dict[str, Dict[str, Dict]] = {}
        self._cdp_to_pw: Dict[str, Dict[str, int]] = defaultdict(dict)
        self._frame_to_page: Dict[int, Page] = {}
        self._action_anchors: Dict[str, List[Dict]] = {}
```

- [ ] **Step 4: Change `_install_source_evidence_capture` to use CDP request ID**

Replace the `on_request_will_be_sent` handler in `_install_source_evidence_capture`:

```python
    async def _install_source_evidence_capture(self, session_id: str, context, page: Page) -> None:
        try:
            cdp = await context.new_cdp_session(page)
            await cdp.send("Network.enable")

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
                self._request_evidence.setdefault(session_id, {})[cdp_req_id] = evidence

            cdp.on("Network.requestWillBeSent", on_request_will_be_sent)
        except Exception as exc:
            logger.debug("[ApiMonitor] CDP source evidence capture unavailable: %s", exc)

        try:
            await page.add_init_script(_FETCH_XHR_STACK_CAPTURE_JS)
        except Exception as exc:
            logger.debug("[ApiMonitor] Fetch/XHR stack capture injection failed: %s", exc)
```

- [ ] **Step 5: Change `_evidence_for_request` to use CDP request ID lookup**

Replace `_evidence_for_request`:

```python
    def _evidence_for_request(self, session_id: str, request) -> Dict:
        pw_id = id(request)
        by_cdp = self._request_evidence.get(session_id, {})
        evidence: Dict = {}

        # Try to find CDP evidence by matching URL+method and linking to this request
        cdp_map = self._cdp_to_pw.get(session_id, {})
        for cdp_id, stored_pw_id in cdp_map.items():
            if stored_pw_id == pw_id:
                evidence = dict(by_cdp.get(cdp_id, {}))
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
                    break

        evidence.setdefault("frame_url", self.sessions.get(session_id).target_url if self.sessions.get(session_id) else "")
        evidence["action_window_matched"] = self._action_window_matched(session_id)
        return evidence
```

- [ ] **Step 6: Add `_cleanup_request_evidence` helper**

Add after `_evidence_for_request`:

```python
    def _cleanup_request_evidence(self, session_id: str, cdp_request_id: str) -> None:
        self._request_evidence.get(session_id, {}).pop(cdp_request_id, None)
        self._cdp_to_pw.get(session_id, {}).pop(cdp_request_id, None)
```

- [ ] **Step 7: Add cleanup to `stop_session`**

In `stop_session`, add cleanup for new dicts after the existing `self._request_evidence.pop(session_id, None)`:

```python
        self._captures.pop(session_id, None)
        self._request_evidence.pop(session_id, None)
        self._cdp_to_pw.pop(session_id, None)
        self._frame_to_page.pop(session_id, None)
        self._action_anchors.pop(session_id, None)
        self._last_action_at.pop(session_id, None)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_evidence.py
git commit -m "feat(api-monitor): change _request_evidence to CDP-request-ID keyed storage"
```

---

### Task 3: Fix `_async_evidence_for_request` to locate correct page via frame mapping

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:2254-2274` (_async_evidence_for_request)
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:1725-1774` (_adopt_page, _on_close)
- Test: `RpaClaw/backend/tests/test_api_monitor_evidence.py`

- [ ] **Step 1: Write the failing test**

Add to `RpaClaw/backend/tests/test_api_monitor_evidence.py`:

```python
class TestAsyncEvidenceCorrectPage:
    async def test_queries_correct_page_not_active_page(self):
        """When request comes from frame_b, should query page_b's stacks, not active page_a."""
        import pytest

        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()
        manager.sessions[session_id].target_url = "https://active.com"

        page_a = MagicMock()
        page_a.url = "https://active.com/list"
        page_a.evaluate = MagicMock(return_value=None)

        page_b = MagicMock()
        page_b.url = "https://other.com/detail"
        page_b.evaluate = MagicMock(return_value={
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py::TestAsyncEvidenceCorrectPage -v`
Expected: FAIL — method queries active page instead of frame-mapped page

- [ ] **Step 3: Update `_adopt_page` to maintain `_frame_to_page` mapping**

In `_adopt_page`, add frame mapping after `page.set_default_navigation_timeout`:

```python
        page.set_default_timeout(PAGE_TIMEOUT_MS)
        page.set_default_navigation_timeout(PAGE_TIMEOUT_MS)

        # Maintain frame-to-page mapping for evidence lookup
        try:
            self._frame_to_page[id(page.main_frame)] = page
            for frame in page.frames:
                self._frame_to_page[id(frame)] = page
        except Exception:
            pass
```

In `_on_close` within `_adopt_page`, add cleanup:

```python
        def _on_close() -> None:
            current_pages = self._session_pages.get(session_id, [])
            if page in current_pages:
                current_pages.remove(page)
            self._listener_pages.discard((session_id, id(page)))
            # Clean up frame-to-page mapping
            try:
                self._frame_to_page.pop(id(page.main_frame), None)
                for frame in page.frames:
                    self._frame_to_page.pop(id(frame), None)
            except Exception:
                pass
            if self._pages.get(session_id) is page:
```

- [ ] **Step 4: Update `_async_evidence_for_request` to use frame-to-page mapping**

Replace `_async_evidence_for_request`:

```python
    async def _async_evidence_for_request(self, session_id: str, request) -> Dict:
        # Resolve the correct page from request's frame, not the active page
        frame = getattr(request, 'frame', None)
        page = self._frame_to_page.get(id(frame)) if frame else None
        page = page or self._pages.get(session_id)
        if not page:
            return {}
        stack_record = await page.evaluate(
            """({url, method}) => {
              const records = window.__apiMonitorStacks || [];
              for (let i = records.length - 1; i >= 0; i--) {
                const item = records[i];
                if (item.url === url && item.method === method.toUpperCase()) return item;
              }
              return null;
            }""",
            {"url": request.url, "method": request.method},
        )
        if not stack_record:
            return {}
        return {
            "js_stack_urls": _stack_to_urls(stack_record.get("stack") or ""),
            "frame_url": stack_record.get("frameUrl") or page.url,
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_evidence.py
git commit -m "feat(api-monitor): resolve correct page from request frame for async evidence"
```

---

### Task 4: Run full Phase 1 regression tests

**Files:** No new files

- [ ] **Step 1: Run all API monitor tests**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_*.py -v`
Expected: All PASS

- [ ] **Step 2: Run confidence tests specifically**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_confidence.py -v`
Expected: All PASS — confidence scoring unchanged

- [ ] **Step 3: Commit if any fixes were needed**

```bash
git add -A
git commit -m "fix(api-monitor): phase 1 regression fixes"
```

---

## Phase 2: Recording Flow Operation Awareness

### Task 5: Write lightweight user action capture JS

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py` (add JS constant)
- Test: `RpaClaw/backend/tests/test_api_monitor_user_action.py` (new file)

- [ ] **Step 1: Write the JS injection script and its test**

Add `_USER_ACTION_CAPTURE_JS` constant in `manager.py`, before the `ApiMonitorSessionManager` class definition (after `_FETCH_XHR_STACK_CAPTURE_JS`):

```python
_USER_ACTION_CAPTURE_JS = r"""
(() => {
  if (window.__apiMonitorActionInstalled) return;
  window.__apiMonitorActionInstalled = true;

  function emit(evt) {
    try {
      const payload = JSON.stringify(evt);
      if (window.__apiMonitorAction) {
        window.__apiMonitorAction(payload);
      }
    } catch (_) {}
  }

  function describeElement(el) {
    const tag = (el.tagName || '').toLowerCase();
    const text = (el.innerText || el.value || el.placeholder || '').trim().slice(0, 80);
    const role = el.getAttribute('role') || '';
    const type = el.getAttribute('type') || '';
    return { tag, text, role, type };
  }

  // Click events
  document.addEventListener('click', (e) => {
    const target = e.target.closest('a, button, [role="button"], input[type="submit"], [onclick]') || e.target;
    emit({
      action: 'click',
      target: describeElement(target),
      url: location.href,
      timestamp: Date.now(),
    });
  }, true);

  // Form submit
  document.addEventListener('submit', (e) => {
    emit({
      action: 'submit',
      target: describeElement(e.target),
      url: location.href,
      timestamp: Date.now(),
    });
  }, true);

  // SPA navigation
  const originalPushState = history.pushState;
  history.pushState = function() {
    emit({ action: 'navigate', url: location.href, timestamp: Date.now() });
    return originalPushState.apply(this, arguments);
  };
  window.addEventListener('popstate', () => {
    emit({ action: 'navigate', url: location.href, timestamp: Date.now() });
  });
})();
"""
```

Create test file `RpaClaw/backend/tests/test_api_monitor_user_action.py`:

```python
"""Tests for user action capture JS and handler."""
import json
import time
from unittest.mock import MagicMock, AsyncMock

import pytest

from backend.rpa.api_monitor.manager import ApiMonitorSessionManager, _USER_ACTION_CAPTURE_JS


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
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_user_action.py -v`
Expected: All PASS (testing constant content)

- [ ] **Step 3: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_user_action.py
git commit -m "feat(api-monitor): add lightweight user action capture JS"
```

---

### Task 6: Add `_handle_user_action` and wire into `create_session`

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py`
- Test: `RpaClaw/backend/tests/test_api_monitor_user_action.py`

- [ ] **Step 1: Write the failing test**

Add to `RpaClaw/backend/tests/test_api_monitor_user_action.py`:

```python
class TestHandleUserAction:
    async def test_click_action_calls_mark_action(self):
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
        await manager._handle_user_action(session_id, evt)

        # Should have called _mark_action
        assert session_id in manager._last_action_at

    async def test_creates_action_anchor(self):
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()

        evt = json.dumps({
            "action": "click",
            "target": {"tag": "button", "text": "Search", "role": "", "type": ""},
            "url": "https://example.com/list",
            "timestamp": int(time.time() * 1000),
        })
        await manager._handle_user_action(session_id, evt)

        anchors = manager._action_anchors.get(session_id, [])
        assert len(anchors) == 1
        assert anchors[0]["action"] == "click"
        assert anchors[0]["description"] == "Search"
        assert anchors[0]["page_url"] == "https://example.com/list"
        assert anchors[0]["call_ids"] == []

    async def test_ignores_irrelevant_actions(self):
        manager = ApiMonitorSessionManager()
        session_id = "test_session"
        manager.sessions[session_id] = MagicMock()

        evt = json.dumps({
            "action": "scroll",
            "url": "https://example.com/list",
            "timestamp": int(time.time() * 1000),
        })
        await manager._handle_user_action(session_id, evt)

        assert session_id not in manager._last_action_at
        assert not manager._action_anchors.get(session_id, [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_user_action.py::TestHandleUserAction -v`
Expected: FAIL — `_handle_user_action` not defined

- [ ] **Step 3: Add `_handle_user_action` method**

Add to `ApiMonitorSessionManager`, after `_mark_action`:

```python
    async def _handle_user_action(self, session_id: str, event_json: str) -> None:
        try:
            evt = json.loads(event_json)
        except (json.JSONDecodeError, TypeError):
            return

        action_type = evt.get("action", "")
        if action_type not in ("click", "fill", "press", "navigate", "submit"):
            return

        self._mark_action(session_id)

        target = evt.get("target") or {}
        self._action_anchors.setdefault(session_id, []).append({
            "action": action_type,
            "description": (target.get("text") or target.get("tag") or "")[:80],
            "timestamp": time.monotonic(),
            "page_url": evt.get("url", ""),
            "frame_path": evt.get("frame_path", []),
            "call_ids": [],
        })

        # Cap anchors at 100 to bound memory
        anchors = self._action_anchors.get(session_id, [])
        if len(anchors) > 100:
            self._action_anchors[session_id] = anchors[-100:]

        logger.info(
            "[ApiMonitor] User action for session %s: %s %s",
            session_id, action_type, (target.get("text") or "")[:40],
        )
```

- [ ] **Step 4: Add `_install_user_action_capture` method**

Add after `_handle_user_action`:

```python
    async def _install_user_action_capture(self, session_id: str, context) -> None:
        async def on_user_action(source, event_json: str):
            await self._handle_user_action(session_id, event_json)

        try:
            await context.expose_binding("__apiMonitorAction", on_user_action, handle=False)
            await context.add_init_script(_USER_ACTION_CAPTURE_JS)
        except Exception as exc:
            logger.debug("[ApiMonitor] User action capture install failed: %s", exc)
```

- [ ] **Step 5: Wire into `create_session`**

In `create_session`, after `context = await browser.new_context(**get_context_kwargs())` and before `page = await context.new_page()`, add:

```python
        context = await browser.new_context(**get_context_kwargs())
        await context.grant_permissions(["clipboard-read", "clipboard-write"])

        # Install user action capture for recording flow operation awareness
        await self._install_user_action_capture(session_id, context)

        page = await context.new_page()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_user_action.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_user_action.py
git commit -m "feat(api-monitor): add user action capture handler and install on session creation"
```

---

### Task 7: Wire `_recording_drain_loop` with action anchors

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:636-668` (_recording_drain_loop)
- Test: `RpaClaw/backend/tests/test_api_monitor_user_action.py`

- [ ] **Step 1: Write the failing test**

Add to `RpaClaw/backend/tests/test_api_monitor_user_action.py`:

```python
class TestRecordingDrainWithAnchors:
    async def test_drain_links_calls_to_last_anchor(self):
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
        processed_calls = []
        original_process = manager._process_captured_calls_for_generation

        async def mock_process(sid, calls, **kwargs):
            processed_calls.extend(calls)
            return []
        manager._process_captured_calls_for_generation = mock_process

        # Run one iteration of drain loop
        import asyncio
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
```

Note: These imports must be at the top of the test file alongside existing ones:

```python
from datetime import datetime
from backend.rpa.api_monitor.models import CapturedApiCall, CapturedRequest
```

Ensure the full import block at top of `test_api_monitor_user_action.py` is:

```python
"""Tests for user action capture JS and handler."""
import asyncio
import json
import time
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

import pytest

from backend.rpa.api_monitor.manager import ApiMonitorSessionManager, _USER_ACTION_CAPTURE_JS
from backend.rpa.api_monitor.models import CapturedApiCall, CapturedRequest
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_user_action.py::TestRecordingDrainWithAnchors -v`
Expected: FAIL — `call_ids` is still empty (anchor not updated)

- [ ] **Step 3: Modify `_recording_drain_loop` to link calls to anchors**

Replace `_recording_drain_loop`:

```python
    async def _recording_drain_loop(
        self,
        session_id: str,
        *,
        model_config: Optional[Dict] = None,
        interval_s: float = 1.0,
    ) -> None:
        try:
            while True:
                await asyncio.sleep(interval_s)
                session = self.sessions.get(session_id)
                if session is None or session.status != "recording":
                    return
                capture = self._captures.get(session_id)
                if not capture:
                    continue
                calls = capture.drain_new_calls()
                if calls:
                    # Link calls to the most recent action anchor
                    anchors = self._action_anchors.get(session_id)
                    if anchors:
                        last_anchor = anchors[-1]
                        last_anchor["call_ids"].extend(call.id for call in calls)

                    action_ctx = self._last_action_context(session_id)
                    processing_task = asyncio.create_task(
                        self._process_captured_calls_for_generation(
                            session_id,
                            calls,
                            action_context=action_ctx,
                            model_config=model_config,
                        )
                    )
                    try:
                        await asyncio.shield(processing_task)
                    except asyncio.CancelledError:
                        await processing_task
                        raise
        except asyncio.CancelledError:
            raise
```

Add `_last_action_context` helper after `_handle_user_action`:

```python
    def _last_action_context(self, session_id: str) -> Optional[Dict]:
        anchors = self._action_anchors.get(session_id)
        if not anchors:
            return None
        last = anchors[-1]
        return {
            "action": last.get("action", ""),
            "description": last.get("description", ""),
            "page_url": last.get("page_url", ""),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_user_action.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_user_action.py
git commit -m "feat(api-monitor): wire recording drain loop with action anchors"
```

---

## Phase 3: Confidence & Analysis Optimization

### Task 8: Add `action_context` support to confidence scoring

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/confidence.py:57-155` (score_api_candidate)
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:294-304` (_apply_confidence_to_tool)
- Test: `RpaClaw/backend/tests/test_api_monitor_confidence.py`

- [ ] **Step 1: Write the failing test**

Add to `RpaClaw/backend/tests/test_api_monitor_confidence.py`:

```python
def test_action_context_adds_confirmed_user_action_bonus():
    call = _call(
        "https://example.com/api/orders",
        initiator_urls=["https://example.com/app/assets/main.js"],
    )
    result = score_api_candidate(
        [call],
        action_context={"action": "click", "description": "Search"},
    )

    assert result.breakdown["confirmed_user_action"] == 15
    assert "由用户操作确认触发: Search" in result.reasons
    assert result.score == 100  # cap at 100


def test_action_context_on_low_confidence_still_helps():
    call = _call(
        "https://example.com/api/config",
        action_window_matched=False,
        initiator_urls=[],
        js_stack_urls=[],
    )
    result = score_api_candidate(
        [call],
        action_context={"action": "click", "description": "Settings"},
    )

    assert result.breakdown["confirmed_user_action"] == 15
    assert "由用户操作确认触发: Settings" in result.reasons
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_confidence.py::test_action_context_adds_confirmed_user_action_bonus -v`
Expected: FAIL — `score_api_candidate` does not accept `action_context` parameter

- [ ] **Step 3: Update `score_api_candidate` to accept and use `action_context`**

Modify `confidence.py`:

```python
def score_api_candidate(
    calls: list[CapturedApiCall],
    *,
    action_context: dict | None = None,
) -> ConfidenceResult:
    first = calls[0]
    evidence = _merge_evidence(calls)
    reasons: list[str] = []
    breakdown: dict[str, int] = {}

    path = urlparse(first.request.url).path.lower()
    body = (first.response.body if first.response else "") or ""
    content_type = ((first.response.content_type if first.response else "") or "").lower()
    action_window_matched = bool(evidence.get("action_window_matched"))
    source_urls = [
        *evidence.get("initiator_urls", []),
        *evidence.get("js_stack_urls", []),
    ]

    has_source = bool(source_urls)
    injected_source = any(_contains_marker(url, INJECTED_SOURCE_MARKERS) for url in source_urls)
    noise_path = any(marker in path for marker in NOISE_PATH_MARKERS)
    business_path = any(marker in path for marker in BUSINESS_PATH_MARKERS)
    json_response = "json" in content_type or body.strip().startswith(("{", "["))
    score = 0

    if action_window_matched:
        score += 30
        breakdown["action_window"] = 30
        reasons.append("由用户动作触发")
    else:
        breakdown["action_window"] = 0

    if action_context:
        score += 15
        breakdown["confirmed_user_action"] = 15
        desc = action_context.get("description", "")
        reasons.append(f"由用户操作确认触发: {desc}" if desc else "由用户操作确认触发")

    if business_path:
        score += 25
        breakdown["business_path"] = 25
        reasons.append("路径疑似业务接口")
    else:
        breakdown["business_path"] = 0

    if json_response:
        score += 20
        breakdown["json_response"] = 20
        reasons.append("响应疑似 JSON 业务数据")
    else:
        breakdown["json_response"] = 0

    if has_source:
        score += 15
        breakdown["has_source"] = 15
        if injected_source:
            reasons.append("来源疑似注入脚本或扩展")
        else:
            reasons.append("由页面业务脚本发起")
    else:
        score -= 10
        breakdown["has_source"] = -10
        reasons.append("缺少 initiator 或 JS 调用栈")

    richness_score, richness_reason = _score_response_richness(body)
    score += richness_score
    breakdown["response_richness"] = richness_score
    if richness_reason:
        reasons.append(richness_reason)

    if injected_source:
        score -= 40
        breakdown["injected_source"] = -40

    if noise_path:
        score -= 30
        breakdown["noise_path"] = -30
        reasons.append("路径疑似配置或后台请求")

    if not action_window_matched:
        score -= 20
        breakdown["no_action_window"] = -20
        reasons.append("不在动作时间窗口内")

    score = max(0, min(100, score))

    if score >= 80:
        confidence: ConfidenceLevel = "high"
        selected = True
    elif score >= 40:
        confidence = "medium"
        selected = False
    else:
        confidence = "low"
        selected = False

    evidence_summary = dict(evidence)
    evidence_summary["score"] = score
    evidence_summary["breakdown"] = breakdown

    return ConfidenceResult(
        confidence=confidence,
        selected=selected,
        reasons=_dedupe(reasons),
        evidence_summary=evidence_summary,
        score=score,
        breakdown=breakdown,
    )
```

- [ ] **Step 4: Update `_apply_confidence_to_tool` to pass through `action_context`**

In `manager.py`, modify `_apply_confidence_to_tool`:

```python
def _apply_confidence_to_tool(
    tool: ApiToolDefinition,
    calls: List[CapturedApiCall],
    *,
    action_context: Optional[Dict] = None,
) -> ApiToolDefinition:
    result = score_api_candidate(calls, action_context=action_context)
    tool.confidence = result.confidence
    tool.score = result.score
    tool.selected = result.selected
    tool.confidence_reasons = result.reasons
    tool.source_evidence = result.evidence_summary
    return tool
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_confidence.py -v`
Expected: All PASS (old tests pass because `action_context` defaults to None)

- [ ] **Step 6: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/confidence.py RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_confidence.py
git commit -m "feat(api-monitor): add action_context support to confidence scoring"
```

---

### Task 9: Change DOM context to cumulative merge and add `step_metadata`

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/models.py:90-108` (ApiToolGenerationCandidate)
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:1794-1841` (_upsert_generation_candidate)
- Test: `RpaClaw/backend/tests/test_api_monitor_evidence.py`

- [ ] **Step 1: Write the failing test**

Add to `RpaClaw/backend/tests/test_api_monitor_evidence.py`:

```python
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
    def test_step_metadata_appends_on_upsert(self):
        from backend.rpa.api_monitor.models import ApiMonitorSession, CapturedApiCall, CapturedRequest, ApiToolGenerationCandidate

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py::TestCumulativeDomContext -v`
Expected: FAIL — DOM context only keeps first observation

- [ ] **Step 3: Add `step_metadata` field to `ApiToolGenerationCandidate`**

In `models.py`, add field to `ApiToolGenerationCandidate`:

```python
class ApiToolGenerationCandidate(BaseModel):
    id: str = Field(default_factory=_gen_id)
    session_id: str
    dedup_key: str
    method: str
    url_pattern: str
    source_call_ids: List[str] = Field(default_factory=list)
    sample_call_ids: List[str] = Field(default_factory=list)
    status: GenerationStatus = "pending"
    tool_id: Optional[str] = None
    error: str = ""
    retry_after: Optional[datetime] = None
    attempts: int = 0
    capture_dom_context: Dict = Field(default_factory=dict)
    capture_page_url: str = ""
    capture_title: str = ""
    capture_dom_digest: str = ""
    step_metadata: List[Dict] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
```

- [ ] **Step 4: Update `_upsert_generation_candidate` to merge DOM context cumulatively**

Replace the DOM context update block in `_upsert_generation_candidate`:

```python
        if dom_context:
            candidate.capture_dom_context = _merge_dom_context(
                candidate.capture_dom_context or {},
                dom_context,
            )
            if page_url:
                candidate.capture_page_url = page_url
            if title:
                candidate.capture_title = title
            if dom_digest:
                candidate.capture_dom_digest = dom_digest
```

Add `_merge_dom_context` as a module-level helper in `manager.py`, before the `ApiMonitorSessionManager` class:

```python
def _merge_dom_context(existing: Dict, new: Dict) -> Dict:
    """Merge two DOM context snapshots, deduplicating by key fields."""
    if not existing:
        return dict(new)
    if not new:
        return dict(existing)

    result: Dict = {}

    # Merge forms by action URL
    existing_forms = {f.get("action", ""): f for f in existing.get("forms", []) if f.get("action")}
    for f in new.get("forms", []):
        action = f.get("action", "")
        if action and action not in existing_forms:
            existing_forms[action] = f
    result["forms"] = list(existing_forms.values())

    # Merge inputs by name
    seen_names: set = set()
    merged_inputs = []
    for inp in [*existing.get("inputs", []), *new.get("inputs", [])]:
        name = inp.get("name") or inp.get("id") or ""
        if name not in seen_names:
            seen_names.add(name)
            merged_inputs.append(inp)
    result["inputs"] = merged_inputs

    # Merge buttons by text
    seen_texts: set = set()
    merged_buttons = []
    for btn in [*existing.get("buttons", []), *new.get("buttons", [])]:
        text = btn.get("text", "")
        if text not in seen_texts:
            seen_texts.add(text)
            merged_buttons.append(btn)
    result["buttons"] = merged_buttons

    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_evidence.py::TestCumulativeDomContext tests/test_api_monitor_evidence.py::TestStepMetadata -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/models.py RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_evidence.py
git commit -m "feat(api-monitor): cumulative DOM context merge and step_metadata field"
```

---

### Task 10: Pass `action_context` from analysis/recording flows and add step context to tool generation prompt

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:2074-2119` (_process_captured_calls_for_generation)
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:1280-1294` (directed analysis step processing)
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:1932-1941` (_calls_for_candidate)
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:294-304` (_apply_confidence_to_tool calls)
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:1951-2055` (_generate_tool_for_candidate)
- Modify: `RpaClaw/backend/rpa/api_monitor/llm_analyzer.py:102-112` (TOOL_GEN_USER prompt)

- [ ] **Step 1: Add `action_context` parameter to `_process_captured_calls_for_generation`**

Update the signature and pass through to `_upsert_generation_candidate` and `_apply_confidence_to_tool`:

```python
    async def _process_captured_calls_for_generation(
        self,
        session_id: str,
        calls: list[CapturedApiCall],
        *,
        dom_context: dict | None = None,
        page_url: str = "",
        title: str = "",
        dom_digest: str = "",
        action_context: Optional[Dict] = None,
        model_config: Optional[Dict] = None,
    ) -> list[ApiToolGenerationCandidate]:
```

The rest of the method body stays the same — `action_context` is stored on the candidate via `_upsert_generation_candidate`:

```python
        for call in generation_calls:
            candidate, _created = self._upsert_generation_candidate(
                session_id,
                call,
                dom_context=dom_context,
                page_url=page_url,
                title=title,
                dom_digest=dom_digest,
                action_context=action_context,
            )
```

- [ ] **Step 2: Update `_upsert_generation_candidate` to accept and store `action_context`**

Add `action_context` parameter:

```python
    def _upsert_generation_candidate(
        self,
        session_id: str,
        call: CapturedApiCall,
        *,
        dom_context: dict | None = None,
        page_url: str = "",
        title: str = "",
        dom_digest: str = "",
        action_context: Optional[Dict] = None,
    ) -> tuple[ApiToolGenerationCandidate, bool]:
```

After the DOM context merge block, append step_metadata:

```python
        if action_context and added_call:
            candidate.step_metadata.append({
                "action": action_context.get("action", ""),
                "action_description": action_context.get("description", ""),
                "page_url": page_url or action_context.get("page_url", ""),
                "call_count": 1,
                "call_ids": [call.id],
            })
```

- [ ] **Step 3: Update `_generate_tool_for_candidate` to pass `action_context`**

In `_generate_tool_for_candidate`, pass `action_context` to `_apply_confidence_to_tool`:

```python
        tool = _apply_confidence_to_tool(
            tool, samples,
            action_context=candidate.step_metadata[-1] if candidate.step_metadata else None,
        )
```

And build step context for the LLM prompt. In the call to `generate_tool_definition`, pass step context:

```python
        step_context = ""
        if candidate.step_metadata:
            lines = []
            for sm in candidate.step_metadata[:5]:
                lines.append(
                    f"- 操作 '{sm.get('action_description', '')}' "
                    f"在页面 {sm.get('page_url', '')} 触发了 {sm.get('call_count', 0)} 次调用"
                )
            step_context = "\n此 API 在以下操作中被观察到:\n" + "\n".join(lines)

        yaml_def = await generate_tool_definition(
            method=candidate.method,
            url_pattern=candidate.url_pattern,
            samples=samples,
            page_context=candidate.capture_page_url or session.target_url or "",
            dom_context=dom_context,
            step_context=step_context,
            model_config=model_config,
        )
```

- [ ] **Step 4: Update `generate_tool_definition` in `llm_analyzer.py`**

Add `step_context` parameter:

```python
async def generate_tool_definition(
    method: str,
    url_pattern: str,
    samples: List[CapturedApiCall],
    page_context: str = "",
    dom_context: str = "",
    step_context: str = "",
    model_config: Optional[Dict] = None,
) -> str:
```

Update `TOOL_GEN_USER` prompt to include step context:

```python
TOOL_GEN_USER = """\
Endpoint: {method} {url_pattern}
Page context: {page_context}

{dom_context_section}

{step_context_section}

API call samples:
{samples_json}

Generate the YAML tool definition. Use DOM context to infer parameters not present in samples.
"""
```

In the format call:

```python
    step_context_section = ""
    if step_context:
        step_context_section = f"Observed context:{step_context}"

    user_prompt = TOOL_GEN_USER.format(
        method=method,
        url_pattern=url_pattern,
        page_context=page_context or "Unknown page",
        dom_context_section=dom_context_section,
        step_context_section=step_context_section,
        samples_json=json.dumps(sample_data, indent=2, ensure_ascii=False),
    )
```

- [ ] **Step 5: Update directed analysis to pass `action_context`**

In `analyze_directed_page`, when processing step_calls after directed action execution (around line 1286):

```python
                    await self._process_captured_calls_for_generation(
                        session_id,
                        step_calls,
                        dom_context=observation.get("raw_snapshot"),
                        page_url=observation.get("url", ""),
                        title=observation.get("title", ""),
                        dom_digest=observation.get("dom_digest", ""),
                        action_context={
                            "action": describe_action(allowed_action),
                            "description": allowed_action.description,
                            "page_url": observation.get("url", ""),
                        },
                        model_config=model_config,
                    )
```

- [ ] **Step 6: Update `_probe_element` to pass `action_context`**

In `analyze_page`, when processing `probed_calls`:

```python
                    await self._process_captured_calls_for_generation(
                        session_id,
                        probed_calls,
                        action_context={
                            "action": "probe",
                            "description": f"probe {elem.get('tag', '')} {elem.get('text', '')[:30]}",
                        },
                        model_config=model_config,
                    )
```

- [ ] **Step 7: Run all API monitor tests**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_*.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/rpa/api_monitor/llm_analyzer.py
git commit -m "feat(api-monitor): pass action_context through analysis/recording flows, add step context to tool generation"
```

---

### Task 11: Final integration test and cleanup

**Files:** No new files

- [ ] **Step 1: Run full test suite**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_*.py -v`
Expected: All PASS

- [ ] **Step 2: Verify no regressions in existing confidence tests**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_confidence.py -v`
Expected: All PASS — existing tests unchanged because `action_context` defaults to None

- [ ] **Step 3: Verify capture tests pass**

Run: `cd RpaClaw/backend && uv run pytest tests/test_api_monitor_capture.py -v`
Expected: All PASS

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore(api-monitor): evidence awareness implementation complete"
```
