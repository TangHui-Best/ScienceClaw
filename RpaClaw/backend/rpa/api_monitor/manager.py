"""Session manager for API Monitor.

Manages browser contexts, network capture, recording, and
orchestrates the automatic page analysis workflow.
"""

import asyncio
import hashlib
import json
import logging
import uuid
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import AsyncGenerator, Callable, Dict, List, Optional, Set

from playwright.async_api import BrowserContext, Page

from backend.rpa.cdp_connector import get_cdp_connector
from backend.rpa.playwright_security import get_context_kwargs
from backend.rpa.screencast import SessionScreencastController

from backend.rpa.assistant_runtime import build_page_snapshot
from backend.rpa.frame_selectors import build_frame_path
from backend.rpa.snapshot_compression import compact_recording_snapshot

from .analysis_modes import AnalysisBusinessSafety
from .directed_analyzer import (
    build_directed_step_decision,
    execute_directed_action,
    filter_action_for_business_safety,
    describe_action,
    describe_locator_code,
)
from .directed_trace import (
    build_directed_retry_context,
    captured_call_ids,
    decision_snapshot,
    directed_action_fingerprint,
    execution_snapshot,
    observation_from_payload,
    retry_guard_skip_reason,
)

from .confidence import dedup_key_for_tool, score_api_candidate, summarize_rejection_reasons
from .intent_filter import filter_by_intent
from .intent_pruner import IntentPruneCandidate, IntentPruneItem, IntentPruneResult, prune_candidates_by_intent
from .llm_analyzer import analyze_elements, generate_tool_definition
from .models import ApiMonitorSession, ApiToolDefinition, ApiToolGenerationCandidate, CapturedApiCall, DirectedAnalysisTrace
from .network_capture import NetworkCaptureEngine, dedup_key

logger = logging.getLogger(__name__)

PAGE_TIMEOUT_MS = 60_000
DOM_CONTEXT_SCAN_TIMEOUT_S = 2.0
INTENT_PRUNE_DEBOUNCE_SECONDS = 3.0
INTENT_PRUNE_MAX_BATCH_SIZE = 8
INTENT_PRUNE_TIMEOUT_S = 20.0
INTENT_PRUNE_MAX_RETRIES = 2
INTENT_PRUNE_RETRY_BASE_DELAY_S = 2.0
INTENT_PRUNE_CONCURRENCY = 2
INTENT_PRUNE_CHUNK_SIZE = 6

# ── Interactive element scanner ──────────────────────────────────────

_SCAN_INTERACTIVE_JS = """
() => {
    const interactiveSelectors = [
        'a[href]',
        'button',
        'input[type="submit"]',
        'input[type="button"]',
        'input[type="text"]',
        'input[type="search"]',
        'input[type="email"]',
        'input[type="number"]',
        'input[type="tel"]',
        'input[type="url"]',
        'select',
        'textarea',
        '[role="button"]',
        '[role="link"]',
        '[role="tab"]',
        '[role="menuitem"]',
        '[role="option"]',
        '[role="switch"]',
        '[role="checkbox"]',
        '[role="radio"]',
        '[onclick]',
        '[data-action]',
    ];
    const all = document.querySelectorAll(interactiveSelectors.join(', '));
    const results = [];
    const seen = new Set();

    for (const el of all) {
        if (seen.has(el)) continue;
        seen.add(el);

        // Skip hidden / disabled elements
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
        if (el.disabled) continue;

        // Compute a simple descriptor
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) continue;

        const tag = el.tagName.toLowerCase();
        const text = (el.innerText || el.value || el.placeholder || '').trim().slice(0, 80);
        const href = el.getAttribute('href') || '';
        const role = el.getAttribute('role') || '';
        const type = el.getAttribute('type') || '';
        const name = el.getAttribute('name') || '';
        const ariaLabel = el.getAttribute('aria-label') || '';

        results.push({
            index: results.length,
            tag,
            text,
            href,
            role,
            type,
            name,
            ariaLabel,
            rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
        });
    }
    return results;
}
"""

# ── DOM context scanner (for LLM parameter inference) ────────────────

_SCAN_DOM_CONTEXT_JS = """
() => {
    const result = { forms: [], inputs: [], buttons: [] };

    // Scan all forms
    for (const form of document.querySelectorAll('form')) {
        const inputs = [];
        for (const input of form.querySelectorAll('input, select, textarea')) {
            if (input.type === 'hidden' || input.type === 'submit' || input.type === 'button') continue;
            let label = form.querySelector('label[for="' + input.id + '"]');
            if (!label) {
                const container = input.closest('.search-item, .form-group, .field, .input-group, .mb-3, .mb-4');
                if (container) label = container.querySelector('label');
            }
            if (!label && input.previousElementSibling && input.previousElementSibling.tagName === 'LABEL') {
                label = input.previousElementSibling;
            }
            const entry = {
                name: input.name || input.id || '',
                type: input.type || input.tagName.toLowerCase(),
                label: label ? label.textContent.trim() : '',
                placeholder: input.placeholder || '',
                required: input.required || false,
            };
            if (input.tagName === 'SELECT') {
                entry.type = 'select';
                entry.options = [...input.options].map(o => ({ value: o.value, text: o.textContent.trim() }));
            }
            inputs.push(entry);
        }
        result.forms.push({
            action: form.action || '',
            method: (form.method || 'GET').toUpperCase(),
            inputs,
            submitText: form.querySelector('button[type="submit"], input[type="submit"]')
                ? (form.querySelector('button[type="submit"], input[type="submit"]').textContent || '').trim()
                : '',
        });
    }

    // Scan standalone inputs (not inside a form)
    for (const input of document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"])')) {
        if (input.closest('form')) continue;
        let label = null;
        const container = input.closest('.search-item, .form-group, .field, .input-group');
        if (container) label = container.querySelector('label');
        if (!label && input.previousElementSibling && input.previousElementSibling.tagName === 'LABEL') {
            label = input.previousElementSibling;
        }
        result.inputs.push({
            id: input.id || '',
            name: input.name || '',
            type: input.type || 'text',
            label: label ? label.textContent.trim() : '',
            placeholder: input.placeholder || '',
        });
    }

    // Scan standalone buttons (not inside a form)
    for (const btn of document.querySelectorAll('button, [role="button"]')) {
        if (btn.closest('form')) continue;
        const text = (btn.textContent || '').trim();
        if (text) {
            result.buttons.push({
                text,
                onclick: btn.getAttribute('onclick') || '',
            });
        }
    }

    return result;
}
"""

# ── Helper ───────────────────────────────────────────────────────────


def should_process_request(request) -> bool:
    """Bridge filter for page event callbacks.

    Returns True if the request looks like an XHR/fetch API call
    (not a static resource, data URI, or WebSocket).
    """
    from .network_capture import should_capture

    return should_capture(request.url, request.resource_type)


_FETCH_XHR_STACK_CAPTURE_JS = r"""
(() => {
  if (window.__apiMonitorStackCaptureInstalled) return;
  window.__apiMonitorStackCaptureInstalled = true;
  window.__apiMonitorStacks = [];

  const record = (method, url) => {
    try {
      window.__apiMonitorStacks.push({
        method: String(method || 'GET').toUpperCase(),
        url: String(url || ''),
        timestamp: Date.now(),
        stack: new Error().stack || '',
        frameUrl: window.location.href,
      });
      if (window.__apiMonitorStacks.length > 500) {
        window.__apiMonitorStacks.splice(0, window.__apiMonitorStacks.length - 500);
      }
    } catch (_) {}
  };

  const originalFetch = window.fetch;
  window.fetch = function(input, init) {
    const url = typeof input === 'string' ? input : input && input.url;
    const method = init && init.method ? init.method : input && input.method ? input.method : 'GET';
    record(method, url);
    return originalFetch.apply(this, arguments);
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url) {
    this.__apiMonitorMethod = method;
    this.__apiMonitorUrl = url;
    return originalOpen.apply(this, arguments);
  };

  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function() {
    record(this.__apiMonitorMethod || 'GET', this.__apiMonitorUrl || '');
    return originalSend.apply(this, arguments);
  };
})();
"""

_STACK_URL_RE = re.compile(
    r"((?:https?|chrome-extension|moz-extension|safari-extension)://[^\s)]+?)(?::\d+)*(:\d+)?(?:\))"
)


def _initiator_to_evidence(initiator: Dict) -> Dict:
    urls: List[str] = []
    stack = initiator.get("stack") or {}
    for frame in stack.get("callFrames") or []:
        url = frame.get("url")
        if url:
            urls.append(url)
    return {
        "initiator_type": initiator.get("type") or "",
        "initiator_urls": _dedupe_strings(urls),
    }


def _stack_to_urls(stack: str) -> List[str]:
    return _dedupe_strings([m.group(1) for m in _STACK_URL_RE.finditer(stack or "")])


def _dedupe_strings(values: List[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


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


# ── Manager ──────────────────────────────────────────────────────────


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


def _create_rejected_candidate(
    session_id: str,
    dedup_key: str,
    method: str,
    url_pattern: str,
    samples: List[CapturedApiCall],
    confidence_result,
    *,
    dom_context: str = "",
    page_url: str = "",
    status: str = "confidence_rejected",
    intent_filter_reason: Optional[str] = None,
    adjusted_score: Optional[int] = None,
) -> ApiToolGenerationCandidate:
    dom_dict: Dict = {}
    if dom_context:
        try:
            dom_dict = json.loads(dom_context)
        except (json.JSONDecodeError, TypeError):
            pass
    candidate = ApiToolGenerationCandidate(
        session_id=session_id,
        dedup_key=dedup_key,
        method=method,
        url_pattern=url_pattern,
        source_call_ids=[c.id for c in samples],
        sample_call_ids=[c.id for c in samples[:5]],
        status=status,
        capture_dom_context=dom_dict,
        capture_page_url=page_url,
        rejection_reason=summarize_rejection_reasons(confidence_result) if status == "confidence_rejected" else None,
        intent_filter_reason=intent_filter_reason,
    )
    return candidate


def _richness_score(tool: ApiToolDefinition) -> int:
    evidence = tool.source_evidence or {}
    breakdown = evidence.get("breakdown") or {}
    try:
        return int(breakdown.get("response_richness", 0))
    except (AttributeError, TypeError, ValueError):
        return 0


def _merge_dom_context(existing: Dict, new: Dict) -> Dict:
    """Merge two DOM context snapshots, deduplicating by key fields."""
    if not existing:
        return dict(new)
    if not new:
        return dict(existing)

    result: Dict = {}

    # Merge forms by action URL; actionless forms keyed by index
    existing_forms: Dict[str, Dict] = {}
    for i, f in enumerate(existing.get("forms", [])):
        key = f.get("action") or f"__form_{i}"
        existing_forms[key] = f
    for j, f in enumerate(new.get("forms", [])):
        action = f.get("action")
        if action:
            if action not in existing_forms:
                existing_forms[action] = f
        elif f"__form_{j}" not in existing_forms:
            existing_forms[f"__form_{j}"] = f
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


class ApiMonitorSessionManager:
    """Core session manager for API Monitor.

    Owns browser contexts, network capture engines, and orchestrates
    the automatic page analysis + recording workflows.
    """

    def __init__(self) -> None:
        self.sessions: Dict[str, ApiMonitorSession] = {}
        self._contexts: Dict[str, BrowserContext] = {}
        self._pages: Dict[str, Page] = {}
        self._session_pages: Dict[str, List[Page]] = {}
        self._listener_pages: Set[tuple[str, int]] = set()
        self._captures: Dict[str, NetworkCaptureEngine] = {}
        self._screencasts: Dict[str, SessionScreencastController] = {}
        self._request_evidence: Dict[str, Dict[str, Dict]] = {}
        self._cdp_to_pw: Dict[str, Dict[str, int]] = defaultdict(dict)
        self._frame_to_page: Dict[int, Page] = {}
        self._action_anchors: Dict[str, List[Dict]] = {}
        self._last_action_at: Dict[str, float] = {}
        self._stop_recording_tasks: Dict[str, asyncio.Task[List[ApiToolDefinition]]] = {}
        self._recording_drain_tasks: Dict[str, asyncio.Task[None]] = {}
        self._last_recording_tools: Dict[str, List[ApiToolDefinition]] = {}
        self._last_recording_calls: Dict[str, List[CapturedApiCall]] = {}
        self._generation_tasks: Dict[str, Dict[str, asyncio.Task[None]]] = defaultdict(dict)
        self._generation_followups: Set[tuple[str, str]] = set()
        self._generation_semaphore = asyncio.Semaphore(2)
        self._intent_prune_semaphore = asyncio.Semaphore(INTENT_PRUNE_CONCURRENCY)
        self._analysis_event_sinks: Dict[str, Callable[[str, dict], None]] = {}
        self._intent_prune_buffers: Dict[str, set[str]] = defaultdict(set)
        self._intent_prune_tasks: Dict[str, asyncio.Task] = {}

    def _emit_analysis_event(self, session_id: str, event: str, data: dict) -> None:
        sink = self._analysis_event_sinks.get(session_id)
        if sink:
            sink(event, data)

    def _candidate_event_payload(self, candidate: ApiToolGenerationCandidate) -> dict:
        return {
            "candidate_id": candidate.id,
            "dedup_key": candidate.dedup_key,
            "method": candidate.method,
            "url_pattern": candidate.url_pattern,
            "status": candidate.status,
            "source_call_count": len(candidate.source_call_ids),
            "tool_id": candidate.tool_id,
            "error": candidate.error,
            "retry_after": candidate.retry_after.isoformat() if candidate.retry_after else None,
            "rejection_reason": candidate.rejection_reason,
            "intent_filter_reason": candidate.intent_filter_reason,
            "intent_group": candidate.intent_group,
            "intent_reason": candidate.intent_reason,
            "intent_score": candidate.intent_score,
            "intent_rank": candidate.intent_rank,
            "intent_batch_id": candidate.intent_batch_id,
            "intent_prune_attempts": candidate.intent_prune_attempts,
            "intent_prune_error": candidate.intent_prune_error,
            "intent_prune_retry_after": candidate.intent_prune_retry_after.isoformat() if candidate.intent_prune_retry_after else None,
        }

    def register_screencast(self, session_id: str, controller: SessionScreencastController) -> None:
        """Register an active screencast controller so capture logs can be forwarded."""
        self._screencasts[session_id] = controller
        # Wire up capture engine's on_log callback
        capture = self._captures.get(session_id)
        if capture and not capture.on_log:
            capture.on_log = self._make_log_forwarder(session_id)

    def unregister_screencast(self, session_id: str) -> None:
        self._screencasts.pop(session_id, None)

    def _make_log_forwarder(self, session_id: str):
        """Create a callback that forwards capture logs to the screencast WS."""
        import asyncio as _asyncio

        def _forward(level: str, message: str) -> None:
            ctrl = self._screencasts.get(session_id)
            if ctrl:
                try:
                    loop = _asyncio.get_running_loop()
                    loop.create_task(ctrl.send_monitor_log(level, message))
                except RuntimeError:
                    pass

        return _forward

    # ── Session lifecycle ────────────────────────────────────────────

    async def create_session(
        self,
        user_id: str,
        target_url: str,
        sandbox_session_id: Optional[str] = None,
    ) -> ApiMonitorSession:
        """Create a new API Monitor session with its own browser context."""
        session_id = str(uuid.uuid4())
        effective_sandbox_id = sandbox_session_id or session_id
        session = ApiMonitorSession(
            id=session_id,
            user_id=user_id,
            sandbox_session_id=effective_sandbox_id,
            target_url=target_url,
        )
        self.sessions[session_id] = session

        # Create browser context via CDP connector
        browser = await get_cdp_connector().get_browser(
            session_id=effective_sandbox_id,
            user_id=user_id,
        )
        context = await browser.new_context(**get_context_kwargs())
        await context.grant_permissions(["clipboard-read", "clipboard-write"])

        # Install user action capture for recording flow operation awareness
        await self._install_user_action_capture(session_id, context)

        page = await context.new_page()
        page.set_default_timeout(PAGE_TIMEOUT_MS)
        page.set_default_navigation_timeout(PAGE_TIMEOUT_MS)

        self._request_evidence[session_id] = {}
        self._contexts[session_id] = context

        # Install network capture. During initial navigation page.url can still be
        # about:blank, so fall back to the intended target URL for origin filtering.
        def _capture_page_url() -> str:
            current_page = self._pages.get(session_id) or page
            current_url = current_page.url
            if current_url and current_url != "about:blank":
                return current_url
            return session.target_url or target_url

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
        self._captures[session_id] = capture
        self._adopt_page(session_id, page, make_active=True)

        def _on_context_page(new_page: Page) -> None:
            self._adopt_page(session_id, new_page, make_active=True)

        context.on("page", _on_context_page)

        # Navigate in background — don't block the HTTP response
        if target_url:
            async def _navigate() -> None:
                try:
                    await page.goto(target_url, wait_until="domcontentloaded")
                    session.target_url = page.url
                    session.updated_at = datetime.now()
                    logger.info("[ApiMonitor] Navigation complete for %s: %s", session_id, page.url)
                except Exception as exc:
                    logger.warning("[ApiMonitor] Navigation failed for %s: %s", session_id, exc)
            asyncio.create_task(_navigate())

        logger.info("[ApiMonitor] Session %s created, target URL=%s", session_id, target_url)
        return session

    async def stop_session(self, session_id: str) -> None:
        """Close browser context and clean up session resources."""
        session = self.sessions.pop(session_id, None)
        if session:
            session.status = "stopped"

        self._captures.pop(session_id, None)
        self._request_evidence.pop(session_id, None)
        self._cdp_to_pw.pop(session_id, None)
        self._action_anchors.pop(session_id, None)
        self._last_action_at.pop(session_id, None)
        self._stop_recording_tasks.pop(session_id, None)
        await self._stop_recording_drain_task(session_id)
        self._intent_prune_buffers.pop(session_id, None)
        prune_task = self._intent_prune_tasks.pop(session_id, None)
        if prune_task and not prune_task.done():
            prune_task.cancel()
            try:
                await prune_task
            except asyncio.CancelledError:
                pass
        self._last_recording_tools.pop(session_id, None)
        self._last_recording_calls.pop(session_id, None)
        # Clean up frame-to-page mapping for all pages in this session
        session_pages = self._session_pages.pop(session_id, [])
        for page in session_pages:
            try:
                self._frame_to_page.pop(id(page.main_frame), None)
                for frame in page.frames:
                    self._frame_to_page.pop(id(frame), None)
            except Exception:
                pass
        self._listener_pages = {
            key for key in self._listener_pages
            if key[0] != session_id
        }
        self._pages.pop(session_id, None)
        self._screencasts.pop(session_id, None)

        context = self._contexts.pop(session_id, None)
        if context:
            try:
                await context.close()
            except Exception as exc:
                logger.warning("[ApiMonitor] Error closing context for %s: %s", session_id, exc)

        logger.info("[ApiMonitor] Session %s stopped", session_id)

    # ── Navigation ───────────────────────────────────────────────────

    async def navigate(self, session_id: str, url: str) -> str:
        """Navigate the session's page to a new URL."""
        page = self._require_page(session_id)
        await page.goto(url, wait_until="domcontentloaded")

        session = self.sessions[session_id]
        session.target_url = page.url
        session.updated_at = datetime.now()
        return session.target_url

    async def _observe_directed_page(self, page: Page, instruction: str) -> Dict:
        raw_snapshot = await build_page_snapshot(page, build_frame_path)
        compact_snapshot = compact_recording_snapshot(raw_snapshot, instruction)
        title = ""
        try:
            title = await page.title()
        except Exception:
            title = str(raw_snapshot.get("title") or "")
        url = getattr(page, "url", "") or str(raw_snapshot.get("url") or "")
        return {
            "url": url,
            "title": title,
            "raw_snapshot": raw_snapshot,
            "compact_snapshot": compact_snapshot,
            "dom_digest": self._build_directed_dom_digest(compact_snapshot),
        }

    def _build_directed_dom_digest(self, compact_snapshot: Dict) -> str:
        action_nodes = compact_snapshot.get("actionable_nodes") or compact_snapshot.get("actions") or []
        digest_payload = {
            "url": compact_snapshot.get("url") or "",
            "title": compact_snapshot.get("title") or "",
            "actionable": [
                {
                    "role": node.get("role") or "",
                    "name": node.get("name") or node.get("label") or "",
                    "text": node.get("text") or "",
                    "ref": node.get("ref") or node.get("internal_ref") or "",
                }
                for node in action_nodes[:80]
                if isinstance(node, dict)
            ],
        }
        encoded = json.dumps(digest_payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    async def _wait_for_directed_settle(
        self,
        page: Page,
        *,
        previous_digest: str,
        instruction: str,
        timeout_ms: int = 1500,
    ) -> None:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=500)
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=500)
        except Exception:
            pass
        deadline = time.monotonic() + max(timeout_ms, 0) / 1000
        last_digest = previous_digest
        stable_count = 0
        while time.monotonic() < deadline:
            try:
                observation = await self._observe_directed_page(page, instruction)
                current_digest = observation["dom_digest"]
            except Exception:
                return
            if current_digest == last_digest:
                stable_count += 1
                if stable_count >= 2:
                    return
            else:
                stable_count = 0
                last_digest = current_digest
            await page.wait_for_timeout(150)

    # ── Getters ──────────────────────────────────────────────────────

    def get_session(self, session_id: str) -> Optional[ApiMonitorSession]:
        return self.sessions.get(session_id)

    def get_page(self, session_id: str) -> Optional[Page]:
        return self._pages.get(session_id)

    def list_tabs(self, session_id: str) -> List[Dict]:
        """Return tab info for the session (used by screencast controller)."""
        session = self.sessions.get(session_id)
        if not session:
            return []

        active_page = self._pages.get(session_id)
        pages = self._session_pages.get(session_id) or ([active_page] if active_page else [])
        return [
            {
                "tab_id": f"{session.id}:{idx}",
                "title": "",
                "url": getattr(page, "url", "") or session.target_url or "",
                "active": page is active_page,
            }
            for idx, page in enumerate(pages)
            if page is not None
        ]

    # ── Recording ────────────────────────────────────────────────────

    async def start_recording(
        self,
        session_id: str,
        model_config: Optional[Dict] = None,
        intent: Optional[str] = None,
    ) -> None:
        """Clear capture buffer and set session status to recording."""
        self._require_session(session_id)

        session = self.sessions[session_id]
        session.intent = intent

        capture = self._captures.get(session_id)
        if capture:
            # Pre-recording calls can provide token/auth evidence, but they were
            # not triggered inside the recording window and must not generate tools.
            pre_calls = capture.drain_new_calls()
            if pre_calls:
                added = self._store_evidence_calls(session_id, pre_calls)
                logger.info(
                    "[ApiMonitor] Stored %d pre-recording calls as evidence for session %s",
                    len(added), session_id,
                )

        self._mark_action(session_id)
        task = self._stop_recording_tasks.get(session_id)
        if task and task.done():
            self._stop_recording_tasks.pop(session_id, None)
        self._last_recording_tools.pop(session_id, None)
        self._last_recording_calls.pop(session_id, None)

        # Keep generation-eligible calls intact; pre-window token/auth calls are
        # stored separately in evidence_calls.
        session.status = "recording"
        session.updated_at = datetime.now()
        await self._stop_recording_drain_task(session_id)
        self._recording_drain_tasks[session_id] = asyncio.create_task(
            self._recording_drain_loop(session_id, model_config=model_config)
        )
        logger.info("[ApiMonitor] Recording started for session %s", session_id)

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
                self._cleanup_stale_evidence(session_id, max_age_seconds=30)
                if calls:
                    # Link calls to the most recent action anchor
                    anchors = self._action_anchors.get(session_id)
                    if anchors:
                        last_anchor = anchors[-1]
                        last_anchor["call_ids"].extend(call.id for call in calls)

                    processing_task = asyncio.create_task(
                        self._process_captured_calls_for_generation(
                            session_id,
                            calls,
                            action_context=self._last_action_context(session_id),
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

    async def _stop_recording_drain_task(self, session_id: str) -> None:
        task = self._recording_drain_tasks.pop(session_id, None)
        if not task:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def stop_recording(
        self,
        session_id: str,
        model_config: Optional[Dict] = None,
    ) -> List[ApiToolDefinition]:
        """Stop recording, drain captured calls, and enqueue tool generation.

        Stop is idempotent because callers may retry after a transient HTTP
        disconnect while the first stop is still processing the capture buffer.
        """
        session = self._require_session(session_id)

        existing_task = self._stop_recording_tasks.get(session_id)
        if existing_task:
            try:
                return await asyncio.shield(existing_task)
            finally:
                if existing_task.done():
                    self._stop_recording_tasks.pop(session_id, None)

        if session.status != "recording":
            cached_tools = self._last_recording_tools.get(session_id)
            if cached_tools is not None:
                return list(cached_tools)
            cached_calls = self._last_recording_calls.get(session_id)
            if cached_calls:
                candidates = await self._process_captured_calls_for_generation(
                    session_id,
                    list(cached_calls),
                    model_config=model_config,
                )
                tools = self._tools_for_generation_candidates(session_id, candidates)
                self._last_recording_tools[session_id] = list(tools)
                return tools
            return []

        task = asyncio.create_task(
            self._stop_recording_once(session_id, model_config=model_config)
        )
        self._stop_recording_tasks[session_id] = task
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                self._stop_recording_tasks.pop(session_id, None)

    async def _stop_recording_once(
        self,
        session_id: str,
        model_config: Optional[Dict] = None,
    ) -> List[ApiToolDefinition]:
        """Perform the single authoritative stop for a recording window."""
        session = self._require_session(session_id)
        await self._stop_recording_drain_task(session_id)

        capture = self._captures.get(session_id)
        new_calls: List[CapturedApiCall] = []
        if capture:
            new_calls = capture.drain_new_calls()

        candidates = await self._process_captured_calls_for_generation(
            session_id,
            new_calls,
            model_config=model_config,
        )
        await self._flush_intent_prune_buffer(session_id, model_config=model_config)
        self._last_recording_calls[session_id] = list(new_calls)
        session.status = "idle"
        session.updated_at = datetime.now()

        if new_calls:
            tools = self._tools_for_generation_candidates(session_id, candidates)
            self._last_recording_tools[session_id] = list(tools)
            return tools

        logger.info("[ApiMonitor] Recording stopped for session %s, %d calls captured", session_id, len(new_calls))
        self._last_recording_tools[session_id] = []
        return []

    # ── Page analysis (async generator) ──────────────────────────────

    async def analyze_page(
        self,
        session_id: str,
        model_config: Optional[Dict] = None,
        intent: Optional[str] = None,
    ) -> AsyncGenerator[Dict, None]:
        """Automatic page analysis: scan DOM, probe elements, generate tools.

        Yields SSE event dicts like {"event": <name>, "data": json.dumps({...})}.
        """
        session = self._require_session(session_id)
        session.intent = intent
        page = self._require_page(session_id)
        session.status = "analyzing"
        session.updated_at = datetime.now()

        yield {
            "event": "analysis_started",
            "data": json.dumps({"session_id": session_id, "url": session.target_url}),
        }

        try:
            # Step 1: Scan interactive elements
            yield {
                "event": "progress",
                "data": json.dumps({"step": "scanning", "message": "Scanning page for interactive elements..."}),
            }

            elements = await self._scan_interactive_elements(page)

            yield {
                "event": "elements_found",
                "data": json.dumps({"count": len(elements)}),
            }

            if not elements:
                session.status = "idle"
                yield {
                    "event": "analysis_complete",
                    "data": json.dumps({"tools_generated": 0, "message": "No interactive elements found."}),
                }
                return

            # Step 2: Classify elements via LLM
            yield {
                "event": "progress",
                "data": json.dumps({"step": "classifying", "message": "Classifying elements via LLM..."}),
            }

            classification = await analyze_elements(
                url=session.target_url or "",
                elements=elements,
                model_config=model_config,
            )

            safe_indices = classification.get("safe", [])
            safe_elements = [elements[i] for i in safe_indices if i < len(elements)]

            yield {
                "event": "elements_classified",
                "data": json.dumps({
                    "safe": len(safe_elements),
                    "skipped": len(elements) - len(safe_elements),
                }),
            }

            if not safe_elements:
                session.status = "idle"
                yield {
                    "event": "analysis_complete",
                    "data": json.dumps({"tools_generated": 0, "message": "No safe elements to probe."}),
                }
                return

            # Step 3: Probe each safe element
            all_probed_calls: List[CapturedApiCall] = []

            for idx, elem in enumerate(safe_elements):
                yield {
                    "event": "progress",
                    "data": json.dumps({
                        "step": "probing",
                        "message": f"Probing element {idx + 1}/{len(safe_elements)}: {elem.get('tag', '')} {elem.get('text', '')[:30]}",
                        "current": idx + 1,
                        "total": len(safe_elements),
                    }),
                }

                capture = self._captures.get(session_id)
                if capture:
                    # Calls accumulated before this probe are token/auth evidence,
                    # not APIs triggered by the current analyzed element.
                    pre_calls = capture.drain_new_calls()
                    if pre_calls:
                        self._store_evidence_calls(session_id, pre_calls)

                probed_calls = await self._probe_element(page, elem)

                if probed_calls:
                    all_probed_calls.extend(probed_calls)
                    await self._process_captured_calls_for_generation(
                        session_id,
                        probed_calls,
                        action_context={
                            "action": "probe",
                            "description": f"probe {elem.get('tag', '')} {elem.get('text', '')[:30]}",
                        },
                        model_config=model_config,
                    )
                    yield {
                        "event": "calls_captured",
                        "data": json.dumps({
                            "element_index": idx,
                            "calls": len(probed_calls),
                        }),
                    }

            session.status = "idle"
            session.updated_at = datetime.now()
            tools = self._tools_for_calls(session_id, all_probed_calls)

            yield {
                "event": "analysis_complete",
                "data": json.dumps({
                    "tools_generated": len(tools),
                    "total_calls": len(all_probed_calls),
                }),
            }

        except Exception as exc:
            session.status = "idle"
            session.updated_at = datetime.now()
            logger.error("[ApiMonitor] Analysis failed for session %s: %s", session_id, exc, exc_info=True)
            yield {
                "event": "analysis_error",
                "data": json.dumps({"error": str(exc)}),
            }

    # ── Directed page analysis ───────────────────────────────────────

    async def analyze_directed_page(
        self,
        session_id: str,
        *,
        instruction: str,
        mode: str,
        business_safety: AnalysisBusinessSafety,
        model_config: Optional[Dict] = None,
    ) -> AsyncGenerator[Dict, None]:
        """Directed analysis: dynamically plan one action from the current DOM each step."""
        session = self._require_session(session_id)
        session.intent = instruction
        page = self._require_page(session_id)
        session.status = "analyzing"
        session.updated_at = datetime.now()

        yield {
            "event": "analysis_started",
            "data": json.dumps(
                {
                    "session_id": session_id,
                    "url": session.target_url or getattr(page, "url", ""),
                    "mode": mode,
                    "has_instruction": bool(instruction.strip()),
                },
                ensure_ascii=False,
            ),
        }

        try:
            capture = self._captures.get(session_id)
            if capture:
                pre_calls = capture.drain_new_calls()
                if pre_calls:
                    self._store_evidence_calls(session_id, pre_calls)

            max_failures = 20
            max_steps = 40
            failed_steps = 0
            run_history: List[Dict] = []
            directed_calls: List[CapturedApiCall] = []
            stop_reason = ""

            for step_index in range(1, max_steps + 1):
                yield {
                    "event": "progress",
                    "data": json.dumps(
                        {
                            "step": "snapshot",
                            "message": f"正在构建第 {step_index} 轮页面 DOM...",
                            "current": step_index,
                            "total": max_steps,
                        },
                        ensure_ascii=False,
                    ),
                }
                observation = await self._observe_directed_page(page, instruction)
                before_observation = observation_from_payload(observation)
                trace = DirectedAnalysisTrace(
                    step=step_index,
                    instruction=instruction,
                    mode=mode,
                    before=before_observation,
                )
                session.directed_traces.append(trace)
                yield {
                    "event": "directed_trace_added",
                    "data": json.dumps(trace.model_dump(mode="json"), ensure_ascii=False),
                }
                observation_for_prompt = {
                    "url": observation["url"],
                    "title": observation["title"],
                    "dom_digest": observation["dom_digest"],
                    "new_call_count": len(directed_calls),
                    "last_result": run_history[-1] if run_history else None,
                }
                completed_traces = session.directed_traces[:-1]
                retry_context = build_directed_retry_context(
                    completed_traces,
                    captured_api_summary=self._summarize_directed_calls(directed_calls),
                )
                observation_for_prompt["retry_context"] = retry_context
                yield {
                    "event": "directed_step_snapshot",
                    "data": json.dumps(
                        {
                            "step": step_index,
                            "url": observation["url"],
                            "title": observation["title"],
                            "dom_digest": observation["dom_digest"],
                        },
                        ensure_ascii=False,
                    ),
                }

                try:
                    decision = await build_directed_step_decision(
                        instruction=instruction,
                        compact_snapshot=observation["compact_snapshot"],
                        run_history=run_history,
                        observation=observation_for_prompt,
                        retry_context=retry_context,
                        model_config=model_config,
                    )
                except Exception as planner_exc:
                    error_text = str(planner_exc)
                    trace.execution = execution_snapshot(
                        result="planner_failed",
                        error=error_text,
                        before=trace.before,
                        after=trace.before,
                    )
                    trace.after = trace.before
                    trace.updated_at = datetime.now()
                    run_history.append(
                        {
                            "step": step_index,
                            "result": "planner_failed",
                            "error": error_text,
                            "url": observation["url"],
                            "title": observation["title"],
                            "dom_digest": observation["dom_digest"],
                        }
                    )
                    failed_steps += 1
                    yield {
                        "event": "directed_replan",
                        "data": json.dumps(
                            {
                                "step": step_index,
                                "description": "planner_failed",
                                "error": error_text,
                            },
                            ensure_ascii=False,
                        ),
                    }
                    yield {
                        "event": "directed_trace_updated",
                        "data": json.dumps(trace.model_dump(mode="json"), ensure_ascii=False),
                    }
                    if failed_steps >= max_failures:
                        stop_reason = f"Reached max directed planner failures: {max_failures}"
                        break
                    continue
                trace.decision = decision_snapshot(decision)
                if decision.next_action is not None:
                    trace.action_fingerprint = directed_action_fingerprint(decision.next_action)
                trace.updated_at = datetime.now()
                yield {
                    "event": "directed_step_planned",
                    "data": json.dumps(
                        {
                            "step": step_index,
                            "goal_status": decision.goal_status,
                            "summary": decision.summary,
                            "expected_change": decision.expected_change,
                            "done_reason": decision.done_reason,
                        },
                        ensure_ascii=False,
                    ),
                }

                if decision.goal_status in ("done", "blocked"):
                    stop_reason = decision.done_reason or decision.summary or decision.goal_status
                    trace.execution = execution_snapshot(
                        result=decision.goal_status,
                        before=trace.before,
                        after=trace.before,
                    )
                    trace.after = trace.before
                    trace.updated_at = datetime.now()
                    yield {
                        "event": "directed_trace_updated",
                        "data": json.dumps(trace.model_dump(mode="json"), ensure_ascii=False),
                    }
                    yield {
                        "event": "directed_done",
                        "data": json.dumps(
                            {
                                "step": step_index,
                                "goal_status": decision.goal_status,
                                "reason": stop_reason,
                            },
                            ensure_ascii=False,
                        ),
                    }
                    break

                action = decision.next_action
                if action is None:
                    stop_reason = "Planner did not return a next action"
                    break

                filtered = filter_action_for_business_safety(action, business_safety)
                if filtered.skipped:
                    skipped = filtered.skipped
                    trace.execution = execution_snapshot(
                        result="skipped",
                        error=skipped.reason,
                        before=trace.before,
                        after=trace.before,
                    )
                    trace.after = trace.before
                    trace.updated_at = datetime.now()
                    run_history.append(
                        {
                            "step": step_index,
                            "result": "skipped",
                            "description": skipped.description,
                            "reason": skipped.reason,
                            "risk": skipped.risk,
                        }
                    )
                    yield {
                        "event": "directed_action_skipped",
                        "data": json.dumps(
                            {
                                "step": step_index,
                                "description": skipped.description,
                                "reason": skipped.reason,
                            },
                            ensure_ascii=False,
                        ),
                    }
                    yield {
                        "event": "directed_trace_updated",
                        "data": json.dumps(trace.model_dump(mode="json"), ensure_ascii=False),
                    }
                    continue

                allowed_action = filtered.allowed
                if allowed_action is None:
                    stop_reason = "No allowed directed action returned"
                    break

                skip_reason = retry_guard_skip_reason(trace.action_fingerprint or "", completed_traces)
                if skip_reason:
                    trace.execution = execution_snapshot(
                        result="retry_guard_skipped",
                        error=skip_reason,
                        before=trace.before,
                        after=trace.before,
                    )
                    trace.after = trace.before
                    trace.retry_advice = {
                        "reason": skip_reason,
                        "blocked_actions": retry_context.get("blocked_actions", []),
                        "block_steps": retry_context.get("block_steps", []),
                    }
                    trace.updated_at = datetime.now()
                    run_history.append(
                        {
                            "step": step_index,
                            "result": "retry_guard_skipped",
                            "description": allowed_action.description,
                            "code": describe_locator_code(allowed_action),
                            "error": skip_reason,
                            "expected_change": decision.expected_change,
                        }
                    )
                    failed_steps += 1
                    yield {
                        "event": "directed_trace_updated",
                        "data": json.dumps(trace.model_dump(mode="json"), ensure_ascii=False),
                    }
                    yield {
                        "event": "directed_replan",
                        "data": json.dumps(
                            {
                                "step": step_index,
                                "description": allowed_action.description,
                                "error": skip_reason,
                            },
                            ensure_ascii=False,
                        ),
                    }
                    if failed_steps >= max_failures:
                        stop_reason = f"Reached max directed action failures: {max_failures}"
                        break
                    continue

                yield {
                    "event": "directed_action_detail",
                    "data": json.dumps(
                        {
                            "index": step_index,
                            "description": describe_action(allowed_action),
                            "code": describe_locator_code(allowed_action),
                            "risk": allowed_action.risk,
                        },
                        ensure_ascii=False,
                    ),
                }
                self._mark_action(session_id)
                try:
                    await execute_directed_action(page, allowed_action)
                except Exception as action_exc:
                    error_text = str(action_exc)
                    failed_step_calls: List[CapturedApiCall] = []
                    if capture:
                        failed_step_calls = capture.drain_new_calls()
                        if failed_step_calls:
                            directed_calls.extend(failed_step_calls)
                            await self._process_captured_calls_for_generation(
                                session_id,
                                failed_step_calls,
                                action_context={
                                    "action": describe_action(allowed_action),
                                    "description": allowed_action.description,
                                    "page_url": observation.get("url", ""),
                                },
                                model_config=model_config,
                            )
                    try:
                        after_payload = await self._observe_directed_page(page, instruction)
                        trace.after = observation_from_payload(after_payload)
                    except Exception:
                        trace.after = trace.before
                    trace.execution = execution_snapshot(
                        result="failed",
                        error=error_text,
                        before=trace.before,
                        after=trace.after,
                    )
                    trace.captured_call_ids = captured_call_ids(failed_step_calls)
                    trace.updated_at = datetime.now()
                    run_history.append(
                        {
                            "step": step_index,
                            "result": "failed",
                            "description": allowed_action.description,
                            "code": describe_locator_code(allowed_action),
                            "error": error_text,
                            "expected_change": decision.expected_change,
                        }
                    )
                    failed_steps += 1
                    yield {
                        "event": "directed_replan",
                        "data": json.dumps(
                            {
                                "step": step_index,
                                "description": allowed_action.description,
                                "error": error_text,
                            },
                            ensure_ascii=False,
                        ),
                    }
                    yield {
                        "event": "directed_trace_updated",
                        "data": json.dumps(trace.model_dump(mode="json"), ensure_ascii=False),
                    }
                    if failed_steps >= max_failures:
                        stop_reason = f"Reached max directed action failures: {max_failures}"
                        break
                    continue

                run_history.append(
                    {
                        "step": step_index,
                        "result": "executed",
                        "description": allowed_action.description,
                        "code": describe_locator_code(allowed_action),
                        "expected_change": decision.expected_change,
                    }
                )
                yield {
                    "event": "directed_step_executed",
                    "data": json.dumps(
                        {
                            "step": step_index,
                            "description": allowed_action.description,
                            "code": describe_locator_code(allowed_action),
                        },
                        ensure_ascii=False,
                    ),
                }
                yield {
                    "event": "directed_action_executed",
                    "data": json.dumps(
                        {
                            "code": describe_locator_code(allowed_action),
                            "description": allowed_action.description,
                        },
                        ensure_ascii=False,
                    ),
                }

                await self._wait_for_directed_settle(
                    page,
                    previous_digest=observation["dom_digest"],
                    instruction=instruction,
                )

                step_calls: List[CapturedApiCall] = []
                if capture:
                    step_calls = capture.drain_new_calls()
                if step_calls:
                    directed_calls.extend(step_calls)
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
                    if run_history:
                        run_history[-1]["new_calls"] = self._summarize_directed_calls(step_calls)
                trace.after = trace.before
                trace.execution = execution_snapshot(
                    result="executed",
                    before=trace.before,
                    after=trace.after,
                )
                trace.captured_call_ids = captured_call_ids(step_calls)
                trace.updated_at = datetime.now()
                yield {
                    "event": "directed_trace_updated",
                    "data": json.dumps(trace.model_dump(mode="json"), ensure_ascii=False),
                }
                if step_calls:
                    yield {
                        "event": "calls_captured",
                        "data": json.dumps(
                            {
                                "mode": mode,
                                "step": step_index,
                                "calls": len(step_calls),
                            },
                            ensure_ascii=False,
                        ),
                    }
                yield {
                    "event": "directed_step_observed",
                    "data": json.dumps(
                        {
                            "step": step_index,
                            "new_calls": len(step_calls),
                            "total_directed_calls": len(directed_calls),
                        },
                        ensure_ascii=False,
                    ),
                }
                if step_calls:
                    completion_observation = {
                        "url": observation["url"],
                        "title": observation["title"],
                        "dom_digest": observation["dom_digest"],
                        "new_call_count": len(directed_calls),
                        "last_result": run_history[-1] if run_history else None,
                        "completion_check": True,
                    }
                    try:
                        completion_decision = await build_directed_step_decision(
                            instruction=instruction,
                            compact_snapshot=observation["compact_snapshot"],
                            run_history=run_history,
                            observation=completion_observation,
                            retry_context=build_directed_retry_context(
                                session.directed_traces,
                                captured_api_summary=self._summarize_directed_calls(directed_calls),
                            ),
                            model_config=model_config,
                        )
                    except Exception as planner_exc:
                        yield {
                            "event": "directed_replan",
                            "data": json.dumps(
                                {
                                    "step": step_index,
                                    "description": "completion_check_failed",
                                    "error": str(planner_exc),
                                },
                                ensure_ascii=False,
                            ),
                        }
                        continue
                    yield {
                        "event": "directed_step_planned",
                        "data": json.dumps(
                            {
                                "step": step_index,
                                "goal_status": completion_decision.goal_status,
                                "summary": completion_decision.summary,
                                "expected_change": completion_decision.expected_change,
                                "done_reason": completion_decision.done_reason,
                                "completion_check": True,
                            },
                            ensure_ascii=False,
                        ),
                    }
                    if completion_decision.goal_status in ("done", "blocked"):
                        stop_reason = (
                            completion_decision.done_reason
                            or completion_decision.summary
                            or completion_decision.goal_status
                        )
                        yield {
                            "event": "directed_done",
                            "data": json.dumps(
                                {
                                    "step": step_index,
                                    "goal_status": completion_decision.goal_status,
                                    "reason": stop_reason,
                                },
                                ensure_ascii=False,
                            ),
                        }
                        break
            else:
                stop_reason = f"Reached max directed steps: {max_steps}"

            session.status = "idle"
            session.updated_at = datetime.now()
            tools = self._tools_for_calls(session_id, directed_calls)

            yield {
                "event": "analysis_complete",
                "data": json.dumps(
                    {
                        "mode": mode,
                        "tools_generated": len(tools),
                        "total_calls": len(directed_calls),
                        "steps": len(run_history),
                        "stop_reason": stop_reason,
                    },
                    ensure_ascii=False,
                ),
            }

        except Exception as exc:
            session.status = "idle"
            session.updated_at = datetime.now()
            logger.error("[ApiMonitor] Directed analysis failed for session %s: %s", session_id, exc, exc_info=True)
            yield {
                "event": "analysis_error",
                "data": json.dumps({"error": str(exc)}, ensure_ascii=False),
            }

    # ── Tool generation ──────────────────────────────────────────────

    def _summarize_directed_calls(self, calls: List[CapturedApiCall]) -> List[Dict]:
        summaries: List[Dict] = []
        for call in calls[:10]:
            response = call.response
            summaries.append(
                {
                    "method": call.request.method,
                    "url": call.request.url,
                    "url_pattern": call.url_pattern or "",
                    "status": response.status if response else None,
                    "content_type": response.content_type if response else None,
                }
            )
        return summaries

    def _tools_for_generation_candidates(
        self,
        session_id: str,
        candidates: list[ApiToolGenerationCandidate],
    ) -> list[ApiToolDefinition]:
        session = self.sessions.get(session_id)
        if not session or not candidates:
            return []
        tool_ids = {candidate.tool_id for candidate in candidates if candidate.tool_id}
        return [tool for tool in session.tool_definitions if tool.id in tool_ids]

    def _tools_for_calls(
        self,
        session_id: str,
        calls: list[CapturedApiCall],
    ) -> list[ApiToolDefinition]:
        if not calls:
            return []
        session = self.sessions.get(session_id)
        if not session:
            return []
        call_ids = {call.id for call in calls}
        return [
            tool
            for tool in session.tool_definitions
            if any(call_id in call_ids for call_id in tool.source_calls)
        ]

    async def _generate_tools_from_calls(
        self,
        session_id: str,
        calls: List[CapturedApiCall],
        source: str = "auto",
        model_config: Optional[Dict] = None,
    ) -> List[ApiToolDefinition]:
        """Group calls by dedup_key, generate YAML tool definition per group."""
        if not calls:
            return []

        session = self.sessions.get(session_id)
        if not session:
            return []

        # Scan DOM context for parameter inference
        dom_context = ""
        page = self._pages.get(session_id)
        if page:
            try:
                dom_data = await asyncio.wait_for(
                    page.evaluate(_SCAN_DOM_CONTEXT_JS),
                    timeout=DOM_CONTEXT_SCAN_TIMEOUT_S,
                )
                dom_context = json.dumps(dom_data, ensure_ascii=False, indent=2)
                logger.debug("[ApiMonitor] DOM context scanned: %d forms, %d inputs, %d buttons",
                             len(dom_data.get("forms", [])),
                             len(dom_data.get("inputs", [])),
                             len(dom_data.get("buttons", [])))
            except asyncio.TimeoutError:
                logger.warning(
                    "[ApiMonitor] DOM context scan timed out after %.1fs; generating API tools without DOM context",
                    DOM_CONTEXT_SCAN_TIMEOUT_S,
                )
            except Exception as exc:
                logger.warning("[ApiMonitor] DOM context scan failed: %s", exc)

        # Group by dedup key
        groups: Dict[str, List[CapturedApiCall]] = defaultdict(list)
        for call in calls:
            key = dedup_key(call)
            groups[key].append(call)

        tools: List[ApiToolDefinition] = []

        # Phase 1: Score each group and collect high-confidence candidates
        high_confidence: list[tuple[str, list[CapturedApiCall], object, ApiToolGenerationCandidate]] = []

        for key, group_calls in groups.items():
            samples = group_calls[:5]
            first = samples[0]
            method = first.request.method
            url_pattern = first.url_pattern or first.request.url

            confidence_result = score_api_candidate(samples)

            if confidence_result.score < 80:
                candidate = _create_rejected_candidate(
                    session_id, key, method, url_pattern, samples,
                    confidence_result, dom_context=dom_context,
                    page_url=session.target_url or "",
                )
                session.generation_candidates.append(candidate)
                self._emit_analysis_event(
                    session_id, "api_candidate_confidence_rejected",
                    {**self._candidate_event_payload(candidate), "score": confidence_result.score},
                )
                continue

            candidate = _create_rejected_candidate(
                session_id, key, method, url_pattern, samples,
                confidence_result, dom_context=dom_context,
                page_url=session.target_url or "",
                status="pending",
            )
            candidate.rejection_reason = None
            session.generation_candidates.append(candidate)
            high_confidence.append((key, samples, confidence_result, candidate))

        # Phase 2: Batch intent prune all high-confidence candidates together
        prune_by_key: dict[str, IntentPruneItem] = {}
        intent = (session.intent or "").strip()
        if intent and high_confidence:
            prune_candidates = [
                self._intent_prune_candidate(session, candidate, confidence_result)
                for _key, _samples, confidence_result, candidate in high_confidence
            ]
            prune_result = await self._prune_candidates_with_retry(
                session,
                [candidate for _key, _samples, _confidence_result, candidate in high_confidence],
                prune_candidates,
                intent,
                model_config=model_config,
            )
            prune_by_key = {item.candidate_key: item for item in prune_result.items}
            for _key, _samples, _confidence_result, candidate in high_confidence:
                item = prune_by_key.get(self._candidate_key_for_prune(candidate))
                if item:
                    self._apply_prune_item_to_candidate(
                        session,
                        candidate,
                        item,
                        batch_id=prune_result.batch_id,
                    )
                    self._emit_analysis_event(
                        session_id,
                        "api_candidate_intent_pruned",
                        self._candidate_event_payload(candidate),
                    )

        # Phase 3: Generate tools only for candidates that passed pruning
        for _key, samples, confidence_result, candidate in high_confidence:
            if candidate.status in ("intent_filtered", "intent_review"):
                continue

            try:
                yaml_def = await generate_tool_definition(
                    method=candidate.method,
                    url_pattern=candidate.url_pattern,
                    samples=samples,
                    page_context=session.target_url or "",
                    dom_context=dom_context,
                    model_config=model_config,
                )

                from backend.rpa.api_monitor_mcp_contract import parse_api_monitor_tool_yaml

                contract = parse_api_monitor_tool_yaml(yaml_def)
                name, description = _metadata_from_contract(
                    contract,
                    method=candidate.method,
                    url_pattern=candidate.url_pattern,
                )
                validation_status = "valid" if contract.valid else "invalid"
                validation_errors = contract.validation_errors if contract.validation_errors else []

                tool = ApiToolDefinition(
                    session_id=session_id,
                    name=name,
                    description=description,
                    method=candidate.method,
                    url_pattern=candidate.url_pattern,
                    yaml_definition=yaml_def,
                    source_calls=[c.id for c in samples],
                    source=source,
                    confidence=confidence_result.confidence,
                    score=confidence_result.score,
                    selected=True,
                    confidence_reasons=confidence_result.reasons,
                    source_evidence=confidence_result.evidence_summary,
                    validation_status=validation_status,
                    validation_errors=validation_errors,
                )

                session.tool_definitions.append(tool)
                tools.append(tool)

                logger.info(
                    "[ApiMonitor] Generated tool '%s' for %s %s (score: %d)",
                    name, candidate.method, candidate.url_pattern, confidence_result.score,
                )

            except Exception as exc:
                logger.warning(
                    "[ApiMonitor] Failed to generate tool for %s: %s",
                    candidate.url_pattern, exc,
                )

        self._dedup_session_tools(session_id, tools)

        return tools

    def _dedup_session_tools(
        self,
        session_id: str,
        new_tools: List[ApiToolDefinition],
    ) -> None:
        """Keep only the best scoring tool for each method + parameterized path."""
        session = self.sessions.get(session_id)
        if not session:
            return

        new_ids = {tool.id for tool in new_tools}
        existing_tools = [tool for tool in session.tool_definitions if tool.id not in new_ids]
        grouped: Dict[str, List[ApiToolDefinition]] = defaultdict(list)

        for tool in [*existing_tools, *new_tools]:
            grouped[dedup_key_for_tool(tool.method, tool.url_pattern)].append(tool)

        deduped: List[ApiToolDefinition] = []
        for group in grouped.values():
            group.sort(
                key=lambda tool: (
                    tool.score,
                    _richness_score(tool),
                    tool.created_at.isoformat() if tool.created_at else "",
                ),
                reverse=True,
            )
            deduped.append(group[0])

        session.tool_definitions = deduped
        survivor_ids = {tool.id for tool in deduped}
        new_tools[:] = [tool for tool in new_tools if tool.id in survivor_ids]

    # ── DOM scanning ─────────────────────────────────────────────────

    async def _scan_interactive_elements(self, page: Page) -> List[Dict]:
        """Inject JS to find clickable/interactive elements on the page."""
        try:
            elements = await page.evaluate(_SCAN_INTERACTIVE_JS)
            logger.info("[ApiMonitor] Found %d interactive elements", len(elements))
            return elements
        except Exception as exc:
            logger.warning("[ApiMonitor] Failed to scan elements: %s", exc)
            return []

    # ── Element probing ──────────────────────────────────────────────

    async def _probe_element(self, page: Page, elem: Dict) -> List[CapturedApiCall]:
        """Click an element, capture API calls, and navigate back if needed."""
        capture = self._captures.get(self._session_id_from_page(page) or "")
        if not capture:
            return []

        url_before = page.url
        calls: List[CapturedApiCall] = []

        try:
            # Build a locator for the element
            tag = elem.get("tag", "")
            text = elem.get("text", "")
            index = elem.get("index", 0)

            # Try various locator strategies
            locator = None
            if tag == "a" and text:
                locator = page.get_by_role("link", name=text, exact=False)
            elif tag == "button" or elem.get("role") == "button":
                if text:
                    locator = page.get_by_role("button", name=text, exact=False)
                else:
                    locator = page.get_by_role("button")
            elif tag in ("input", "select", "textarea"):
                name_attr = elem.get("name", "")
                aria_label = elem.get("ariaLabel", "")
                placeholder = ""
                if name_attr:
                    locator = page.get_by_label(name_attr)
                elif aria_label:
                    locator = page.get_by_label(aria_label)
                elif placeholder:
                    locator = page.get_by_placeholder(placeholder)
                else:
                    locator = page.locator(f"{tag}:nth-child({index + 1})")
            elif text:
                locator = page.get_by_text(text, exact=False)
            else:
                # Fallback: use CSS selector with tag and index
                locator = page.locator(f"{tag} >> nth={index}")

            if locator:
                session_id = self._session_id_from_page(page) or ""
                self._mark_action(session_id)
                # Brief wait to settle
                await page.wait_for_timeout(300)

                try:
                    await locator.click(timeout=5000)
                except Exception:
                    # Click failed (element may be obscured, detached, etc.)
                    return []

                # Wait for network activity
                await page.wait_for_timeout(1500)

                # Drain captured calls
                calls = capture.drain_new_calls()

                # If navigation occurred, go back
                current_url = page.url
                if current_url != url_before:
                    try:
                        await page.go_back(wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                        await page.wait_for_timeout(500)
                    except Exception as back_exc:
                        logger.warning("[ApiMonitor] go_back failed: %s", back_exc)

        except Exception as exc:
            logger.debug("[ApiMonitor] Probe failed for element %s: %s", elem.get("tag"), exc)

        return calls

    # ── Network listener installation ────────────────────────────────

    def _install_listeners(
        self,
        session_id: str,
        page: Page,
        capture: NetworkCaptureEngine,
    ) -> None:
        """Install page.on('request') and page.on('response') listeners."""
        listener_key = (session_id, id(page))
        if listener_key in self._listener_pages:
            return
        self._listener_pages.add(listener_key)

        def on_request(request) -> None:
            logger.debug(
                "[ApiMonitor] page.on('request') fired: resource_type=%s url=%s",
                request.resource_type,
                request.url[:120],
            )
            if should_process_request(request):
                capture.on_request(request)

        async def on_response(response) -> None:
            logger.debug(
                "[ApiMonitor] page.on('response') fired: status=%d url=%s",
                response.status,
                response.url[:120],
            )
            await capture.on_response(response)

        page.on("request", on_request)
        page.on("response", on_response)

        logger.info("[ApiMonitor] Network listeners installed for session %s", session_id)

    def _adopt_page(self, session_id: str, page: Page, *, make_active: bool) -> None:
        """Track a page in the session and install API capture hooks on it."""
        session = self._require_session(session_id)
        pages = self._session_pages.setdefault(session_id, [])
        if page not in pages:
            pages.append(page)

        if make_active:
            self._pages[session_id] = page
            session.active_tab_id = f"{session.id}:{pages.index(page)}"
            if getattr(page, "url", ""):
                session.target_url = page.url
            session.updated_at = datetime.now()

        page.set_default_timeout(PAGE_TIMEOUT_MS)
        page.set_default_navigation_timeout(PAGE_TIMEOUT_MS)

        # Maintain frame-to-page mapping for evidence lookup
        try:
            self._frame_to_page[id(page.main_frame)] = page
            for frame in page.frames:
                self._frame_to_page[id(frame)] = page
        except Exception:
            pass

        capture = self._captures.get(session_id)
        if capture:
            self._install_listeners(session_id, page, capture)

        async def _install_page_evidence() -> None:
            context = self._contexts.get(session_id) or getattr(page, "context", None)
            if context is not None:
                await self._install_source_evidence_capture(session_id, context, page)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            loop.create_task(_install_page_evidence())

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
                fallback = current_pages[-1] if current_pages else None
                if fallback is not None:
                    self._pages[session_id] = fallback
                    session.active_tab_id = f"{session.id}:{current_pages.index(fallback)}"
                    if getattr(fallback, "url", ""):
                        session.target_url = fallback.url
                else:
                    self._pages.pop(session_id, None)
                    session.active_tab_id = None

        page.on("close", _on_close)

    # ── Internal helpers ─────────────────────────────────────────────

    def _candidate_dedup_key(self, call: CapturedApiCall) -> str:
        return dedup_key(call)

    def _candidate_url_pattern(self, call: CapturedApiCall) -> str:
        return call.url_pattern or call.request.url

    def _find_generation_candidate(
        self,
        session: ApiMonitorSession,
        dedup_key_value: str,
    ) -> ApiToolGenerationCandidate | None:
        for candidate in session.generation_candidates:
            if candidate.dedup_key == dedup_key_value:
                return candidate
        return None

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
        session = self._require_session(session_id)
        key = self._candidate_dedup_key(call)
        candidate = self._find_generation_candidate(session, key)
        created = candidate is None
        now = datetime.now()

        if candidate is None:
            candidate = ApiToolGenerationCandidate(
                session_id=session_id,
                dedup_key=key,
                method=call.request.method,
                url_pattern=self._candidate_url_pattern(call),
                capture_dom_context=dom_context or {},
                capture_page_url=page_url,
                capture_title=title,
                capture_dom_digest=dom_digest,
            )
            session.generation_candidates.append(candidate)

        added_call = False
        if call.id not in candidate.source_call_ids:
            candidate.source_call_ids.append(call.id)
            added_call = True
        if call.id not in candidate.sample_call_ids and len(candidate.sample_call_ids) < 5:
            candidate.sample_call_ids.append(call.id)

        if dom_context and not created:
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

        if action_context and added_call:
            candidate.step_metadata.append({
                "action": action_context.get("action", ""),
                "action_description": action_context.get("description", ""),
                "page_url": page_url or action_context.get("page_url", ""),
                "call_count": 1,
                "call_ids": [call.id],
            })

        if added_call and not created and candidate.status in ("generated", "running"):
            candidate.status = "stale"

        candidate.updated_at = now
        session.updated_at = now
        return candidate, created

    def _enqueue_generation_candidate(
        self,
        session_id: str,
        candidate_id: str,
        *,
        model_config: Optional[Dict] = None,
        skip_filter: bool = False,
    ) -> None:
        session_tasks = self._generation_tasks.setdefault(session_id, {})
        existing = session_tasks.get(candidate_id)
        if existing and not existing.done():
            self._generation_followups.add((session_id, candidate_id))
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(
            self._run_generation_candidate(session_id, candidate_id, model_config=model_config, skip_filter=skip_filter)
        )
        session_tasks[candidate_id] = task

    async def _run_generation_candidate(
        self,
        session_id: str,
        candidate_id: str,
        *,
        model_config: Optional[Dict] = None,
        skip_filter: bool = False,
    ) -> None:
        try:
            async with self._generation_semaphore:
                while True:
                    try:
                        await self._generate_tool_for_candidate(
                            session_id,
                            candidate_id,
                            model_config=model_config,
                            skip_filter=skip_filter,
                        )
                    except Exception as exc:
                        self._mark_generation_candidate_failed(session_id, candidate_id, exc)
                        break
                    session = self.sessions.get(session_id)
                    candidate = next(
                        (item for item in (session.generation_candidates if session else []) if item.id == candidate_id),
                        None,
                    )
                    if candidate is None or candidate.status != "stale":
                        break
        finally:
            session_tasks = self._generation_tasks.get(session_id)
            current_task = asyncio.current_task()
            if session_tasks and session_tasks.get(candidate_id) is current_task:
                session_tasks.pop(candidate_id, None)
            followup_requested = (session_id, candidate_id) in self._generation_followups
            self._generation_followups.discard((session_id, candidate_id))
            session = self.sessions.get(session_id)
            candidate = next(
                (item for item in (session.generation_candidates if session else []) if item.id == candidate_id),
                None,
            )
            if followup_requested and candidate and candidate.status in ("pending", "stale", "failed", "confidence_rejected", "intent_filtered", "intent_review"):
                self._enqueue_generation_candidate(session_id, candidate_id, model_config=model_config, skip_filter=skip_filter)

    def _mark_generation_candidate_failed(
        self,
        session_id: str,
        candidate_id: str,
        exc: Exception,
    ) -> None:
        session = self.sessions.get(session_id)
        candidate = next(
            (item for item in (session.generation_candidates if session else []) if item.id == candidate_id),
            None,
        )
        if candidate is None:
            return
        candidate.attempts += 1
        candidate.error = str(exc)
        candidate.status = "rate_limited" if self._is_rate_limit_error(exc) else "failed"
        candidate.retry_after = (
            self._retry_after_for_attempt(candidate.attempts)
            if candidate.status == "rate_limited"
            else None
        )
        candidate.updated_at = datetime.now()
        if session:
            session.updated_at = datetime.now()
        event_name = "api_candidate_rate_limited" if candidate.status == "rate_limited" else "api_tool_generation_failed"
        self._emit_analysis_event(session_id, event_name, self._candidate_event_payload(candidate))

    def _calls_for_candidate(
        self,
        session: ApiMonitorSession,
        candidate: ApiToolGenerationCandidate,
    ) -> list[CapturedApiCall]:
        by_id = {call.id: call for call in session.captured_calls}
        calls = [by_id[call_id] for call_id in candidate.sample_call_ids if call_id in by_id]
        if calls:
            return calls
        return [call for call in session.captured_calls if self._candidate_dedup_key(call) == candidate.dedup_key][:5]

    def _request_summary_for_prune(self, calls: list[CapturedApiCall]) -> str:
        if not calls:
            return "(无请求体)"
        first = calls[0]
        body = first.request.body or ""
        return (body[:500] + "...") if len(body) > 500 else (body or "(无请求体)")

    def _response_summary_for_prune(self, calls: list[CapturedApiCall]) -> str:
        if not calls:
            return "(无响应)"
        first = calls[0]
        if not first.response:
            return "(无响应)"
        parts = [f"状态码: {first.response.status}"]
        if first.response.content_type:
            parts.append(f"Content-Type: {first.response.content_type}")
        body = first.response.body or ""
        if body:
            parts.append("响应体: " + ((body[:800] + "...") if len(body) > 800 else body))
        return "\n".join(parts)

    def _step_summary_for_prune(self, candidate: ApiToolGenerationCandidate) -> str:
        lines = []
        for item in candidate.step_metadata[:3]:
            lines.append(
                f"{item.get('action', '')} {item.get('action_description', '')} "
                f"on {item.get('page_url', '')}"
            )
        return "\n".join(line.strip() for line in lines if line.strip()) or "(无操作摘要)"

    def _candidate_key_for_prune(self, candidate: ApiToolGenerationCandidate) -> str:
        return candidate.dedup_key or f"{candidate.method.upper()} {candidate.url_pattern}"

    def _intent_prune_candidate(
        self,
        session: ApiMonitorSession,
        candidate: ApiToolGenerationCandidate,
        confidence_result,
    ) -> IntentPruneCandidate:
        calls = self._calls_for_candidate(session, candidate)
        return IntentPruneCandidate(
            candidate_key=self._candidate_key_for_prune(candidate),
            method=candidate.method,
            url_pattern=candidate.url_pattern,
            confidence_score=confidence_result.score,
            confidence_reasons=confidence_result.reasons,
            request_summary=self._request_summary_for_prune(calls),
            response_summary=self._response_summary_for_prune(calls),
            step_summary=self._step_summary_for_prune(candidate),
            page_url=candidate.capture_page_url or session.target_url or "",
            title=candidate.capture_title or "",
        )

    def _intent_prune_retry_delay(self, failed_attempts: int) -> float:
        return INTENT_PRUNE_RETRY_BASE_DELAY_S * (2 ** max(failed_attempts - 1, 0))

    def _intent_prune_failure_reason(self, error: str) -> str:
        return f"意图裁剪多次失败，需人工确认：{error or '未知错误'}"

    def _mark_intent_prune_retrying(
        self,
        session: ApiMonitorSession,
        candidates: list[ApiToolGenerationCandidate],
        *,
        error: str,
        retry_after: datetime,
    ) -> None:
        for candidate in candidates:
            candidate.status = "intent_prune_retrying"
            candidate.intent_prune_error = error
            candidate.intent_prune_retry_after = retry_after
            candidate.updated_at = datetime.now()
            self._emit_analysis_event(
                session.id,
                "api_candidate_intent_prune_retrying",
                self._candidate_event_payload(candidate),
            )
        session.updated_at = datetime.now()

    def _failed_intent_prune_result(
        self,
        candidates: list[ApiToolGenerationCandidate],
        *,
        batch_id: str,
        error: str,
    ) -> IntentPruneResult:
        reason = self._intent_prune_failure_reason(error)
        return IntentPruneResult(
            batch_id=batch_id,
            items=[
                IntentPruneItem(
                    candidate_key=self._candidate_key_for_prune(candidate),
                    intent_group="uncertain",
                    intent_score=0,
                    intent_rank=None,
                    intent_reason=reason,
                )
                for candidate in candidates
            ],
        )

    async def _prune_candidates_with_retry(
        self,
        session: ApiMonitorSession,
        candidates: list[ApiToolGenerationCandidate],
        prune_candidates: list[IntentPruneCandidate],
        intent: str,
        *,
        model_config: Optional[Dict] = None,
    ) -> IntentPruneResult:
        batch_id = f"intent_prune_failed_{uuid.uuid4().hex[:12]}"
        if not candidates or not prune_candidates:
            return IntentPruneResult(batch_id=batch_id, items=[])

        last_error = ""
        max_attempts = 1 + INTENT_PRUNE_MAX_RETRIES
        for attempt in range(1, max_attempts + 1):
            for candidate in candidates:
                candidate.status = "intent_pruning"
                candidate.intent_prune_attempts = attempt
                candidate.intent_prune_retry_after = None
                candidate.updated_at = datetime.now()
                self._emit_analysis_event(
                    session.id,
                    "api_candidate_intent_prune_started",
                    self._candidate_event_payload(candidate),
                )
            session.updated_at = datetime.now()

            try:
                async with self._intent_prune_semaphore:
                    result = await asyncio.wait_for(
                        prune_candidates_by_intent(
                            prune_candidates,
                            intent,
                            page_context=session.target_url or "",
                            model_config=model_config,
                        ),
                        timeout=INTENT_PRUNE_TIMEOUT_S,
                    )
                for candidate in candidates:
                    candidate.status = "intent_pruning"
                    candidate.intent_prune_error = ""
                    candidate.intent_prune_retry_after = None
                    candidate.updated_at = datetime.now()
                session.updated_at = datetime.now()
                return result
            except asyncio.TimeoutError:
                last_error = f"意图裁剪超过 {INTENT_PRUNE_TIMEOUT_S:.0f}s"
            except Exception as exc:
                last_error = str(exc) or exc.__class__.__name__

            if attempt <= INTENT_PRUNE_MAX_RETRIES:
                delay = self._intent_prune_retry_delay(attempt)
                retry_after = datetime.now() + timedelta(seconds=delay)
                self._mark_intent_prune_retrying(
                    session,
                    candidates,
                    error=last_error,
                    retry_after=retry_after,
                )
                if delay > 0:
                    await asyncio.sleep(delay)

        # Exhausted all retries — leave candidates in retrying state with last error
        for candidate in candidates:
            candidate.status = "intent_prune_retrying"
            candidate.intent_prune_error = last_error
            candidate.updated_at = datetime.now()
        session.updated_at = datetime.now()

        return self._failed_intent_prune_result(
            candidates,
            batch_id=batch_id,
            error=last_error,
        )

    def _apply_prune_item_to_candidate(
        self,
        session: ApiMonitorSession,
        candidate: ApiToolGenerationCandidate,
        item: IntentPruneItem,
        *,
        batch_id: str,
    ) -> None:
        candidate.intent_group = item.intent_group
        candidate.intent_score = item.intent_score
        candidate.intent_rank = item.intent_rank
        candidate.intent_reason = item.intent_reason
        candidate.intent_batch_id = batch_id
        candidate.intent_prune_retry_after = None
        if item.intent_group in ("adjacent", "bootstrap", "noise"):
            candidate.status = "intent_filtered"
            candidate.intent_filter_reason = item.intent_reason
        elif item.intent_group == "uncertain":
            candidate.status = "pending"
            candidate.intent_filter_reason = item.intent_reason
        candidate.updated_at = datetime.now()
        session.updated_at = datetime.now()

    def _schedule_intent_prune_flush(
        self,
        session_id: str,
        *,
        model_config: Optional[Dict] = None,
        immediate: bool = False,
    ) -> None:
        existing = self._intent_prune_tasks.get(session_id)
        if existing and not existing.done():
            if not immediate:
                return
            existing.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(
            self._delayed_intent_prune_flush(
                session_id,
                model_config=model_config,
                delay=0 if immediate else INTENT_PRUNE_DEBOUNCE_SECONDS,
            )
        )
        self._intent_prune_tasks[session_id] = task

    async def _delayed_intent_prune_flush(
        self,
        session_id: str,
        *,
        model_config: Optional[Dict] = None,
        delay: float = INTENT_PRUNE_DEBOUNCE_SECONDS,
    ) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await self._flush_intent_prune_buffer(session_id, model_config=model_config)
        except asyncio.CancelledError:
            raise
        finally:
            current = asyncio.current_task()
            if self._intent_prune_tasks.get(session_id) is current:
                self._intent_prune_tasks.pop(session_id, None)
            if self._intent_prune_buffers.get(session_id):
                self._schedule_intent_prune_flush(session_id, model_config=model_config)

    async def _flush_intent_prune_buffer(
        self,
        session_id: str,
        *,
        model_config: Optional[Dict] = None,
    ) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            self._intent_prune_buffers.pop(session_id, None)
            return
        candidate_ids = list(self._intent_prune_buffers.pop(session_id, set()))
        candidates = [
            candidate
            for candidate in session.generation_candidates
            if candidate.id in candidate_ids and candidate.status in ("pending", "stale", "failed", "intent_prune_retrying")
        ]
        if not candidates:
            return
        intent = (session.intent or "").strip()
        if not intent:
            for candidate in candidates:
                self._enqueue_generation_candidate(session_id, candidate.id, model_config=model_config)
            return

        prune_candidates = []
        for candidate in candidates:
            samples = self._calls_for_candidate(session, candidate)
            if not samples:
                continue
            confidence_result = score_api_candidate(
                samples,
                action_context=candidate.step_metadata[-1] if candidate.step_metadata else None,
            )
            if confidence_result.score < 80:
                candidate.status = "confidence_rejected"
                candidate.rejection_reason = summarize_rejection_reasons(confidence_result)
                self._emit_analysis_event(session_id, "api_candidate_confidence_rejected", self._candidate_event_payload(candidate))
                continue
            prune_candidates.append(self._intent_prune_candidate(session, candidate, confidence_result))

        if not prune_candidates:
            return

        prune_key_to_candidate = {
            self._candidate_key_for_prune(c): c for c in candidates
        }
        all_items: list[IntentPruneItem] = []
        last_batch_id = ""
        total_chunks = (len(prune_candidates) + INTENT_PRUNE_CHUNK_SIZE - 1) // INTENT_PRUNE_CHUNK_SIZE
        for chunk_idx, chunk_start in enumerate(range(0, len(prune_candidates), INTENT_PRUNE_CHUNK_SIZE)):
            prune_chunk = prune_candidates[chunk_start:chunk_start + INTENT_PRUNE_CHUNK_SIZE]
            candidate_chunk = [
                prune_key_to_candidate[pc.candidate_key]
                for pc in prune_chunk
                if pc.candidate_key in prune_key_to_candidate
            ]
            if not candidate_chunk:
                continue
            logger.info(
                "[IntentPrune] session=%s chunk=%d/%d candidates=%d",
                session_id, chunk_idx + 1, total_chunks, len(prune_chunk),
            )
            chunk_t0 = asyncio.get_event_loop().time()
            chunk_result = await self._prune_candidates_with_retry(
                session,
                candidate_chunk,
                prune_chunk,
                intent,
                model_config=model_config,
            )
            chunk_elapsed = asyncio.get_event_loop().time() - chunk_t0
            group_counts: dict[str, int] = {}
            for item in chunk_result.items:
                group_counts[item.intent_group] = group_counts.get(item.intent_group, 0) + 1
            logger.info(
                "[IntentPrune] session=%s chunk=%d/%d done %.1fs groups=%s",
                session_id, chunk_idx + 1, total_chunks, chunk_elapsed, group_counts,
            )
            all_items.extend(chunk_result.items)
            last_batch_id = chunk_result.batch_id

        by_key = {item.candidate_key: item for item in all_items}
        for candidate in candidates:
            item = by_key.get(self._candidate_key_for_prune(candidate))
            if item is None:
                continue
            self._apply_prune_item_to_candidate(session, candidate, item, batch_id=last_batch_id)
            self._emit_analysis_event(session_id, "api_candidate_intent_pruned", self._candidate_event_payload(candidate))
            if candidate.status not in ("intent_filtered",):
                self._enqueue_generation_candidate(session_id, candidate.id, model_config=model_config, skip_filter=True)

    def _is_rate_limit_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return "429" in text or "rate limit" in text or "too many requests" in text

    def _retry_after_for_attempt(self, attempts: int) -> datetime:
        delay = min(300, 2 ** max(attempts - 1, 0))
        return datetime.now() + timedelta(seconds=delay)

    async def _generate_tool_for_candidate(
        self,
        session_id: str,
        candidate_id: str,
        *,
        model_config: Optional[Dict] = None,
        skip_filter: bool = False,
    ) -> ApiToolDefinition | None:
        session = self._require_session(session_id)
        candidate = next(
            (item for item in session.generation_candidates if item.id == candidate_id),
            None,
        )
        if candidate is None:
            return None

        samples = self._calls_for_candidate(session, candidate)
        if not samples:
            candidate.status = "failed"
            candidate.error = "No captured calls available for this candidate"
            candidate.updated_at = datetime.now()
            return None
        generated_sample_ids = {call.id for call in samples}

        # Round 1: Confidence scoring before LLM generation
        confidence_result = score_api_candidate(
            samples,
            action_context=candidate.step_metadata[-1] if candidate.step_metadata else None,
        )

        if not skip_filter and confidence_result.score < 80:
            candidate.status = "confidence_rejected"
            candidate.rejection_reason = summarize_rejection_reasons(confidence_result)
            candidate.updated_at = datetime.now()
            session.updated_at = datetime.now()
            self._emit_analysis_event(
                session_id, "api_candidate_confidence_rejected",
                {**self._candidate_event_payload(candidate), "score": confidence_result.score},
            )
            return None

        # Round 2: AI intent filter
        intent = session.intent
        if not skip_filter and intent and intent.strip():
            try:
                intent_result = await filter_by_intent(
                    samples, intent.strip(), confidence_result.reasons,
                    model_config=model_config,
                )
                if not intent_result.relevant:
                    final_score = confidence_result.score - 25
                    candidate.status = "intent_filtered"
                    candidate.intent_filter_reason = intent_result.reason
                    candidate.updated_at = datetime.now()
                    session.updated_at = datetime.now()
                    self._emit_analysis_event(
                        session_id, "api_candidate_intent_filtered",
                        {
                            **self._candidate_event_payload(candidate),
                            "score": final_score,
                            "intent_filter_reason": intent_result.reason,
                        },
                    )
                    return None
            except Exception as exc:
                logger.warning("[ApiMonitor] Intent filter failed for candidate %s: %s", candidate_id, exc)

        candidate.status = "running"
        candidate.error = ""
        candidate.updated_at = datetime.now()
        dom_context = json.dumps(candidate.capture_dom_context, ensure_ascii=False, indent=2)

        step_context = ""
        if candidate.step_metadata:
            lines = []
            for sm in candidate.step_metadata[:5]:
                lines.append(
                    f"- 操作 '{sm.get('action_description', '')}' "
                    f"在页面 {sm.get('page_url', '')} 触发了 {sm.get('call_count', 0)} 次调用"
                )
            step_context = "\n此 API 在以下操作中被观察到:\n" + "\n".join(lines)

        try:
            yaml_def = await generate_tool_definition(
                method=candidate.method,
                url_pattern=candidate.url_pattern,
                samples=samples,
                page_context=candidate.capture_page_url or session.target_url or "",
                dom_context=dom_context,
                step_context=step_context,
                model_config=model_config,
            )
        except Exception as exc:
            candidate.attempts += 1
            candidate.error = str(exc)
            if self._is_rate_limit_error(exc):
                candidate.status = "rate_limited"
                candidate.retry_after = self._retry_after_for_attempt(candidate.attempts)
                self._emit_analysis_event(session_id, "api_candidate_rate_limited", self._candidate_event_payload(candidate))
            else:
                candidate.status = "failed"
                candidate.retry_after = None
                self._emit_analysis_event(session_id, "api_tool_generation_failed", self._candidate_event_payload(candidate))
            candidate.updated_at = datetime.now()
            session.updated_at = datetime.now()
            return None

        from backend.rpa.api_monitor_mcp_contract import parse_api_monitor_tool_yaml

        contract = parse_api_monitor_tool_yaml(yaml_def)
        name, description = _metadata_from_contract(
            contract,
            method=candidate.method,
            url_pattern=candidate.url_pattern,
        )

        existing = None
        if candidate.tool_id:
            existing = next(
                (tool for tool in session.tool_definitions if tool.id == candidate.tool_id),
                None,
            )
        if existing is None:
            existing = next(
                (tool for tool in session.tool_definitions if tool.generation_candidate_id == candidate.id),
                None,
            )
        if existing is None:
            tool = ApiToolDefinition(
                session_id=session_id,
                name=name,
                description=description,
                method=candidate.method,
                url_pattern=candidate.url_pattern,
                yaml_definition=yaml_def,
                source_calls=[call.id for call in samples],
                source="auto",
                generation_candidate_id=candidate.id,
            )
            session.tool_definitions.append(tool)
        else:
            tool = existing
            previous_selected = tool.selected
            tool.name = name
            tool.description = description
            tool.method = candidate.method
            tool.url_pattern = candidate.url_pattern
            tool.yaml_definition = yaml_def
            tool.source_calls = [call.id for call in samples]
            tool.generation_candidate_id = candidate.id
            tool.selected = previous_selected
            tool.updated_at = datetime.now()

        tool.validation_status = "valid" if contract.valid else "invalid"
        tool.validation_errors = contract.validation_errors if contract.validation_errors else []
        tool.confidence = confidence_result.confidence
        tool.score = confidence_result.score
        reserve = candidate.intent_group == "supporting" or (skip_filter and candidate.intent_group in ("uncertain", "adjacent", "bootstrap", "noise"))
        tool.is_reserve = reserve
        tool.intent_group = candidate.intent_group
        tool.intent_reason = candidate.intent_reason or candidate.intent_filter_reason
        tool.intent_score = candidate.intent_score
        if existing is None:
            tool.selected = not reserve
        elif reserve:
            tool.selected = False
        tool.confidence_reasons = confidence_result.reasons
        tool.source_evidence = confidence_result.evidence_summary
        new_tools = [tool]
        self._dedup_session_tools(session_id, new_tools)

        if tool.id in {item.id for item in session.tool_definitions}:
            candidate.tool_id = tool.id
        else:
            candidate.tool_id = None
        if any(call_id not in generated_sample_ids for call_id in candidate.sample_call_ids):
            candidate.status = "stale"
        else:
            candidate.status = "generated"
        candidate.error = ""
        candidate.updated_at = datetime.now()
        session.updated_at = datetime.now()
        self._emit_analysis_event(
            session_id,
            "api_tool_generated",
            {
                **self._candidate_event_payload(candidate),
                "tool": tool.model_dump(mode="json"),
            },
        )
        return tool

    async def _capture_generation_dom_context(self, session_id: str) -> tuple[dict, str, str, str]:
        page = self._pages.get(session_id)
        if not page:
            return {}, "", "", ""
        try:
            dom_data = await asyncio.wait_for(
                page.evaluate(_SCAN_DOM_CONTEXT_JS),
                timeout=DOM_CONTEXT_SCAN_TIMEOUT_S,
            )
        except Exception:
            dom_data = {}
        try:
            observation = await self._observe_directed_page(page, "")
            return dom_data, observation.get("url", ""), observation.get("title", ""), observation.get("dom_digest", "")
        except Exception:
            return dom_data, getattr(page, "url", "") or "", "", ""

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
        if not calls:
            return []
        session = self._require_session(session_id)
        evidence_ids = {call.id for call in session.evidence_calls}
        captured_ids = {call.id for call in session.captured_calls}
        generation_calls: list[CapturedApiCall] = []
        for call in calls:
            if call.id in evidence_ids:
                continue
            if call.id not in captured_ids:
                session.captured_calls.append(call)
                captured_ids.add(call.id)
            generation_calls.append(call)
        if not generation_calls:
            return []

        if dom_context is None:
            dom_context, page_url, title, dom_digest = await self._capture_generation_dom_context(session_id)

        changed: list[ApiToolGenerationCandidate] = []
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
            event_name = "api_candidate_created" if _created else "api_candidate_updated"
            self._emit_analysis_event(session_id, event_name, self._candidate_event_payload(candidate))
            changed.append(candidate)
            if candidate.status in ("pending", "stale", "failed"):
                if (session.intent or "").strip():
                    self._intent_prune_buffers[session_id].add(candidate.id)
                    self._schedule_intent_prune_flush(
                        session_id,
                        model_config=model_config,
                        immediate=len(self._intent_prune_buffers[session_id]) >= INTENT_PRUNE_MAX_BATCH_SIZE,
                    )
                else:
                    self._enqueue_generation_candidate(session_id, candidate.id, model_config=model_config)
        return changed

    def _store_evidence_calls(
        self,
        session_id: str,
        calls: list[CapturedApiCall],
    ) -> list[CapturedApiCall]:
        if not calls:
            return []
        session = self._require_session(session_id)
        existing_ids = {
            *(call.id for call in session.captured_calls),
            *(call.id for call in session.evidence_calls),
        }
        added: list[CapturedApiCall] = []
        for call in calls:
            if call.id in existing_ids:
                continue
            session.evidence_calls.append(call)
            existing_ids.add(call.id)
            added.append(call)
        if added:
            session.updated_at = datetime.now()
        return added

    def _token_flow_calls(self, session_id: str) -> list[CapturedApiCall]:
        session = self._require_session(session_id)
        by_id: dict[str, CapturedApiCall] = {}
        for call in [*session.evidence_calls, *session.captured_calls]:
            by_id.setdefault(call.id, call)
        return list(by_id.values())

    def reconcile_generation_candidates(
        self,
        session_id: str,
        *,
        enqueue: bool = True,
    ) -> list[ApiToolGenerationCandidate]:
        session = self._require_session(session_id)
        changed: list[ApiToolGenerationCandidate] = []

        for call in session.captured_calls:
            candidate, created = self._upsert_generation_candidate(session_id, call)
            if created or candidate.status in ("pending", "failed", "rate_limited", "stale", "confidence_rejected", "intent_filtered", "intent_review"):
                changed.append(candidate)

        if enqueue:
            for candidate in changed:
                self._enqueue_generation_candidate(session_id, candidate.id)

        return changed

    def list_generation_candidates(self, session_id: str) -> list[ApiToolGenerationCandidate]:
        self.reconcile_generation_candidates(session_id, enqueue=False)
        return list(self._require_session(session_id).generation_candidates)

    def _candidate_has_dom_context(self, candidate: ApiToolGenerationCandidate) -> bool:
        return bool(candidate.capture_dom_context)

    def _candidate_for_tool_regeneration(
        self,
        session: ApiMonitorSession,
        tool: ApiToolDefinition,
    ) -> ApiToolGenerationCandidate | None:
        source_call_ids = set(tool.source_calls)
        source_calls = [call for call in session.captured_calls if call.id in source_call_ids]
        if not source_calls:
            return None
        dedup_key_value = self._candidate_dedup_key(source_calls[0])

        if tool.generation_candidate_id:
            candidate = next(
                (item for item in session.generation_candidates if item.id == tool.generation_candidate_id),
                None,
            )
            if candidate is not None and self._candidate_has_dom_context(candidate):
                return candidate

        return next(
            (
                item
                for item in session.generation_candidates
                if item.dedup_key == dedup_key_value and self._candidate_has_dom_context(item)
            ),
            None,
        )

    async def regenerate_tool(
        self,
        session_id: str,
        tool_id: str,
        model_config: dict | None = None,
    ):
        """Regenerate a tool's YAML through the generation-candidate main path."""
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        tool = next((t for t in session.tool_definitions if t.id == tool_id), None)
        if not tool:
            raise ValueError(f"Tool {tool_id} not found")

        source_calls = [c for c in session.captured_calls if c.id in tool.source_calls]
        if not source_calls:
            raise ValueError(f"No source calls found for tool {tool_id}")

        candidate = self._candidate_for_tool_regeneration(session, tool)
        if candidate is None:
            raise ValueError(f"Tool {tool_id} is missing generation candidate context")
        if not self._candidate_has_dom_context(candidate):
            raise ValueError(f"Tool {tool_id} is missing historical DOM context")

        candidate.tool_id = tool.id
        candidate.method = tool.method
        candidate.url_pattern = tool.url_pattern
        candidate.source_call_ids = list(dict.fromkeys([*candidate.source_call_ids, *tool.source_calls]))
        for call_id in tool.source_calls:
            if call_id not in candidate.sample_call_ids and len(candidate.sample_call_ids) < 5:
                candidate.sample_call_ids.append(call_id)
        tool.generation_candidate_id = candidate.id
        candidate.status = "pending"
        candidate.error = ""
        candidate.retry_after = None
        candidate.updated_at = datetime.now()
        session.updated_at = datetime.now()

        regenerated = await self._generate_tool_for_candidate(
            session_id,
            candidate.id,
            model_config=model_config,
            skip_filter=True,
        )
        if regenerated is None:
            raise ValueError(candidate.error or f"Failed to regenerate tool {tool_id}")
        return regenerated

    def retry_generation_candidate(
        self,
        session_id: str,
        candidate_id: str,
        *,
        model_config: Optional[Dict] = None,
    ) -> ApiToolGenerationCandidate:
        session = self._require_session(session_id)
        candidate = next(
            (item for item in session.generation_candidates if item.id == candidate_id),
            None,
        )
        if candidate is None:
            raise ValueError("Generation candidate not found")
        candidate.status = "pending"
        candidate.error = ""
        candidate.retry_after = None
        candidate.updated_at = datetime.now()
        self._enqueue_generation_candidate(session_id, candidate.id, model_config=model_config)
        return candidate

    def delete_generation_candidate(
        self,
        session_id: str,
        candidate_id: str,
    ) -> None:
        session = self._require_session(session_id)
        idx = next(
            (i for i, item in enumerate(session.generation_candidates) if item.id == candidate_id),
            None,
        )
        if idx is None:
            raise ValueError("Generation candidate not found")
        session.generation_candidates.pop(idx)

    def force_generate_candidate(
        self,
        session_id: str,
        candidate_id: str,
        *,
        model_config: Optional[Dict] = None,
    ) -> ApiToolGenerationCandidate:
        session = self._require_session(session_id)
        candidate = next(
            (item for item in session.generation_candidates if item.id == candidate_id),
            None,
        )
        if candidate is None:
            raise ValueError("Generation candidate not found")
        if candidate.status not in ("confidence_rejected", "intent_filtered", "intent_review"):
            raise ValueError("Only rejected/filtered/review candidates can be force-generated")
        candidate.status = "pending"
        candidate.error = ""
        candidate.retry_after = None
        candidate.rejection_reason = None
        candidate.intent_filter_reason = None
        candidate.updated_at = datetime.now()
        self._enqueue_generation_candidate(session_id, candidate.id, model_config=model_config, skip_filter=True)
        return candidate

    def _require_session(self, session_id: str) -> ApiMonitorSession:
        """Get session or raise ValueError."""
        session = self.sessions.get(session_id)
        if session is None:
            raise ValueError(f"API Monitor session {session_id} not found")
        return session

    def _require_page(self, session_id: str) -> Page:
        """Get page or raise ValueError."""
        page = self._pages.get(session_id)
        if page is None:
            raise ValueError(f"No page for API Monitor session {session_id}")
        return page

    def _session_id_from_page(self, page: Page) -> Optional[str]:
        """Reverse lookup: find session_id from a Page object."""
        for sid, p in self._pages.items():
            if p is page:
                return sid
        return None

    def _mark_action(self, session_id: str) -> None:
        self._last_action_at[session_id] = time.monotonic()

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

    async def _install_user_action_capture(self, session_id: str, context) -> None:
        async def on_user_action(source, event_json: str):
            await self._handle_user_action(session_id, event_json)

        try:
            await context.expose_binding("__apiMonitorAction", on_user_action, handle=False)
            await context.add_init_script(_USER_ACTION_CAPTURE_JS)
        except Exception as exc:
            logger.debug("[ApiMonitor] User action capture install failed: %s", exc)

    def _action_window_matched(self, session_id: str, window_seconds: float = 2.0) -> bool:
        last_action_at = self._last_action_at.get(session_id)
        return last_action_at is not None and (time.monotonic() - last_action_at) <= window_seconds

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

        method_upper = request_method.upper()
        for cdp_id, cdp_ev in by_cdp.items():
            if cdp_id in self._cdp_to_pw.get(session_id, {}):
                continue
            if (cdp_ev.get("_cdp_url") == request_url
                    and cdp_ev.get("_cdp_method") == method_upper):
                if frame_url and cdp_ev.get("frame_url") != frame_url:
                    logger.debug(
                        "[ApiMonitor] Retry evidence: frame_url mismatch for %s (expected=%s got=%s)",
                        request_url[:80], frame_url[:60], cdp_ev.get("frame_url", "")[:60],
                    )
                    continue
                # Update the actual _cdp_to_pw mapping
                self._cdp_to_pw[session_id][cdp_id] = 0
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

    def _cleanup_request_evidence(self, session_id: str, cdp_request_id: str) -> None:
        self._request_evidence.get(session_id, {}).pop(cdp_request_id, None)
        self._cdp_to_pw.get(session_id, {}).pop(cdp_request_id, None)

    def _cleanup_evidence_by_request_id(self, session_id: str, pw_request_id: str) -> None:
        """Clean up CDP evidence linked to a Playwright request ID (string form of id())."""
        cdp_map = self._cdp_to_pw.get(session_id, {})
        cdp_ids = [cdp_id for cdp_id, stored_pw_id in cdp_map.items()
                    if str(stored_pw_id) == pw_request_id]
        for cdp_id in cdp_ids:
            self._cleanup_request_evidence(session_id, cdp_id)

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


def _metadata_from_contract(contract, *, method: str, url_pattern: str) -> tuple[str, str]:
    name = str(getattr(contract, "name", "") or "").strip()
    description = str(getattr(contract, "description", "") or "").strip()
    if not name:
        name = _fallback_tool_name(method, url_pattern)
    if not description:
        description = (
            "Generated API tool (YAML validation failed)"
            if not getattr(contract, "valid", False)
            else "Generated API tool"
        )
    return name, description


def _fallback_tool_name(method: str, url_pattern: str) -> str:
    path = str(url_pattern or "").split("?", 1)[0]
    parts = [str(method or "").lower(), *re.findall(r"[A-Za-z0-9]+", path)]
    name = re.sub(r"_+", "_", "_".join(part for part in parts if part)).strip("_").lower()
    if not name:
        return "api_tool"
    if name[0].isdigit():
        return f"api_{name}"
    return name


# ── Global singleton ─────────────────────────────────────────────────

api_monitor_manager = ApiMonitorSessionManager()
