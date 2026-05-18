# RPA Region Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add chat-first page-region attachments to RpaClaw recording so users can box-select page areas and then describe extraction or action commands in natural language.

**Architecture:** Region selection is stored as session-scoped evidence, referenced by `region_id` from the next chat request, and passed into `RecordingRuntimeAgent` as high-priority planner context. Accepted traces preserve `region_context` plus a compact `region_selection` signal so the timeline, configure flow, compiler, and diagnostics can consume the evidence without making raw coordinates the replay strategy.

**Tech Stack:** FastAPI, Pydantic v2, Playwright async API, Vue 3, TypeScript, Vite/Vitest, Tailwind CSS.

---

## File Map

Backend:

- Create `RpaClaw/backend/rpa/region_context.py`: Pydantic request/response/evidence models, region evidence analysis helpers, DOM collector script, session staleness helpers.
- Modify `RpaClaw/backend/rpa/trace_models.py`: add `region_context` to `RPAAcceptedTrace`.
- Modify `RpaClaw/backend/rpa/manager.py`: store pending region contexts, resolve/delete/consume by `region_id`, return active page by tab id.
- Modify `RpaClaw/backend/route/rpa.py`: add `/session/{session_id}/region/analyze`, extend `ChatRequest.region_id`, resolve context before planner execution, emit region metadata in stream events.
- Modify `RpaClaw/backend/rpa/recording_runtime_agent.py`: accept `region_context`, compact it for planner payload, write debug artifacts, attach region evidence to accepted traces.
- Modify `RpaClaw/backend/rpa/trace_timeline.py`: project region-backed traces with data/action summaries and evidence indicators.
- Modify `RpaClaw/backend/rpa/trace_skill_compiler.py`: add conservative V1 compile paths for region single-value/table/list traces, with runtime AI fallback when evidence is insufficient.

Frontend:

- Create `RpaClaw/frontend/src/utils/rpaRegionSelection.ts`: region selection types, geometry conversion, summary formatting, attachment stale helpers.
- Create `RpaClaw/frontend/src/utils/rpaRegionSelection.test.ts`: focused unit tests for region geometry and payload helpers.
- Modify `RpaClaw/frontend/src/utils/rpaAssistantModel.ts`: add optional `region_id` to chat payload.
- Modify `RpaClaw/frontend/src/utils/rpaAssistantRun.ts`: render `region_context` stream evidence as a run item.
- Modify `RpaClaw/frontend/src/pages/rpa/RecorderPage.vue`: add composer selection button, one-shot canvas overlay, attachment chip, `region_id` send path, and evidence card rendering.
- Modify `RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts`: add interaction tests for selection, send, cancel, and replacement.
- Modify `RpaClaw/frontend/src/utils/rpaStepTimeline.ts` and tests if timeline labels need frontend-only display support.
- Modify `RpaClaw/frontend/src/locales/en.ts` and `RpaClaw/frontend/src/locales/zh.ts`: add new UI strings for the selection button, attachment status, errors, and evidence labels.

Backend tests:

- Create `RpaClaw/backend/tests/test_rpa_region_context.py`.
- Modify `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`.
- Modify `RpaClaw/backend/tests/test_rpa_trace_timeline.py`.
- Modify `RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py`.

---

### Task 1: Backend Region Evidence Models And Session Storage

**Files:**
- Create: `RpaClaw/backend/rpa/region_context.py`
- Modify: `RpaClaw/backend/rpa/manager.py`
- Test: `RpaClaw/backend/tests/test_rpa_region_context.py`

- [ ] **Step 1: Write tests for session storage and stale resolution**

Create `RpaClaw/backend/tests/test_rpa_region_context.py` with these initial tests:

```python
from __future__ import annotations

from datetime import datetime

from backend.rpa.manager import RPASession, RPASessionManager
from backend.rpa.region_context import RPARegionContext, RPARegionEvidence


def _session() -> RPASession:
    return RPASession(
        id="session-1",
        user_id="user-1",
        sandbox_session_id="sandbox-1",
        active_tab_id="tab-1",
    )


def _context(region_id: str = "region-1", url: str = "https://example.test/a") -> RPARegionContext:
    return RPARegionContext(
        region_id=region_id,
        session_id="session-1",
        tab_id="tab-1",
        page_url=url,
        page_title="Example",
        created_at=datetime.now(),
        evidence=RPARegionEvidence(
            url=url,
            title="Example",
            frame_path=[],
            rect={"x": 10, "y": 20, "width": 100, "height": 50},
            local_text=["SKU", "Price"],
            inferred_kind="table_region",
            warnings=[],
        ),
    )


def test_region_context_storage_replaces_prior_context_for_session():
    manager = RPASessionManager()
    manager.sessions["session-1"] = _session()

    first = manager.store_region_context("session-1", _context("region-1"))
    second = manager.store_region_context("session-1", _context("region-2"))

    assert first.region_id == "region-1"
    assert second.region_id == "region-2"
    assert manager.resolve_region_context("session-1", "region-1") is None
    assert manager.resolve_region_context("session-1", "region-2") == second


def test_region_context_resolution_rejects_stale_page_url():
    manager = RPASessionManager()
    session = _session()
    manager.sessions["session-1"] = session
    manager.store_region_context("session-1", _context("region-1", url="https://example.test/old"))

    resolved = manager.resolve_region_context(
        "session-1",
        "region-1",
        current_url="https://example.test/new",
    )

    assert resolved is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_region_context.py -q
```

Expected: FAIL because `backend.rpa.region_context` and manager methods do not exist.

- [ ] **Step 3: Add Pydantic models**

Create `RpaClaw/backend/rpa/region_context.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class RPARegionRect(BaseModel):
    x: float
    y: float
    width: float
    height: float


class RPARegionViewport(BaseModel):
    width: float
    height: float


class RPARegionAnalyzeRequest(BaseModel):
    tab_id: str
    rect: RPARegionRect
    viewport: RPARegionViewport


class RPARegionEvidence(BaseModel):
    url: str = ""
    title: str = ""
    frame_path: List[str] = Field(default_factory=list)
    rect: Dict[str, float] = Field(default_factory=dict)
    dominant_container: Dict[str, Any] = Field(default_factory=dict)
    intersecting_elements: List[Dict[str, Any]] = Field(default_factory=list)
    locator_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    local_text: List[str] = Field(default_factory=list)
    inferred_kind: str = "unknown"
    table_summary: Optional[Dict[str, Any]] = None
    list_summary: Optional[Dict[str, Any]] = None
    action_summary: Optional[Dict[str, Any]] = None
    warnings: List[str] = Field(default_factory=list)


class RPARegionContext(BaseModel):
    region_id: str = Field(default_factory=lambda: f"region-{uuid4().hex}")
    session_id: str
    tab_id: str
    page_url: str = ""
    page_title: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    evidence: RPARegionEvidence

    def preview(self) -> Dict[str, Any]:
        evidence = self.evidence
        rect = evidence.rect or {}
        width = int(float(rect.get("width", 0) or 0))
        height = int(float(rect.get("height", 0) or 0))
        count = len(evidence.intersecting_elements)
        return {
            "region_id": self.region_id,
            "tab_id": self.tab_id,
            "summary": f"区域 {width}x{height} · {count} elements",
            "inferred_kind": evidence.inferred_kind,
            "page_url": self.page_url,
            "page_title": self.page_title,
            "warnings": list(evidence.warnings),
        }


class RPARegionAnalyzeResponse(BaseModel):
    region_id: str
    summary: str
    inferred_kind: str = "unknown"
    evidence: RPARegionEvidence
```

- [ ] **Step 4: Add manager storage methods**

Modify `RpaClaw/backend/rpa/manager.py`:

```python
from .region_context import RPARegionContext
```

Add state in `RPASessionManager.__init__`:

```python
self._pending_region_contexts: Dict[str, Dict[str, RPARegionContext]] = {}
```

Add methods near runtime result helpers:

```python
    def store_region_context(self, session_id: str, context: RPARegionContext) -> RPARegionContext:
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        self._pending_region_contexts[session_id] = {context.region_id: context}
        return context

    def resolve_region_context(
        self,
        session_id: str,
        region_id: str | None,
        *,
        current_url: str | None = None,
    ) -> Optional[RPARegionContext]:
        if not region_id:
            return None
        context = self._pending_region_contexts.get(session_id, {}).get(region_id)
        if context is None:
            return None
        if current_url and context.page_url and context.page_url != current_url:
            return None
        return context

    def clear_region_context(self, session_id: str, region_id: str | None = None) -> None:
        if region_id:
            self._pending_region_contexts.get(session_id, {}).pop(region_id, None)
            return
        self._pending_region_contexts.pop(session_id, None)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_region_context.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add RpaClaw/backend/rpa/region_context.py RpaClaw/backend/rpa/manager.py RpaClaw/backend/tests/test_rpa_region_context.py
git commit -m "feat: store rpa region contexts"
```

---

### Task 2: Region Analyze Endpoint And DOM Evidence Collector

**Files:**
- Modify: `RpaClaw/backend/rpa/region_context.py`
- Modify: `RpaClaw/backend/rpa/manager.py`
- Modify: `RpaClaw/backend/route/rpa.py`
- Test: `RpaClaw/backend/tests/test_rpa_region_context.py`

- [ ] **Step 1: Add tests for endpoint validation and evidence response**

Append to `RpaClaw/backend/tests/test_rpa_region_context.py`:

```python
import pytest

from backend.rpa.region_context import (
    analyze_region_on_page,
    classify_region_evidence,
    RPARegionAnalyzeRequest,
)


def test_classify_region_evidence_prefers_table_summary():
    kind = classify_region_evidence(
        {
            "table_summary": {"headers": ["SKU", "Price"], "sample_rows": [["A-1", "$3"]]},
            "action_summary": {"controls": [{"role": "button"}]},
        }
    )

    assert kind == "table_region"


def test_region_request_rejects_negative_dimensions():
    with pytest.raises(ValueError):
        RPARegionAnalyzeRequest.model_validate(
            {
                "tab_id": "tab-1",
                "rect": {"x": 0, "y": 0, "width": -1, "height": 10},
                "viewport": {"width": 1280, "height": 720},
            }
        )
```

- [ ] **Step 2: Run tests to verify failures**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_region_context.py -q
```

Expected: FAIL because classifier/analyzer validation is not implemented.

- [ ] **Step 3: Add validators and classifier**

Update `RPARegionRect` and `RPARegionViewport` in `region_context.py`:

```python
from pydantic import BaseModel, Field, field_validator
```

```python
class RPARegionRect(BaseModel):
    x: float
    y: float
    width: float
    height: float

    @field_validator("width", "height")
    @classmethod
    def _positive_size(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("region width and height must be positive")
        return value


class RPARegionViewport(BaseModel):
    width: float
    height: float

    @field_validator("width", "height")
    @classmethod
    def _positive_size(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("viewport width and height must be positive")
        return value
```

Add:

```python
def classify_region_evidence(raw: Dict[str, Any]) -> str:
    if isinstance(raw.get("table_summary"), dict) and raw["table_summary"].get("headers"):
        return "table_region"
    if isinstance(raw.get("list_summary"), dict) and raw["list_summary"].get("item_count", 0):
        return "list_sample"
    action_summary = raw.get("action_summary")
    if isinstance(action_summary, dict) and action_summary.get("controls"):
        return "action_target"
    if raw.get("local_text"):
        return "single_value"
    return "unknown"
```

- [ ] **Step 4: Add initial Playwright DOM collector**

Add to `region_context.py`:

```python
REGION_COLLECTOR_JS = r"""
({ rect }) => {
  const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
  const roleOf = el => el.getAttribute('role') || '';
  const isVisibleBox = box => box && box.width > 0 && box.height > 0;
  const intersects = (a, b) => (
    a.left < b.x + b.width &&
    a.left + a.width > b.x &&
    a.top < b.y + b.height &&
    a.top + a.height > b.y
  );
  const all = Array.from(document.querySelectorAll('body *'));
  const selected = [];
  for (const el of all) {
    const box = el.getBoundingClientRect();
    if (!isVisibleBox(box) || !intersects(box, rect)) continue;
    const text = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '');
    if (!text && !['BUTTON', 'A', 'INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) continue;
    selected.push({
      tag: el.tagName.toLowerCase(),
      role: roleOf(el),
      text: text.slice(0, 500),
      aria_label: norm(el.getAttribute('aria-label')),
      title: norm(el.getAttribute('title')),
      placeholder: norm(el.getAttribute('placeholder')),
      input_type: norm(el.getAttribute('type')),
      box: { x: box.x, y: box.y, width: box.width, height: box.height },
      actionable: ['BUTTON', 'A', 'INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName) ||
        ['button', 'link', 'checkbox', 'radio', 'combobox', 'menuitem'].includes(roleOf(el))
    });
    if (selected.length >= 80) break;
  }
  const localText = [];
  for (const item of selected) {
    if (item.text && !localText.includes(item.text)) localText.push(item.text);
    if (localText.length >= 20) break;
  }
  const table = selected.find(item => item.tag === 'table' || item.role === 'grid');
  const controls = selected.filter(item => item.actionable).slice(0, 20);
  return {
    rect,
    intersecting_elements: selected,
    local_text: localText,
    dominant_container: selected[0] || {},
    table_summary: table ? { headers: localText.slice(0, 8), sample_rows: [] } : null,
    list_summary: null,
    action_summary: controls.length ? { controls } : null,
    warnings: selected.length ? [] : ['no_visible_elements']
  };
}
"""


async def analyze_region_on_page(*, page: Any, request: RPARegionAnalyzeRequest) -> RPARegionEvidence:
    frame, frame_rect, frame_path = await resolve_region_frame(page=page, rect=request.rect.model_dump())
    collector_rect = request.rect.model_dump()
    if frame_rect:
        collector_rect = {
            "x": max(0, collector_rect["x"] - frame_rect["x"]),
            "y": max(0, collector_rect["y"] - frame_rect["y"]),
            "width": collector_rect["width"],
            "height": collector_rect["height"],
        }
    raw = await frame.evaluate(
        REGION_COLLECTOR_JS,
        {"rect": collector_rect},
    )
    raw = dict(raw or {})
    inferred = classify_region_evidence(raw)
    title = ""
    try:
        title = await page.title()
    except Exception:
        title = ""
    url = str(getattr(page, "url", "") or "")
    return RPARegionEvidence(
        url=url,
        title=title,
        frame_path=frame_path,
        rect=dict(raw.get("rect") or request.rect.model_dump()),
        dominant_container=dict(raw.get("dominant_container") or {}),
        intersecting_elements=list(raw.get("intersecting_elements") or []),
        locator_candidates=[],
        local_text=list(raw.get("local_text") or []),
        inferred_kind=inferred,
        table_summary=raw.get("table_summary"),
        list_summary=raw.get("list_summary"),
        action_summary=raw.get("action_summary"),
        warnings=list(raw.get("warnings") or []),
    )
```

- [ ] **Step 5: Add iframe resolver**

Add imports to `region_context.py`:

```python
from .frame_selectors import build_frame_path
```

Add:

```python
def _intersection_area(a: Dict[str, float], b: Dict[str, float]) -> float:
    left = max(float(a.get("x", 0)), float(b.get("x", 0)))
    top = max(float(a.get("y", 0)), float(b.get("y", 0)))
    right = min(float(a.get("x", 0)) + float(a.get("width", 0)), float(b.get("x", 0)) + float(b.get("width", 0)))
    bottom = min(float(a.get("y", 0)) + float(a.get("height", 0)), float(b.get("y", 0)) + float(b.get("height", 0)))
    return max(0.0, right - left) * max(0.0, bottom - top)


async def _frame_element_box(frame: Any) -> Optional[Dict[str, float]]:
    try:
        element = await frame.frame_element()
        box = await element.bounding_box()
    except Exception:
        return None
    if not box:
        return None
    return {
        "x": float(box.get("x", 0)),
        "y": float(box.get("y", 0)),
        "width": float(box.get("width", 0)),
        "height": float(box.get("height", 0)),
    }


async def resolve_region_frame(*, page: Any, rect: Dict[str, float]) -> tuple[Any, Optional[Dict[str, float]], List[str]]:
    best_frame = page.main_frame
    best_box: Optional[Dict[str, float]] = None
    best_area = 0.0
    frames = list(getattr(page, "frames", []) or [])
    for frame in frames:
        if frame == page.main_frame:
            continue
        box = await _frame_element_box(frame)
        if not box:
            continue
        area = _intersection_area(rect, box)
        if area > best_area:
            best_frame = frame
            best_box = box
            best_area = area
    if best_box is None:
        return page.main_frame, None, []
    try:
        frame_path = await build_frame_path(best_frame)
    except Exception:
        frame_path = []
    return best_frame, best_box, frame_path
```

The iframe resolver intentionally chooses one dominant frame. It does not merge element evidence across multiple frames.

- [ ] **Step 6: Add tab page access in manager**

Modify `RpaClaw/backend/rpa/manager.py`:

```python
    def get_page_for_tab(self, session_id: str, tab_id: str | None) -> Optional[Page]:
        if not tab_id:
            return self.get_page(session_id)
        return self._tabs.get(session_id, {}).get(tab_id)
```

- [ ] **Step 7: Add route endpoint**

Modify imports in `RpaClaw/backend/route/rpa.py`:

```python
from backend.rpa.region_context import (
    RPARegionAnalyzeRequest,
    RPARegionAnalyzeResponse,
    RPARegionContext,
    analyze_region_on_page,
)
```

Add route before `/session/{session_id}/chat`:

```python
@router.post("/session/{session_id}/region/analyze")
async def analyze_region(
    session_id: str,
    request: RPARegionAnalyzeRequest,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    page = rpa_manager.get_page_for_tab(session_id, request.tab_id)
    if not page:
        raise HTTPException(status_code=400, detail="No page for selected tab")
    evidence = await analyze_region_on_page(page=page, request=request)
    context = RPARegionContext(
        session_id=session_id,
        tab_id=request.tab_id,
        page_url=evidence.url,
        page_title=evidence.title,
        evidence=evidence,
    )
    context = rpa_manager.store_region_context(session_id, context)
    preview = context.preview()
    return RPARegionAnalyzeResponse(
        region_id=context.region_id,
        summary=str(preview["summary"]),
        inferred_kind=evidence.inferred_kind,
        evidence=evidence,
    )
```

- [ ] **Step 8: Run backend tests**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_region_context.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```powershell
git add RpaClaw/backend/rpa/region_context.py RpaClaw/backend/rpa/manager.py RpaClaw/backend/route/rpa.py RpaClaw/backend/tests/test_rpa_region_context.py
git commit -m "feat: analyze rpa selected regions"
```

---

### Task 3: Region Context In Runtime Agent And Trace Model

**Files:**
- Modify: `RpaClaw/backend/rpa/trace_models.py`
- Modify: `RpaClaw/backend/rpa/recording_runtime_agent.py`
- Test: `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`
- Test: `RpaClaw/backend/tests/test_rpa_trace_models.py`

- [ ] **Step 1: Add tests for planner payload and accepted trace evidence**

Append focused tests to `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py` using the existing fake page/test helpers in that file. Add a planner spy:

```python
async def test_recording_runtime_agent_passes_region_context_to_planner(fake_page):
    captured = {}

    async def planner(payload):
        captured.update(payload)
        return {
            "description": "extract selected price",
            "action_type": "run_python",
            "expected_effect": "extract",
            "output_key": "price",
            "code": "async def run(page, results):\n    return {'price': '$12'}",
        }

    agent = RecordingRuntimeAgent(planner=planner)
    result = await agent.run(
        page=fake_page,
        instruction="extract price",
        region_context={
            "region_id": "region-1",
            "evidence": {
                "inferred_kind": "single_value",
                "local_text": ["Price $12"],
                "rect": {"x": 1, "y": 2, "width": 30, "height": 10},
            },
        },
    )

    assert result.success is True
    assert captured["region_context"]["region_id"] == "region-1"
    assert result.trace is not None
    assert result.trace.region_context["region_id"] == "region-1"
    assert result.trace.signals["region_selection"]["region_id"] == "region-1"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_passes_region_context_to_planner -q
```

Expected: FAIL because `run(..., region_context=...)` is not supported.

- [ ] **Step 3: Add trace field**

Modify `RpaClaw/backend/rpa/trace_models.py`:

```python
    region_context: Dict[str, Any] = Field(default_factory=dict)
```

Add it near `signals` and before `value` so trace evidence fields remain grouped.

- [ ] **Step 4: Add region compaction helpers**

Modify `RpaClaw/backend/rpa/recording_runtime_agent.py`:

```python
def _compact_region_context(region_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(region_context, dict) or not region_context:
        return {}
    evidence = region_context.get("evidence") if isinstance(region_context.get("evidence"), dict) else {}
    return {
        "region_id": str(region_context.get("region_id") or "").strip(),
        "tab_id": str(region_context.get("tab_id") or "").strip(),
        "page_url": str(region_context.get("page_url") or evidence.get("url") or "").strip(),
        "page_title": str(region_context.get("page_title") or evidence.get("title") or "").strip(),
        "inferred_kind": str(evidence.get("inferred_kind") or "unknown"),
        "frame_path": list(evidence.get("frame_path") or []),
        "rect": dict(evidence.get("rect") or {}),
        "local_text": list(evidence.get("local_text") or [])[:20],
        "dominant_container": dict(evidence.get("dominant_container") or {}),
        "locator_candidates": list(evidence.get("locator_candidates") or [])[:10],
        "table_summary": evidence.get("table_summary"),
        "list_summary": evidence.get("list_summary"),
        "action_summary": evidence.get("action_summary"),
        "warnings": list(evidence.get("warnings") or []),
    }


def _region_selection_signal(region_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    compact = _compact_region_context(region_context)
    if not compact:
        return {}
    return {
        "region_id": compact.get("region_id", ""),
        "inferred_kind": compact.get("inferred_kind", "unknown"),
        "rect": compact.get("rect", {}),
        "frame_path": compact.get("frame_path", []),
        "local_text_preview": compact.get("local_text", [])[:5],
        "table_summary": compact.get("table_summary"),
        "list_summary": compact.get("list_summary"),
        "action_summary": compact.get("action_summary"),
        "warnings": compact.get("warnings", []),
    }
```

- [ ] **Step 5: Extend `RecordingRuntimeAgent.run` signature and payload**

Update signature:

```python
        region_context: Optional[Dict[str, Any]] = None,
```

Before payload creation:

```python
        compact_region_context = _compact_region_context(region_context)
```

Add to payload only when present:

```python
        if compact_region_context:
            payload["region_context"] = compact_region_context
```

Update debug writes by using the existing `extra` argument on `_write_recording_snapshot_debug`:

```python
            extra={
                "raw_region_evidence": region_context or {},
                "planner_region_context": compact_region_context,
            },
```

- [ ] **Step 6: Attach evidence to accepted trace**

Update `_accepted_trace(...)` signature:

```python
        region_context: Optional[Dict[str, Any]] = None,
```

Before returning:

```python
        compact_region_context = _compact_region_context(region_context)
        region_signal = _region_selection_signal(region_context)
        if region_signal:
            signals["region_selection"] = region_signal
```

Pass to `RPAAcceptedTrace`:

```python
            region_context=compact_region_context,
```

Pass `region_context=region_context` from both success and repair accepted trace calls.

- [ ] **Step 7: Run tests**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_passes_region_context_to_planner -q
uv run pytest RpaClaw/backend/tests/test_rpa_trace_models.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add RpaClaw/backend/rpa/trace_models.py RpaClaw/backend/rpa/recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_trace_models.py
git commit -m "feat: pass region context into recording runtime"
```

---

### Task 4: Chat Endpoint Region Contract And Stream Events

**Files:**
- Modify: `RpaClaw/backend/route/rpa.py`
- Modify: `RpaClaw/backend/rpa/manager.py`
- Test: `RpaClaw/backend/tests/test_rpa_region_context.py`

- [ ] **Step 1: Add endpoint tests for missing/stale region id**

Add a small pure helper in `RpaClaw/backend/route/rpa.py` before wiring it into the route:

```python
def _resolve_chat_region_context(session_id: str, region_id: str | None, current_url: str) -> dict[str, Any] | None:
    if not region_id:
        return None
    region_context_model = rpa_manager.resolve_region_context(
        session_id,
        region_id,
        current_url=current_url,
    )
    if region_context_model is None:
        raise HTTPException(status_code=400, detail="Selected page region expired. Please select it again.")
    return region_context_model.model_dump(mode="json")
```

Then add tests in `RpaClaw/backend/tests/test_rpa_region_context.py`:

```python
import pytest
from fastapi import HTTPException

from backend.route.rpa import _resolve_chat_region_context


def test_resolve_chat_region_context_rejects_missing_region_before_planner(monkeypatch):
    monkeypatch.setattr(
        "backend.route.rpa.rpa_manager.resolve_region_context",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(HTTPException) as exc:
        _resolve_chat_region_context("session-1", "region-missing", "https://example.test")

    assert exc.value.status_code == 400
    assert "expired" in str(exc.value.detail)


def test_resolve_chat_region_context_returns_model_dump(monkeypatch):
    class Context:
        def model_dump(self, mode="json"):
            return {"region_id": "region-1", "evidence": {"local_text": ["Price"]}}

    monkeypatch.setattr(
        "backend.route.rpa.rpa_manager.resolve_region_context",
        lambda *args, **kwargs: Context(),
    )

    resolved = _resolve_chat_region_context("session-1", "region-1", "https://example.test")

    assert resolved["region_id"] == "region-1"
```

- [ ] **Step 2: Extend request model**

Modify `ChatRequest` in `RpaClaw/backend/route/rpa.py`:

```python
class ChatRequest(BaseModel):
    message: str
    mode: str = "chat"
    model_config_id: str | None = None
    region_id: str | None = None
```

- [ ] **Step 3: Resolve region before event generator**

After active page resolution:

```python
    region_context = _resolve_chat_region_context(
        session_id,
        request.region_id,
        str(getattr(page, "url", "") or ""),
    )
```

For stream previews, recover the stored model only after helper validation succeeds:

```python
    region_context_model = (
        rpa_manager.resolve_region_context(session_id, request.region_id)
        if request.region_id else None
    )
```

- [ ] **Step 4: Include region event and pass context into agent**

Inside trace-first branch before `agent_thought`:

```python
                if region_context:
                    yield {
                        "event": "region_context",
                        "data": json.dumps(region_context_model.preview(), ensure_ascii=False),
                    }
```

Update `agent.run(...)`:

```python
                    region_context=region_context,
```

After `_apply_recording_agent_result`, clear consumed context on success:

```python
                if request.region_id and result.success:
                    rpa_manager.clear_region_context(session_id, request.region_id)
```

- [ ] **Step 5: Add region diagnostics to abort payload**

In `agent_aborted` event data, include:

```python
"region": region_context_model.preview() if region_context else None,
```

- [ ] **Step 6: Run tests**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_region_context.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add RpaClaw/backend/route/rpa.py RpaClaw/backend/rpa/manager.py RpaClaw/backend/tests/test_rpa_region_context.py
git commit -m "feat: attach rpa regions to chat commands"
```

---

### Task 5: Frontend Region Geometry Utility

**Files:**
- Create: `RpaClaw/frontend/src/utils/rpaRegionSelection.ts`
- Create: `RpaClaw/frontend/src/utils/rpaRegionSelection.test.ts`

- [ ] **Step 1: Write utility tests**

Create `RpaClaw/frontend/src/utils/rpaRegionSelection.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import {
  buildRegionAnalyzePayload,
  formatRegionAttachmentSummary,
  normalizeSelectionRect,
} from './rpaRegionSelection';

describe('rpaRegionSelection', () => {
  it('normalizes drag rectangles in any direction', () => {
    expect(normalizeSelectionRect({ x: 30, y: 40 }, { x: 10, y: 15 })).toEqual({
      x: 10,
      y: 15,
      width: 20,
      height: 25,
    });
  });

  it('builds analyze payload from viewport-space points', () => {
    expect(buildRegionAnalyzePayload({
      tabId: 'tab-1',
      start: { x: 10, y: 20 },
      end: { x: 50, y: 80 },
      inputSize: { width: 1280, height: 720 },
    })).toEqual({
      tab_id: 'tab-1',
      rect: { x: 10, y: 20, width: 40, height: 60 },
      viewport: { width: 1280, height: 720 },
    });
  });

  it('formats attachment summaries from analyze responses', () => {
    expect(formatRegionAttachmentSummary({
      summary: '区域 420x180 · 12 elements',
      inferred_kind: 'table_region',
    })).toEqual('区域 420x180 · 12 elements');
  });
});
```

- [ ] **Step 2: Run tests to verify failure**

Run from `RpaClaw/frontend`:

```powershell
npm run test -- src/utils/rpaRegionSelection.test.ts
```

Expected: FAIL because the utility file does not exist.

- [ ] **Step 3: Implement utility**

Create `RpaClaw/frontend/src/utils/rpaRegionSelection.ts`:

```ts
import type { ScreencastSize } from './screencastGeometry';

export interface ViewportPoint {
  x: number;
  y: number;
}

export interface RegionSelectionRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface RegionAnalyzePayload {
  tab_id: string;
  rect: RegionSelectionRect;
  viewport: ScreencastSize;
}

export interface RegionAnalyzeResponse {
  region_id: string;
  summary: string;
  inferred_kind: string;
  evidence?: Record<string, unknown>;
}

export interface PendingRegionAttachment {
  regionId: string;
  tabId: string;
  rect: RegionSelectionRect;
  viewport: ScreencastSize;
  summary: string;
  inferredKind: string;
  evidence?: Record<string, unknown>;
}

export const MIN_REGION_SIZE = 8;

export const normalizeSelectionRect = (
  start: ViewportPoint,
  end: ViewportPoint,
): RegionSelectionRect => ({
  x: Math.min(start.x, end.x),
  y: Math.min(start.y, end.y),
  width: Math.abs(end.x - start.x),
  height: Math.abs(end.y - start.y),
});

export const isUsableRegionRect = (rect: RegionSelectionRect): boolean => (
  rect.width >= MIN_REGION_SIZE && rect.height >= MIN_REGION_SIZE
);

export const buildRegionAnalyzePayload = ({
  tabId,
  start,
  end,
  inputSize,
}: {
  tabId: string;
  start: ViewportPoint;
  end: ViewportPoint;
  inputSize: ScreencastSize;
}): RegionAnalyzePayload => ({
  tab_id: tabId,
  rect: normalizeSelectionRect(start, end),
  viewport: {
    width: inputSize.width,
    height: inputSize.height,
  },
});

export const formatRegionAttachmentSummary = (response: Pick<RegionAnalyzeResponse, 'summary'>): string => (
  response.summary || '已选择页面区域'
);

export const regionKindLabel = (kind: string): string => {
  if (kind === 'table_region') return '表格候选';
  if (kind === 'list_sample') return '列表候选';
  if (kind === 'single_value') return '单值候选';
  if (kind === 'action_target') return '按钮候选';
  return '区域候选';
};
```

- [ ] **Step 4: Run utility tests**

Run:

```powershell
npm run test -- src/utils/rpaRegionSelection.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add RpaClaw/frontend/src/utils/rpaRegionSelection.ts RpaClaw/frontend/src/utils/rpaRegionSelection.test.ts
git commit -m "feat: add rpa region selection helpers"
```

---

### Task 6: Frontend Chat Payload And Composer State

**Files:**
- Modify: `RpaClaw/frontend/src/utils/rpaAssistantModel.ts`
- Modify: `RpaClaw/frontend/src/pages/rpa/RecorderPage.vue`
- Modify: `RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts`
- Modify: `RpaClaw/frontend/src/locales/en.ts`
- Modify: `RpaClaw/frontend/src/locales/zh.ts`

- [ ] **Step 1: Add payload unit test**

Add to existing `rpaAssistantModel` tests or create one if absent:

```ts
import { describe, expect, it } from 'vitest';
import { buildRpaAssistantChatPayload } from './rpaAssistantModel';

describe('buildRpaAssistantChatPayload', () => {
  it('includes region_id only when provided', () => {
    expect(buildRpaAssistantChatPayload('extract', 'model-1', 'region-1')).toEqual({
      message: 'extract',
      mode: 'trace_first',
      model_config_id: 'model-1',
      region_id: 'region-1',
    });
    expect(buildRpaAssistantChatPayload('extract', null)).toEqual({
      message: 'extract',
      mode: 'trace_first',
    });
  });
});
```

- [ ] **Step 2: Update payload helper**

Modify `RpaClaw/frontend/src/utils/rpaAssistantModel.ts`:

```ts
export interface RpaAssistantChatPayload {
  message: string;
  mode: 'trace_first';
  model_config_id?: string;
  region_id?: string;
}
```

```ts
export function buildRpaAssistantChatPayload(
  message: string,
  selectedModelId: string | null,
  regionId?: string | null,
): RpaAssistantChatPayload {
  const payload: RpaAssistantChatPayload = {
    message,
    mode: 'trace_first',
  };
  if (selectedModelId) payload.model_config_id = selectedModelId;
  if (regionId) payload.region_id = regionId;
  return payload;
}
```

- [ ] **Step 3: Add locale keys**

Append keys to both `RpaClaw/frontend/src/locales/en.ts` and `RpaClaw/frontend/src/locales/zh.ts`.

English:

```ts
'Select page region': 'Select page region',
'Drag to select page region · Esc to cancel': 'Drag to select page region · Esc to cancel',
'Selected page region': 'Selected page region',
'Remove selected region': 'Remove selected region',
'Region analysis failed, please select again': 'Region analysis failed, please select again',
'Type what to do with the selected region': 'Type what to do with the selected region',
'Page region evidence': 'Page region evidence',
```

Chinese:

```ts
'Select page region': '选择页面区域',
'Drag to select page region · Esc to cancel': '拖拽框选页面区域 · Esc 取消',
'Selected page region': '已选择页面区域',
'Remove selected region': '移除所选区域',
'Region analysis failed, please select again': '区域分析失败，请重新框选',
'Type what to do with the selected region': '请描述要对所选区域执行什么操作',
'Page region evidence': '页面区域证据',
```

- [ ] **Step 4: Add composer state to `RecorderPage.vue`**

Add imports:

```ts
import { Crop, X } from 'lucide-vue-next';
import { useI18n } from 'vue-i18n';
import {
  buildRegionAnalyzePayload,
  formatRegionAttachmentSummary,
  isUsableRegionRect,
  normalizeSelectionRect,
  regionKindLabel,
  type PendingRegionAttachment,
  type ViewportPoint,
} from '@/utils/rpaRegionSelection';
```

Add state:

```ts
const { t } = useI18n();
const selectingRegion = ref(false);
const regionDragStart = ref<ViewportPoint | null>(null);
const regionDragCurrent = ref<ViewportPoint | null>(null);
const pendingRegion = ref<PendingRegionAttachment | null>(null);
const regionError = ref('');
```

Add helper:

```ts
const clearPendingRegion = () => {
  pendingRegion.value = null;
  regionError.value = '';
};
```

- [ ] **Step 5: Wire send payload**

In `sendMessage`, keep empty instruction blocked even if a region exists:

```ts
if (!newMessage.value.trim() || !sessionId.value || sending.value) {
  if (pendingRegion.value && !newMessage.value.trim()) {
    regionError.value = t('Type what to do with the selected region');
  }
  return;
}
```

Capture and clear only after successful request body construction:

```ts
const regionForMessage = pendingRegion.value;
```

Update fetch body:

```ts
body: JSON.stringify(buildRpaAssistantChatPayload(
  userText,
  selectedModelId.value,
  regionForMessage?.regionId,
)),
```

After pushing the user message, include attachment metadata in the local chat object by extending `ChatMessage`:

```ts
regionAttachment?: PendingRegionAttachment;
```

Push:

```ts
chatMessages.value.push({ role: 'user', text: userText, time: now, regionAttachment: regionForMessage || undefined });
pendingRegion.value = null;
```

- [ ] **Step 6: Add component tests**

Update `RecorderPage.test.ts` to mock `apiClient.post('/rpa/session/session-1/region/analyze', ...)` and assert:

```ts
it('sends region_id with the next chat message when a region attachment exists', async () => {
  // Mount RecorderPage with an active session and active tab.
  // Set component pendingRegion or complete selection interaction.
  // Type a message and send.
  // Assert fetch body includes region_id.
});
```

- [ ] **Step 7: Run frontend tests**

Run from `RpaClaw/frontend`:

```powershell
npm run test -- src/utils/rpaRegionSelection.test.ts src/pages/rpa/RecorderPage.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add RpaClaw/frontend/src/utils/rpaAssistantModel.ts RpaClaw/frontend/src/pages/rpa/RecorderPage.vue RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts RpaClaw/frontend/src/locales/en.ts RpaClaw/frontend/src/locales/zh.ts
git commit -m "feat: attach selected regions to rpa chat"
```

---

### Task 7: Frontend One-Shot Canvas Selection Overlay

**Files:**
- Modify: `RpaClaw/frontend/src/pages/rpa/RecorderPage.vue`
- Modify: `RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts`

- [ ] **Step 1: Add selection event tests**

In `RecorderPage.test.ts`, add tests for:

```ts
it('does not forward mouse drag events while selecting a region', async () => {
  // Click selection button.
  // Dispatch mousedown/mousemove/mouseup on canvas.
  // Assert screencast websocket send was not called with mousePressed/mouseMoved/mouseReleased for that drag.
});

it('esc cancels one-shot region selection', async () => {
  // Click selection button.
  // Dispatch keydown Escape on canvas.
  // Assert selection overlay is gone and no region analyze call happens.
});
```

- [ ] **Step 2: Add selection controls**

Add functions to `RecorderPage.vue`:

```ts
const startRegionSelection = () => {
  if (!sessionId.value || sending.value || agentRunning.value) return;
  selectingRegion.value = true;
  regionDragStart.value = null;
  regionDragCurrent.value = null;
  regionError.value = '';
  focusCanvas();
};

const cancelRegionSelection = () => {
  selectingRegion.value = false;
  regionDragStart.value = null;
  regionDragCurrent.value = null;
};
```

Add mouse helpers:

```ts
const viewportPointFromMouse = (event: MouseEvent): ViewportPoint | null => {
  const canvas = canvasRef.value;
  if (!canvas) return null;
  const rect = canvas.getBoundingClientRect();
  return mapClientPointToViewportPoint({
    clientX: event.clientX,
    clientY: event.clientY,
    containerRect: {
      left: rect.left,
      top: rect.top,
      width: rect.width,
      height: rect.height,
    },
    frameSize: screencastFrameSize.value,
    inputSize: screencastInputSize.value,
  });
};
```

- [ ] **Step 3: Branch canvas mouse routing**

At the top of `sendInputEvent`:

```ts
if (selectingRegion.value && e instanceof MouseEvent && !(e instanceof WheelEvent)) {
  const point = viewportPointFromMouse(e);
  if (!point) return;
  e.preventDefault();
  if (e.type === 'mousedown') {
    regionDragStart.value = point;
    regionDragCurrent.value = point;
  } else if (e.type === 'mousemove' && regionDragStart.value) {
    regionDragCurrent.value = point;
  } else if (e.type === 'mouseup' && regionDragStart.value) {
    regionDragCurrent.value = point;
    finalizeRegionSelection();
  }
  return;
}
```

Handle Esc in keyboard branch:

```ts
if (selectingRegion.value && e instanceof KeyboardEvent && e.key === 'Escape') {
  e.preventDefault();
  cancelRegionSelection();
  return;
}
```

- [ ] **Step 4: Analyze region on mouseup**

Add:

```ts
const finalizeRegionSelection = async () => {
  if (!sessionId.value || !activeTabId.value || !regionDragStart.value || !regionDragCurrent.value) {
    cancelRegionSelection();
    return;
  }
  const rect = normalizeSelectionRect(regionDragStart.value, regionDragCurrent.value);
  if (!isUsableRegionRect(rect)) {
    cancelRegionSelection();
    return;
  }
  try {
    const payload = buildRegionAnalyzePayload({
      tabId: activeTabId.value,
      start: regionDragStart.value,
      end: regionDragCurrent.value,
      inputSize: screencastInputSize.value,
    });
    const resp = await apiClient.post(`/rpa/session/${sessionId.value}/region/analyze`, payload);
    pendingRegion.value = {
      regionId: resp.data.region_id,
      tabId: activeTabId.value,
      rect,
      viewport: screencastInputSize.value,
      summary: formatRegionAttachmentSummary(resp.data),
      inferredKind: resp.data.inferred_kind || 'unknown',
      evidence: resp.data.evidence || {},
    };
  } catch (err: any) {
    regionError.value = err.response?.data?.detail || t('Region analysis failed, please select again');
  } finally {
    cancelRegionSelection();
  }
};
```

- [ ] **Step 5: Render overlay and composer button**

In template near canvas overlay:

```vue
<div
  v-if="selectingRegion"
  class="pointer-events-none absolute bottom-3 left-1/2 z-20 flex -translate-x-1/2 items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1.5 text-[10px] font-bold text-white backdrop-blur-md"
>
  {{ t('Drag to select page region · Esc to cancel') }}
</div>
```

In composer bottom row between model selector and send:

```vue
<button
  type="button"
  class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl transition-colors disabled:cursor-not-allowed disabled:opacity-50"
  :class="selectingRegion ? 'bg-violet-50 text-[#831bd7] dark:bg-[#831bd7]/20 dark:text-purple-200' : 'bg-[#f2f4f6] text-gray-500 hover:bg-[#edeef0] dark:bg-white/10 dark:text-gray-300 dark:hover:bg-white/[0.14]'"
  :title="t('Select page region')"
  :disabled="sending || agentRunning || !sessionId"
  @click="startRegionSelection"
>
  <Crop :size="15" />
</button>
```

- [ ] **Step 6: Render attachment preview**

Above the textarea:

```vue
<div v-if="pendingRegion || regionError" class="mb-2 flex flex-wrap items-center gap-1.5">
  <div
    v-if="pendingRegion"
    class="inline-flex max-w-full items-center gap-1.5 rounded-lg bg-[#f2f4f6] px-2 py-1 text-[10px] font-semibold text-gray-700 dark:bg-white/10 dark:text-gray-200"
  >
    <Crop :size="12" class="text-[#831bd7]" />
    <span class="truncate">{{ pendingRegion.summary }}</span>
    <span class="rounded bg-white px-1 py-0.5 text-[9px] font-bold text-[#831bd7] dark:bg-black/20 dark:text-purple-200">
      {{ regionKindLabel(pendingRegion.inferredKind) }}
    </span>
    <button type="button" :title="t('Remove selected region')" @click="clearPendingRegion">
      <X :size="11" />
    </button>
  </div>
  <span v-if="regionError" class="text-[10px] font-semibold text-rose-600">{{ regionError }}</span>
</div>
```

- [ ] **Step 7: Run tests**

Run:

```powershell
npm run test -- src/pages/rpa/RecorderPage.test.ts src/utils/rpaRegionSelection.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add RpaClaw/frontend/src/pages/rpa/RecorderPage.vue RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts
git commit -m "feat: select rpa regions from screencast"
```

---

### Task 8: Region Evidence In Assistant Run Cards And Timeline

**Files:**
- Modify: `RpaClaw/frontend/src/utils/rpaAssistantRun.ts`
- Modify: `RpaClaw/frontend/src/utils/rpaStepTimeline.ts`
- Modify: `RpaClaw/frontend/src/pages/rpa/RecorderPage.vue`
- Modify: `RpaClaw/backend/rpa/trace_timeline.py`
- Tests: frontend and backend timeline tests

- [ ] **Step 1: Add run-card event test**

Add a test to `RpaClaw/frontend/src/utils/rpaAssistantRun.test.ts`:

```ts
it('adds page region evidence item for region_context events', () => {
  const run = createRpaAssistantRun('10:00');
  const next = applyRpaAssistantRunEvent(run, 'region_context', {
    summary: '区域 420x180 · 12 elements',
    inferred_kind: 'table_region',
    warnings: [],
  });
  expect(next.rounds[0].items[0]).toMatchObject({
    kind: 'plan',
    title: '页面区域证据',
  });
});
```

- [ ] **Step 2: Update run event mapper**

In `rpaAssistantRun.ts`, extend `RpaAssistantRunItemKind` only if needed. Reuse `plan` to avoid new styling:

```ts
case 'region_context': {
  const detail = [
    data.summary ? `区域: ${data.summary}` : '',
    data.inferred_kind ? `类型: ${data.inferred_kind}` : '',
    Array.isArray(data.warnings) && data.warnings.length ? `提示: ${data.warnings.join(', ')}` : '',
  ].filter(Boolean).join('\n');
  addItem(run, 'plan', '页面区域证据', detail);
  break;
}
```

- [ ] **Step 3: Add backend timeline test**

In `RpaClaw/backend/tests/test_rpa_trace_timeline.py`, add:

```python
def test_region_backed_trace_projects_region_summary():
    trace = RPAAcceptedTrace(
        trace_type=RPATraceType.AI_OPERATION,
        source="ai",
        description="提取区域数据",
        output_key="pricing_table",
        signals={
            "region_selection": {
                "region_id": "region-1",
                "inferred_kind": "table_region",
                "local_text_preview": ["SKU", "Price"],
            }
        },
        region_context={"region_id": "region-1"},
    )

    item = build_trace_timeline_items([trace], [])[0]

    assert item.summary_value == "pricing_table"
    assert item.raw["signals"]["region_selection"]["region_id"] == "region-1"
```

Adjust property names to match `RPATimelineItem` if they differ.

- [ ] **Step 4: Update timeline projection if needed**

In `RpaClaw/backend/rpa/trace_timeline.py`, ensure `_trace_to_item` includes `signals` and `region_context` in `raw`, and uses `output_key` for region-backed extract summaries:

```python
raw = trace.model_dump(mode="json")
region_signal = trace.signals.get("region_selection") if isinstance(trace.signals, dict) else None
if isinstance(region_signal, dict) and trace.output_key:
    summary_label = "output_key"
    summary_value = trace.output_key
```

Keep existing non-region behavior unchanged.

- [ ] **Step 5: Render user message attachment**

In `RecorderPage.vue` user bubble template, render `msg.regionAttachment` before text:

```vue
<div
  v-if="msg.regionAttachment"
  class="mb-2 inline-flex max-w-full items-center gap-1.5 rounded-lg bg-white/15 px-2 py-1 text-[10px] font-semibold text-white/90"
>
  <Crop :size="12" />
  <span class="truncate">{{ msg.regionAttachment.summary }}</span>
</div>
```

- [ ] **Step 6: Run tests**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_trace_timeline.py -q
npm run test -- src/utils/rpaAssistantRun.test.ts src/pages/rpa/RecorderPage.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add RpaClaw/backend/rpa/trace_timeline.py RpaClaw/backend/tests/test_rpa_trace_timeline.py RpaClaw/frontend/src/utils/rpaAssistantRun.ts RpaClaw/frontend/src/utils/rpaAssistantRun.test.ts RpaClaw/frontend/src/pages/rpa/RecorderPage.vue
git commit -m "feat: show rpa region evidence in recording UI"
```

---

### Task 9: Conservative Compiler Support For Region Extraction

**Files:**
- Modify: `RpaClaw/backend/rpa/trace_skill_compiler.py`
- Test: `RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py`

- [ ] **Step 1: Add compiler tests for V1 boundaries**

Add tests:

```python
def test_region_single_value_trace_compiles_to_locator_text_extract():
    trace = RPAAcceptedTrace(
        trace_type=RPATraceType.AI_OPERATION,
        source="ai",
        description="提取区域价格",
        output_key="price",
        signals={
            "region_selection": {
                "inferred_kind": "single_value",
                "dominant_locator": {"method": "css", "value": ".price"},
                "local_text_preview": ["$12"],
            }
        },
        region_context={
            "locator_candidates": [{"selected": True, "locator": {"method": "css", "value": ".price"}}],
            "inferred_kind": "single_value",
        },
    )
    script = TraceSkillCompiler().compile([trace])
    assert "_results['price']" in script or '_results["price"]' in script
    assert ".inner_text()" in script


def test_region_table_without_headers_preserves_runtime_ai():
    trace = RPAAcceptedTrace(
        trace_type=RPATraceType.AI_OPERATION,
        source="ai",
        description="提取表格",
        output_key="rows",
        signals={"region_selection": {"inferred_kind": "table_region"}},
        region_context={"inferred_kind": "table_region", "table_summary": {}},
    )
    assert trace_requires_runtime_ai_replay(trace) is True
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q
```

Expected: FAIL for new region compiler expectations.

- [ ] **Step 3: Add region signal helpers**

In `trace_skill_compiler.py`, add:

```python
def _trace_region_context(trace: RPAAcceptedTrace) -> Dict[str, Any]:
    return trace.region_context if isinstance(trace.region_context, dict) else {}


def _trace_region_kind(trace: RPAAcceptedTrace) -> str:
    signal = _trace_signal(trace, "region_selection")
    context = _trace_region_context(trace)
    return str(signal.get("inferred_kind") or context.get("inferred_kind") or "").strip()
```

- [ ] **Step 4: Route eligible region traces**

At the top of `_render_ai_operation_trace`, before embedded AI code handling:

```python
        region_kind = _trace_region_kind(trace)
        if region_kind == "single_value" and self._region_has_selected_locator(trace):
            return self._render_region_single_value_trace(index, trace, used_output_keys)
```

Add:

```python
    @staticmethod
    def _region_has_selected_locator(trace: RPAAcceptedTrace) -> bool:
        context = _trace_region_context(trace)
        candidates = context.get("locator_candidates")
        if isinstance(candidates, list) and candidates:
            return True
        signal = _trace_signal(trace, "region_selection")
        return isinstance(signal.get("dominant_locator"), dict) and bool(signal["dominant_locator"])
```

- [ ] **Step 5: Render single-value region extraction**

Add method:

```python
    def _render_region_single_value_trace(
        self,
        index: int,
        trace: RPAAcceptedTrace,
        used_output_keys: Dict[str, int],
    ) -> List[str]:
        key = self._allocate_output_key(trace, trace.output_key or f"region_value_{index}", used_output_keys)
        locator = self._preferred_locator_for_trace(trace, trace.locator_candidates)
        if not locator:
            context = _trace_region_context(trace)
            candidates = context.get("locator_candidates") if isinstance(context.get("locator_candidates"), list) else []
            locator = self._preferred_locator_for_trace(trace, candidates)
        expr = self._locator_expression(locator)
        lines = ["", f"    # trace {index}: {trace.description or 'region single value extract'}"]
        lines.append(f"    _region_locator = {expr}")
        lines.append("    _region_value = await _region_locator.inner_text()")
        lines.append("    _region_value = _region_value.strip()")
        lines.append(f"    _results[{key!r}] = _region_value")
        return lines
```

Use the existing locator rendering helper from the manual/data capture path. In this codebase that means reusing the same method already called by `_render_manual_action_trace` for Playwright locator expressions; keep one locator renderer rather than adding a parallel string builder.

- [ ] **Step 6: Preserve runtime AI for unsupported table/list region traces**

Update `trace_requires_runtime_ai_replay`:

```python
    region_kind = _trace_region_kind(trace)
    if region_kind in {"table_region", "list_sample"}:
        context = _trace_region_context(trace)
        if region_kind == "table_region" and not (isinstance(context.get("table_summary"), dict) and context["table_summary"].get("headers")):
            return True
        if region_kind == "list_sample" and not isinstance(context.get("list_summary"), dict):
            return True
```

This keeps V1 conservative until deterministic renderers have enough evidence.

- [ ] **Step 7: Run compiler tests**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add RpaClaw/backend/rpa/trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py
git commit -m "feat: compile simple rpa region extracts"
```

---

### Task 10: Verification And Regression Pass

**Files:**
- No new feature files unless verification exposes issues.

- [ ] **Step 1: Run backend focused suite**

Run:

```powershell
uv run pytest RpaClaw/backend/tests/test_rpa_region_context.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_trace_timeline.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend focused suite**

Run from `RpaClaw/frontend`:

```powershell
npm run test -- src/utils/rpaRegionSelection.test.ts src/utils/rpaAssistantRun.test.ts src/pages/rpa/RecorderPage.test.ts
```

Expected: PASS.

- [ ] **Step 3: Type-check frontend**

Run from `RpaClaw/frontend`:

```powershell
npm run type-check
```

Expected: PASS.

- [ ] **Step 4: Build frontend**

Run from `RpaClaw/frontend`:

```powershell
npm run build
```

Expected: PASS.

- [ ] **Step 5: Manual smoke test**

Start backend and frontend using the existing project commands, then verify:

1. Open Recorder page.
2. Click the composer selection button.
3. Drag a region on the screencast.
4. Confirm attachment chip appears above textarea.
5. Type `提取这个区域里的价格、SKU 和库存`.
6. Send message.
7. Confirm request body includes `region_id`.
8. Confirm assistant run card shows `页面区域证据`.
9. Confirm a trace appears in left timeline with region evidence.
10. Select a button region and send `点击这个区域里的导出按钮`; confirm it routes as an action, not forced `DATA_CAPTURE`.

- [ ] **Step 6: Commit verification fixes only if needed**

If any verification fix is required:

```powershell
git add <changed-files>
git commit -m "fix: stabilize rpa region context flow"
```

If no fixes are required, do not create an empty commit.

---

## Self-Review Checklist

- Spec coverage:
  - Chat-first composer attachment: Tasks 5, 6, 7, 8.
  - No canvas mode switch: Tasks 6 and 7 keep one-shot selection only.
  - Three extraction shapes: Tasks 2, 3, 9.
  - Region action targeting: Tasks 2, 3, 4, 9.
  - `region_id` chat contract: Tasks 4 and 6.
  - iframe and frame path: Task 2 owns iframe intersection, frame-local coordinate conversion, and `frame_path` capture before compiler work begins.
  - Debug artifacts: Task 3.
  - Timeline evidence: Task 8.
  - Frontend API double-prefix rule: Task 2 and Task 7 use `apiClient.post('/rpa/...')`.
- Placeholder scan: no `TBD`, `TODO`, or open-ended implementation placeholders are intentionally left.
- Type consistency:
  - Backend request uses `region_id`.
  - Frontend payload uses `region_id`.
  - Trace model uses `region_context`.
  - Signal key is `region_selection`.
