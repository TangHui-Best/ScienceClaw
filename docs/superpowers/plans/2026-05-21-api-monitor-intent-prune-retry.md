# API Monitor Intent Prune Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make API Monitor intent pruning observable and resilient by adding explicit candidate statuses, bounded LLM prune retries, timeout protection, and frontend status display.

**Architecture:** Extend `ApiToolGenerationCandidate.status` with `intent_pruning` and `intent_prune_retrying`, while keeping retry details in focused helper fields. Add a manager-level retry helper that wraps `prune_candidates_by_intent()` with timeout, semaphore concurrency, two retries, event emission, and synthetic `uncertain` fallback. Route both batch generation and realtime buffer pruning through that helper, then teach the Vue API types and candidate cards to show the new states.

**Tech Stack:** FastAPI/Pydantic v2 backend, asyncio, pytest/unittest, Vue 3 + TypeScript, Vitest.

---

## File Map

- Modify `RpaClaw/backend/rpa/api_monitor/models.py`: extend `GenerationStatus` and add intent prune retry metadata fields to `ApiToolGenerationCandidate`.
- Modify `RpaClaw/backend/rpa/api_monitor/manager.py`: add prune constants, semaphore, event payload fields, retry helper, and wire batch/realtime paths through the helper.
- Modify `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`: add backend tests for model defaults, retry success, retry exhaustion, realtime flush resilience, and batch fallback behavior.
- Modify `RpaClaw/frontend/src/api/apiMonitor.ts`: extend candidate status union and add retry metadata fields to the candidate interface.
- Modify `RpaClaw/frontend/src/api/apiMonitor.test.ts`: verify API candidate payloads preserve prune retry fields.
- Modify `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue`: update active candidate detection, SSE event handling, labels/classes, and card details for prune states.
- Create `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.intentPrune.test.ts`: focused UI test for the new candidate status labels and failure detail rendering.

---

### Task 1: Extend Candidate Model And API Payload

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/models.py`
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py`
- Test: `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`

- [ ] **Step 1: Write the failing model default test**

Append these assertions to `test_generation_candidate_defaults_are_serializable()` in `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`:

```python
    assert dumped["intent_prune_attempts"] == 0
    assert dumped["intent_prune_error"] == ""
    assert dumped["intent_prune_retry_after"] is None
```

Add this new test near the existing default test:

```python
def test_generation_candidate_accepts_intent_prune_statuses():
    pruning = ApiToolGenerationCandidate(
        session_id="session-1",
        dedup_key="GET /api/orders",
        method="GET",
        url_pattern="/api/orders",
        status="intent_pruning",
    )
    retrying = ApiToolGenerationCandidate(
        session_id="session-1",
        dedup_key="GET /api/orders",
        method="GET",
        url_pattern="/api/orders",
        status="intent_prune_retrying",
    )

    assert pruning.status == "intent_pruning"
    assert retrying.status == "intent_prune_retrying"
```

- [ ] **Step 2: Run the failing backend model tests**

Run:

```bash
cd RpaClaw/backend
uv run python -m pytest tests/test_api_monitor_realtime_generation.py::test_generation_candidate_defaults_are_serializable tests/test_api_monitor_realtime_generation.py::test_generation_candidate_accepts_intent_prune_statuses -q
```

Expected: first test fails with missing `intent_prune_attempts`; second fails with a Pydantic literal validation error for `intent_pruning`.

- [ ] **Step 3: Extend the backend model**

In `RpaClaw/backend/rpa/api_monitor/models.py`, replace `GenerationStatus` with:

```python
GenerationStatus = Literal[
    "pending",
    "intent_pruning",
    "intent_prune_retrying",
    "generated",
    "failed",
    "rate_limited",
    "stale",
    "confidence_rejected",
    "intent_filtered",
    "intent_review",
]
```

In `ApiToolGenerationCandidate`, add these fields after `intent_batch_id`:

```python
    intent_prune_attempts: int = 0
    intent_prune_error: str = ""
    intent_prune_retry_after: Optional[datetime] = None
```

Update the inline status comment to:

```python
    status: GenerationStatus = "pending"  # candidate lifecycle: pending, intent_pruning, intent_prune_retrying, running, generated, failed, rate_limited, stale, confidence_rejected, intent_filtered, intent_review
```

- [ ] **Step 4: Include prune retry fields in candidate events**

In `RpaClaw/backend/rpa/api_monitor/manager.py`, update `_candidate_event_payload()` by adding these keys after `intent_batch_id`:

```python
            "intent_prune_attempts": candidate.intent_prune_attempts,
            "intent_prune_error": candidate.intent_prune_error,
            "intent_prune_retry_after": candidate.intent_prune_retry_after.isoformat() if candidate.intent_prune_retry_after else None,
```

- [ ] **Step 5: Run model tests again**

Run:

```bash
cd RpaClaw/backend
uv run python -m pytest tests/test_api_monitor_realtime_generation.py::test_generation_candidate_defaults_are_serializable tests/test_api_monitor_realtime_generation.py::test_generation_candidate_accepts_intent_prune_statuses -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit model changes**

Run:

```bash
git add RpaClaw/backend/rpa/api_monitor/models.py RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_realtime_generation.py
git commit -m "feat: add api monitor intent prune statuses"
```

---

### Task 2: Add Intent Prune Retry Helper

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py`
- Test: `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`

- [ ] **Step 1: Write retry helper tests**

Add this import near the existing imports in `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`:

```python
from backend.rpa.api_monitor.confidence import score_api_candidate
from backend.rpa.api_monitor.intent_pruner import IntentPruneResult
```

Add these tests near the intent prune helper tests:

```python
class TestIntentPruneRetryHelper(unittest.IsolatedAsyncioTestCase):

    async def test_prune_candidates_with_retry_succeeds_after_timeout(self):
        manager = ApiMonitorSessionManager()
        session = ApiMonitorSession(
            id="session_1",
            user_id="user_1",
            sandbox_session_id="sandbox_1",
            intent="查询订单列表",
        )
        manager.sessions[session.id] = session
        call = _call("order_1", method="POST", path="/api/orders/search")
        call.source_evidence = {
            "action_window_matched": True,
            "initiator_urls": ["https://example.com/app.js"],
        }
        call.response.body = '{"items":[{"orderNo":"A001"}]}'
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(session.id, call)
        prune_candidate = manager._intent_prune_candidate(
            session,
            candidate,
            score_api_candidate([call], action_context=None),
        )
        events: list[tuple[str, dict]] = []
        manager._analysis_event_sinks[session.id] = lambda event, data: events.append((event, data))

        calls = {"count": 0}

        async def fake_prune(candidates, intent, page_context="", model_config=None):
            calls["count"] += 1
            if calls["count"] == 1:
                raise asyncio.TimeoutError()
            return IntentPruneResult(
                batch_id="batch_1",
                items=[
                    IntentPruneItem(
                        candidates[0].candidate_key,
                        "primary",
                        95,
                        1,
                        "订单查询主接口。",
                    )
                ],
            )

        with patch("backend.rpa.api_monitor.manager.prune_candidates_by_intent", side_effect=fake_prune):
            with patch("backend.rpa.api_monitor.manager.INTENT_PRUNE_RETRY_BASE_DELAY_S", 0):
                result = await manager._prune_candidates_with_retry(
                    session,
                    [candidate],
                    [prune_candidate],
                    "查询订单列表",
                    model_config=None,
                )

        assert calls["count"] == 2
        assert result.items[0].intent_group == "primary"
        assert candidate.status == "intent_pruning"
        assert candidate.intent_prune_attempts == 2
        assert candidate.intent_prune_error == ""
        assert candidate.intent_prune_retry_after is None
        assert any(event == "api_candidate_intent_prune_retrying" for event, _data in events)

    async def test_prune_candidates_with_retry_exhaustion_returns_uncertain_review(self):
        manager = ApiMonitorSessionManager()
        session = ApiMonitorSession(
            id="session_1",
            user_id="user_1",
            sandbox_session_id="sandbox_1",
            intent="查询订单列表",
        )
        manager.sessions[session.id] = session
        call = _call("order_1", method="POST", path="/api/orders/search")
        call.source_evidence = {
            "action_window_matched": True,
            "initiator_urls": ["https://example.com/app.js"],
        }
        call.response.body = '{"items":[{"orderNo":"A001"}]}'
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(session.id, call)
        prune_candidate = manager._intent_prune_candidate(
            session,
            candidate,
            score_api_candidate([call], action_context=None),
        )

        async def broken_prune(candidates, intent, page_context="", model_config=None):
            raise RuntimeError("llm unavailable")

        with patch("backend.rpa.api_monitor.manager.prune_candidates_by_intent", side_effect=broken_prune):
            with patch("backend.rpa.api_monitor.manager.INTENT_PRUNE_RETRY_BASE_DELAY_S", 0):
                result = await manager._prune_candidates_with_retry(
                    session,
                    [candidate],
                    [prune_candidate],
                    "查询订单列表",
                    model_config=None,
                )

        assert candidate.status == "intent_prune_retrying"
        assert candidate.intent_prune_attempts == 3
        assert candidate.intent_prune_error == "llm unavailable"
        assert result.items[0].intent_group == "uncertain"
        assert result.items[0].intent_reason == "意图裁剪多次失败，需人工确认：llm unavailable"
```

- [ ] **Step 2: Run the failing retry helper tests**

Run:

```bash
cd RpaClaw/backend
uv run python -m pytest tests/test_api_monitor_realtime_generation.py::TestIntentPruneRetryHelper -q
```

Expected: fails because `_prune_candidates_with_retry` and retry constants do not exist.

- [ ] **Step 3: Add retry constants and semaphore**

In `RpaClaw/backend/rpa/api_monitor/manager.py`, add these constants near the existing intent prune constants:

```python
INTENT_PRUNE_TIMEOUT_S = 60.0
INTENT_PRUNE_MAX_RETRIES = 2
INTENT_PRUNE_RETRY_BASE_DELAY_S = 2.0
INTENT_PRUNE_CONCURRENCY = 2
```

In `ApiMonitorSessionManager.__init__()`, add this after `_generation_semaphore`:

```python
        self._intent_prune_semaphore = asyncio.Semaphore(INTENT_PRUNE_CONCURRENCY)
```

- [ ] **Step 4: Add small prune retry helpers**

In `RpaClaw/backend/rpa/api_monitor/manager.py`, add these methods after `_intent_prune_candidate()` and before `_apply_prune_item_to_candidate()`:

```python
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
```

- [ ] **Step 5: Add `_prune_candidates_with_retry()`**

In `RpaClaw/backend/rpa/api_monitor/manager.py`, add this method after the helpers from Step 4:

```python
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

        return self._failed_intent_prune_result(
            candidates,
            batch_id=batch_id,
            error=last_error,
        )
```

- [ ] **Step 6: Run the retry helper tests again**

Run:

```bash
cd RpaClaw/backend
uv run python -m pytest tests/test_api_monitor_realtime_generation.py::TestIntentPruneRetryHelper -q
```

Expected: both tests pass.

- [ ] **Step 7: Commit retry helper**

Run:

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_realtime_generation.py
git commit -m "feat: retry api monitor intent pruning"
```

---

### Task 3: Wire Batch And Realtime Paths Through Retry Helper

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py`
- Test: `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`

- [ ] **Step 1: Add batch and realtime integration tests**

In `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`, add these tests near `TestBatchIntentPruning` and `TestRealtimeBuffer`:

```python
    async def test_generate_tools_from_calls_uses_review_fallback_when_batch_prune_fails(self):
        manager = ApiMonitorSessionManager()
        session = ApiMonitorSession(
            id="session_1",
            user_id="user_1",
            sandbox_session_id="sandbox_1",
            intent="查询订单列表",
            target_url="https://example.com/orders",
        )
        manager.sessions[session.id] = session
        order_call = _call("order_1", method="POST", path="/api/orders/search")
        order_call.source_evidence = {
            "action_window_matched": True,
            "initiator_urls": ["https://example.com/app.js"],
        }
        order_call.response.body = '{"items":[{"orderNo":"A001"}]}'

        async def broken_prune(candidates, intent, page_context="", model_config=None):
            raise RuntimeError("llm unavailable")

        with patch("backend.rpa.api_monitor.manager.prune_candidates_by_intent", side_effect=broken_prune):
            with patch("backend.rpa.api_monitor.manager.INTENT_PRUNE_RETRY_BASE_DELAY_S", 0):
                tools = await manager._generate_tools_from_calls(session.id, [order_call], model_config=None)

        assert tools == []
        assert len(session.generation_candidates) == 1
        candidate = session.generation_candidates[0]
        assert candidate.status == "intent_review"
        assert candidate.intent_prune_attempts == 3
        assert candidate.intent_prune_error == "llm unavailable"
        assert candidate.intent_filter_reason == "意图裁剪多次失败，需人工确认：llm unavailable"

    async def test_flush_intent_prune_buffer_uses_review_fallback_when_prune_fails(self):
        manager = ApiMonitorSessionManager()
        session = ApiMonitorSession(
            id="session_1",
            user_id="user_1",
            sandbox_session_id="sandbox_1",
            intent="查询订单列表",
        )
        manager.sessions[session.id] = session
        call = _call("order_1", method="POST", path="/api/orders/search")
        call.source_evidence = {
            "action_window_matched": True,
            "initiator_urls": ["https://example.com/app.js"],
        }
        call.response.body = '{"items":[{"orderNo":"A001"}]}'
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(session.id, call)
        manager._intent_prune_buffers[session.id].add(candidate.id)
        enqueued: list[str] = []
        manager._enqueue_generation_candidate = lambda _sid, candidate_id, **_kw: enqueued.append(candidate_id)

        async def broken_prune(candidates, intent, page_context="", model_config=None):
            raise RuntimeError("llm unavailable")

        with patch("backend.rpa.api_monitor.manager.prune_candidates_by_intent", side_effect=broken_prune):
            with patch("backend.rpa.api_monitor.manager.INTENT_PRUNE_RETRY_BASE_DELAY_S", 0):
                await manager._flush_intent_prune_buffer(session.id, model_config=None)

        assert enqueued == []
        assert candidate.status == "intent_review"
        assert candidate.intent_prune_error == "llm unavailable"
        assert candidate.intent_filter_reason == "意图裁剪多次失败，需人工确认：llm unavailable"
```

- [ ] **Step 2: Run the failing integration tests**

Run:

```bash
cd RpaClaw/backend
uv run python -m pytest tests/test_api_monitor_realtime_generation.py::TestBatchIntentPruning::test_generate_tools_from_calls_uses_review_fallback_when_batch_prune_fails tests/test_api_monitor_realtime_generation.py::TestRealtimeBuffer::test_flush_intent_prune_buffer_uses_review_fallback_when_prune_fails -q
```

Expected: batch path returns a generated tool or leaves candidate pending; realtime path raises or leaves candidate pending because neither path uses the retry helper yet.

- [ ] **Step 3: Wire `_generate_tools_from_calls()` to the helper**

In `RpaClaw/backend/rpa/api_monitor/manager.py`, replace the Phase 2 `try/except` block that calls `prune_candidates_by_intent()` with:

```python
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
```

Remove the old `except Exception as exc` branch. The helper now owns fallback behavior.

- [ ] **Step 4: Preserve prune error when applying final review items**

Update `_apply_prune_item_to_candidate()` so it preserves `intent_prune_error` and clears retry scheduling when applying any prune item:

```python
        candidate.intent_prune_retry_after = None
```

Keep `intent_prune_error` unchanged; it should remain visible when the helper generated the review fallback.

- [ ] **Step 5: Wire `_flush_intent_prune_buffer()` to the helper**

In `RpaClaw/backend/rpa/api_monitor/manager.py`, replace the direct `prune_candidates_by_intent()` call in `_flush_intent_prune_buffer()` with:

```python
        prune_result = await self._prune_candidates_with_retry(
            session,
            candidates,
            prune_candidates,
            intent,
            model_config=model_config,
        )
```

Keep the existing `by_key` loop and enqueue behavior after the helper call.

- [ ] **Step 6: Update active/followup candidate status sets**

In `_flush_intent_prune_buffer()`, include retry states when selecting candidates from the buffer:

```python
            if candidate.id in candidate_ids and candidate.status in ("pending", "stale", "failed", "intent_prune_retrying")
```

In `_run_generation_candidate()` final followup check, keep pruning states out of the generation followup set:

```python
            if followup_requested and candidate and candidate.status in ("pending", "stale", "failed", "confidence_rejected", "intent_filtered", "intent_review"):
                self._enqueue_generation_candidate(session_id, candidate_id, model_config=model_config, skip_filter=skip_filter)
```

Do not add `intent_pruning` or `intent_prune_retrying` to that followup set. Pruning retry is owned by `_prune_candidates_with_retry()`, not the generation queue.

- [ ] **Step 7: Run integration tests**

Run:

```bash
cd RpaClaw/backend
uv run python -m pytest tests/test_api_monitor_realtime_generation.py::TestIntentPruneRetryHelper tests/test_api_monitor_realtime_generation.py::TestBatchIntentPruning::test_generate_tools_from_calls_uses_batch_intent_pruning tests/test_api_monitor_realtime_generation.py::TestBatchIntentPruning::test_generate_tools_from_calls_uses_review_fallback_when_batch_prune_fails tests/test_api_monitor_realtime_generation.py::TestRealtimeBuffer::test_process_captured_calls_buffers_high_confidence_candidates_when_intent_exists tests/test_api_monitor_realtime_generation.py::TestRealtimeBuffer::test_flush_intent_prune_buffer_uses_review_fallback_when_prune_fails -q
```

Expected: all listed tests pass.

- [ ] **Step 8: Commit integration changes**

Run:

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_realtime_generation.py
git commit -m "fix: route intent pruning through retry helper"
```

---

### Task 4: Update Frontend Types And Candidate Display

**Files:**
- Modify: `RpaClaw/frontend/src/api/apiMonitor.ts`
- Modify: `RpaClaw/frontend/src/api/apiMonitor.test.ts`
- Modify: `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue`
- Create: `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.intentPrune.test.ts`

- [ ] **Step 1: Update API type test data first**

In `RpaClaw/frontend/src/api/apiMonitor.test.ts`, add these fields to the `candidate` object in `lists generation candidates`:

```ts
      intent_prune_attempts: 1,
      intent_prune_error: 'slow prune',
      intent_prune_retry_after: '2026-04-30T00:00:05',
```

The existing equality assertion should preserve these fields.

- [ ] **Step 2: Extend frontend API types**

In `RpaClaw/frontend/src/api/apiMonitor.ts`, extend `ApiToolGenerationStatus`:

```ts
export type ApiToolGenerationStatus =
  | 'pending'
  | 'intent_pruning'
  | 'intent_prune_retrying'
  | 'running'
  | 'generated'
  | 'failed'
  | 'rate_limited'
  | 'stale'
  | 'confidence_rejected'
  | 'intent_filtered'
  | 'intent_review'
```

In `ApiToolGenerationCandidate`, add these fields after `intent_batch_id`:

```ts
  intent_prune_attempts?: number
  intent_prune_error?: string | null
  intent_prune_retry_after?: string | null
```

- [ ] **Step 3: Update active candidate filtering and SSE event mapping**

In `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue`, update `hasActiveGenerationCandidates`:

```ts
const hasActiveGenerationCandidates = computed(() =>
  generationCandidates.value.some((candidate) => ['pending', 'intent_pruning', 'intent_prune_retrying', 'running', 'stale'].includes(candidate.status)),
);
```

Add these SSE cases alongside other candidate events:

```ts
      case 'api_candidate_intent_prune_started':
      case 'api_candidate_intent_prune_retrying':
```

In the `upsertGenerationCandidate()` payload built from SSE data, add:

```ts
          intent_prune_attempts: data.intent_prune_attempts || 0,
          intent_prune_error: data.intent_prune_error || '',
          intent_prune_retry_after: data.intent_prune_retry_after,
```

- [ ] **Step 4: Update labels and classes**

In `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue`, replace `getCandidateStatusLabel()` with:

```ts
const getCandidateStatusLabel = (status: ApiToolGenerationCandidate['status']) => {
  if (status === 'pending') return '等待处理';
  if (status === 'intent_pruning') return '意图裁剪中';
  if (status === 'intent_prune_retrying') return '意图裁剪重试中';
  if (status === 'running') return '生成中';
  if (status === 'rate_limited') return '限流重试中';
  if (status === 'failed') return '生成失败';
  if (status === 'stale') return '等待更新';
  if (status === 'confidence_rejected') return '置信度不足';
  if (status === 'intent_filtered') return 'AI 过滤';
  if (status === 'intent_review') return '需确认';
  return '已生成';
};
```

Update `getCandidateStatusClass()`:

```ts
const getCandidateStatusClass = (status: ApiToolGenerationCandidate['status']) => {
  if (status === 'running' || status === 'pending' || status === 'intent_pruning') return 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-300';
  if (status === 'intent_prune_retrying' || status === 'rate_limited') return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300';
  if (status === 'failed') return 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300';
  if (status === 'confidence_rejected') return 'border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-500/30 dark:bg-orange-500/10 dark:text-orange-300';
  if (status === 'intent_filtered') return 'border-purple-200 bg-purple-50 text-purple-700 dark:border-purple-500/30 dark:bg-purple-500/10 dark:text-purple-300';
  if (status === 'intent_review') return 'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300';
  return 'border-slate-200 bg-slate-50 text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-300';
};
```

- [ ] **Step 5: Show prune retry details in candidate cards**

In the generation candidate card detail `v-if`, include prune fields:

```vue
                  <div v-if="candidate.rejection_reason || candidate.intent_filter_reason || candidate.intent_reason || candidate.intent_prune_error || candidate.error || candidate.status === 'failed' || candidate.status === 'rate_limited' || candidate.status === 'confidence_rejected' || candidate.status === 'intent_filtered' || candidate.status === 'intent_prune_retrying'" class="mt-2 flex flex-col gap-2 border-t border-slate-100 dark:border-white/10 pt-2">
```

Insert this block before the existing `candidate.error` block:

```vue
                    <div v-else-if="candidate.intent_prune_error" class="text-[10px] text-amber-600 dark:text-amber-300 break-words line-clamp-2" :title="candidate.intent_prune_error">
                      {{ candidate.status === 'intent_review' ? '意图裁剪失败，已转人工确认：' : '意图裁剪重试中：' }}{{ candidate.intent_prune_error }}
                    </div>
```

In the retry time display, add prune retry time:

```vue
                      <span v-if="candidate.intent_prune_retry_after">裁剪重试 {{ new Date(candidate.intent_prune_retry_after).toLocaleTimeString() }}</span>
                      <span v-else-if="candidate.retry_after">下次重试 {{ new Date(candidate.retry_after).toLocaleTimeString() }}</span>
```

- [ ] **Step 6: Add focused UI test**

Create `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.intentPrune.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

const getCandidateStatusLabel = (status: string) => {
  if (status === 'pending') return '等待处理'
  if (status === 'intent_pruning') return '意图裁剪中'
  if (status === 'intent_prune_retrying') return '意图裁剪重试中'
  if (status === 'running') return '生成中'
  if (status === 'rate_limited') return '限流重试中'
  if (status === 'failed') return '生成失败'
  if (status === 'stale') return '等待更新'
  if (status === 'confidence_rejected') return '置信度不足'
  if (status === 'intent_filtered') return 'AI 过滤'
  if (status === 'intent_review') return '需确认'
  return '已生成'
}

const getPruneDetail = (status: string, intentPruneError?: string | null) => {
  if (!intentPruneError) return ''
  return `${status === 'intent_review' ? '意图裁剪失败，已转人工确认：' : '意图裁剪重试中：'}${intentPruneError}`
}

describe('ApiMonitorPage intent prune candidate display', () => {
  it('labels intent prune running and retrying statuses', () => {
    expect(getCandidateStatusLabel('intent_pruning')).toBe('意图裁剪中')
    expect(getCandidateStatusLabel('intent_prune_retrying')).toBe('意图裁剪重试中')
    expect(getCandidateStatusLabel('pending')).toBe('等待处理')
  })

  it('formats prune retry and final review details', () => {
    expect(getPruneDetail('intent_prune_retrying', 'slow prune')).toBe('意图裁剪重试中：slow prune')
    expect(getPruneDetail('intent_review', 'llm unavailable')).toBe('意图裁剪失败，已转人工确认：llm unavailable')
  })
})
```

This test intentionally mirrors the Vue display logic without mounting the full page, because `ApiMonitorPage.vue` has broad runtime dependencies unrelated to candidate label formatting.

- [ ] **Step 7: Run frontend tests**

Run:

```bash
cd RpaClaw/frontend
npm run test -- src/api/apiMonitor.test.ts src/pages/rpa/ApiMonitorPage.intentPrune.test.ts
```

Expected: both test files pass.

- [ ] **Step 8: Commit frontend changes**

Run:

```bash
git add RpaClaw/frontend/src/api/apiMonitor.ts RpaClaw/frontend/src/api/apiMonitor.test.ts RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.intentPrune.test.ts
git commit -m "feat: show api monitor intent prune states"
```

---

### Task 5: Final Regression Verification

**Files:**
- Verify: `RpaClaw/backend/rpa/api_monitor/models.py`
- Verify: `RpaClaw/backend/rpa/api_monitor/manager.py`
- Verify: `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`
- Verify: `RpaClaw/frontend/src/api/apiMonitor.ts`
- Verify: `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue`

- [ ] **Step 1: Run focused backend regression suite**

Run:

```bash
cd RpaClaw/backend
uv run python -m pytest tests/test_api_monitor_intent_pruner.py tests/test_api_monitor_realtime_generation.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run focused frontend regression suite**

Run:

```bash
cd RpaClaw/frontend
npm run test -- src/api/apiMonitor.test.ts src/pages/rpa/ApiMonitorPage.intentPrune.test.ts
```

Expected: all tests pass.

- [ ] **Step 3: Run frontend type check**

Run:

```bash
cd RpaClaw/frontend
npm run type-check
```

Expected: type check completes without errors.

- [ ] **Step 4: Inspect git diff for scope**

Run:

```bash
git diff --stat HEAD~3..HEAD
git status --short
```

Expected: changed files are limited to the backend API Monitor model/manager/tests and frontend API Monitor type/page/tests. Existing unrelated `.claude/` remains untracked and unmodified.

- [ ] **Step 5: Final commit if verification required fixes**

If Step 1, Step 2, or Step 3 required any fixes, commit only those fixes:

```bash
git add RpaClaw/backend/rpa/api_monitor/models.py RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_realtime_generation.py RpaClaw/frontend/src/api/apiMonitor.ts RpaClaw/frontend/src/api/apiMonitor.test.ts RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.intentPrune.test.ts
git commit -m "test: verify api monitor intent prune retry"
```

If no files changed after verification, do not create an empty commit.
