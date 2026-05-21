# RPA Region Local-First Context Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make selected page regions the actual planner context for region-backed recording commands, so the backend LLM receives local region evidence instead of the full page snapshot as a competing input.

**Architecture:** Keep the existing chat-first `region_id` contract and trace-first recording path, but introduce a region-scoped planner payload builder inside `RecordingRuntimeAgent`. When `region_context` is present, the initial planner payload uses a minimal selected-region snapshot containing URL/title plus compact region evidence, disables full-page ordinal overlay shortcuts, and prevents oversized DOM ancestors from polluting region evidence. Full-page context remains available only to non-region commands and explicit diagnostics, not as normal LLM input for region-backed commands.

**Tech Stack:** FastAPI, Pydantic v2, Playwright async API, Vue 3, TypeScript, Vite/Vitest, pytest.

---

## Optimization Scheme

### Current Problem

The implementation currently treats selected regions as an extra hint. `RecordingRuntimeAgent.run()` always builds a full page snapshot and passes `payload["snapshot"] = compact_snapshot` to the planner. If a region exists, it appends `payload["region_context"] = compact_region_context`. That means the LLM still sees the whole page and may choose candidates outside the user-selected area.

There is a second bypass: `_build_table_ordinal_overlay_plan()` and `_build_ordinal_overlay_plan()` run before the planner. They consume the full raw snapshot and can generate a plan without consulting `region_context`. A selected region therefore does not reliably constrain ordinal commands such as "extract the first row" or "click the first button".

The region collector also risks local evidence pollution because it records intersecting ancestor containers and their full `textContent`. On app-shell-heavy pages, a selected 300px area can inherit large page-level text from a parent `div`, `main`, or `section`.

### Target Behavior

For a region-backed chat command:

- Frontend still sends only `region_id` in the chat request.
- Backend resolves `region_id` to stored authoritative evidence.
- Initial planner LLM input contains:
  - user instruction,
  - minimal page state: URL/title only,
  - runtime results,
  - compact selected region evidence.
- Initial planner LLM input does not contain full-page `actionable_nodes`, `frames`, `table_views`, `detail_views`, `form_views`, `expanded_regions`, or `sampled_regions`.
- Full-page ordinal overlay shortcuts are skipped when region context is present.
- Region evidence preserves parent scope locator hierarchy, including stable card/list/table/form containers and nested parent-child locator candidates for controls or repeated values.
- Region evidence is pruned so oversized ancestor text cannot dominate `local_text`, `dominant_container`, or planner evidence.
- Repair remains factual but region-scoped: include the original error, failed plan, current page URL/title, and region evidence. Do not add full-page compact snapshot to region repair unless a future explicit diagnostic mode asks for it.

### Non-Goals

- Do not redesign the RecorderPage UI. The bottom icon button and attachment chip remain unchanged.
- Do not add a center-canvas mode switch.
- Do not replay raw coordinates.
- Do not add global non-empty output blocking.
- Do not replace the trace-first architecture with a persistent extraction contract layer.

---

## File Map

Backend:

- Modify `RpaClaw/backend/rpa/recording_runtime_agent.py`: add region-scoped planner payload helpers, skip full-page overlay shortcuts for region commands, make repair payload region-scoped, and keep debug artifacts clear.
- Modify `RpaClaw/backend/rpa/region_context.py`: add scoped locator hierarchy collection, nested locator candidates, and evidence pruning helpers that drop oversized ancestor text while preserving usable scope locators.
- Modify `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`: add tests for region planner payload isolation, repair payload isolation, and overlay bypass prevention.
- Modify `RpaClaw/backend/tests/test_rpa_region_context.py`: add tests for scoped locator hierarchy, ancestor pruning, and local text derivation.
- Modify `RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py`: add a region nested-locator compile regression.

Frontend:

- No production UI change expected.
- Modify `RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts` only if a regression test is missing for "chat sends `region_id` only".

Verification:

- `uv run pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_region_context.py -q`
- `uv run pytest RpaClaw/backend/tests/test_rpa_trace_timeline.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q`
- `npm run test -- src/pages/rpa/RecorderPage.test.ts src/utils/rpaAssistantModel.test.ts src/utils/rpaRegionSelection.test.ts`
- `npm run build`

---

### Task 1: Lock Region Planner Payload To Local Evidence

**Files:**
- Modify: `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`
- Modify: `RpaClaw/backend/rpa/recording_runtime_agent.py`

- [ ] **Step 1: Write failing test for initial planner payload isolation**

Add a test near `test_recording_runtime_agent_passes_region_context_to_planner`:

```python
def test_recording_runtime_agent_uses_region_scoped_snapshot_for_region_planner():
    async def run_test():
        planner_calls = []
        region_context = {
            "region_id": "region-1",
            "tab_id": "tab-1",
            "page_url": "https://example.test/orders",
            "page_title": "Orders",
            "evidence": {
                "url": "https://example.test/orders",
                "title": "Orders",
                "rect": {"x": 10, "y": 20, "width": 300, "height": 160},
                "inferred_kind": "table_region",
                "local_text": ["Order A", "$10"],
                "table_summary": {"headers": ["Name", "Price"], "sample_rows": [["Order A", "$10"]]},
                "locator_candidates": [{"kind": "css", "selector": "table.orders"}],
            },
        }

        async def planner(payload):
            planner_calls.append(payload)
            return {
                "description": "Extract selected order",
                "action_type": "run_python",
                "expected_effect": "extract",
                "output_key": "selected_order",
                "code": "async def run(page, results):\n    return {'name': 'Order A'}",
            }

        result = await RecordingRuntimeAgent(planner=planner).run(
            page=_FakePage(),
            instruction="extract selected order",
            runtime_results={"previous": "value"},
            region_context=region_context,
        )

        assert result.success is True
        payload = planner_calls[0]
        assert payload["context_scope"] == "selected_region"
        assert payload["region_context"]["region_id"] == "region-1"
        assert payload["snapshot"]["mode"] == "selected_region_snapshot"
        assert payload["snapshot"]["selected_region"]["local_text"] == ["Order A", "$10"]
        assert payload["snapshot"]["url"] == "https://example.test/start"
        assert payload["runtime_results"] == {"previous": "value"}

        forbidden = {
            "actionable_nodes",
            "frames",
            "table_views",
            "detail_views",
            "form_views",
            "expanded_regions",
            "sampled_regions",
            "region_catalogue",
        }
        assert forbidden.isdisjoint(payload["snapshot"])

    asyncio.run(run_test())
```

- [ ] **Step 2: Run the test and confirm failure**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_uses_region_scoped_snapshot_for_region_planner -q
```

Expected: FAIL because `context_scope` and `selected_region_snapshot` do not exist and full compact snapshot is still passed.

- [ ] **Step 3: Add region-scoped payload helpers**

In `RpaClaw/backend/rpa/recording_runtime_agent.py`, add helpers near `_compact_region_context`:

```python
def _selected_region_snapshot(
    compact_snapshot: Dict[str, Any],
    page_state: RPAPageState,
    region_context: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "mode": "selected_region_snapshot",
        "url": str(compact_snapshot.get("url") or page_state.url or ""),
        "title": str(compact_snapshot.get("title") or page_state.title or ""),
        "selected_region": region_context,
        "scope_note": (
            "The user selected this page region for the current command. "
            "Plan extraction or action targeting from selected_region evidence first."
        ),
    }


def _build_recording_planner_payload(
    *,
    instruction: str,
    page_state: RPAPageState,
    compact_snapshot: Dict[str, Any],
    runtime_results: Dict[str, Any],
    compact_region_context: Dict[str, Any],
) -> Dict[str, Any]:
    if compact_region_context:
        return {
            "instruction": instruction,
            "page": {
                "url": page_state.url,
                "title": page_state.title,
            },
            "context_scope": "selected_region",
            "snapshot": _selected_region_snapshot(compact_snapshot, page_state, compact_region_context),
            "region_context": compact_region_context,
            "runtime_results": runtime_results,
        }
    return {
        "instruction": instruction,
        "page": page_state.model_dump(mode="json"),
        "context_scope": "full_page",
        "snapshot": compact_snapshot,
        "runtime_results": runtime_results,
    }
```

- [ ] **Step 4: Use the helper in `RecordingRuntimeAgent.run()`**

Replace the direct `payload = {...}` construction with:

```python
        payload = _build_recording_planner_payload(
            instruction=instruction,
            page_state=before,
            compact_snapshot=compact_snapshot,
            runtime_results=runtime_results,
            compact_region_context=compact_region_context,
        )
```

Remove the later manual `if compact_region_context: payload["region_context"] = compact_region_context` block because the helper owns that contract.

- [ ] **Step 5: Run the focused test**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_uses_region_scoped_snapshot_for_region_planner -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add RpaClaw/backend/rpa/recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py
git commit -m "fix: scope rpa region planner payload"
```

---

### Task 2: Disable Full-Page Overlay Shortcuts For Region Commands

**Files:**
- Modify: `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`
- Modify: `RpaClaw/backend/rpa/recording_runtime_agent.py`

- [ ] **Step 1: Write failing test for overlay bypass**

Add this test:

```python
def test_recording_runtime_agent_does_not_use_full_page_ordinal_overlay_with_region_context(monkeypatch):
    async def run_test():
        planner_calls = []

        def fake_table_overlay(instruction, snapshot):
            return {
                "description": "Wrong full-page table plan",
                "action_type": "run_python",
                "expected_effect": "extract",
                "output_key": "wrong_full_page",
                "code": "async def run(page, results):\n    return {'wrong': True}",
            }

        monkeypatch.setattr(
            "backend.rpa.recording_runtime_agent._build_table_ordinal_overlay_plan",
            fake_table_overlay,
        )

        async def planner(payload):
            planner_calls.append(payload)
            return {
                "description": "Region plan",
                "action_type": "run_python",
                "expected_effect": "extract",
                "output_key": "region_value",
                "code": "async def run(page, results):\n    return {'region': True}",
            }

        result = await RecordingRuntimeAgent(planner=planner).run(
            page=_FakePage(),
            instruction="extract the first row from this selected area",
            runtime_results={},
            region_context={
                "region_id": "region-1",
                "tab_id": "tab-1",
                "evidence": {
                    "url": "https://example.test/orders",
                    "title": "Orders",
                    "rect": {"x": 10, "y": 20, "width": 200, "height": 100},
                    "inferred_kind": "table_region",
                    "local_text": ["Region row"],
                },
            },
        )

        assert result.success is True
        assert result.output_key == "region_value"
        assert result.output == {"region": True}
        assert len(planner_calls) == 1

    asyncio.run(run_test())
```

- [ ] **Step 2: Run the test and confirm failure**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_does_not_use_full_page_ordinal_overlay_with_region_context -q
```

Expected: FAIL because the fake full-page overlay returns a plan before the planner is called.

- [ ] **Step 3: Gate overlay planning by context scope**

In `RecordingRuntimeAgent.run()`, replace:

```python
        first_plan = _build_table_ordinal_overlay_plan(instruction, snapshot)
        if not first_plan:
            first_plan = _build_ordinal_overlay_plan(instruction, snapshot)
```

with:

```python
        first_plan = None
        if not compact_region_context:
            first_plan = _build_table_ordinal_overlay_plan(instruction, snapshot)
            if not first_plan:
                first_plan = _build_ordinal_overlay_plan(instruction, snapshot)
```

- [ ] **Step 4: Run the overlay test**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_does_not_use_full_page_ordinal_overlay_with_region_context -q
```

Expected: PASS.

- [ ] **Step 5: Run non-region overlay tests**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py -q
```

Expected: PASS. Existing non-region ordinal behavior must remain intact.

- [ ] **Step 6: Commit**

```powershell
git add RpaClaw/backend/rpa/recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py
git commit -m "fix: skip full page overlays for region commands"
```

---

### Task 3: Keep Region Repair Payload Region-Scoped

**Files:**
- Modify: `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`
- Modify: `RpaClaw/backend/rpa/recording_runtime_agent.py`

- [ ] **Step 1: Write failing test for repair payload isolation**

Add this test:

```python
def test_recording_runtime_agent_region_repair_payload_excludes_full_page_snapshot():
    async def run_test():
        planner_calls = []

        async def planner(payload):
            planner_calls.append(payload)
            if len(planner_calls) == 1:
                return {
                    "description": "Broken region plan",
                    "action_type": "run_python",
                    "expected_effect": "extract",
                    "output_key": "region_value",
                    "code": "async def run(page, results):\n    raise Exception('locator failed')",
                }
            return {
                "description": "Fixed region plan",
                "action_type": "run_python",
                "expected_effect": "extract",
                "output_key": "region_value",
                "code": "async def run(page, results):\n    return {'ok': True}",
            }

        result = await RecordingRuntimeAgent(planner=planner).run(
            page=_FakePage(),
            instruction="extract selected value",
            runtime_results={},
            region_context={
                "region_id": "region-1",
                "tab_id": "tab-1",
                "evidence": {
                    "url": "https://example.test/orders",
                    "title": "Orders",
                    "rect": {"x": 10, "y": 20, "width": 200, "height": 100},
                    "inferred_kind": "text_region",
                    "local_text": ["Selected Value"],
                },
            },
        )

        assert result.success is True
        repair_payload = planner_calls[1]
        assert repair_payload["context_scope"] == "selected_region"
        assert repair_payload["snapshot"]["mode"] == "selected_region_snapshot"
        assert repair_payload["repair"]["snapshot_after_failure"]["mode"] == "selected_region_snapshot"
        assert repair_payload["repair"]["page_after_failure"]["url"] == "https://example.test/start"
        assert "actionable_nodes" not in repair_payload["repair"]["snapshot_after_failure"]
        assert "frames" not in repair_payload["repair"]["snapshot_after_failure"]

    asyncio.run(run_test())
```

- [ ] **Step 2: Run the test and confirm failure**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_region_repair_payload_excludes_full_page_snapshot -q
```

Expected: FAIL because repair currently uses `compact_failed_snapshot`.

- [ ] **Step 3: Build repair snapshot from selected region when present**

In `RecordingRuntimeAgent.run()`, after `compact_failed_snapshot` is built, add:

```python
        repair_snapshot = (
            _selected_region_snapshot(compact_failed_snapshot, failed_page, compact_region_context)
            if compact_region_context
            else compact_failed_snapshot
        )
```

Then change `diagnostic_raw["snapshot_after_failure"]` and `repair_context["snapshot_after_failure"]` to use `repair_snapshot`.

Keep debug files writing the full `raw_snapshot` and `compact_snapshot`; debug artifacts are local diagnostics, not LLM planner input.

- [ ] **Step 4: Run repair test**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_region_repair_payload_excludes_full_page_snapshot -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add RpaClaw/backend/rpa/recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py
git commit -m "fix: keep rpa region repair context local"
```

---

### Task 4: Preserve Scoped Region Locator Hierarchy

**Files:**
- Modify: `RpaClaw/backend/tests/test_rpa_region_context.py`
- Modify: `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`
- Modify: `RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py`
- Modify: `RpaClaw/backend/rpa/region_context.py`
- Modify: `RpaClaw/backend/rpa/recording_runtime_agent.py`

- [ ] **Step 1: Write failing tests for scope hierarchy preservation**

Add these tests to `RpaClaw/backend/tests/test_rpa_region_context.py`:

```python
def test_region_evidence_model_preserves_scope_locator_hierarchy():
    evidence = RPARegionEvidence(
        url="https://example.test/orders",
        title="Orders",
        rect={"x": 10, "y": 20, "width": 320, "height": 160},
        inferred_kind="action_region",
        local_text=["Order A", "Details"],
        scope_candidates=[
            {
                "kind": "css",
                "locator": {"method": "css", "value": "article.order-card"},
                "source": "ancestor_chain",
            }
        ],
        intersecting_elements=[
            {
                "tag": "button",
                "text": "Details",
                "ancestor_chain": [
                    {
                        "tag": "article",
                        "text": "Order A",
                        "locator_candidates": [
                            {"kind": "text", "locator": {"method": "text", "value": "Order A"}}
                        ],
                    }
                ],
                "nested_locator_candidates": [
                    {
                        "kind": "nested",
                        "locator": {
                            "method": "nested",
                            "parent": {"method": "text", "value": "Order A"},
                            "child": {"method": "role", "role": "button", "name": "Details"},
                        },
                    }
                ],
            }
        ],
    )

    payload = evidence.model_dump(mode="json")

    assert payload["scope_candidates"][0]["locator"]["value"] == "article.order-card"
    assert payload["intersecting_elements"][0]["ancestor_chain"][0]["tag"] == "article"
    assert payload["intersecting_elements"][0]["nested_locator_candidates"][0]["locator"]["method"] == "nested"
```

Add this test to `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`:

```python
def test_compact_region_context_forwards_scope_and_nested_locators():
    compact = _compact_region_context(
        {
            "region_id": "region-1",
            "tab_id": "tab-1",
            "evidence": {
                "url": "https://example.test/orders",
                "title": "Orders",
                "rect": {"x": 10, "y": 20, "width": 320, "height": 160},
                "inferred_kind": "action_region",
                "local_text": ["Order A", "Details"],
                "scope_candidates": [
                    {
                        "kind": "css",
                        "locator": {"method": "css", "value": "article.order-card"},
                        "source": "ancestor_chain",
                    }
                ],
                "intersecting_elements": [
                    {
                        "tag": "button",
                        "text": "Details",
                        "nested_locator_candidates": [
                            {
                                "kind": "nested",
                                "locator": {
                                    "method": "nested",
                                    "parent": {"method": "text", "value": "Order A"},
                                    "child": {"method": "role", "role": "button", "name": "Details"},
                                },
                            }
                        ],
                    }
                ],
            },
        }
    )

    assert compact["scope_candidates"][0]["locator"]["value"] == "article.order-card"
    assert compact["intersecting_elements"][0]["nested_locator_candidates"][0]["locator"]["method"] == "nested"
```

Add this regression to `RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py`:

```python
def test_region_single_value_prefers_nested_scope_locator():
    trace = RPAAcceptedTrace(
        trace_type=RPATraceType.AI_OPERATION,
        user_instruction="Extract the selected order status",
        description="Extract selected order status",
        output_key="order_status",
        region_context={
            "inferred_kind": "single_value",
            "locator_candidates": [
                {
                    "selected": True,
                    "kind": "nested",
                    "locator": {
                        "method": "nested",
                        "parent": {"method": "text", "value": "Order A"},
                        "child": {"method": "text", "value": "Paid"},
                    },
                }
            ],
        },
    )

    script = TraceSkillCompiler().generate_script([trace], is_local=True)
    _assert_script_loads(script)
    body = _execute_body(script)

    assert "get_by_text('Order A').get_by_text('Paid')" in body
    assert "_results['order_status'] = _result" in body
```

If `_compact_region_context` is not imported in `test_rpa_recording_runtime_agent.py`, extend the existing import from `backend.rpa.recording_runtime_agent` to include it.

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_region_context.py::test_region_evidence_model_preserves_scope_locator_hierarchy RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_compact_region_context_forwards_scope_and_nested_locators RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_region_single_value_prefers_nested_scope_locator -q
```

Expected: at least the model/context tests fail because `scope_candidates` and planner-facing nested locator evidence are not preserved as explicit contract fields.

- [ ] **Step 3: Add explicit evidence fields**

In `RpaClaw/backend/rpa/region_context.py`, extend `RPARegionEvidence`:

```python
    scope_candidates: List[Dict[str, Any]] = Field(default_factory=list)
```

Keep `ancestor_chain` and `nested_locator_candidates` inside `intersecting_elements` records because they are per-element evidence.

- [ ] **Step 4: Add scoped hierarchy helpers to the collector script**

Inside `REGION_COLLECTOR_JS`, add these functions after `locatorCandidates(el)`:

```javascript
  function compactAncestorRecord(el) {
    const rect = rectFromDomRect(el.getBoundingClientRect());
    return {
      tag: (el.tagName || '').toLowerCase(),
      role: roleOf(el),
      name: nameOf(el),
      text: norm(el.textContent).slice(0, 180),
      rect,
      locator_candidates: locatorCandidates(el).slice(0, 3)
    };
  }

  function isScopeCandidate(el) {
    if (!el || !el.tagName) return false;
    const tag = (el.tagName || '').toLowerCase();
    const role = roleOf(el);
    return ['article', 'section', 'form', 'table', 'ul', 'ol', 'li'].includes(tag) ||
      ['article', 'group', 'region', 'row', 'listitem', 'table', 'grid', 'list', 'form'].includes(role) ||
      Boolean(el.getAttribute && (
        el.getAttribute('data-testid') ||
        el.getAttribute('data-test') ||
        el.getAttribute('aria-label')
      ));
  }

  function ancestorChain(el) {
    const chain = [];
    let cur = el && el.parentElement;
    while (cur && cur !== document.body && cur !== document.documentElement && chain.length < 5) {
      if (isScopeCandidate(cur)) {
        chain.push(compactAncestorRecord(cur));
      }
      cur = cur.parentElement;
    }
    return chain;
  }

  function locatorPayload(candidate) {
    if (!candidate || typeof candidate !== 'object') return null;
    if (candidate.locator && typeof candidate.locator === 'object') return candidate.locator;
    if (candidate.kind === 'css' && candidate.selector) return {method: 'css', value: candidate.selector};
    return null;
  }

  function nestedLocatorCandidates(el) {
    const childCandidates = locatorCandidates(el);
    const ancestors = ancestorChain(el);
    const nested = [];
    for (const ancestor of ancestors) {
      const parentCandidate = (ancestor.locator_candidates || []).map(locatorPayload).find(Boolean);
      if (!parentCandidate) continue;
      const childCandidate = childCandidates.map(locatorPayload).find(Boolean);
      if (!childCandidate) continue;
      nested.push({
        kind: 'nested',
        locator: {
          method: 'nested',
          parent: parentCandidate,
          child: childCandidate
        },
        source: 'region_ancestor_scope'
      });
      break;
    }
    return nested;
  }
```

Then change `elementRecord(el, rect)` to include:

```javascript
      ancestor_chain: ancestorChain(el),
      nested_locator_candidates: nestedLocatorCandidates(el).slice(0, 3),
```

Add a collector-level `scope_candidates` output:

```javascript
    scope_candidates: dominantElement ? locatorCandidates(dominantElement).slice(0, 8) : [],
```

The final returned object should contain both `scope_candidates` and existing `locator_candidates`. `locator_candidates` remains the dominant container candidates for backward compatibility.

- [ ] **Step 5: Normalize and compact hierarchy fields**

In `_normalize_evidence`, normalize root scope candidates:

```python
    evidence["scope_candidates"] = evidence.get("scope_candidates") if isinstance(evidence.get("scope_candidates"), list) else []
```

In `_compact_region_context`, forward:

```python
    _set_if_present(compact, "scope_candidates", _compact_list(evidence.get("scope_candidates"), limit=10))
    _set_if_present(compact, "intersecting_elements", _compact_list(evidence.get("intersecting_elements"), limit=20))
```

This temporary forwarding keeps the new locator hierarchy visible to tests and planner payloads. Task 5 immediately follows by pruning oversized ancestor text before this evidence is compacted, so production region payloads do not keep app-shell text.

- [ ] **Step 6: Run the focused tests**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_region_context.py::test_region_evidence_model_preserves_scope_locator_hierarchy RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_compact_region_context_forwards_scope_and_nested_locators RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_region_single_value_prefers_nested_scope_locator -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add RpaClaw/backend/rpa/region_context.py RpaClaw/backend/rpa/recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_region_context.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py
git commit -m "feat: preserve rpa region scoped locators"
```

---

### Task 5: Prune Oversized Ancestors From Region Evidence

**Files:**
- Modify: `RpaClaw/backend/tests/test_rpa_region_context.py`
- Modify: `RpaClaw/backend/rpa/region_context.py`

- [ ] **Step 1: Write failing tests for evidence pruning**

Add these tests:

```python
def test_region_evidence_pruning_drops_oversized_ancestor_text():
    raw = {
        "rect": {"x": 100, "y": 100, "width": 200, "height": 100},
        "intersecting_elements": [
            {
                "tag": "main",
                "role": "",
                "text": "Global nav Settings Reports Orders Selected Price Footer",
                "rect": {"x": 0, "y": 0, "width": 1200, "height": 900},
                "locator_candidates": [{"kind": "css", "selector": "main"}],
            },
            {
                "tag": "span",
                "role": "",
                "text": "Selected Price",
                "name": "Selected Price",
                "rect": {"x": 120, "y": 120, "width": 120, "height": 24},
                "locator_candidates": [{"kind": "text", "locator": {"method": "text", "value": "Selected Price"}}],
            },
        ],
        "local_text": ["Global nav Settings Reports Orders Selected Price Footer", "Selected Price"],
        "dominant_container": {
            "tag": "main",
            "text": "Global nav Settings Reports Orders Selected Price Footer",
            "rect": {"x": 0, "y": 0, "width": 1200, "height": 900},
        },
        "scope_candidates": [
            {
                "kind": "css",
                "locator": {"method": "css", "value": "article.order-card"},
                "source": "ancestor_chain",
            }
        ],
    }

    pruned = prune_region_evidence(raw)

    assert [item["text"] for item in pruned["intersecting_elements"]] == ["Selected Price"]
    assert pruned["local_text"] == ["Selected Price"]
    assert pruned["dominant_container"]["tag"] == "span"
    assert pruned["scope_candidates"][0]["locator"]["value"] == "article.order-card"


def test_region_evidence_pruning_keeps_semantic_table_container():
    raw = {
        "rect": {"x": 100, "y": 100, "width": 500, "height": 250},
        "intersecting_elements": [
            {
                "tag": "table",
                "role": "table",
                "text": "Name Price A 10",
                "rect": {"x": 90, "y": 90, "width": 520, "height": 260},
                "locator_candidates": [{"kind": "css", "selector": "table.orders"}],
            },
            {
                "tag": "td",
                "role": "",
                "text": "A",
                "rect": {"x": 130, "y": 150, "width": 60, "height": 24},
            },
        ],
        "local_text": ["Name Price A 10", "A"],
        "dominant_container": {
            "tag": "table",
            "role": "table",
            "text": "Name Price A 10",
            "rect": {"x": 90, "y": 90, "width": 520, "height": 260},
        },
    }

    pruned = prune_region_evidence(raw)

    assert pruned["dominant_container"]["tag"] == "table"
    assert pruned["local_text"][0] == "Name Price A 10"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_region_context.py::test_region_evidence_pruning_drops_oversized_ancestor_text RpaClaw/backend/tests/test_rpa_region_context.py::test_region_evidence_pruning_keeps_semantic_table_container -q
```

Expected: FAIL because `prune_region_evidence` does not exist.

- [ ] **Step 3: Add pruning helpers**

In `RpaClaw/backend/rpa/region_context.py`, add:

```python
_SEMANTIC_CONTAINER_TAGS = {"article", "section", "form", "table", "ul", "ol", "li", "tr", "tbody", "fieldset"}
_SEMANTIC_CONTAINER_ROLES = {
    "article",
    "group",
    "region",
    "row",
    "listitem",
    "table",
    "grid",
    "list",
    "listbox",
    "menu",
    "dialog",
    "form",
}


def _record_rect(record: Dict[str, Any]) -> Dict[str, float]:
    return _rect_dict(record.get("rect") or {})


def _is_semantic_region_container(record: Dict[str, Any]) -> bool:
    tag = str(record.get("tag") or "").strip().lower()
    role = str(record.get("role") or "").strip().lower()
    return tag in _SEMANTIC_CONTAINER_TAGS or role in _SEMANTIC_CONTAINER_ROLES


def _is_oversized_ancestor_record(record: Dict[str, Any], selected_rect: Dict[str, float]) -> bool:
    if _is_semantic_region_container(record):
        return False
    selected_area = max(_rect_area(selected_rect), 1.0)
    record_area = _rect_area(_record_rect(record))
    text = str(record.get("text") or "").strip()
    return record_area > selected_area * 4 and len(text) > 120


def _dedupe_text(values: List[str], *, limit: int = 20) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text[:240])
        if len(result) >= limit:
            break
    return result


def prune_region_evidence(raw: Dict[str, Any]) -> Dict[str, Any]:
    evidence = dict(raw or {})
    selected_rect = _rect_dict(evidence.get("rect") or {})
    evidence["scope_candidates"] = (
        evidence.get("scope_candidates")
        if isinstance(evidence.get("scope_candidates"), list)
        else []
    )
    elements = [
        dict(item)
        for item in evidence.get("intersecting_elements") or []
        if isinstance(item, dict) and not _is_oversized_ancestor_record(item, selected_rect)
    ]
    if elements:
        evidence["intersecting_elements"] = elements
        dominant = evidence.get("dominant_container")
        if not isinstance(dominant, dict) or _is_oversized_ancestor_record(dominant, selected_rect):
            evidence["dominant_container"] = elements[0]
        evidence["local_text"] = _dedupe_text([str(item.get("text") or item.get("name") or "") for item in elements])
    else:
        evidence["intersecting_elements"] = []
        evidence["local_text"] = _dedupe_text([str(item) for item in evidence.get("local_text") or []])
    return evidence
```

- [ ] **Step 4: Apply pruning during normalization**

In `_normalize_evidence`, before setting normalized fields, add:

```python
    evidence = prune_region_evidence(evidence)
```

Place it after warnings are merged and before `dominant_container`, `intersecting_elements`, and `local_text` are normalized.

- [ ] **Step 5: Run region context tests**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_region_context.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add RpaClaw/backend/rpa/region_context.py RpaClaw/backend/tests/test_rpa_region_context.py
git commit -m "fix: prune oversized rpa region evidence"
```

---

### Task 6: Strengthen Existing Frontend Contract Tests

**Files:**
- Modify: `RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts`
- Modify: `RpaClaw/frontend/src/utils/rpaAssistantModel.test.ts`

- [ ] **Step 1: Confirm or add test that chat sends only `region_id`**

If existing coverage is insufficient, add this assertion to the region chat test:

```ts
const [, requestInit] = fetchMock.mock.calls[0];
const body = JSON.parse(String((requestInit as RequestInit).body));

expect(body).toMatchObject({
  message: 'extract selected results',
  mode: 'trace_first',
  region_id: 'region-42',
});
expect(body).not.toHaveProperty('region_context');
expect(body).not.toHaveProperty('evidence');
expect(body).not.toHaveProperty('rect');
expect(body).not.toHaveProperty('viewport');
```

- [ ] **Step 2: Run frontend focused tests**

Run:

```powershell
npm run test -- src/pages/rpa/RecorderPage.test.ts src/utils/rpaAssistantModel.test.ts src/utils/rpaRegionSelection.test.ts
```

Expected: PASS.

- [ ] **Step 3: Commit only if tests changed**

```powershell
git add RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts RpaClaw/frontend/src/utils/rpaAssistantModel.test.ts
git commit -m "test: lock rpa region chat payload contract"
```

If no test change is required, skip this commit.

---

### Task 7: Full Regression And Documentation Update

**Files:**
- Modify: `docs/superpowers/specs/2026-05-18-rpa-region-context-design.md`
- Modify: `docs/superpowers/plans/2026-05-18-rpa-region-context-implementation.md` only if it needs a note pointing to this hardening plan.

- [ ] **Step 1: Add design note**

Append a short section to `docs/superpowers/specs/2026-05-18-rpa-region-context-design.md`:

```markdown
## Region-Scoped Planner Context Hardening

When a chat command includes `region_id`, the selected region is the planner scope for the initial runtime LLM call. The planner receives page URL/title, runtime results, and compact region evidence. It must not receive full-page snapshot structures such as `actionable_nodes`, `frames`, `table_views`, `detail_views`, `form_views`, `expanded_regions`, or `sampled_regions` as competing initial context.

Full-page ordinal overlay shortcuts are disabled for region-backed commands. Region evidence must preserve scoped locator hierarchy, including stable parent containers and nested parent-child locator candidates, while pruning oversized ancestor text from planner-facing local text. Region evidence may still include locator-backed local table/list/control summaries, but raw coordinates remain diagnostic evidence rather than replay logic.
```

- [ ] **Step 2: Run backend focused regression**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_region_context.py RpaClaw/backend/tests/test_rpa_trace_timeline.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend focused regression**

Run:

```powershell
npm run test -- src/pages/rpa/RecorderPage.test.ts src/utils/rpaAssistantModel.test.ts src/utils/rpaRegionSelection.test.ts
```

Expected: PASS.

- [ ] **Step 4: Run build**

Run:

```powershell
npm run build
```

Expected: PASS. Existing duplicate locale key and chunk size warnings are acceptable if unchanged.

- [ ] **Step 5: Type-check caveat**

Run:

```powershell
npm run type-check
```

Expected: The command may still fail on existing unrelated global TypeScript errors. Confirm no new errors mention:

- `src/pages/rpa/RecorderPage.test.ts`
- `src/utils/rpaAssistantModel.ts`
- `src/utils/rpaRegionSelection.ts`

- [ ] **Step 6: Commit docs**

```powershell
git add docs/superpowers/specs/2026-05-18-rpa-region-context-design.md docs/superpowers/plans/2026-05-19-rpa-region-local-first-context-hardening.md
git commit -m "docs: plan rpa region local first hardening"
```

---

## Acceptance Criteria

- With `region_id`, the first LLM planner call receives `context_scope="selected_region"`.
- With `region_id`, the first LLM planner call does not receive full-page `actionable_nodes`, `frames`, `table_views`, `detail_views`, `form_views`, `expanded_regions`, `sampled_regions`, or `region_catalogue`.
- With `region_id`, full-page ordinal overlay shortcuts do not run.
- Region repair payload remains region-scoped and contains error facts plus current URL/title, not full-page compact snapshot.
- Region planner evidence preserves `scope_candidates`, per-element `ancestor_chain`, and `nested_locator_candidates` where available.
- Region single-value/action compiler paths can consume nested parent-child locator candidates and generate scoped Playwright calls.
- Region evidence pruning removes oversized non-semantic ancestors from planner-facing evidence.
- Region evidence pruning removes parent text pollution without deleting stable parent scope locators.
- Frontend chat request still sends only `region_id`, not full evidence payload.
- Existing non-region recording behavior is unchanged.
- Trace/compiler behavior remains trace-first and locator-backed; raw coordinates are not replay selectors.

## Risk Notes

- This intentionally reduces initial LLM context for region-backed commands. If users select too small or wrong a region, the failure should surface as a region-selection problem instead of letting the LLM silently use unrelated full-page candidates.
- Repair loses broad page context for region commands. That is acceptable for this hardening because the selected region is the user’s explicit scope; future diagnostics can add an opt-in full-page repair mode if evidence shows it is needed.
- Existing full-page overlay plans remain available for non-region commands.
