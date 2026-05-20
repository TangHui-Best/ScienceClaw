# API Monitor Batch Intent Pruning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-endpoint binary intent filtering with batch intent pruning so API Monitor only auto-publishes primary APIs, folds generated reserve tools into the not-adopted group, and leaves unrelated high-confidence APIs as explainable candidates.

**Architecture:** Keep rule confidence scoring as the first gate, then pass high-confidence candidates through a batch LLM classifier that returns `primary/supporting/adjacent/bootstrap/noise/uncertain`. `primary` candidates generate selected tools, `supporting` candidates generate reserve tools with `selected=false`, and filtered or uncertain candidates keep candidate records with reasons and force-generation entry points.

**Tech Stack:** FastAPI/Python 3.13, Pydantic v2, LangChain model calls, Vue 3 + TypeScript, existing API Monitor SSE and polling.

---

## Scope Check

This plan implements one feature across backend and frontend because the data model, candidate lifecycle, publish behavior, and UI grouping are coupled. It does not change capture mechanics, confidence scoring weights, OpenAPI YAML generation, MCP auth, or token-flow detection.

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `RpaClaw/backend/rpa/api_monitor/models.py` | Add intent pruning fields, `intent_review` status, and reserve-tool metadata. |
| Create | `RpaClaw/backend/rpa/api_monitor/intent_pruner.py` | Build batch pruning prompts, parse LLM JSON, normalize invalid output, and provide safe fallback results. |
| Modify | `RpaClaw/backend/rpa/api_monitor/manager.py` | Replace per-candidate intent filter with batch pruning, add realtime prune buffer, carry reserve metadata into generated tools. |
| Modify | `RpaClaw/backend/rpa/api_monitor_mcp_registry.py` | Exclude reserve tools from MCP publish even if selected state drifts. |
| Modify | `RpaClaw/backend/route/api_monitor.py` | Treat reserve adoption as clearing `is_reserve`; expose new candidate fields through existing model dumps. |
| Modify | `RpaClaw/frontend/src/api/apiMonitor.ts` | Add TypeScript status, intent group, reserve fields. |
| Modify | `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue` | Change grouping to `采用 -> 不采用 -> 未生成/过滤候选`; show reserve badges and new pruning reasons. |
| Modify | `RpaClaw/frontend/src/locales/en.ts` | Add English labels for new groups and statuses if the page uses i18n keys. |
| Modify | `RpaClaw/frontend/src/locales/zh.ts` | Add Chinese labels for new groups and statuses if the page uses i18n keys. |
| Create | `RpaClaw/backend/tests/test_api_monitor_intent_pruner.py` | Unit-test pruning parser and fallback behavior. |
| Modify | `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py` | Cover manager integration for primary, supporting, filtered, uncertain, and force generation. |
| Modify | `RpaClaw/backend/tests/test_api_monitor_publish_mcp.py` | Verify reserve tools are not published. |

---

### Task 1: Model Fields And Publish Semantics

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/models.py`
- Modify: `RpaClaw/backend/rpa/api_monitor_mcp_registry.py`
- Modify: `RpaClaw/backend/route/api_monitor.py`
- Test: `RpaClaw/backend/tests/test_api_monitor_publish_mcp.py`

- [ ] **Step 1: Write failing backend model/publish tests**

Append these tests to `RpaClaw/backend/tests/test_api_monitor_publish_mcp.py`. They use the existing `_MemoryRepo` helper in that file.

```python
import pytest

from backend.rpa.api_monitor.models import ApiMonitorSession, ApiToolDefinition
from backend.rpa.api_monitor_mcp_registry import ApiMonitorMcpRegistry


@pytest.mark.asyncio
async def test_publish_session_excludes_reserve_tools():
    servers = _MemoryRepo([])
    tools = _MemoryRepo([])
    registry = ApiMonitorMcpRegistry(server_repository=servers, tool_repository=tools)
    session = ApiMonitorSession(
        id="session_1",
        user_id="user_1",
        sandbox_session_id="sandbox_1",
        target_url="https://example.com/app",
        tool_definitions=[
            ApiToolDefinition(
                session_id="session_1",
                name="list_orders",
                description="List orders",
                method="GET",
                url_pattern="/api/orders",
                yaml_definition='swagger: "2.0"\ninfo:\n  title: list_orders\n  version: "1.0"\npaths:\n  /api/orders:\n    get:\n      operationId: list_orders\n      responses:\n        "200":\n          description: OK\n',
                selected=True,
            ),
            ApiToolDefinition(
                session_id="session_1",
                name="list_order_statuses",
                description="List order statuses",
                method="GET",
                url_pattern="/api/order/status-options",
                yaml_definition='swagger: "2.0"\ninfo:\n  title: list_order_statuses\n  version: "1.0"\npaths:\n  /api/order/status-options:\n    get:\n      operationId: list_order_statuses\n      responses:\n        "200":\n          description: OK\n',
                selected=True,
                is_reserve=True,
                intent_group="supporting",
            ),
        ],
    )

    result = await registry.publish_session(
        session=session,
        user_id="user_1",
        mcp_name="Orders MCP",
        description="",
    )

    assert result["tool_count"] == 1
    stored_server = await servers.find_one({"_id": result["server_id"], "user_id": "user_1"})
    assert stored_server["tool_count"] == 1
    stored_tools = await tools.find_many({"mcp_server_id": result["server_id"]})
    assert [tool["name"] for tool in stored_tools] == ["list_orders"]


def test_tool_selection_clears_reserve_flag_when_adopted():
    tool = ApiToolDefinition(
        session_id="session_1",
        name="list_statuses",
        description="List statuses",
        method="GET",
        url_pattern="/api/statuses",
        yaml_definition="name: list_statuses",
        selected=False,
        is_reserve=True,
    )

    tool.selected = True
    tool.is_reserve = False

    assert tool.selected is True
    assert tool.is_reserve is False
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_publish_mcp.py -q
```

Expected: the reserve-field test fails with `unexpected keyword argument 'is_reserve'` or publish includes two tools.

- [ ] **Step 3: Add model fields**

In `RpaClaw/backend/rpa/api_monitor/models.py`, add this alias near the existing `ConfidenceLevel` type:

```python
IntentGroup = Literal[
    "primary",
    "supporting",
    "adjacent",
    "bootstrap",
    "noise",
    "uncertain",
]
```

Change `GenerationStatus` to include `intent_review`:

```python
GenerationStatus = Literal[
    "pending",
    "running",
    "generated",
    "failed",
    "rate_limited",
    "stale",
    "confidence_rejected",
    "intent_filtered",
    "intent_review",
]
```

Add these fields to `ApiToolDefinition` after `selected`:

```python
    is_reserve: bool = False
    intent_group: Optional[IntentGroup] = None
    intent_reason: Optional[str] = None
    intent_score: Optional[int] = None
```

Add these fields to `ApiToolGenerationCandidate` after `intent_filter_reason`:

```python
    intent_group: Optional[IntentGroup] = None
    intent_reason: Optional[str] = None
    intent_score: Optional[int] = None
    intent_rank: Optional[int] = None
    intent_batch_id: Optional[str] = None
```

Update the `status` comment to include `intent_review`.

- [ ] **Step 4: Exclude reserve tools from publish**

In `RpaClaw/backend/rpa/api_monitor_mcp_registry.py`, change:

```python
selected_tools = [tool for tool in session.tool_definitions if getattr(tool, "selected", False)]
```

to:

```python
selected_tools = [
    tool
    for tool in session.tool_definitions
    if getattr(tool, "selected", False) and not getattr(tool, "is_reserve", False)
]
```

- [ ] **Step 5: Clear reserve when a user adopts a tool**

In `RpaClaw/backend/route/api_monitor.py`, inside `update_tool_selection`, replace the update block with:

```python
        if tool.id == tool_id:
            tool.selected = request.selected
            if request.selected:
                tool.is_reserve = False
            from datetime import datetime
            tool.updated_at = datetime.now()
            return {"status": "success", "tool": tool.model_dump()}
```

- [ ] **Step 6: Run task tests**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_publish_mcp.py -q
```

Expected: PASS for publish tests.

- [ ] **Step 7: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/models.py RpaClaw/backend/rpa/api_monitor_mcp_registry.py RpaClaw/backend/route/api_monitor.py RpaClaw/backend/tests/test_api_monitor_publish_mcp.py
git commit -m "feat: support api monitor reserve tools"
```

---

### Task 2: Batch Intent Pruner Module

**Files:**
- Create: `RpaClaw/backend/rpa/api_monitor/intent_pruner.py`
- Test: `RpaClaw/backend/tests/test_api_monitor_intent_pruner.py`

- [ ] **Step 1: Write failing parser and fallback tests**

Create `RpaClaw/backend/tests/test_api_monitor_intent_pruner.py`:

```python
import pytest

from backend.rpa.api_monitor.intent_pruner import (
    IntentPruneCandidate,
    _parse_prune_response,
    _fallback_result,
)


def _candidate(key: str) -> IntentPruneCandidate:
    return IntentPruneCandidate(
        candidate_key=key,
        method=key.split(" ", 1)[0],
        url_pattern=key.split(" ", 1)[1],
        confidence_score=100,
        confidence_reasons=["由用户动作触发"],
        request_summary="(无请求体)",
        response_summary='{"items":[]}',
        step_summary="点击 查询",
        page_url="https://example.com/orders",
        title="Orders",
    )


def test_parse_prune_response_normalizes_items():
    candidates = [_candidate("POST /api/orders/search"), _candidate("GET /api/menu/tree")]
    raw = """
    ```json
    {
      "items": [
        {
          "candidate_key": "POST /api/orders/search",
          "group": "primary",
          "score": 110,
          "rank": 1,
          "reason": "订单查询主接口。"
        },
        {
          "candidate_key": "GET /api/menu/tree",
          "group": "bootstrap",
          "score": -5,
          "rank": null,
          "reason": "菜单初始化接口。"
        }
      ]
    }
    ```
    """

    result = _parse_prune_response(raw, candidates, batch_id="batch_1")

    assert result.batch_id == "batch_1"
    assert [(item.candidate_key, item.intent_group, item.intent_score) for item in result.items] == [
        ("POST /api/orders/search", "primary", 100),
        ("GET /api/menu/tree", "bootstrap", 0),
    ]
    assert result.items[0].intent_rank == 1
    assert result.items[1].intent_rank is None


def test_parse_prune_response_fills_missing_and_invalid_as_uncertain():
    candidates = [_candidate("POST /api/orders/search"), _candidate("GET /api/user/profile")]
    raw = '{"items":[{"candidate_key":"POST /api/orders/search","group":"other","score":80,"reason":"bad group"}]}'

    result = _parse_prune_response(raw, candidates, batch_id="batch_2")

    assert [(item.candidate_key, item.intent_group) for item in result.items] == [
        ("POST /api/orders/search", "uncertain"),
        ("GET /api/user/profile", "uncertain"),
    ]
    assert all(item.intent_reason for item in result.items)


def test_fallback_result_marks_all_uncertain():
    candidates = [_candidate("GET /api/user/profile"), _candidate("GET /api/menu/tree")]

    result = _fallback_result(candidates, batch_id="batch_3", reason="意图裁剪失败，需人工确认")

    assert [item.intent_group for item in result.items] == ["uncertain", "uncertain"]
    assert [item.intent_reason for item in result.items] == ["意图裁剪失败，需人工确认", "意图裁剪失败，需人工确认"]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_intent_pruner.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.rpa.api_monitor.intent_pruner'`.

- [ ] **Step 3: Implement `intent_pruner.py`**

Create `RpaClaw/backend/rpa/api_monitor/intent_pruner.py`:

```python
"""Batch LLM intent pruning for API Monitor generation candidates."""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Optional

from .llm_analyzer import _call_llm

logger = logging.getLogger(__name__)

VALID_GROUPS = {"primary", "supporting", "adjacent", "bootstrap", "noise", "uncertain"}

INTENT_PRUNER_SYSTEM = """\
You are an API Monitor candidate pruner. Given a user's intent and a batch of high-confidence API candidates,
classify each candidate by how it should be handled for MCP tool generation.

Goal: reduce irrelevant tool retention.

Groups:
- primary: directly serves the user's intent. Only these should become selected tools.
- supporting: useful auxiliary data for the primary APIs, but not a user-requested capability.
- adjacent: same page or business domain, but not useful for this intent.
- bootstrap: page initialization such as user profile, menu, config, permissions, dictionaries.
- noise: telemetry, tracking, polling, recommendations, preloads, heartbeat, notifications.
- uncertain: insufficient evidence or ambiguous; do not auto-promote.

Rules:
- Return exactly one item for every input candidate.
- Mark only APIs that directly satisfy the user intent as primary.
- Prefer bootstrap for identity, menu, config, permission, and dictionary APIs even if they are JSON and high confidence.
- Prefer adjacent for business APIs that belong to a nearby domain but do not satisfy the intent.
- Use uncertain when unsure. Do not mark uncertain APIs as primary.
- Return only valid JSON, no markdown fences.
"""

INTENT_PRUNER_USER = """\
用户意图：
{intent}

页面上下文：
{page_context}

候选 API：
{candidates_json}

请返回 JSON：
{{
  "items": [
    {{
      "candidate_key": "<same candidate_key>",
      "group": "primary|supporting|adjacent|bootstrap|noise|uncertain",
      "score": 0,
      "rank": null,
      "reason": "一句中文理由"
    }}
  ]
}}
"""


@dataclass(frozen=True)
class IntentPruneCandidate:
    candidate_key: str
    method: str
    url_pattern: str
    confidence_score: int
    confidence_reasons: list[str]
    request_summary: str
    response_summary: str
    step_summary: str
    page_url: str
    title: str


@dataclass(frozen=True)
class IntentPruneItem:
    candidate_key: str
    intent_group: str
    intent_score: int
    intent_rank: int | None
    intent_reason: str


@dataclass(frozen=True)
class IntentPruneResult:
    batch_id: str
    items: list[IntentPruneItem]


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\\s*", "", text)
    text = re.sub(r"\\s*```\\s*$", "", text)
    return text.strip()


def _clamp_score(value: object) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        score = 0
    return max(0, min(100, score))


def _normalize_rank(value: object, group: str) -> int | None:
    if group != "primary":
        return None
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return None
    return rank if rank > 0 else None


def _uncertain_item(candidate_key: str, reason: str) -> IntentPruneItem:
    return IntentPruneItem(
        candidate_key=candidate_key,
        intent_group="uncertain",
        intent_score=0,
        intent_rank=None,
        intent_reason=reason,
    )


def _fallback_result(
    candidates: list[IntentPruneCandidate],
    *,
    batch_id: str,
    reason: str,
) -> IntentPruneResult:
    return IntentPruneResult(
        batch_id=batch_id,
        items=[_uncertain_item(candidate.candidate_key, reason) for candidate in candidates],
    )


def _parse_prune_response(
    raw: str,
    candidates: list[IntentPruneCandidate],
    *,
    batch_id: str,
) -> IntentPruneResult:
    keys = [candidate.candidate_key for candidate in candidates]
    try:
        parsed = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        logger.warning("[IntentPruner] Failed to parse LLM response: %s", raw[:500])
        return _fallback_result(candidates, batch_id=batch_id, reason="意图裁剪失败，需人工确认")

    raw_items = parsed.get("items", []) if isinstance(parsed, dict) else []
    by_key: dict[str, IntentPruneItem] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("candidate_key") or "")
        if key not in keys or key in by_key:
            continue
        group = str(item.get("group") or "uncertain")
        if group not in VALID_GROUPS:
            by_key[key] = _uncertain_item(key, "意图裁剪返回了无效分类，需人工确认")
            continue
        reason = str(item.get("reason") or "意图裁剪未提供理由")
        by_key[key] = IntentPruneItem(
            candidate_key=key,
            intent_group=group,
            intent_score=_clamp_score(item.get("score")),
            intent_rank=_normalize_rank(item.get("rank"), group),
            intent_reason=reason,
        )

    items = [
        by_key.get(candidate.candidate_key)
        or _uncertain_item(candidate.candidate_key, "意图裁剪缺少该候选结果，需人工确认")
        for candidate in candidates
    ]
    return IntentPruneResult(batch_id=batch_id, items=items)


def _candidate_payload(candidate: IntentPruneCandidate) -> dict:
    return {
        "candidate_key": candidate.candidate_key,
        "method": candidate.method,
        "url_pattern": candidate.url_pattern,
        "confidence_score": candidate.confidence_score,
        "confidence_reasons": candidate.confidence_reasons,
        "request_summary": candidate.request_summary[:500],
        "response_summary": candidate.response_summary[:800],
        "step_summary": candidate.step_summary[:500],
        "page_url": candidate.page_url,
        "title": candidate.title,
    }


async def prune_candidates_by_intent(
    candidates: list[IntentPruneCandidate],
    intent: str,
    *,
    page_context: str = "",
    model_config: Optional[dict] = None,
) -> IntentPruneResult:
    batch_id = f"intent_prune_{uuid.uuid4().hex[:12]}"
    if not candidates:
        return IntentPruneResult(batch_id=batch_id, items=[])
    payload = [_candidate_payload(candidate) for candidate in candidates]
    user_prompt = INTENT_PRUNER_USER.format(
        intent=intent,
        page_context=page_context or "(无)",
        candidates_json=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    try:
        raw = await _call_llm(INTENT_PRUNER_SYSTEM, user_prompt, model_config)
    except Exception as exc:
        logger.warning("[IntentPruner] LLM call failed: %s", exc)
        return _fallback_result(candidates, batch_id=batch_id, reason="意图裁剪失败，需人工确认")
    return _parse_prune_response(raw, candidates, batch_id=batch_id)
```

- [ ] **Step 4: Run pruner tests**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_intent_pruner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/intent_pruner.py RpaClaw/backend/tests/test_api_monitor_intent_pruner.py
git commit -m "feat: add api monitor batch intent pruner"
```

---

### Task 3: Manager Helpers For Prune Results

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py`
- Test: `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`

- [ ] **Step 1: Write failing helper tests**

Append these tests to `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`:

```python
from backend.rpa.api_monitor.intent_pruner import IntentPruneItem
from backend.rpa.api_monitor.manager import ApiMonitorSessionManager
from backend.rpa.api_monitor.models import ApiMonitorSession, ApiToolGenerationCandidate


def test_apply_prune_item_sets_filtered_candidate_state():
    manager = ApiMonitorSessionManager()
    session = ApiMonitorSession(id="session_1", user_id="user_1", sandbox_session_id="sandbox_1")
    candidate = ApiToolGenerationCandidate(
        session_id="session_1",
        dedup_key="GET /api/menu/tree",
        method="GET",
        url_pattern="/api/menu/tree",
    )
    session.generation_candidates.append(candidate)
    manager.sessions[session.id] = session

    manager._apply_prune_item_to_candidate(
        session,
        candidate,
        IntentPruneItem(
            candidate_key="GET /api/menu/tree",
            intent_group="bootstrap",
            intent_score=20,
            intent_rank=None,
            intent_reason="菜单初始化接口。",
        ),
        batch_id="batch_1",
    )

    assert candidate.status == "intent_filtered"
    assert candidate.intent_group == "bootstrap"
    assert candidate.intent_filter_reason == "菜单初始化接口。"
    assert candidate.intent_batch_id == "batch_1"


def test_apply_prune_item_sets_uncertain_candidate_state():
    manager = ApiMonitorSessionManager()
    session = ApiMonitorSession(id="session_1", user_id="user_1", sandbox_session_id="sandbox_1")
    candidate = ApiToolGenerationCandidate(
        session_id="session_1",
        dedup_key="GET /api/unknown",
        method="GET",
        url_pattern="/api/unknown",
    )
    session.generation_candidates.append(candidate)
    manager.sessions[session.id] = session

    manager._apply_prune_item_to_candidate(
        session,
        candidate,
        IntentPruneItem(
            candidate_key="GET /api/unknown",
            intent_group="uncertain",
            intent_score=0,
            intent_rank=None,
            intent_reason="证据不足。",
        ),
        batch_id="batch_2",
    )

    assert candidate.status == "intent_review"
    assert candidate.intent_group == "uncertain"
    assert candidate.intent_reason == "证据不足。"
```

- [ ] **Step 2: Run helper tests and verify they fail**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_realtime_generation.py -q -k "apply_prune_item"
```

Expected: FAIL with `AttributeError: 'ApiMonitorSessionManager' object has no attribute '_apply_prune_item_to_candidate'`.

- [ ] **Step 3: Add imports and helper methods**

In `RpaClaw/backend/rpa/api_monitor/manager.py`, replace the intent filter import:

```python
from .intent_filter import filter_by_intent
```

with:

```python
from .intent_pruner import IntentPruneCandidate, IntentPruneItem, prune_candidates_by_intent
```

Add these methods inside `ApiMonitorSessionManager`, near `_calls_for_candidate`:

```python
    def _request_summary_for_prune(self, calls: list[CapturedApiCall]) -> str:
        first = calls[0]
        body = first.request.body or ""
        return (body[:500] + "...") if len(body) > 500 else (body or "(无请求体)")

    def _response_summary_for_prune(self, calls: list[CapturedApiCall]) -> str:
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
        if item.intent_group in ("adjacent", "bootstrap", "noise"):
            candidate.status = "intent_filtered"
            candidate.intent_filter_reason = item.intent_reason
        elif item.intent_group == "uncertain":
            candidate.status = "intent_review"
            candidate.intent_filter_reason = item.intent_reason
        candidate.updated_at = datetime.now()
        session.updated_at = datetime.now()
```

- [ ] **Step 4: Include intent fields in candidate events**

In `_candidate_event_payload`, add these keys:

```python
            "intent_group": candidate.intent_group,
            "intent_reason": candidate.intent_reason,
            "intent_score": candidate.intent_score,
            "intent_rank": candidate.intent_rank,
            "intent_batch_id": candidate.intent_batch_id,
```

- [ ] **Step 5: Run helper tests**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_realtime_generation.py -q -k "apply_prune_item"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_realtime_generation.py
git commit -m "feat: add api monitor intent pruning candidate helpers"
```

---

### Task 4: Batch Analysis Path Integration

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py`
- Test: `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`

- [ ] **Step 1: Write failing batch integration tests**

Append this test to `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`:

```python
import pytest

from backend.rpa.api_monitor.intent_pruner import IntentPruneItem, IntentPruneResult
from backend.rpa.api_monitor.manager import ApiMonitorSessionManager
from backend.rpa.api_monitor.models import ApiMonitorSession


@pytest.mark.asyncio
async def test_generate_tools_from_calls_uses_batch_intent_pruning(monkeypatch):
    manager = ApiMonitorSessionManager()
    session = ApiMonitorSession(
        id="session_1",
        user_id="user_1",
        sandbox_session_id="sandbox_1",
        intent="查询订单列表",
        target_url="https://example.com/orders",
    )
    manager.sessions[session.id] = session
    order_call = _call(
        "order_1",
        method="POST",
        path="/api/orders/search",
    )
    order_call.source_evidence = {
        "action_window_matched": True,
        "initiator_urls": ["https://example.com/app.js"],
    }
    order_call.response.body = '{"items":[{"orderNo":"A001"}]}'
    menu_call = _call(
        "menu_1",
        method="GET",
        path="/api/menu/tree",
    )
    menu_call.source_evidence = {
        "action_window_matched": True,
        "initiator_urls": ["https://example.com/app.js"],
    }
    menu_call.response.body = '{"menus":[]}'

    async def fake_prune(candidates, intent, page_context="", model_config=None):
        assert intent == "查询订单列表"
        return IntentPruneResult(
            batch_id="batch_1",
            items=[
                IntentPruneItem(candidates[0].candidate_key, "primary", 95, 1, "订单查询主接口。"),
                IntentPruneItem(candidates[1].candidate_key, "bootstrap", 20, None, "菜单初始化接口。"),
            ],
        )

    async def fake_generate_tool_definition(**kwargs):
        return 'swagger: "2.0"\ninfo:\n  title: list_orders\n  version: "1.0"\npaths:\n  /api/orders/search:\n    post:\n      operationId: list_orders\n      responses:\n        "200":\n          description: OK\n'

    monkeypatch.setattr("backend.rpa.api_monitor.manager.prune_candidates_by_intent", fake_prune)
    monkeypatch.setattr("backend.rpa.api_monitor.manager.generate_tool_definition", fake_generate_tool_definition)

    tools = await manager._generate_tools_from_calls(session.id, [order_call, menu_call], model_config=None)

    assert [tool.url_pattern for tool in tools] == [order_call.url_pattern or order_call.request.url]
    assert session.tool_definitions[0].selected is True
    filtered = [candidate for candidate in session.generation_candidates if candidate.status == "intent_filtered"]
    assert len(filtered) == 1
    assert filtered[0].intent_group == "bootstrap"
    assert filtered[0].intent_filter_reason == "菜单初始化接口。"
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_realtime_generation.py -q -k "batch_intent_pruning"
```

Expected: FAIL because `_generate_tools_from_calls` still uses per-candidate intent filtering.

- [ ] **Step 3: Refactor `_generate_tools_from_calls` high-confidence flow**

In `_generate_tools_from_calls`, keep DOM scan and grouping. Replace the per-group `filter_by_intent` section with a two-phase flow:

```python
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
```

Then, before generating tools:

```python
        prune_by_key: dict[str, IntentPruneItem] = {}
        intent = (session.intent or "").strip()
        if intent and high_confidence:
            prune_candidates = [
                self._intent_prune_candidate(session, candidate, confidence_result)
                for _key, _samples, confidence_result, candidate in high_confidence
            ]
            prune_result = await prune_candidates_by_intent(
                prune_candidates,
                intent,
                page_context=session.target_url or "",
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

Finally, generate only candidates whose group is empty, `primary`, or `supporting`:

```python
        for _key, samples, confidence_result, candidate in high_confidence:
            if candidate.status in ("intent_filtered", "intent_review"):
                continue
            reserve = candidate.intent_group == "supporting"
            try:
                yaml_def = await generate_tool_definition(
                    method=candidate.method,
                    url_pattern=candidate.url_pattern,
                    samples=samples,
                    page_context=session.target_url or "",
                    dom_context=dom_context,
                    model_config=model_config,
                )
            except Exception as exc:
                logger.warning("[ApiMonitor] Failed to generate tool for %s: %s", candidate.url_pattern, exc)
                continue
            tool = self._tool_from_generated_yaml(
                session_id=session_id,
                candidate=candidate,
                samples=samples,
                yaml_def=yaml_def,
                confidence_result=confidence_result,
                is_reserve=reserve,
            )
            tools.append(tool)
```

If `_tool_from_generated_yaml` does not exist yet, create it by extracting the tool creation block from `_generate_tool_for_candidate`. It must set:

```python
tool.is_reserve = is_reserve
tool.selected = False if is_reserve else True
tool.intent_group = candidate.intent_group
tool.intent_reason = candidate.intent_reason
tool.intent_score = candidate.intent_score
```

- [ ] **Step 4: Run batch integration test**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_realtime_generation.py -q -k "batch_intent_pruning"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_realtime_generation.py
git commit -m "feat: prune api monitor batch analysis candidates"
```

---

### Task 5: Realtime Recording Prune Buffer

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py`
- Test: `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`

- [ ] **Step 1: Write failing realtime buffer test**

Append this test to `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`:

```python
@pytest.mark.asyncio
async def test_process_captured_calls_buffers_high_confidence_candidates_when_intent_exists(monkeypatch):
    manager = ApiMonitorSessionManager()
    session = ApiMonitorSession(
        id="session_1",
        user_id="user_1",
        sandbox_session_id="sandbox_1",
        intent="查询订单列表",
    )
    manager.sessions[session.id] = session
    enqueued: list[str] = []
    monkeypatch.setattr(manager, "_enqueue_generation_candidate", lambda _sid, candidate_id, **_kw: enqueued.append(candidate_id))
    monkeypatch.setattr(manager, "_schedule_intent_prune_flush", lambda _sid, **_kw: None)
    call = _call(
        "order_1",
        method="POST",
        path="/api/orders/search",
    )
    call.source_evidence = {
        "action_window_matched": True,
        "initiator_urls": ["https://example.com/app.js"],
    }
    call.response.body = '{"items":[{"orderNo":"A001"}]}'

    changed = await manager._process_captured_calls_for_generation(session.id, [call], model_config=None)

    assert len(changed) == 1
    assert enqueued == []
    assert manager._intent_prune_buffers[session.id] == {changed[0].id}
```

- [ ] **Step 2: Run realtime test and verify it fails**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_realtime_generation.py -q -k "buffers_high_confidence"
```

Expected: FAIL because `_intent_prune_buffers` does not exist and the candidate is enqueued immediately.

- [ ] **Step 3: Add buffer state**

In `ApiMonitorSessionManager.__init__`, add:

```python
        self._intent_prune_buffers: Dict[str, set[str]] = defaultdict(set)
        self._intent_prune_tasks: Dict[str, asyncio.Task] = {}
```

Near other constants, add:

```python
INTENT_PRUNE_DEBOUNCE_SECONDS = 3.0
INTENT_PRUNE_MAX_BATCH_SIZE = 8
```

- [ ] **Step 4: Add flush scheduling methods**

Add these methods to `ApiMonitorSessionManager`:

```python
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
```

- [ ] **Step 5: Add flush implementation**

Add:

```python
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
            if candidate.id in candidate_ids and candidate.status in ("pending", "stale", "failed")
        ]
        if not candidates:
            return
        intent = (session.intent or "").strip()
        if not intent:
            for candidate in candidates:
                self._enqueue_generation_candidate(session_id, candidate.id, model_config=model_config)
            return

        confidence_by_id = {}
        prune_candidates = []
        for candidate in candidates:
            samples = self._calls_for_candidate(session, candidate)
            if not samples:
                continue
            confidence_result = score_api_candidate(
                samples,
                action_context=candidate.step_metadata[-1] if candidate.step_metadata else None,
            )
            confidence_by_id[candidate.id] = confidence_result
            if confidence_result.score < 80:
                candidate.status = "confidence_rejected"
                candidate.rejection_reason = summarize_rejection_reasons(confidence_result)
                self._emit_analysis_event(session_id, "api_candidate_confidence_rejected", self._candidate_event_payload(candidate))
                continue
            prune_candidates.append(self._intent_prune_candidate(session, candidate, confidence_result))

        if not prune_candidates:
            return
        prune_result = await prune_candidates_by_intent(
            prune_candidates,
            intent,
            page_context=session.target_url or "",
            model_config=model_config,
        )
        by_key = {item.candidate_key: item for item in prune_result.items}
        for candidate in candidates:
            item = by_key.get(self._candidate_key_for_prune(candidate))
            if item is None:
                continue
            self._apply_prune_item_to_candidate(session, candidate, item, batch_id=prune_result.batch_id)
            self._emit_analysis_event(session_id, "api_candidate_intent_pruned", self._candidate_event_payload(candidate))
            if candidate.status not in ("intent_filtered", "intent_review"):
                self._enqueue_generation_candidate(session_id, candidate.id, model_config=model_config)
```

- [ ] **Step 6: Buffer instead of enqueue in `_process_captured_calls_for_generation`**

In `_process_captured_calls_for_generation`, replace:

```python
            if candidate.status in ("pending", "stale", "failed"):
                self._enqueue_generation_candidate(session_id, candidate.id, model_config=model_config)
```

with:

```python
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
```

- [ ] **Step 7: Flush on stop recording**

In `stop_recording`, before returning tools, add:

```python
        await self._flush_intent_prune_buffer(session_id, model_config=model_config)
```

Place it after draining final captured calls and before final tool list is read.

- [ ] **Step 8: Run realtime buffer tests**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_realtime_generation.py -q -k "buffers_high_confidence or apply_prune_item"
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_realtime_generation.py
git commit -m "feat: batch prune realtime api monitor candidates"
```

---

### Task 6: Generation Candidate Reserve And Force Flow

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py`
- Test: `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`

- [ ] **Step 1: Write failing reserve generation tests**

Append:

```python
@pytest.mark.asyncio
async def test_supporting_candidate_generates_reserve_tool(monkeypatch):
    manager = ApiMonitorSessionManager()
    session = ApiMonitorSession(
        id="session_1",
        user_id="user_1",
        sandbox_session_id="sandbox_1",
        intent="查询订单列表",
    )
    manager.sessions[session.id] = session
    call = _call(
        "status_1",
        method="GET",
        path="/api/order/status-options",
    )
    call.source_evidence = {
        "action_window_matched": True,
        "initiator_urls": ["https://example.com/app.js"],
    }
    call.response.body = '{"options":["paid"]}'
    session.captured_calls.append(call)
    candidate, _ = manager._upsert_generation_candidate(session.id, call)
    candidate.intent_group = "supporting"
    candidate.intent_reason = "订单查询筛选条件。"
    candidate.intent_score = 75

    async def fake_generate_tool_definition(**kwargs):
        return 'swagger: "2.0"\ninfo:\n  title: list_order_statuses\n  version: "1.0"\npaths:\n  /api/order/status-options:\n    get:\n      operationId: list_order_statuses\n      responses:\n        "200":\n          description: OK\n'

    monkeypatch.setattr("backend.rpa.api_monitor.manager.generate_tool_definition", fake_generate_tool_definition)

    tool = await manager._generate_tool_for_candidate(session.id, candidate.id, skip_filter=True)

    assert tool is not None
    assert tool.selected is False
    assert tool.is_reserve is True
    assert tool.intent_group == "supporting"
    assert tool.intent_reason == "订单查询筛选条件。"


def test_force_generate_allows_intent_review_candidate():
    manager = ApiMonitorSessionManager()
    session = ApiMonitorSession(id="session_1", user_id="user_1", sandbox_session_id="sandbox_1")
    candidate = ApiToolGenerationCandidate(
        session_id="session_1",
        dedup_key="GET /api/unknown",
        method="GET",
        url_pattern="/api/unknown",
        status="intent_review",
        intent_group="uncertain",
    )
    session.generation_candidates.append(candidate)
    manager.sessions[session.id] = session

    manager.force_generate_candidate(session.id, candidate.id)

    assert candidate.status == "pending"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_realtime_generation.py -q -k "supporting_candidate_generates_reserve_tool or force_generate_allows_intent_review"
```

Expected: FAIL because generated tools are selected and force generation excludes `intent_review`.

- [ ] **Step 3: Set reserve metadata during generation**

In `_generate_tool_for_candidate`, after tool confidence fields are set, replace:

```python
        if existing is None:
            tool.selected = True
```

with:

```python
        reserve = candidate.intent_group == "supporting" or (skip_filter and candidate.intent_group in ("uncertain", "adjacent", "bootstrap", "noise"))
        tool.is_reserve = reserve
        tool.intent_group = candidate.intent_group
        tool.intent_reason = candidate.intent_reason or candidate.intent_filter_reason
        tool.intent_score = candidate.intent_score
        if existing is None:
            tool.selected = not reserve
        elif reserve:
            tool.selected = False
```

- [ ] **Step 4: Allow force generation for `intent_review`**

In `force_generate_candidate`, change:

```python
        if candidate.status not in ("confidence_rejected", "intent_filtered"):
            raise ValueError("Only rejected/filtered candidates can be force-generated")
```

to:

```python
        if candidate.status not in ("confidence_rejected", "intent_filtered", "intent_review"):
            raise ValueError("Only rejected/filtered/review candidates can be force-generated")
```

Do not clear `candidate.intent_group`, `candidate.intent_reason`, or `candidate.intent_score`. Only clear `rejection_reason` and `intent_filter_reason`.

- [ ] **Step 5: Include `intent_review` in followup/retry candidate statuses**

Update status tuples in `_run_generation_candidate`, `reconcile_generation_candidates`, and `visible retry` logic from:

```python
("pending", "stale", "failed", "confidence_rejected", "intent_filtered")
```

to:

```python
("pending", "stale", "failed", "confidence_rejected", "intent_filtered", "intent_review")
```

- [ ] **Step 6: Run reserve tests**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_realtime_generation.py -q -k "supporting_candidate_generates_reserve_tool or force_generate_allows_intent_review"
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_realtime_generation.py
git commit -m "feat: generate reserve tools from supporting candidates"
```

---

### Task 7: Frontend Types And Grouping

**Files:**
- Modify: `RpaClaw/frontend/src/api/apiMonitor.ts`
- Modify: `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue`

- [ ] **Step 1: Update API types**

In `RpaClaw/frontend/src/api/apiMonitor.ts`, extend `ApiToolGenerationStatus`:

```ts
  | 'intent_review'
```

Add:

```ts
export type ApiMonitorIntentGroup =
  | 'primary'
  | 'supporting'
  | 'adjacent'
  | 'bootstrap'
  | 'noise'
  | 'uncertain'
```

Add to `ApiToolGenerationCandidate`:

```ts
  intent_group?: ApiMonitorIntentGroup | null
  intent_reason?: string | null
  intent_score?: number | null
  intent_rank?: number | null
  intent_batch_id?: string | null
```

Add to `ApiToolDefinition`:

```ts
  is_reserve?: boolean
  intent_group?: ApiMonitorIntentGroup | null
  intent_reason?: string | null
  intent_score?: number | null
```

- [ ] **Step 2: Change frontend grouping**

In `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue`, replace the current computed block:

```ts
const adoptedTools = computed(() => tools.value.filter((tool) => tool.selected));
const notAdoptedTools = computed(() => tools.value.filter((tool) => !tool.selected));
const reserveCandidates = computed(() =>
  generationCandidates.value.filter((c) => c.status === 'confidence_rejected' || c.status === 'intent_filtered'),
);
const adoptedToolCount = computed(() => adoptedTools.value.length);
const toolGroups = computed(() => [
  { key: 'adopted', title: '采用', items: adoptedTools.value },
  { key: 'reserve', title: '候补', items: reserveCandidates.value },
  { key: 'not-adopted', title: '不采用', items: notAdoptedTools.value },
]);
```

with:

```ts
const adoptedTools = computed(() => tools.value.filter((tool) => tool.selected && !tool.is_reserve));
const notAdoptedTools = computed(() => tools.value.filter((tool) => !tool.selected || tool.is_reserve));
const filteredCandidates = computed(() =>
  generationCandidates.value.filter((c) =>
    c.status === 'confidence_rejected' || c.status === 'intent_filtered' || c.status === 'intent_review',
  ),
);
const adoptedToolCount = computed(() => adoptedTools.value.length);
const toolGroups = computed(() => [
  { key: 'adopted', title: '采用', items: adoptedTools.value },
  { key: 'not-adopted', title: '不采用', items: notAdoptedTools.value },
  { key: 'filtered-candidates', title: '未生成/过滤候选', items: filteredCandidates.value },
]);
```

Also replace `reserveCandidates.value.length` in stop-recording messages with `filteredCandidates.value.length`.

- [ ] **Step 3: Update template branch for candidate group**

In the grouped cards template, change:

```vue
<template v-if="group.key === 'reserve'">
```

to:

```vue
<template v-if="group.key === 'filtered-candidates'">
```

In the regular tool card markup, add a reserve badge next to the confidence badge:

```vue
<span
  v-if="tool.is_reserve"
  class="shrink-0 rounded-md border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300"
>
  候补
</span>
```

- [ ] **Step 4: Update candidate status helpers**

Find `getCandidateStatusLabel` and add:

```ts
intent_review: '需确认',
```

Find `getCandidateStatusClass` and add a neutral review style:

```ts
intent_review: 'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-500/20 dark:bg-amber-500/10 dark:text-amber-300',
```

Update the candidate reason display:

```vue
<div v-if="candidate.rejection_reason || candidate.intent_filter_reason || candidate.intent_reason" class="mt-1.5 text-[10px] text-orange-600 dark:text-orange-400">
  {{ candidate.rejection_reason || candidate.intent_filter_reason || candidate.intent_reason }}
</div>
```

- [ ] **Step 5: Run frontend type check/build**

Run:

```bash
cd RpaClaw/frontend
npm run build
```

Expected: PASS. If the project uses `npm run typecheck`, run it too and expect PASS.

- [ ] **Step 6: Commit**

```bash
git add RpaClaw/frontend/src/api/apiMonitor.ts RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue
git commit -m "feat: group api monitor generated and filtered items"
```

---

### Task 8: End-To-End Regression Tests

**Files:**
- Modify: `RpaClaw/backend/tests/test_api_monitor_confidence.py`
- Modify: `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`
- Modify: `RpaClaw/backend/tests/test_api_monitor_publish_mcp.py`

- [ ] **Step 1: Run focused backend regression**

Run:

```bash
cd RpaClaw/backend
uv run pytest \
  tests/test_api_monitor_intent_pruner.py \
  tests/test_api_monitor_confidence.py \
  tests/test_api_monitor_realtime_generation.py \
  tests/test_api_monitor_publish_mcp.py \
  -q
```

Expected: PASS. If failures occur, fix only code paths touched by this plan.

- [ ] **Step 2: Run API Monitor adjacent tests**

Run:

```bash
cd RpaClaw/backend
uv run pytest \
  tests/test_api_monitor_capture.py \
  tests/test_api_monitor_analysis_modes.py \
  tests/test_api_monitor_openapi_contract.py \
  tests/test_api_monitor_mcp_contract.py \
  -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run:

```bash
cd RpaClaw/frontend
npm run build
```

Expected: PASS.

- [ ] **Step 4: Inspect final diff**

Run:

```bash
git diff --stat
git diff -- RpaClaw/backend/rpa/api_monitor/models.py RpaClaw/backend/rpa/api_monitor/intent_pruner.py RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/rpa/api_monitor_mcp_registry.py RpaClaw/backend/route/api_monitor.py RpaClaw/frontend/src/api/apiMonitor.ts RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue
```

Expected: only files listed in this plan are changed, plus the tests touched by this plan.

- [ ] **Step 5: Final commit if Task 8 produced fixes**

If Task 8 required any fixes, commit them:

```bash
git add RpaClaw/backend RpaClaw/frontend
git commit -m "fix: stabilize api monitor batch intent pruning"
```

If Task 8 produced no code changes, do not create an empty commit.

---

## Self-Review

Spec coverage:

- Batch LLM pruning: Task 2, Task 4, Task 5.
- Classification groups and fallback to review: Task 1, Task 2, Task 3, Task 4.
- Supporting as generated reserve tools: Task 1, Task 6, Task 7.
- Filtered candidates retained with reasons and force generation: Task 3, Task 6, Task 7.
- Realtime debounce/buffer: Task 5.
- Publish excludes reserve tools: Task 1.
- Frontend order `采用 -> 不采用 -> 未生成/过滤候选`: Task 7.
- Tests and regressions: Task 1 through Task 8.

Placeholder scan:

- No unresolved placeholders are left in the plan.
- Commands include expected outcomes.
- Code steps include concrete snippets.

Type consistency:

- Backend uses `intent_group`, `intent_reason`, `intent_score`, `intent_rank`, `intent_batch_id`.
- Frontend uses the same snake_case API fields.
- Reserve tools use `is_reserve`; adoption clears `is_reserve`.
