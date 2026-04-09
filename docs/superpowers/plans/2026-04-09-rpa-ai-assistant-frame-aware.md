# RPA AI Assistant Frame-Aware Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the RPA AI recording assistant automatically observe and act inside iframes, support self-adapting `first` / `nth` collection actions, and persist successful atomic AI actions as Recorder V2 enriched steps.

**Architecture:** Add a frame-aware assistant runtime that builds grouped page snapshots across all frames, resolves structured action intents through backend-owned helper logic, and emits Recorder V2 style steps instead of opaque `ai_script` payloads for common actions. Keep `ai_script` as a fallback for advanced custom logic, and surface frame/collection diagnostics through the existing SSE endpoint and recorder UI.

**Tech Stack:** Python 3.13, FastAPI, Playwright async API, Pydantic v2, Vue 3 + TypeScript, existing `unittest` backend tests, frontend `vue-tsc` type-check.

---

## File Map

### Create

- `RpaClaw/backend/rpa/assistant_runtime.py`
  - Frame-aware snapshot models and builders
  - Collection detection helpers
  - Structured action resolution helpers
  - Enriched AI step compilation helpers

### Modify

- `RpaClaw/backend/rpa/assistant.py`
  - Replace flat main-frame element extraction with frame-aware snapshot usage
  - Parse structured AI intent responses before falling back to code execution
  - Emit richer SSE events with frame and collection diagnostics
  - Persist successful atomic AI actions as enriched steps

- `RpaClaw/backend/rpa/manager.py`
  - Expose recorder-compatible frame-path helpers for assistant reuse
  - Extend `RPAStep` for AI collection metadata and diagnostic summaries
  - Keep existing multi-tab and Recorder V2 behavior intact

- `RpaClaw/backend/route/rpa.py`
  - Pass through richer assistant result payloads without changing auth or session ownership rules

- `RpaClaw/frontend/src/pages/rpa/RecorderPage.vue`
  - Render assistant frame diagnostics, collection summaries, and structured success/failure details
  - Map structured AI-originated steps into the left timeline consistently with manual recorder steps

- `RpaClaw/backend/tests/test_rpa_assistant.py`
  - Add snapshot, collection, structured execution, and persistence coverage

- `RpaClaw/backend/tests/test_rpa_manager.py`
  - Add coverage for public frame-path reuse helpers and step metadata support

## Execution Constraints

- The user explicitly requested: do not create any new commit during implementation until all work is complete and verified.
- Do not add a frontend unit test framework in this task. Use `npm run type-check` for frontend verification because the repo does not currently ship with Vitest or Jest.
- Keep the current ReAct agent behavior working. Do not regress `react` mode while upgrading the normal chat assistant path.

### Task 1: Add Failing Backend Tests For Frame-Aware Snapshots

**Files:**
- Modify: `RpaClaw/backend/tests/test_rpa_assistant.py`
- Test: `RpaClaw/backend/tests/test_rpa_assistant.py`

- [ ] **Step 1: Add a fake frame tree and a failing snapshot test**

```python
class _FakeSnapshotFrame:
    def __init__(self, name, url, frame_path, elements=None, child_frames=None):
        self.name = name
        self.url = url
        self._frame_path = frame_path
        self._elements = elements or []
        self.child_frames = child_frames or []

    async def evaluate(self, _script):
        return json.dumps(self._elements)


class _FakeSnapshotPage:
    url = "https://example.com"

    def __init__(self, main_frame):
        self.main_frame = main_frame

    async def title(self):
        return "Example"


class RPAAssistantFrameAwareSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_page_snapshot_includes_iframe_elements_and_collections(self):
        iframe = _FakeSnapshotFrame(
            name="editor",
            url="https://example.com/editor",
            frame_path=["iframe[title='editor']"],
            elements=[
                {"index": 1, "tag": "a", "role": "link", "name": "Quarterly Report"},
                {"index": 2, "tag": "a", "role": "link", "name": "Annual Report"},
            ],
        )
        main = _FakeSnapshotFrame(
            name="main",
            url="https://example.com",
            frame_path=[],
            elements=[{"index": 1, "tag": "button", "role": "button", "name": "Search"}],
            child_frames=[iframe],
        )
        page = _FakeSnapshotPage(main)

        snapshot = await ASSISTANT_MODULE.build_page_snapshot(page, frame_path_builder=lambda frame: frame._frame_path)

        self.assertEqual(snapshot["title"], "Example")
        self.assertEqual(len(snapshot["frames"]), 2)
        self.assertEqual(snapshot["frames"][1]["frame_path"], ["iframe[title='editor']"])
        self.assertEqual(snapshot["frames"][1]["elements"][0]["name"], "Quarterly Report")
        self.assertEqual(snapshot["frames"][1]["collections"][0]["item_count"], 2)
```

- [ ] **Step 2: Run the new assistant snapshot test and confirm it fails**

Run:

```bash
cd D:\code\MyScienceClaw\RpaClaw
python -m unittest backend.tests.test_rpa_assistant.RPAAssistantFrameAwareSnapshotTests.test_build_page_snapshot_includes_iframe_elements_and_collections -v
```

Expected:

```text
ERROR: module 'backend.rpa.assistant' has no attribute 'build_page_snapshot'
```

- [ ] **Step 3: Add a second failing test for collection-scoped `first` semantics**

```python
    async def test_pick_first_item_uses_collection_scope_not_global_page_order(self):
        snapshot = {
            "frames": [
                {
                    "frame_path": [],
                    "elements": [{"name": "Sidebar Link", "role": "link"}],
                    "collections": [],
                },
                {
                    "frame_path": ["iframe[title='results']"],
                    "elements": [],
                    "collections": [
                        {
                            "kind": "search_results",
                            "frame_path": ["iframe[title='results']"],
                            "container_hint": {"role": "list"},
                            "item_hint": {"role": "link"},
                            "items": [
                                {"name": "Result A", "role": "link"},
                                {"name": "Result B", "role": "link"},
                            ],
                        }
                    ],
                },
            ]
        }

        resolved = ASSISTANT_MODULE.resolve_collection_target(snapshot, {"action": "click", "ordinal": "first"})

        self.assertEqual(resolved["frame_path"], ["iframe[title='results']"])
        self.assertEqual(resolved["resolved_target"]["name"], "Result A")
```

- [ ] **Step 4: Run the collection test and confirm it fails**

Run:

```bash
cd D:\code\MyScienceClaw\RpaClaw
python -m unittest backend.tests.test_rpa_assistant.RPAAssistantFrameAwareSnapshotTests.test_pick_first_item_uses_collection_scope_not_global_page_order -v
```

Expected:

```text
ERROR: module 'backend.rpa.assistant' has no attribute 'resolve_collection_target'
```

### Task 2: Implement Frame-Aware Snapshot Building And Collection Detection

**Files:**
- Create: `RpaClaw/backend/rpa/assistant_runtime.py`
- Modify: `RpaClaw/backend/rpa/assistant.py`
- Test: `RpaClaw/backend/tests/test_rpa_assistant.py`

- [ ] **Step 1: Create the assistant runtime module with snapshot helpers**

```python
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List

EXTRACT_ELEMENTS_JS = r"""() => {
  const INTERACTIVE = 'a,button,input,textarea,select,[role=button],[role=link],[role=menuitem],[role=menuitemradio],[role=tab],[role=checkbox],[role=radio],[contenteditable=true]';
  const els = document.querySelectorAll(INTERACTIVE);
  const rows = [];
  let index = 1;
  for (const el of els) {
    const rect = el.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    const role = el.getAttribute('role') || '';
    const name = (el.getAttribute('aria-label') || el.innerText || '').trim().replace(/\s+/g, ' ');
    rows.push({
      index,
      tag: el.tagName.toLowerCase(),
      role,
      name: name.substring(0, 80),
      href: (el.getAttribute('href') || '').substring(0, 120),
      placeholder: el.getAttribute('placeholder') || '',
    });
    index += 1;
    if (rows.length >= 80) break;
  }
  return JSON.stringify(rows);
}"""


async def _extract_frame_elements(frame) -> List[Dict[str, Any]]:
    raw = await frame.evaluate(EXTRACT_ELEMENTS_JS)
    data = json.loads(raw) if isinstance(raw, str) else raw
    return data if isinstance(data, list) else []


def _detect_collections(elements: List[Dict[str, Any]], frame_path: List[str]) -> List[Dict[str, Any]]:
    links = [el for el in elements if el.get("role") == "link" or el.get("tag") == "a"]
    if len(links) >= 2:
        return [{
            "kind": "search_results",
            "frame_path": frame_path,
            "container_hint": {"role": "list"},
            "item_hint": {"role": "link"},
            "item_count": len(links),
            "items": links[:10],
        }]
    return []


async def build_page_snapshot(page, frame_path_builder: Callable[[Any], List[str]]) -> Dict[str, Any]:
    frames: List[Dict[str, Any]] = []

    async def walk(frame) -> None:
        frame_path = list(frame_path_builder(frame))
        elements = await _extract_frame_elements(frame)
        frames.append({
            "frame_path": frame_path,
            "url": getattr(frame, "url", ""),
            "frame_hint": "main document" if not frame_path else " -> ".join(frame_path),
            "elements": elements,
            "collections": _detect_collections(elements, frame_path),
        })
        for child in getattr(frame, "child_frames", []):
            await walk(child)

    await walk(page.main_frame)
    return {
        "url": page.url,
        "title": await page.title(),
        "frames": frames,
    }


def resolve_collection_target(snapshot: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
    ordinal = intent.get("ordinal", "first")
    index = 0 if ordinal == "first" else int(ordinal) - 1
    for frame in snapshot.get("frames", []):
        for collection in frame.get("collections", []):
            items = collection.get("items", [])
            if items and 0 <= index < len(items):
                return {
                    "frame_path": collection.get("frame_path", []),
                    "resolved_target": items[index],
                    "collection": collection,
                }
    raise ValueError("No collection target matched")
```

- [ ] **Step 2: Re-export the runtime helpers from `assistant.py` for test and chat-path use**

```python
from backend.rpa.assistant_runtime import (
    build_page_snapshot,
    resolve_collection_target,
)
```

- [ ] **Step 3: Run the two assistant snapshot tests and confirm they pass**

Run:

```bash
cd D:\code\MyScienceClaw\RpaClaw
python -m unittest backend.tests.test_rpa_assistant.RPAAssistantFrameAwareSnapshotTests -v
```

Expected:

```text
OK
```

### Task 3: Add Structured Intent Resolution And Enriched AI Step Persistence

**Files:**
- Modify: `RpaClaw/backend/rpa/assistant_runtime.py`
- Modify: `RpaClaw/backend/rpa/assistant.py`
- Modify: `RpaClaw/backend/rpa/manager.py`
- Test: `RpaClaw/backend/tests/test_rpa_assistant.py`
- Test: `RpaClaw/backend/tests/test_rpa_manager.py`

- [ ] **Step 1: Add failing tests for structured click execution inside an iframe and enriched step output**

```python
class _FakeLocator:
    def __init__(self):
        self.click_calls = 0

    async def click(self):
        self.click_calls += 1


class _FakeFrameScope:
    def __init__(self):
        self.locator_calls = []
        self.locator_obj = _FakeLocator()

    def locator(self, selector):
        self.locator_calls.append(selector)
        return self.locator_obj

    def frame_locator(self, selector):
        self.locator_calls.append(f"frame:{selector}")
        return self


class _FakeActionPage(_FakePage):
    def __init__(self):
        super().__init__()
        self.scope = _FakeFrameScope()

    def frame_locator(self, selector):
        self.scope.locator_calls.append(f"frame:{selector}")
        return self.scope

    def locator(self, selector):
        self.scope.locator_calls.append(selector)
        return self.scope.locator_obj


class RPAAssistantStructuredExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_structured_click_uses_frame_locator_chain(self):
        page = _FakeActionPage()
        intent = {
            "action": "click",
            "resolved": {
                "frame_path": ["iframe[title='editor']"],
                "locator": {"method": "role", "role": "button", "name": "Send"},
                "locator_candidates": [{"kind": "role", "selected": True, "locator": {"method": "role", "role": "button", "name": "Send"}}],
            },
        }

        result = await ASSISTANT_MODULE.execute_structured_intent(page, intent)

        self.assertTrue(result["success"])
        self.assertEqual(page.scope.locator_calls[0], "frame:iframe[title='editor']")
        self.assertEqual(result["step"]["frame_path"], ["iframe[title='editor']"])
        self.assertEqual(result["step"]["source"], "ai")
        self.assertEqual(result["step"]["target"], '{"method": "role", "role": "button", "name": "Send"}')
```

- [ ] **Step 2: Run the new structured execution test and confirm it fails**

Run:

```bash
cd D:\code\MyScienceClaw\RpaClaw
python -m unittest backend.tests.test_rpa_assistant.RPAAssistantStructuredExecutionTests.test_execute_structured_click_uses_frame_locator_chain -v
```

Expected:

```text
ERROR: module 'backend.rpa.assistant' has no attribute 'execute_structured_intent'
```

- [ ] **Step 3: Extend `RPAStep` for AI collection metadata and assistant diagnostics**

```python
class RPAStep(BaseModel):
    id: str
    action: str
    target: Optional[str] = None
    frame_path: List[str] = Field(default_factory=list)
    locator_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    validation: Dict[str, Any] = Field(default_factory=dict)
    signals: Dict[str, Any] = Field(default_factory=dict)
    element_snapshot: Dict[str, Any] = Field(default_factory=dict)
    value: Optional[str] = None
    screenshot_url: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    description: Optional[str] = None
    tag: Optional[str] = None
    label: Optional[str] = None
    url: Optional[str] = None
    source: str = "record"
    prompt: Optional[str] = None
    sensitive: bool = False
    tab_id: Optional[str] = None
    source_tab_id: Optional[str] = None
    target_tab_id: Optional[str] = None
    collection_hint: Dict[str, Any] = Field(default_factory=dict)
    item_hint: Dict[str, Any] = Field(default_factory=dict)
    ordinal: Optional[str] = None
    assistant_diagnostics: Dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Expose a public frame-path helper in `manager.py` for assistant reuse**

```python
    async def build_frame_path(self, frame) -> List[str]:
        return await self._build_frame_path(frame)
```

- [ ] **Step 5: Implement structured execution helpers in `assistant_runtime.py`**

```python
import json


def _locator_from_payload(scope, payload):
    method = payload.get("method")
    if method == "role":
        kwargs = {"name": payload.get("name")} if payload.get("name") else {}
        return scope.get_by_role(payload["role"], **kwargs)
    if method == "text":
        return scope.get_by_text(payload["value"])
    return scope.locator(payload.get("value", ""))


async def execute_structured_intent(page, intent: Dict[str, Any]) -> Dict[str, Any]:
    resolved = intent["resolved"]
    frame_path = resolved.get("frame_path", [])
    scope = page
    for frame_selector in frame_path:
        scope = scope.frame_locator(frame_selector)

    locator_payload = resolved["locator"]
    locator = _locator_from_payload(scope, locator_payload)
    action = intent["action"]
    if action == "click":
        await locator.click()
    elif action == "extract_text":
        value = await locator.inner_text()
    else:
        raise ValueError(f"Unsupported action: {action}")

    step = {
        "action": action,
        "source": "ai",
        "target": json.dumps(locator_payload, ensure_ascii=False),
        "frame_path": frame_path,
        "locator_candidates": resolved.get("locator_candidates", []),
        "validation": {"status": "ok", "details": "assistant structured action"},
        "collection_hint": resolved.get("collection_hint", {}),
        "item_hint": resolved.get("item_hint", {}),
        "ordinal": resolved.get("ordinal"),
        "assistant_diagnostics": {
            "resolved_frame_path": frame_path,
            "selected_locator_kind": resolved.get("selected_locator_kind", ""),
        },
        "description": intent.get("description", action),
        "prompt": intent.get("prompt"),
    }
    return {"success": True, "step": step, "output": value if action == "extract_text" else "ok"}
```

- [ ] **Step 6: Upgrade `RPAAssistant.chat()` to try structured JSON intent first and keep code fallback second**

```python
parsed_intent = self._extract_structured_intent(full_response)
if parsed_intent:
    yield {"event": "resolution", "data": {"intent": parsed_intent}}
    current_page = page_provider() if page_provider else page
    if current_page is None:
        yield {"event": "error", "data": {"message": "No active page available"}}
        yield {"event": "done", "data": {}}
        return
    result = await execute_structured_intent(current_page, parsed_intent)
else:
    code = self._extract_code(full_response)
    if not code:
        ...
    yield {"event": "script", "data": {"code": code}}
    result = await self._execute_on_page(current_page, code)
```

- [ ] **Step 7: Add a parser that accepts structured JSON intent before code blocks**

```python
    @staticmethod
    def _extract_structured_intent(text: str) -> Optional[Dict[str, Any]]:
        stripped = text.strip()
        try:
            parsed = json.loads(stripped)
        except Exception:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("action"):
            return parsed
        match = re.search(r"```json\\s*\\n(.*?)```", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1).strip())
            except Exception:
                return None
            if isinstance(parsed, dict) and parsed.get("action"):
                return parsed
        return None
```

- [ ] **Step 8: Run assistant and manager tests for the new execution path**

Run:

```bash
cd D:\code\MyScienceClaw\RpaClaw
python -m unittest backend.tests.test_rpa_assistant backend.tests.test_rpa_manager -v
```

Expected:

```text
OK
```

### Task 4: Build Prompt And Snapshot Formatting Around Frames And Collections

**Files:**
- Modify: `RpaClaw/backend/rpa/assistant.py`
- Modify: `RpaClaw/backend/rpa/assistant_runtime.py`
- Test: `RpaClaw/backend/tests/test_rpa_assistant.py`

- [ ] **Step 1: Add a failing test that prompt context is grouped by frame and collection**

```python
class RPAAssistantPromptFormattingTests(unittest.TestCase):
    def test_build_messages_lists_frames_and_collections(self):
        assistant = ASSISTANT_MODULE.RPAAssistant()
        snapshot = {
            "frames": [
                {"frame_hint": "main document", "frame_path": [], "elements": [{"index": 1, "tag": "button", "role": "button", "name": "Search"}], "collections": []},
                {"frame_hint": "iframe title=results", "frame_path": ["iframe[title='results']"], "elements": [{"index": 1, "tag": "a", "role": "link", "name": "Result A"}], "collections": [{"kind": "search_results", "item_count": 2}]},
            ]
        }

        messages = assistant._build_messages("点击第一个结果", [], snapshot, [])
        content = messages[-1]["content"]

        self.assertIn("Frame: main document", content)
        self.assertIn("Frame: iframe title=results", content)
        self.assertIn("Collection: search_results (2 items)", content)
```

- [ ] **Step 2: Run the prompt-formatting test and confirm it fails**

Run:

```bash
cd D:\code\MyScienceClaw\RpaClaw
python -m unittest backend.tests.test_rpa_assistant.RPAAssistantPromptFormattingTests.test_build_messages_lists_frames_and_collections -v
```

Expected:

```text
FAIL: 'Frame: iframe title=results' not found in prompt content
```

- [ ] **Step 3: Change `_build_messages()` to accept a snapshot dict instead of `elements_json`**

```python
    def _build_messages(
        self,
        user_message: str,
        steps: List[Dict[str, Any]],
        snapshot: Dict[str, Any],
        history: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        frame_lines: List[str] = []
        for frame in snapshot.get("frames", []):
            frame_lines.append(f"Frame: {frame.get('frame_hint', 'main document')}")
            for collection in frame.get("collections", []):
                frame_lines.append(
                    f"  Collection: {collection.get('kind', 'collection')} ({collection.get('item_count', 0)} items)"
                )
            for el in frame.get("elements", []):
                parts = [f"[{el.get('index', '?')}]", el.get("role") or el.get("tag", "element")]
                if el.get("name"):
                    parts.append(f'"{el["name"]}"')
                frame_lines.append("  " + " ".join(parts))
        elements_text = "\n".join(frame_lines) or "(no observable elements)"
```

- [ ] **Step 4: Rewrite the system prompt to prefer structured intent and collection semantics**

```python
SYSTEM_PROMPT = """你是一个 RPA 录制助手。

优先输出 JSON 结构化动作，而不是直接输出 Playwright 代码。常见格式：
{
  "action": "click|fill|extract_text|press",
  "description": "简短动作描述",
  "prompt": "用户原始指令",
  "resolved": {
    "frame_path": ["iframe[title='results']"],
    "locator": {"method": "role", "role": "link", "name": "Search"},
    "locator_candidates": [],
    "collection_hint": {"kind": "search_results"},
    "item_hint": {"role": "link"},
    "ordinal": "first",
    "selected_locator_kind": "role"
  }
}

规则：
1. 用户说“第一个 / 第 n 个”时，必须基于集合语义，不要硬编码页面里的具体数据文本。
2. 优先使用 role、label、placeholder、结构化集合定位，不要把动态标题、动态 href 当作主定位方式。
3. 只有在必须写复杂逻辑时才输出 ```python 代码块。
"""
```

- [ ] **Step 5: Run all assistant tests again**

Run:

```bash
cd D:\code\MyScienceClaw\RpaClaw
python -m unittest backend.tests.test_rpa_assistant -v
```

Expected:

```text
OK
```

### Task 5: Surface Frame And Collection Diagnostics Through The API And UI

**Files:**
- Modify: `RpaClaw/backend/route/rpa.py`
- Modify: `RpaClaw/frontend/src/pages/rpa/RecorderPage.vue`

- [ ] **Step 1: Forward structured assistant step payloads and resolution events unchanged from the SSE endpoint**

```python
                async for event in assistant.chat(
                    session_id=session_id,
                    page=page,
                    message=request.message,
                    steps=steps,
                    model_config=model_config,
                    page_provider=lambda: rpa_manager.get_page(session_id),
                ):
                    evt_type = event.get("event", "message")
                    evt_data = event.get("data", {})
                    if evt_type == "result" and evt_data.get("success") and evt_data.get("step"):
                        await rpa_manager.add_step(session_id, evt_data["step"])
                    yield {
                        "event": evt_type,
                        "data": json.dumps(evt_data, ensure_ascii=False),
                    }
```

Note: keep this structure, but ensure the assistant now emits `resolution` and enriched `step.assistant_diagnostics` without route-side filtering.

- [ ] **Step 2: Extend the recorder chat message model for assistant diagnostics**

```ts
interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  time: string;
  script?: string;
  status?: 'streaming' | 'executing' | 'done' | 'error';
  error?: string;
  showCode?: boolean;
  actions?: Array<{ description: string; code: string; showCode?: boolean }>;
  frameSummary?: string;
  locatorSummary?: string;
  collectionSummary?: string;
  diagnostics?: string[];
}
```

- [ ] **Step 3: Handle the new `resolution` event in `RecorderPage.vue`**

```ts
            } else if (eventType === 'resolution') {
              const resolved = data.intent?.resolved || {};
              chatMessages.value[msgIdx].frameSummary = (resolved.frame_path || []).length
                ? (resolved.frame_path || []).join(' -> ')
                : 'Main frame';
              chatMessages.value[msgIdx].locatorSummary = resolved.selected_locator_kind || '';
              if (resolved.collection_hint?.kind) {
                chatMessages.value[msgIdx].collectionSummary = `${resolved.collection_hint.kind} / ${resolved.ordinal || ''}`.trim();
              }
            }
```

- [ ] **Step 4: Render assistant diagnostics below the assistant bubble and in the step list**

```vue
              <div v-if="msg.frameSummary || msg.collectionSummary || msg.locatorSummary" class="mt-2 space-y-1 text-[10px] text-gray-500">
                <div v-if="msg.frameSummary">
                  <span class="font-semibold text-gray-600">Frame:</span>
                  <span class="ml-1 font-mono">{{ msg.frameSummary }}</span>
                </div>
                <div v-if="msg.collectionSummary">
                  <span class="font-semibold text-gray-600">Collection:</span>
                  <span class="ml-1">{{ msg.collectionSummary }}</span>
                </div>
                <div v-if="msg.locatorSummary">
                  <span class="font-semibold text-gray-600">Locator:</span>
                  <span class="ml-1">{{ msg.locatorSummary }}</span>
                </div>
              </div>
```

- [ ] **Step 5: Surface enriched AI step metadata in `mapServerSteps()`**

```ts
  ...serverSteps.map((s: any, i: number) => ({
    id: String(i + 1),
    title: s.description || s.action,
    description: s.source === 'ai'
      ? (s.prompt || s.description || 'AI 操作')
      : `${s.action} -> ${formatLocator(s.target || s.label || '')}`,
    status: 'completed',
    source: s.source || 'record',
    sensitive: s.sensitive || false,
    locatorSummary: formatLocator(s.target),
    frameSummary: formatFramePath(s.frame_path),
    validationStatus: s.validation?.status || '',
    validationDetails: s.validation?.details || '',
  }))
```

- [ ] **Step 6: Run frontend type-check**

Run:

```bash
cd D:\code\MyScienceClaw\RpaClaw\frontend
npm run type-check
```

Expected:

```text
Exit code 0
```

### Task 6: Final Verification

**Files:**
- Verify only

- [ ] **Step 1: Run targeted backend tests**

Run:

```bash
cd D:\code\MyScienceClaw\RpaClaw
python -m unittest backend.tests.test_rpa_assistant backend.tests.test_rpa_manager backend.tests.test_rpa_generator -v
```

Expected:

```text
OK
```

- [ ] **Step 2: Re-run frontend type-check**

Run:

```bash
cd D:\code\MyScienceClaw\RpaClaw\frontend
npm run type-check
```

Expected:

```text
Exit code 0
```

- [ ] **Step 3: Manual spot-check list**

Check these flows manually in the recorder:

```text
1. On a page with a single iframe, ask the assistant to click a button inside the iframe.
2. On a page with repeated result items inside an iframe, ask the assistant to "点击第一个结果".
3. On a page with repeated result items inside an iframe, ask the assistant to "获取第一个结果标题".
4. Verify the left timeline shows frame summary and validation details for the AI step.
5. Generate the final script and confirm it uses frame_locator(...) for the AI-generated atomic step.
```

- [ ] **Step 4: Do not commit**

```text
Leave all implementation changes uncommitted. Report verification results to the user and wait for their decision before creating any commit.
```

## Self-Review

### Spec Coverage

- Frame-aware observation: Task 1 and Task 2
- Collection-aware `first` / `nth`: Task 1, Task 2, and Task 4
- Backend-owned frame-aware execution: Task 3
- Enriched AI step persistence: Task 3
- SSE and UI diagnostics: Task 5
- Verification and no-commit handoff: Task 6

### Placeholder Scan

- No `TODO`, `TBD`, or deferred "write tests later" steps remain.
- All file paths, commands, and code snippets are explicit.

### Type Consistency

- The plan consistently uses `collection_hint`, `item_hint`, `ordinal`, and `assistant_diagnostics` as the persisted AI metadata fields.
- The runtime helper names are consistent across tasks:
  - `build_page_snapshot`
  - `resolve_collection_target`
  - `execute_structured_intent`

