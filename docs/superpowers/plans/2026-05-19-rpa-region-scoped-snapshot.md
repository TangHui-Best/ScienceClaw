# RPA Region-Scoped Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a selected page region constrain the next RPA natural-language instruction by feeding `region_scope` into raw snapshot capture and compact snapshot compression.

**Architecture:** Keep the existing region selection UI and API shape. Convert stored region evidence into a small `RegionScope`, pass that scope through `build_page_snapshot()` and `compact_recording_snapshot()`, and produce a unified `region_scoped_snapshot` planner payload. Preserve Trace-first by storing scope as evidence on accepted traces without replaying coordinates.

**Tech Stack:** FastAPI, Python, Pydantic v2, Playwright page/frame evaluation, existing `snapshot_compression.py`, existing Vue recorder UI without visual changes.

---

## Hard Boundaries

- Do not change the current region selection UI interaction. If an implementation step appears to require visible UI behavior changes, stop and ask the user first.
- Keep `POST /rpa/session/{session_id}/region/analyze` and chat `region_id` payload compatible with the current frontend.
- Do not compile or replay raw coordinates.
- Do not use screenshot/VLM as the main path.
- Do not let `region_context.py` become a second snapshot/compression/compiler system.

## File Structure

- Modify `RpaClaw/backend/rpa/region_context.py`
  - Add `RPARegionScope` and conversion from stored `RPARegionContext`.
  - Keep preview/evidence compatibility.
- Modify `RpaClaw/backend/rpa/assistant_snapshot_runtime.py`
  - Allow snapshot JS to accept a frame-local region scope and mark scope relation.
  - Prioritize scoped nodes before global caps.
- Modify `RpaClaw/backend/rpa/assistant_runtime.py`
  - Thread optional `region_scope` into frame snapshot extraction.
  - Add raw snapshot `region_scope` metadata.
- Modify `RpaClaw/backend/rpa/snapshot_compression.py`
  - Add optional `region_scope`.
  - Add `region_scoped_snapshot` mode.
  - Scope `table_views`, `detail_views`, `form_views`, `expanded_regions`, `sampled_regions`, and `region_catalogue`.
- Modify `RpaClaw/backend/rpa/recording_runtime_agent.py`
  - Convert `region_context` into scope.
  - Pass scope into snapshot capture/compression.
  - Stop using top-level planner `region_context` as the main path.
  - Keep trace/debug compatibility signals.
- Modify `RpaClaw/backend/rpa/trace_models.py`
  - Add `region_scope: Dict[str, Any] = Field(default_factory=dict)` while keeping `region_context` for backward compatibility.
- Modify backend tests:
  - `RpaClaw/backend/tests/test_rpa_region_context.py`
  - `RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py`
  - `RpaClaw/backend/tests/test_rpa_snapshot_compression.py`
  - `RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py`
  - `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`
  - `RpaClaw/backend/tests/test_rpa_trace_models.py`
- Do not modify frontend files in this implementation unless the user explicitly approves a UI/API adjustment.

---

### Task 1: Add RegionScope Model And Conversion

**Files:**
- Modify: `RpaClaw/backend/rpa/region_context.py`
- Test: `RpaClaw/backend/tests/test_rpa_region_context.py`

- [ ] **Step 1: Write failing tests for scope conversion**

Append these tests near the existing region context model tests:

```python
def test_region_context_builds_scope_from_evidence():
    context = _context("region-1", url="https://example.test/a")
    context.evidence.frame_path = ["iframe.detail"]
    context.evidence.rect = {"x": 10, "y": 20, "width": 100, "height": 50}

    scope = context.to_scope()

    assert scope.model_dump(mode="json") == {
        "region_id": "region-1",
        "session_id": "session-1",
        "tab_id": "tab-1",
        "page_url": "https://example.test/a",
        "page_title": "Example",
        "viewport_rect": {"x": 10.0, "y": 20.0, "width": 100.0, "height": 50.0},
        "frame_path": ["iframe.detail"],
        "frame_rect": {"x": 10.0, "y": 20.0, "width": 100.0, "height": 50.0},
        "warnings": [],
    }


def test_region_scope_omits_standalone_evidence_payload():
    context = _context("region-1")
    context.evidence.local_text = ["Price", "SKU"]
    context.evidence.intersecting_elements = [{"text": "raw dom"}]

    payload = context.to_scope().model_dump(mode="json")

    assert "local_text" not in payload
    assert "intersecting_elements" not in payload
```

- [ ] **Step 2: Run model tests and verify failure**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_region_context.py::test_region_context_builds_scope_from_evidence RpaClaw/backend/tests/test_rpa_region_context.py::test_region_scope_omits_standalone_evidence_payload -q
```

Expected: fail because `RPARegionContext.to_scope()` does not exist.

- [ ] **Step 3: Add `RPARegionScope` and conversion**

In `RpaClaw/backend/rpa/region_context.py`, add after `RPARegionEvidence`:

```python
class RPARegionScope(BaseModel):
    region_id: str
    session_id: str
    tab_id: str
    page_url: str = ""
    page_title: str = ""
    viewport_rect: Dict[str, float] = Field(default_factory=dict)
    frame_path: List[str] = Field(default_factory=list)
    frame_rect: Dict[str, float] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
```

Then add this method to `RPARegionContext`:

```python
    def to_scope(self) -> RPARegionScope:
        rect = _rect_dict(self.evidence.rect or {})
        return RPARegionScope(
            region_id=self.region_id,
            session_id=self.session_id,
            tab_id=self.tab_id,
            page_url=self.page_url,
            page_title=self.page_title,
            viewport_rect=rect,
            frame_path=list(self.evidence.frame_path or []),
            frame_rect=rect,
            warnings=list(self.evidence.warnings or []),
        )
```

- [ ] **Step 4: Run model tests and verify pass**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_region_context.py::test_region_context_builds_scope_from_evidence RpaClaw/backend/tests/test_rpa_region_context.py::test_region_scope_omits_standalone_evidence_payload -q
```

Expected: 2 passed.

- [ ] **Step 5: Commit Task 1**

```powershell
git add RpaClaw/backend/rpa/region_context.py RpaClaw/backend/tests/test_rpa_region_context.py
git commit -m "feat: add rpa region scope model"
```

---

### Task 2: Thread RegionScope Through Raw Snapshot Capture

**Files:**
- Modify: `RpaClaw/backend/rpa/assistant_snapshot_runtime.py`
- Modify: `RpaClaw/backend/rpa/assistant_runtime.py`
- Test: `RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py`

- [ ] **Step 1: Write failing runtime JS contract test**

Add this test:

```python
def test_snapshot_v2_js_accepts_region_scope_and_marks_scope_relation():
    assert "(regionScopeArg = null)" in SNAPSHOT_V2_JS
    assert "scopeRelationForRect" in SNAPSHOT_V2_JS
    assert "scope_relation: scopeRelationForRect(rect)" in SNAPSHOT_V2_JS
    assert "sortScopedFirst" in SNAPSHOT_V2_JS
```

- [ ] **Step 2: Write failing Python signature test**

Add this test:

```python
def test_build_page_snapshot_accepts_region_scope():
    from backend.rpa.assistant_runtime import build_page_snapshot

    signature = inspect.signature(build_page_snapshot)

    assert "region_scope" in signature.parameters
    assert signature.parameters["region_scope"].default is None
```

- [ ] **Step 3: Run capture contract tests and verify failure**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py::test_snapshot_v2_js_accepts_region_scope_and_marks_scope_relation RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py::test_build_page_snapshot_accepts_region_scope -q
```

Expected: fail because JS and Python signatures do not accept scope.

- [ ] **Step 4: Update JS function signature and helpers**

In `RpaClaw/backend/rpa/assistant_snapshot_runtime.py`, change:

```javascript
SNAPSHOT_V2_JS = r"""() => {
```

to:

```javascript
SNAPSHOT_V2_JS = r"""(regionScopeArg = null) => {
```

Add these helpers near `bbox(rect)`:

```javascript
    const regionScope = regionScopeArg && regionScopeArg.rect ? regionScopeArg : null;

    function rectIntersectionArea(left, right) {
        if (!left || !right)
            return 0;
        const lx = Number(left.x || 0);
        const ly = Number(left.y || 0);
        const rx = Number(right.x || 0);
        const ry = Number(right.y || 0);
        const lright = lx + Number(left.width || 0);
        const lbottom = ly + Number(left.height || 0);
        const rright = rx + Number(right.width || 0);
        const rbottom = ry + Number(right.height || 0);
        const width = Math.max(0, Math.min(lright, rright) - Math.max(lx, rx));
        const height = Math.max(0, Math.min(lbottom, rbottom) - Math.max(ly, ry));
        return width * height;
    }

    function scopeRelationForRect(rect) {
        if (!regionScope)
            return '';
        const nodeBox = bbox(rect);
        return rectIntersectionArea(nodeBox, regionScope.rect) > 0 ? 'inside_region' : 'outside_context';
    }

    function sortScopedFirst(elements) {
        if (!regionScope)
            return elements;
        return elements.slice().sort((left, right) => {
            const leftArea = rectIntersectionArea(bbox(left.getBoundingClientRect()), regionScope.rect);
            const rightArea = rectIntersectionArea(bbox(right.getBoundingClientRect()), regionScope.rect);
            if (leftArea !== rightArea)
                return rightArea - leftArea;
            return 0;
        });
    }
```

- [ ] **Step 5: Apply scoped ordering and relation to node loops**

Change both loops:

```javascript
for (const el of Array.from(document.querySelectorAll(ACTIONABLE))) {
```

and:

```javascript
for (const el of Array.from(document.querySelectorAll(CONTENT))) {
```

to:

```javascript
for (const el of sortScopedFirst(Array.from(document.querySelectorAll(ACTIONABLE)))) {
```

and:

```javascript
for (const el of sortScopedFirst(Array.from(document.querySelectorAll(CONTENT)))) {
```

Add `scope_relation` to both node records:

```javascript
            scope_relation: scopeRelationForRect(rect),
```

- [ ] **Step 6: Thread scope through Python frame extraction**

In `RpaClaw/backend/rpa/assistant_runtime.py`, update `_extract_frame_snapshot_v2`:

```python
async def _extract_frame_snapshot_v2(frame, region_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        ready = await frame.evaluate("() => !!globalThis.__rpaPlaywrightRecorder")
        if not ready:
            await frame.evaluate(PLAYWRIGHT_RECORDER_RUNTIME_JS)
        raw = await frame.evaluate(SNAPSHOT_V2_JS, region_scope or None)
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        data = None
```

Update `build_page_snapshot` signature:

```python
async def build_page_snapshot(
    page,
    frame_path_builder: Callable[[Any], Any],
    region_scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
```

Inside `walk(frame)`, compute frame-local scope before calling `_extract_frame_snapshot_v2`:

```python
            scope_frame_path = list((region_scope or {}).get("frame_path") or [])
            frame_scope = None
            if region_scope and scope_frame_path == frame_path:
                frame_scope = {"rect": dict(region_scope.get("frame_rect") or region_scope.get("viewport_rect") or {})}
            snapshot_v2 = await _extract_frame_snapshot_v2(frame, frame_scope)
```

Add `region_scope` to the returned snapshot when present:

```python
    payload = {
        "url": page.url,
        "title": await page.title(),
        "frames": frames,
        "actionable_nodes": actionable_nodes,
        "content_nodes": content_nodes,
        "containers": containers,
        "table_views": table_views,
        "detail_views": detail_views,
    }
    if region_scope:
        payload["region_scope"] = dict(region_scope)
    return payload
```

- [ ] **Step 7: Run capture contract tests and verify pass**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py::test_snapshot_v2_js_accepts_region_scope_and_marks_scope_relation RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py::test_build_page_snapshot_accepts_region_scope -q
```

Expected: 2 passed.

- [ ] **Step 8: Commit Task 2**

```powershell
git add RpaClaw/backend/rpa/assistant_snapshot_runtime.py RpaClaw/backend/rpa/assistant_runtime.py RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py
git commit -m "feat: prioritize rpa region nodes in snapshot capture"
```

---

### Task 3: Add Region-Scoped Compression Mode

**Files:**
- Modify: `RpaClaw/backend/rpa/snapshot_compression.py`
- Test: `RpaClaw/backend/tests/test_rpa_snapshot_compression.py`
- Test: `RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py`

- [ ] **Step 1: Write failing compression test for candidate filtering**

Add this test to `test_rpa_snapshot_compression.py`:

```python
def test_region_scoped_snapshot_expands_only_selected_candidate_regions():
    snapshot = {
        "url": "https://example.test/page",
        "title": "Scoped Page",
        "content_nodes": [
            {
                "node_id": "outside-title",
                "container_id": "outside",
                "semantic_kind": "text",
                "text": "Invoice Price Total",
                "bbox": {"x": 20, "y": 20, "width": 220, "height": 20},
                "scope_relation": "outside_context",
            },
            {
                "node_id": "inside-label",
                "container_id": "inside",
                "semantic_kind": "label",
                "text": "SKU:",
                "bbox": {"x": 100, "y": 100, "width": 60, "height": 20},
                "scope_relation": "inside_region",
            },
            {
                "node_id": "inside-value",
                "container_id": "inside",
                "semantic_kind": "value",
                "text": "A-001",
                "bbox": {"x": 170, "y": 100, "width": 80, "height": 20},
                "scope_relation": "inside_region",
            },
        ],
        "actionable_nodes": [],
        "containers": [
            {"container_id": "outside", "summary": "Invoice Price Total", "bbox": {"x": 0, "y": 0, "width": 400, "height": 80}},
            {"container_id": "inside", "summary": "SKU A-001", "bbox": {"x": 90, "y": 90, "width": 200, "height": 80}},
        ],
        "frames": [],
        "table_views": [],
        "detail_views": [],
        "region_scope": {
            "region_id": "region-1",
            "frame_path": [],
            "frame_rect": {"x": 90, "y": 90, "width": 220, "height": 120},
        },
    }

    compact = compact_recording_snapshot(snapshot, "extract invoice price total", char_budget=1)

    assert compact["mode"] == "region_scoped_snapshot"
    assert compact["region_scope"]["region_id"] == "region-1"
    assert [region["summary"] for region in compact["expanded_regions"]] == ["SKU=A-001"]
    assert compact["sampled_regions"] == []
    assert all("Invoice Price Total" not in str(region) for region in compact["expanded_regions"])
```

- [ ] **Step 2: Write failing structured view scoped test**

Add this test to `test_rpa_snapshot_compression_structured.py`:

```python
def test_region_scoped_snapshot_keeps_selected_table_headers_and_rows():
    snapshot = _structured_view_snapshot()
    snapshot["region_scope"] = {
        "region_id": "region-table",
        "frame_path": [],
        "frame_rect": {"x": 0, "y": 0, "width": 500, "height": 300},
    }
    snapshot["table_views"][0]["scope_relation"] = "inside_region"
    snapshot["detail_views"][0]["scope_relation"] = "outside_context"

    compact = compact_recording_snapshot(snapshot, "提取采购信息", char_budget=1)

    assert compact["mode"] == "region_scoped_snapshot"
    assert len(compact["table_views"]) == 1
    assert compact["table_views"][0]["title"] == "EDM Request"
    assert compact["detail_views"] == []
```

- [ ] **Step 3: Run scoped compression tests and verify failure**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_expands_only_selected_candidate_regions RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py::test_region_scoped_snapshot_keeps_selected_table_headers_and_rows -q
```

Expected: fail because scoped mode does not exist.

- [ ] **Step 4: Update compression signature and branch**

In `snapshot_compression.py`, update the function signature:

```python
def compact_recording_snapshot(
    snapshot: Dict[str, Any],
    instruction: str,
    *,
    char_budget: int = 60000,
    region_scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    effective_scope = dict(region_scope or snapshot.get("region_scope") or {})
    if effective_scope:
        return _compact_region_scoped_snapshot(snapshot, instruction, effective_scope, char_budget=char_budget)
    regions = build_structured_regions(snapshot)
```

- [ ] **Step 5: Add scoped compaction helpers**

Add these helpers near `compact_recording_snapshot`:

```python
def _compact_region_scoped_snapshot(
    snapshot: Dict[str, Any],
    instruction: str,
    region_scope: Dict[str, Any],
    *,
    char_budget: int,
) -> Dict[str, Any]:
    regions = build_structured_regions(snapshot)
    selected_regions = [region for region in regions if _region_is_inside_scope(region, snapshot)]
    context_regions = [region for region in regions if region not in selected_regions and _region_is_context_scope(region, snapshot)]
    if not selected_regions:
        selected_regions = _regions_intersecting_scope(regions, region_scope)
    selected_regions.sort(key=lambda region: (-_region_relevance(region, instruction), _region_rank(region), region.get("title", "")))
    expanded_regions = [_expanded_region(region) for region in selected_regions]
    context_catalogue = [_summary_region(region) for region in context_regions[:4]]
    return {
        "mode": "region_scoped_snapshot",
        "url": snapshot.get("url", ""),
        "title": snapshot.get("title", ""),
        "region_scope": _compact_region_scope(region_scope),
        "page_context": _region_page_context(snapshot, context_regions),
        "table_views": _compact_table_views(snapshot, scope_only=True),
        "detail_views": _compact_detail_views(snapshot, scope_only=True),
        "form_views": _compact_form_views(snapshot, scope_only=True),
        "expanded_regions": expanded_regions,
        "sampled_regions": [],
        "region_catalogue": context_catalogue,
    }
```

Add relation helpers:

```python
def _node_scope_relation(node: Dict[str, Any]) -> str:
    return str(node.get("scope_relation") or "").strip()


def _region_node_relations(region: Dict[str, Any], snapshot: Dict[str, Any]) -> set[str]:
    container_id = str(region.get("container_id") or "")
    relations: set[str] = set()
    for node in list(snapshot.get("content_nodes") or []) + list(snapshot.get("actionable_nodes") or []):
        if str(node.get("container_id") or "") == container_id:
            relation = _node_scope_relation(node)
            if relation:
                relations.add(relation)
    return relations


def _region_is_inside_scope(region: Dict[str, Any], snapshot: Dict[str, Any]) -> bool:
    return "inside_region" in _region_node_relations(region, snapshot)


def _region_is_context_scope(region: Dict[str, Any], snapshot: Dict[str, Any]) -> bool:
    return bool(_region_node_relations(region, snapshot) & {"ancestor_context", "outside_context"})
```

Add compact scope/context helpers:

```python
def _compact_region_scope(region_scope: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "region_id": region_scope.get("region_id", ""),
        "tab_id": region_scope.get("tab_id", ""),
        "frame_path": list(region_scope.get("frame_path") or []),
        "frame_rect": dict(region_scope.get("frame_rect") or {}),
        "warnings": list(region_scope.get("warnings") or []),
    }


def _region_page_context(snapshot: Dict[str, Any], context_regions: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "url": snapshot.get("url", ""),
        "title": snapshot.get("title", ""),
        "context_regions": [_summary_region(region) for region in list(context_regions)[:4]],
    }
```

Add a simple fallback helper:

```python
def _regions_intersecting_scope(regions: Sequence[Dict[str, Any]], region_scope: Dict[str, Any]) -> List[Dict[str, Any]]:
    scope_rect = region_scope.get("frame_rect") or region_scope.get("viewport_rect") or {}
    if not scope_rect:
        return []
    return [
        region for region in regions
        if _rects_intersect(region.get("bbox") or {}, scope_rect)
    ]


def _rects_intersect(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    if not left or not right:
        return False
    lx = float(left.get("x", 0) or 0)
    ly = float(left.get("y", 0) or 0)
    rx = float(right.get("x", 0) or 0)
    ry = float(right.get("y", 0) or 0)
    return (
        min(lx + float(left.get("width", 0) or 0), rx + float(right.get("width", 0) or 0)) > max(lx, rx)
        and min(ly + float(left.get("height", 0) or 0), ry + float(right.get("height", 0) or 0)) > max(ly, ry)
    )
```

- [ ] **Step 6: Make structured view compactors scope-aware**

Update signatures:

```python
def _compact_table_views(snapshot: Dict[str, Any], *, row_limit: int = 10, cell_limit: int = 12, scope_only: bool = False) -> List[Dict[str, Any]]:
```

```python
def _compact_detail_views(snapshot: Dict[str, Any], *, field_limit: int = 40, scope_only: bool = False) -> List[Dict[str, Any]]:
```

```python
def _compact_form_views(snapshot: Dict[str, Any], *, field_limit: int = 30, scope_only: bool = False) -> List[Dict[str, Any]]:
```

At the start of each view loop, skip outside views:

```python
        if scope_only and str(view.get("scope_relation") or "") not in {"inside_region", "ancestor_context"}:
            continue
```

For `_compact_form_views`, because form views are derived from containers/nodes, filter controls:

```python
        if scope_only:
            controls = [node for node in controls if _node_scope_relation(node) == "inside_region"]
```

- [ ] **Step 7: Run scoped compression tests and verify pass**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py::test_region_scoped_snapshot_expands_only_selected_candidate_regions RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py::test_region_scoped_snapshot_keeps_selected_table_headers_and_rows -q
```

Expected: 2 passed.

- [ ] **Step 8: Run existing compression regression subset**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py -q
```

Expected: all tests pass. If unrelated existing failures appear, record exact failures in F002 Evidence before proceeding.

- [ ] **Step 9: Commit Task 3**

```powershell
git add RpaClaw/backend/rpa/snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py
git commit -m "feat: add rpa region-scoped snapshot compression"
```

---

### Task 4: Wire RecordingRuntimeAgent To Scoped Snapshot

**Files:**
- Modify: `RpaClaw/backend/rpa/recording_runtime_agent.py`
- Test: `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`

- [ ] **Step 1: Replace old planner region-context test with scoped snapshot expectation**

Update `test_recording_runtime_agent_passes_region_context_to_planner` so the key assertion becomes:

```python
        snapshot = planner_calls[0]["snapshot"]
        assert "region_context" not in planner_calls[0]
        assert snapshot["mode"] == "region_scoped_snapshot"
        assert snapshot["region_scope"]["region_id"] == "region-1"
```

Keep assertions that trace signals include `region_selection`, but update trace scope assertions after Task 5.

- [ ] **Step 2: Run runtime test and verify failure**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_passes_region_context_to_planner -q
```

Expected: fail because runtime still sends top-level `region_context`.

- [ ] **Step 3: Update snapshot helper signatures in runtime**

Find `_safe_page_snapshot` and `_compact_snapshot` in `recording_runtime_agent.py` and update them to:

```python
async def _safe_page_snapshot(page: Any, region_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        return await build_page_snapshot(page, build_frame_path, region_scope=region_scope)
    except Exception as exc:
        logger.warning("[RPA] failed to build page snapshot: %s", exc)
        return {}
```

```python
def _compact_snapshot(snapshot: Dict[str, Any], instruction: str, region_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        return compact_recording_snapshot(snapshot, instruction, region_scope=region_scope)
    except Exception as exc:
        logger.warning("[RPA] failed to compact page snapshot: %s", exc)
        return snapshot
```

- [ ] **Step 4: Add runtime scope conversion helper**

Add near existing region helpers:

```python
def _region_scope_from_context(region_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(region_context, dict) or not region_context:
        return {}
    evidence = region_context.get("evidence") if isinstance(region_context.get("evidence"), dict) else {}
    rect = dict(evidence.get("rect") or {})
    return {
        "region_id": region_context.get("region_id", ""),
        "session_id": region_context.get("session_id", ""),
        "tab_id": region_context.get("tab_id", ""),
        "page_url": region_context.get("page_url", ""),
        "page_title": region_context.get("page_title", ""),
        "viewport_rect": rect,
        "frame_path": list(evidence.get("frame_path") or []),
        "frame_rect": rect,
        "warnings": list(evidence.get("warnings") or []),
    }
```

- [ ] **Step 5: Use scoped snapshot in `run()`**

In `RecordingRuntimeAgent.run`, replace:

```python
        snapshot = await _safe_page_snapshot(page)
        compact_snapshot = _compact_snapshot(snapshot, instruction)
        compact_region_context = _compact_region_context(region_context)
        raw_region_evidence = _raw_region_evidence(region_context)
```

with:

```python
        region_scope = _region_scope_from_context(region_context)
        snapshot = await _safe_page_snapshot(page, region_scope=region_scope or None)
        compact_snapshot = _compact_snapshot(snapshot, instruction, region_scope=region_scope or None)
        compact_region_context = _compact_region_context(region_context)
        raw_region_evidence = _raw_region_evidence(region_context)
```

Remove this planner payload block:

```python
        if compact_region_context:
            payload["region_context"] = compact_region_context
```

Keep debug extras for transition, but rename/add scoped data:

```python
        if region_scope:
            snapshot_extra["region_scope"] = region_scope
            snapshot_extra["region_scoped_snapshot"] = compact_snapshot
```

- [ ] **Step 6: Run runtime scoped planner test and verify pass**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_passes_region_context_to_planner RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_omits_region_context_when_absent -q
```

Expected: both pass.

- [ ] **Step 7: Commit Task 4**

```powershell
git add RpaClaw/backend/rpa/recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py
git commit -m "feat: route rpa region selections through scoped snapshots"
```

---

### Task 5: Persist Trace Scope Evidence Without Coordinates As Replay Logic

**Files:**
- Modify: `RpaClaw/backend/rpa/trace_models.py`
- Modify: `RpaClaw/backend/rpa/recording_runtime_agent.py`
- Test: `RpaClaw/backend/tests/test_rpa_trace_models.py`
- Test: `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`

- [ ] **Step 1: Write failing trace model test**

In `test_rpa_trace_models.py`, add:

```python
def test_accepted_trace_carries_region_scope_evidence():
    trace = RPAAcceptedTrace(
        trace_type=RPATraceType.AI_OPERATION,
        region_scope={"region_id": "region-1", "mode": "region_scoped_snapshot"},
    )

    payload = trace.model_dump(mode="json")

    assert payload["region_scope"] == {"region_id": "region-1", "mode": "region_scoped_snapshot"}
```

- [ ] **Step 2: Run trace model test and verify failure**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_trace_models.py::test_accepted_trace_carries_region_scope_evidence -q
```

Expected: fail because `region_scope` field does not exist.

- [ ] **Step 3: Add trace model field**

In `RPAAcceptedTrace`, add after `region_context`:

```python
    region_scope: Dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Persist scope in accepted trace**

Update `_accepted_trace` signature:

```python
        region_scope: Optional[Dict[str, Any]] = None,
```

When constructing `RPAAcceptedTrace`, pass:

```python
            region_scope=dict(region_scope or {}),
```

Update both `_accepted_trace(...)` call sites in `run()` to include:

```python
                region_scope=region_scope,
```

- [ ] **Step 5: Update runtime test scope assertions**

In `test_recording_runtime_agent_passes_region_context_to_planner`, add:

```python
        assert result.trace.region_scope["region_id"] == "region-1"
        assert result.trace.region_scope["frame_path"] == ["iframe.detail"]
```

In `test_recording_runtime_agent_omits_region_context_when_absent`, add:

```python
        assert result.trace.region_scope == {}
```

- [ ] **Step 6: Run trace model and runtime tests**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_trace_models.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_passes_region_context_to_planner RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_omits_region_context_when_absent -q
```

Expected: pass.

- [ ] **Step 7: Commit Task 5**

```powershell
git add RpaClaw/backend/rpa/trace_models.py RpaClaw/backend/rpa/recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_trace_models.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py
git commit -m "feat: persist rpa region scope on traces"
```

---

### Task 6: Preserve API And UI Behavior Without Visual Changes

**Files:**
- Modify only if tests prove backend payload compatibility is broken: `RpaClaw/backend/route/rpa.py`
- Test: `RpaClaw/backend/tests/test_rpa_region_context.py`
- Test only, no UI edit: `RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts`

- [ ] **Step 1: Run backend region route tests**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_region_context.py -q
```

Expected: pass in a fully provisioned backend environment. If the local environment lacks `langchain_openai`, record the dependency failure in Evidence and run the pure model tests from Task 1 plus runtime tests instead.

- [ ] **Step 2: Inspect frontend payload tests without changing UI**

Run from `RpaClaw/frontend` when `node_modules` exists:

```powershell
npm run test -- RecorderPage rpaRegionSelection rpaAssistantModel
```

Expected: existing region selection behavior remains green. If `node_modules` is missing, record `node_modules missing` in Evidence and do not edit frontend files.

- [ ] **Step 3: Stop if a UI change appears necessary**

If backend contract changes require editing `RecorderPage.vue`, stop and ask the user. The allowed no-question changes are limited to test expectation updates that prove existing UI behavior still sends `region_id` once and clears it after successful send.

- [ ] **Step 4: Commit only if backend compatibility code or tests changed**

If no files changed in this task, do not create an empty commit.

If route/test compatibility changes were needed:

```powershell
git add RpaClaw/backend/route/rpa.py RpaClaw/backend/tests/test_rpa_region_context.py RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts
git commit -m "test: preserve rpa region selection ui contract"
```

---

### Task 7: Update Harness Evidence And Run Final Verification

**Files:**
- Create or Modify: `docs/evidence/EV-002-rpa-region-scoped-snapshot.md`
- Modify: `docs/features/F002-rpa-region-scoped-snapshot.md`

- [ ] **Step 1: Create Evidence document**

Create `docs/evidence/EV-002-rpa-region-scoped-snapshot.md`:

```markdown
---
doc_kind: evidence
id: EV-002
title: RPA Region-Scoped Snapshot Evidence
status: active
feature_ids: [F002]
created: 2026-05-19
updated: 2026-05-19
scope: RPA region-scoped snapshot capture and compression
---

# EV-002 RPA Region-Scoped Snapshot Evidence

## Commands

Pending implementation verification.

## Results

Pending implementation verification.

## Artifacts

- Feature: `docs/features/F002-rpa-region-scoped-snapshot.md`
- Spec: `docs/superpowers/specs/2026-05-19-rpa-region-scoped-snapshot-design.md`
- Plan: `docs/superpowers/plans/2026-05-19-rpa-region-scoped-snapshot.md`

## Notes

Implementation must prove that selected-region DOM enters raw capture before global caps and that compact snapshot excludes outside DOM from task candidates while preserving page identity/context.
```

- [ ] **Step 2: Link Evidence from Feature**

Update `docs/features/F002-rpa-region-scoped-snapshot.md` frontmatter:

```yaml
evidence:
  - docs/evidence/EV-002-rpa-region-scoped-snapshot.md
```

- [ ] **Step 3: Run final backend verification**

Run:

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_region_context.py RpaClaw/backend/tests/test_rpa_assistant_snapshot_runtime.py RpaClaw/backend/tests/test_rpa_snapshot_compression.py RpaClaw/backend/tests/test_rpa_snapshot_compression_structured.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_trace_models.py -q
```

Expected: pass in a fully provisioned backend environment. If route imports fail because optional LLM packages are not installed, record exact missing packages and rerun the subset that does not import `backend.route.rpa`.

- [ ] **Step 4: Run frontend contract verification without UI edits**

Run from `RpaClaw/frontend` when dependencies exist:

```powershell
npm run test -- RecorderPage rpaRegionSelection rpaAssistantModel
npm run type-check
```

Expected: pass. If dependencies are missing, record that no frontend verification was possible in this worktree.

- [ ] **Step 5: Update Evidence results**

Replace the pending sections in `EV-002` with the commands actually run and their results. Include:

```markdown
## Commands

- `$env:PYTHONPATH="RpaClaw"; python -m pytest ... -q`
- `npm run test -- RecorderPage rpaRegionSelection rpaAssistantModel`
- `npm run type-check`

## Results

- Backend: pass or exact failure.
- Frontend: pass, skipped with reason, or exact failure.

## Artifacts

- Scoped snapshot test names.
- Debug artifact path if a manual run produced one.

## Notes

- UI interaction was not changed.
- Region selection remains one-shot for the next natural-language instruction.
```

- [ ] **Step 6: Run Harness knowledge check**

Run:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root . --docs-path docs\features
```

Expected for changed F002/EV-002: no new F002/EV-002 errors. Existing F001 format errors may remain and should be recorded separately instead of fixed in this feature slice.

- [ ] **Step 7: Commit Evidence closeout**

```powershell
git add docs/features/F002-rpa-region-scoped-snapshot.md docs/evidence/EV-002-rpa-region-scoped-snapshot.md
git commit -m "docs: record rpa region-scoped snapshot evidence"
```

---

## Plan Self-Review

Spec coverage:

- One-shot selected region: Task 1, Task 4, Task 6.
- Region-aware raw capture: Task 2.
- Region-scoped compression: Task 3.
- `region_context.py` keep/downgrade boundary: Task 1 and Task 4.
- Trace-first compatibility: Task 5.
- UI no-change constraint: Task 6.
- Harness evidence: Task 7.

Concrete-step scan:

- The plan contains concrete file paths, commands, expected results, and implementation snippets.

Type consistency:

- `RPARegionScope` converts from `RPARegionContext`.
- `region_scope` is passed from runtime into capture and compression.
- `region_scoped_snapshot` is the planner payload mode.
- `region_scope` on `RPAAcceptedTrace` is evidence only; existing `region_context` remains compatible during transition.
