# API Monitor 意图裁剪分块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将意图裁剪的大批候选按固定 chunk size 分块处理，避免单个 LLM 调用超时导致全部候选卡死。

**Architecture:** 在 `_flush_intent_prune_buffer` 中，将 `prune_candidates` 列表按 `INTENT_PRUNE_CHUNK_SIZE=6` 切分为多个 chunk。每个 chunk 独立调用 `_prune_candidates_with_retry`，享有独立的超时、重试和信号量控制。chunk 串行处理，结果合并后统一应用。

**Tech Stack:** Python 3.13, asyncio, unittest.IsolatedAsyncioTestCase, unittest.mock.patch

---

### Task 1: 新增常量

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:62`

- [ ] **Step 1: 在 `INTENT_PRUNE_CONCURRENCY` 后新增 `INTENT_PRUNE_CHUNK_SIZE` 常量**

在 `manager.py` 第 62 行（`INTENT_PRUNE_CONCURRENCY = 2` 之后）添加：

```python
INTENT_PRUNE_CHUNK_SIZE = 6
```

最终常量区块应为：

```python
INTENT_PRUNE_DEBOUNCE_SECONDS = 3.0
INTENT_PRUNE_MAX_BATCH_SIZE = 8
INTENT_PRUNE_TIMEOUT_S = 60.0
INTENT_PRUNE_MAX_RETRIES = 2
INTENT_PRUNE_RETRY_BASE_DELAY_S = 2.0
INTENT_PRUNE_CONCURRENCY = 2
INTENT_PRUNE_CHUNK_SIZE = 6
```

- [ ] **Step 2: 验证常量可导入**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run python -c "from backend.rpa.api_monitor.manager import INTENT_PRUNE_CHUNK_SIZE; print(INTENT_PRUNE_CHUNK_SIZE)"`
Expected: `6`

---

### Task 2: 编写分块测试

**Files:**
- Modify: `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py` (追加到 `TestRealtimeBuffer` 类末尾)

- [ ] **Step 1: 编写测试 — 单 chunk（候选数 <= CHUNK_SIZE）走现有逻辑**

在 `TestRealtimeBuffer` 类末尾（`test_flush_intent_prune_buffer_uses_review_fallback_when_prune_fails` 方法之后）添加：

```python
async def test_flush_intent_prune_buffer_single_chunk_no_split(self):
    """When prune_candidates <= CHUNK_SIZE, a single prune call is made."""
    manager = ApiMonitorSessionManager()
    session = ApiMonitorSession(
        id="session_1",
        user_id="user_1",
        sandbox_session_id="sandbox_1",
        intent="查询订单列表",
    )
    manager.sessions[session.id] = session
    enqueued: list[str] = []
    manager._enqueue_generation_candidate = lambda _sid, candidate_id, **_kw: enqueued.append(candidate_id)
    for i in range(4):
        call = _call(f"call_{i}", method="POST", path=f"/api/orders/search/{i}")
        call.source_evidence = {"action_window_matched": True, "initiator_urls": ["https://example.com/app.js"]}
        call.response.body = f'{{"items":[{{"orderNo":"A{i:03d}"}}]}}'
        session.captured_calls.append(call)
    for call in session.captured_calls:
        manager._upsert_generation_candidate(session.id, call)
    candidates = session.generation_candidates
    for c in candidates:
        manager._intent_prune_buffers[session.id].add(c.id)
    prune_call_count = 0

    async def mock_prune(candidates_arg, intent, page_context="", model_config=None):
        nonlocal prune_call_count
        prune_call_count += 1
        return IntentPruneResult(
            batch_id="test_batch",
            items=[
                IntentPruneItem(candidate_key=c.candidate_key, intent_group="primary", intent_score=90, intent_rank=i + 1, intent_reason="test")
                for i, c in enumerate(candidates_arg)
            ],
        )

    with patch("backend.rpa.api_monitor.manager.prune_candidates_by_intent", side_effect=mock_prune):
        await manager._flush_intent_prune_buffer(session.id, model_config=None)
    assert prune_call_count == 1
    assert len(enqueued) == 4
```

注意：需要额外导入 `IntentPruneItem`：

```python
from backend.rpa.api_monitor.intent_pruner import IntentPruneResult, IntentPruneItem
```

- [ ] **Step 2: 编写测试 — 多 chunk 正确切分**

```python
async def test_flush_intent_prune_buffer_splits_into_chunks(self):
    """When prune_candidates > CHUNK_SIZE, multiple prune calls are made per chunk."""
    manager = ApiMonitorSessionManager()
    session = ApiMonitorSession(
        id="session_1",
        user_id="user_1",
        sandbox_session_id="sandbox_1",
        intent="查询订单列表",
    )
    manager.sessions[session.id] = session
    enqueued: list[str] = []
    manager._enqueue_generation_candidate = lambda _sid, candidate_id, **_kw: enqueued.append(candidate_id)
    chunk_sizes_seen: list[int] = []
    for i in range(14):
        call = _call(f"call_{i}", method="POST", path=f"/api/orders/search/{i}")
        call.source_evidence = {"action_window_matched": True, "initiator_urls": ["https://example.com/app.js"]}
        call.response.body = f'{{"items":[{{"orderNo":"A{i:03d}"}}]}}'
        session.captured_calls.append(call)
    for call in session.captured_calls:
        manager._upsert_generation_candidate(session.id, call)
    candidates = session.generation_candidates
    for c in candidates:
        manager._intent_prune_buffers[session.id].add(c.id)

    async def mock_prune(candidates_arg, intent, page_context="", model_config=None):
        chunk_sizes_seen.append(len(candidates_arg))
        return IntentPruneResult(
            batch_id="test_batch",
            items=[
                IntentPruneItem(candidate_key=c.candidate_key, intent_group="primary", intent_score=90, intent_rank=i + 1, intent_reason="test")
                for i, c in enumerate(candidates_arg)
            ],
        )

    with patch("backend.rpa.api_monitor.manager.INTENT_PRUNE_CHUNK_SIZE", 6):
        with patch("backend.rpa.api_monitor.manager.prune_candidates_by_intent", side_effect=mock_prune):
            await manager._flush_intent_prune_buffer(session.id, model_config=None)
    assert chunk_sizes_seen == [6, 6, 2]
    assert len(enqueued) == 14
```

- [ ] **Step 3: 编写测试 — 部分 chunk 失败不影响其他 chunk**

```python
async def test_flush_intent_prune_buffer_partial_chunk_failure(self):
    """When one chunk fails all retries, its candidates go to intent_review; other chunks succeed."""
    manager = ApiMonitorSessionManager()
    session = ApiMonitorSession(
        id="session_1",
        user_id="user_1",
        sandbox_session_id="sandbox_1",
        intent="查询订单列表",
    )
    manager.sessions[session.id] = session
    enqueued: list[str] = []
    manager._enqueue_generation_candidate = lambda _sid, candidate_id, **_kw: enqueued.append(candidate_id)
    for i in range(9):
        call = _call(f"call_{i}", method="POST", path=f"/api/orders/search/{i}")
        call.source_evidence = {"action_window_matched": True, "initiator_urls": ["https://example.com/app.js"]}
        call.response.body = f'{{"items":[{{"orderNo":"A{i:03d}"}}]}}'
        session.captured_calls.append(call)
    for call in session.captured_calls:
        manager._upsert_generation_candidate(session.id, call)
    candidates = session.generation_candidates
    for c in candidates:
        manager._intent_prune_buffers[session.id].add(c.id)
    call_count = 0

    async def mock_prune(candidates_arg, intent, page_context="", model_config=None):
        nonlocal call_count
        call_count += 1
        if len(candidates_arg) <= 3:
            raise RuntimeError("llm unavailable for small chunk")
        return IntentPruneResult(
            batch_id="test_batch",
            items=[
                IntentPruneItem(candidate_key=c.candidate_key, intent_group="primary", intent_score=90, intent_rank=i + 1, intent_reason="test")
                for i, c in enumerate(candidates_arg)
            ],
        )

    with patch("backend.rpa.api_monitor.manager.INTENT_PRUNE_CHUNK_SIZE", 6):
        with patch("backend.rpa.api_monitor.manager.INTENT_PRUNE_RETRY_BASE_DELAY_S", 0):
            with patch("backend.rpa.api_monitor.manager.prune_candidates_by_intent", side_effect=mock_prune):
                await manager._flush_intent_prune_buffer(session.id, model_config=None)
    first_6 = candidates[:6]
    last_3 = candidates[6:]
    for c in first_6:
        assert c.status not in ("intent_review",), f"first chunk candidate {c.dedup_key} should not be intent_review"
    for c in last_3:
        assert c.status == "intent_review", f"last chunk candidate {c.dedup_key} should be intent_review"
    assert len(enqueued) == 6
```

- [ ] **Step 4: 运行新测试验证全部失败（实现前）**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_realtime_generation.py::TestRealtimeBuffer::test_flush_intent_prune_buffer_single_chunk_no_split tests/test_api_monitor_realtime_generation.py::TestRealtimeBuffer::test_flush_intent_prune_buffer_splits_into_chunks tests/test_api_monitor_realtime_generation.py::TestRealtimeBuffer::test_flush_intent_prune_buffer_partial_chunk_failure -v`
Expected: `test_flush_intent_prune_buffer_single_chunk_no_split` PASS（<=6 走现有逻辑），`test_flush_intent_prune_buffer_splits_into_chunks` FAIL（14 个候选只产生 1 次 prune 调用而非 3 次），`test_flush_intent_prune_buffer_partial_chunk_failure` FAIL（失败 chunk 的候选未进入 intent_review）

---

### Task 3: 实现分块逻辑

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:2543-2576`（`_flush_intent_prune_buffer` 方法）

- [ ] **Step 1: 替换 `_flush_intent_prune_buffer` 中 prune_candidates 构建之后的逻辑**

将 `_flush_intent_prune_buffer` 方法中，从 `if not prune_candidates:` 到方法末尾的代码替换为分块版本。原代码（第 2559-2576 行）：

```python
if not prune_candidates:
    return
prune_result = await self._prune_candidates_with_retry(
    session,
    candidates,
    prune_candidates,
    intent,
    model_config=model_config,
)
by_key = {item.candidate_key: item for item in prune_result.items}
for candidate in candidates:
    item = by_key.get(self._candidate_key_for_prune(candidate))
    if item is None:
        continue
    self._apply_prune_item_to_candidate(session, candidate, item, batch_id=prune_result.batch_id)
    self._emit_analysis_event(session_id, "api_candidate_intent_pruned", self._candidate_event_payload(candidate))
    if candidate.status not in ("intent_filtered",):
        self._enqueue_generation_candidate(session_id, candidate.id, model_config=model_config, skip_filter=True)
```

替换为：

```python
if not prune_candidates:
    return

prune_key_to_candidate = {
    self._candidate_key_for_prune(c): c for c in candidates
}
prune_key_to_prune = {
    pc.candidate_key: pc for pc in prune_candidates
}
all_items: list[IntentPruneItem] = []
for chunk_start in range(0, len(prune_candidates), INTENT_PRUNE_CHUNK_SIZE):
    prune_chunk = prune_candidates[chunk_start:chunk_start + INTENT_PRUNE_CHUNK_SIZE]
    candidate_chunk = [
        prune_key_to_candidate[pc.candidate_key]
        for pc in prune_chunk
        if pc.candidate_key in prune_key_to_candidate
    ]
    if not candidate_chunk:
        continue
    chunk_result = await self._prune_candidates_with_retry(
        session,
        candidate_chunk,
        prune_chunk,
        intent,
        model_config=model_config,
    )
    all_items.extend(chunk_result.items)

by_key = {item.candidate_key: item for item in all_items}
for candidate in candidates:
    item = by_key.get(self._candidate_key_for_prune(candidate))
    if item is None:
        continue
    self._apply_prune_item_to_candidate(session, candidate, item, batch_id=chunk_result.batch_id if chunk_result else "")
    self._emit_analysis_event(session_id, "api_candidate_intent_pruned", self._candidate_event_payload(candidate))
    if candidate.status not in ("intent_filtered",):
        self._enqueue_generation_candidate(session_id, candidate.id, model_config=model_config, skip_filter=True)
```

注意：`chunk_result` 变量在循环中逐次覆盖，`batch_id` 取最后一个 chunk 的 batch_id。这是合理的，因为 `batch_id` 主要用于调试追踪，不同 chunk 各自的 batch_id 已记录在各自的 `IntentPruneResult` 中。

- [ ] **Step 2: 确保 `IntentPruneItem` 已在文件顶部导入**

检查 `manager.py` 顶部的 import 块。如果只导入了 `IntentPruneResult`，需要追加 `IntentPruneItem`：

```python
from .intent_pruner import IntentPruneCandidate, IntentPruneItem, IntentPruneResult, prune_candidates_by_intent
```

- [ ] **Step 3: 运行全部测试验证**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_realtime_generation.py -v`
Expected: ALL PASS

---

### Task 4: 运行现有回归测试

**Files:** 无变更

- [ ] **Step 1: 运行意图裁剪相关测试**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_intent_pruner.py tests/test_api_monitor_realtime_generation.py -v`
Expected: ALL PASS

- [ ] **Step 2: 运行完整测试套件**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/ -v`
Expected: ALL PASS

---

### Task 5: 提交

- [ ] **Step 1: 提交实现和测试**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_realtime_generation.py
git commit -m "fix: 意图裁剪分块处理，防止大批候选超时卡死"
```
