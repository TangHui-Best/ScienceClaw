# RPA Region Context Design

## Summary

RpaClaw recording should support page-region selection as a lightweight companion to the existing chat-first recorder. The user should still describe the next recording command in natural language, but may attach a selected page region to make the instruction precise.

This design covers three extraction shapes:

- Single value extraction, such as a price, count, title, status, or date.
- List or card extraction, where the selected region is one sample item or a visible list area.
- Table extraction, where the selected region is a table, grid, row group, or selected columns.

It also covers action targeting:

- The user may select a region containing a button or control and say "click the export button in this area" or "fill the search box in this selected area".

The region is evidence for the next command. It is not a separate recorder mode and not a final replay strategy.

## Goals

- Preserve the current RPA recorder mental model: chat remains the primary way to express intent.
- Reduce ambiguity when page data has weak labels or when the full-page snapshot is too noisy.
- Reuse existing trace-first recording, locator candidate, element snapshot, and compiler flow.
- Support extraction and action commands from the same selection attachment.
- Keep recording factual. Generalization remains a post-hoc compiler responsibility.

## Non-Goals

- Do not add a persistent canvas mode switch such as Operate, Box Select, or Field Review.
- Do not turn the right assistant panel into a permanent extraction inspector.
- Do not generate final skill code directly from the selection UI.
- Do not hard-code observed selected text, page coordinates, URL values, or site-specific structures as replay logic.
- Do not introduce pre-execution stability blocking for weak selectors, empty values, or broad matches. These remain diagnostic and repair evidence.

## UX Design

### Layout Baseline

The feature should be an incremental change to the existing `RecorderPage` layout:

- Top `RpaFlowGuide` remains 64px tall, with the existing purple-to-magenta active step gradient.
- Left `RpaStepTimeline` remains 320px wide with compact white trace cards.
- Center browser frame keeps the current tab strip, address bar strip, black canvas, rounded-2xl shell, and CDP status pill.
- Right assistant panel remains 320px wide and chat-first.
- Composer remains the current white rounded-2xl card with textarea, model selector, and gradient send button.

Stitch refined screen:

![RpaClaw refined chat-first region selection](https://lh3.googleusercontent.com/aida/ADBb0ugKDg94Io3ieEXwt_6YlXdChZ82wfVY8goz5ZRvJBWjE3kfqqrxgXDgGpBJZy5klQGvFuXLrLb60-q-cZDlkPCoWFtKrVS3Onu7OXxWP6mrKltIXZ4U9zz3f4xDzVIS7sWVxLFSNvGQ2KVMU75sbfisqsr891Td270JEaLWcBrNYsp8nNPCgUklzpJvTffMRzmj-bXd81ZETjke0Q3sfEaGXUZXOoOI-cYK_zRio2XE-ZU5Itx6mpPPvjw)

### Composer Attachment Flow

Add one icon-only selection button inside the existing composer bottom row:

- Position: between the model selector and the send button.
- Size: 32px by 32px, rounded-xl, matching the send button footprint.
- Default state: neutral gray background, gray icon.
- Active selection state: violet-tinted background and `#831bd7` icon.
- Disabled state: follows send/model disabled behavior when sending or agent-running.
- Tooltip: `选择页面区域`.

When clicked:

1. The center canvas enters one-shot selection state.
2. Normal canvas input forwarding pauses only for the drag gesture used to draw the selection.
3. The browser frame shows a subtle bottom-center pill: `拖拽框选页面区域 · Esc 取消`.
4. The user drags a rectangle over the screencast.
5. The selected rectangle remains visible as a context marker until the message is sent or the attachment is removed.
6. A region attachment preview appears above the textarea inside the composer card.

The attachment preview should be compact:

- Left icon: selection/crop icon.
- Primary text: `区域 420x180 · 12 elements`.
- Secondary chip: inferred candidate type, such as `单值候选`, `表格候选`, `列表候选`, or `按钮候选`.
- Remove button: icon-only `X`.

The user then writes the instruction in the normal textarea. Examples:

- `提取这个区域里的价格、SKU 和库存`
- `从这个表格区域提取所有行`
- `提取这个卡片列表里的标题、链接和发布时间`
- `点击这个区域里的导出按钮`

### Chat History

The sent user message should show both:

- The natural-language instruction.
- A compact region attachment chip inside or immediately above the user bubble.

The assistant run card should stay in the current run-card style. Region details should appear as a collapsible evidence item, not as a persistent inspector:

- Title: `页面区域证据`
- Rows:
  - `类型`: inferred selection kind.
  - `文本`: selected local text snippets.
  - `定位器`: locator candidate count and selected primary locator kind.
  - `Frame`: frame path summary.
  - `结构`: table/list/control summary when available.

### Timeline

The left timeline should show normal accepted traces created from the chat instruction plus attached region:

- Extraction command: accepted `DATA` trace, title such as `提取区域数据`, `AI` badge when runtime AI planned it, accepted status, output key summary.
- Action command: accepted action trace or AI operation trace, title such as `点击选区内导出按钮`, with locator summary and evidence badge.

The timeline should not expose raw coordinates as the primary summary. Coordinates are diagnostic evidence, not the user's workflow concept.

## Frontend Behavior

### State Model

`RecorderPage.vue` should track a single pending region attachment:

```ts
interface PendingRegionAttachment {
  id: string;
  rect: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  viewport: {
    width: number;
    height: number;
    scale: number;
    offsetX: number;
    offsetY: number;
  };
  summary: string;
  inferredKind: 'unknown' | 'single_value' | 'list_sample' | 'table_region' | 'action_target';
  evidence?: RpaRegionEvidencePreview;
}
```

`rect` is in browser viewport CSS pixels after converting from canvas coordinates. The frontend should not send raw display coordinates without viewport metadata.

### Canvas Input Routing

The canvas currently forwards mouse and keyboard events to the remote browser. Region selection adds a temporary routing branch:

- When not selecting, keep current forwarding behavior unchanged.
- When selection is active:
  - `mousedown`, `mousemove`, and `mouseup` draw the overlay instead of forwarding drag input.
  - `wheel`, keyboard input, and paste remain disabled or ignored during the short selection gesture.
  - `Esc` cancels selection and restores normal forwarding.
  - `mouseup` finalizes the rectangle if it passes minimum size.

Minimum selection size:

- Width at least 8 CSS pixels.
- Height at least 8 CSS pixels.

If the selection is smaller, cancel silently and keep the composer unchanged.

### Coordinate Conversion

The screencast canvas uses `object-contain`, so the visible browser image may have letterboxing. The frontend must convert canvas pointer coordinates to browser viewport coordinates using:

- Canvas bounding client rect.
- Rendered image dimensions.
- Offset caused by object-contain.
- Current remote browser viewport size.

Converted region payload:

```ts
interface RpaRegionSelectionRequest {
  tab_id: string;
  rect: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  viewport: {
    width: number;
    height: number;
  };
}
```

The frontend stores the pending attachment by `region_id` after server analysis succeeds. The natural-language instruction request should send only the `region_id`, not the full evidence payload. The backend resolves the authoritative region evidence from the session.

## Backend Design

### API Shape

Add a selection analysis endpoint:

```text
POST /api/v1/rpa/session/{session_id}/region/analyze
```

Frontend implementation note:

- `apiClient` already prefixes `/api/v1`.
- Vue code should call `/rpa/session/${sessionId}/region/analyze`, not `/api/v1/rpa/session/...`.

Request:

```json
{
  "tab_id": "tab-123",
  "rect": { "x": 120, "y": 220, "width": 420, "height": 180 },
  "viewport": { "width": 1280, "height": 720 }
}
```

Response:

```json
{
  "region_id": "region-...",
  "summary": "区域 420x180 · 12 elements",
  "inferred_kind": "table_region",
  "evidence": {
    "url": "https://example.test/orders",
    "title": "Orders",
    "frame_path": [],
    "rect": { "x": 120, "y": 220, "width": 420, "height": 180 },
    "dominant_container": {
      "tag": "table",
      "role": "grid",
      "text": "SKU Price Stock ..."
    },
    "intersecting_elements": [],
    "locator_candidates": [],
    "local_text": ["SKU", "Price", "Stock", "A-001", "$12.00", "In stock"],
    "table_summary": {
      "headers": ["SKU", "Price", "Stock"],
      "sample_rows": [["A-001", "$12.00", "In stock"]]
    },
    "list_summary": null,
    "action_summary": null
  }
}
```

The region evidence should be stored server-side in the active session until either:

- The next assistant instruction consumes it.
- The user removes the attachment.
- The session stops.

The frontend may keep a preview copy, but backend execution should use the authoritative evidence captured from the live page.

### Assistant Instruction Contract

The existing assistant instruction and streaming endpoint should accept an optional `region_id`:

```json
{
  "instruction": "提取这个区域里的价格、SKU 和库存",
  "model_id": "optional-model-id",
  "region_id": "region-..."
}
```

Rules:

- `region_id` is optional. Existing chat-only recording commands must keep working unchanged.
- If `region_id` is present, the backend resolves it from the active session and passes the resolved `region_context` into `RecordingRuntimeAgent`.
- If `region_id` is missing from the session, stale, or belongs to another tab/page state, the endpoint should return a compact user-facing error and should not call the planner.
- The stream should include region attachment metadata in run events so the frontend can render the user message and assistant evidence card consistently after refresh.
- The stream should not send the full raw DOM evidence unless explicitly needed for debugging. Normal UI payloads should use summaries and counts.

The frontend send path should include `region_id` only when a pending attachment exists. Removing the attachment before send must clear `region_id`.

### Recording Runtime Agent Input

Extend `RecordingRuntimeAgent.run(...)` with optional region context:

```python
async def run(
    *,
    page: Any,
    instruction: str,
    runtime_results: Optional[Dict[str, Any]] = None,
    debug_context: Optional[Dict[str, Any]] = None,
    region_context: Optional[Dict[str, Any]] = None,
) -> RecordingAgentResult:
```

Planner payload gains:

```json
{
  "instruction": "...",
  "page": {},
  "snapshot": {},
  "runtime_results": {},
  "region_context": {}
}
```

Planner rules:

- Treat `region_context` as high-priority page evidence for the current instruction.
- Use region-local locator candidates and summaries before broad page snapshot evidence.
- If the instruction asks to extract, produce structured output and a `DATA_CAPTURE` or `AI_OPERATION` trace with region evidence signals.
- If the instruction asks to click, fill, hover, select, or otherwise operate, use region evidence to narrow candidate controls.
- Do not interpret region attachment alone as an action. The natural-language instruction defines the action.

### Trace Model

Add an optional field to `RPAAcceptedTrace`:

```python
region_context: Dict[str, Any] = Field(default_factory=dict)
```

For extraction traces, also add a signal:

```json
{
  "region_selection": {
    "region_id": "region-...",
    "inferred_kind": "table_region",
    "rect": {},
    "dominant_locator": {},
    "local_text_preview": [],
    "table_summary": {},
    "list_summary": {},
    "action_summary": {}
  }
}
```

This keeps the new evidence available to:

- Timeline projection.
- Configure page review.
- Compiler generalization.
- Test failure diagnostics.

### Debug Artifacts

Region-backed recording needs the same evidence discipline as full-page snapshot recording.

For every region-backed assistant run, write debug artifacts alongside the existing recording debug output:

- `raw_region_evidence`: the full factual DOM evidence returned by region analysis, including intersecting elements, bounding boxes, text snippets, locator candidates, and structure summaries.
- `planner_region_context`: the compacted region evidence actually sent to the planner.
- `region_context_decision`: the planner/executor outcome that records whether the region was used for extraction, action targeting, or only as supporting evidence.

Debug review order for wrong extraction or wrong action targeting:

1. Check whether the intended target appears in `raw_region_evidence`.
2. If present in raw evidence but missing from `planner_region_context`, fix region evidence compression.
3. If present in compact region context but the planner chose the wrong target, fix planner prompting or execution logic.
4. If absent from raw evidence, fix coordinate conversion, iframe handling, or DOM evidence collection.

This mirrors the existing raw snapshot versus compact snapshot rule and prevents prompt-only fixes for evidence collection failures.

### Region Evidence Extraction

The backend should execute JavaScript in the selected page/frame to collect facts from DOM elements intersecting the rectangle:

- Element bounding boxes.
- Text content, trimmed and length-limited.
- Tag, role, aria-label, title, placeholder, input type.
- Clickable/editable state.
- Existing Playwright locator candidates using the vendored Playwright recorder runtime.
- Nearest common container for the selected elements.
- Table/grid summary when a table-like structure dominates the region.
- Repeated item summary when sibling cards/rows are detected.
- Action summary when buttons, links, inputs, or menu items dominate the region.

Important boundary:

- Region evidence collection is factual.
- Classification can be lightweight and heuristic because it only labels evidence for user review and planner context.
- It must not force an execution strategy or block execution.

### Iframe Handling

Region selection coordinates originate from the top-level screencast viewport. The backend must resolve iframe targets before collecting DOM evidence:

1. Start with the top-level page viewport rect.
2. Find visible iframes whose bounding boxes intersect the selected rect.
3. If no iframe intersects, collect evidence from the main frame using the original rect.
4. If one iframe dominates the selected area, convert the selected rect into frame-local CSS pixels by subtracting the iframe bounding box origin and accounting for iframe client border/scroll offsets when available.
5. Use the existing server-side `build_frame_path` helper to store the frame path.
6. Execute the region evidence collector in the resolved Playwright `Frame`.
7. If multiple iframes materially overlap the region, return a warning and collect evidence from the dominant frame plus a small main-frame summary. Do not silently merge unrelated frames.

Cross-origin iframes are still accessible through Playwright frame evaluation when the browser context has access to the frame. If frame evaluation fails, the endpoint should return an evidence object with:

- `frame_path`
- iframe element summary from the parent frame
- warning details
- empty `intersecting_elements`

The planner may still use the warning as context, but the recorder should not pretend that element-level evidence was collected.

## Compiler Design

`TraceSkillCompiler` should consume region-backed traces conservatively:

### Single Value

Use the selected or dominant locator when it resolves cleanly. Extract visible text or control value. Preserve `output_key`.

V1 support boundary:

- Support one dominant element or one dominant label/value container.
- Support visible text, input value, selected option text, and simple attribute extraction such as `href` for links when the instruction asks for a link.
- If the selected region contains multiple unrelated values and the instruction does not name fields, preserve runtime AI or surface a review warning instead of inventing fields.

### Table Region

Prefer semantic table/grid locators and headers from `table_summary`. Generate row iteration using stable table structure rather than recorded row text.

V1 support boundary:

- Support native `table`, ARIA `grid`, and row/cell structures where headers can be inferred from visible header cells.
- Support extracting all visible rows for requested or inferred columns.
- Do not support virtualized offscreen rows in V1 unless the recording evidence contains a clear pagination or scrolling instruction.
- If headers cannot be inferred, keep the trace as runtime AI or require configure-stage review instead of compiling brittle positional columns.

### List or Card Sample

If the user selected one sample item, infer the sibling collection from repeated structure evidence. Generate item iteration relative to the repeated container and extract requested fields from each item.

V1 support boundary:

- Support repeated sibling elements under one parent when at least two sibling candidates share tag/class/role structure.
- Support extracting text, links, timestamps, badges/status text, and simple numeric values from each repeated item.
- If the selected region is an entire list area, choose a dominant repeated item pattern from inside the region.
- If no repeated structure is detected, compile as single-region extraction or preserve runtime AI; do not create keyword-driven site templates.

### Action Target

For click/fill actions, use region-local controls and selected locator candidates to render normal action code. Do not compile raw coordinates as replay logic except as last-resort diagnostic fallback.

V1 support boundary:

- Support click, fill, select option, press, and hover only when a region-local actionable element has a usable locator candidate.
- If multiple region-local controls match the instruction, prefer planner clarification or preserve runtime AI rather than preselecting by fragile visual order.
- Do not compile coordinate clicks in V1. Raw coordinates may appear in diagnostics only.

## Error Handling

- If region analysis fails, keep the user in chat mode and show a compact composer error: `区域分析失败，请重新框选`.
- If the selected region maps to no visible elements, return an evidence object with empty `intersecting_elements` and a warning. The user may still send the instruction, but the planner sees the warning.
- If the region is inside an iframe, include `frame_path` from the server-side frame path builder.
- If the page navigates before the user sends the message, mark the attachment stale and ask for re-selection.
- If the user removes the attachment, delete the pending region context from the session.
- If the user starts a new selection while another pending attachment exists, replace the old pending attachment after successful analysis.
- If the user sends an empty instruction with a region attachment, keep the attachment and show a composer validation message. A region alone is not an instruction.

## Testing Strategy

### Frontend Unit Tests

Add tests for:

- Composer selection button renders and disables with `sending || agentRunning`.
- Clicking the button sets one-shot selection active state.
- Dragging on the canvas creates an attachment preview and does not send browser input events for that drag.
- `Esc` cancels selection.
- Removing the attachment clears the preview and prevents region context from being sent.
- Sending a message includes `region_id` only when an attachment is present.
- Sending an empty message with an attachment does not call the assistant endpoint and keeps the attachment.
- Starting a second successful selection replaces the first pending attachment.

### Backend Unit Tests

Add tests for:

- Region analysis endpoint validates rect and tab id.
- Region evidence response includes frame path, summary, inferred kind, and local text.
- Region analysis converts iframe-intersecting top-level coordinates into frame-local coordinates and records `frame_path`.
- Assistant streaming endpoint passes stored `region_context` into `RecordingRuntimeAgent`.
- Assistant streaming endpoint rejects stale or missing `region_id` before planner execution.
- Successful region-backed extraction writes a trace with `region_context` and `region_selection` signal.
- Region-backed action writes an action or AI operation trace without forcing `DATA_CAPTURE`.
- Debug artifacts include `raw_region_evidence`, `planner_region_context`, and `region_context_decision`.

### Compiler Tests

Add tests for:

- Single-value region trace compiles to deterministic extraction.
- Table-region trace compiles using headers and row iteration.
- List-sample trace compiles using repeated item structure.
- Action-target region trace compiles through the existing action path and preserves locator candidates.

## Implementation Sequence

1. Add backend region evidence models and session storage.
2. Add `/region/analyze` endpoint and DOM evidence collector.
3. Extend assistant request and `RecordingRuntimeAgent` payload with optional `region_context`.
4. Persist `region_context` and `region_selection` signal on accepted traces.
5. Add frontend composer attachment state and selection button.
6. Add canvas one-shot selection overlay and coordinate conversion.
7. Send `region_id` with chat instructions and render attachment chips in chat history.
8. Extend timeline projection for region-backed data/action traces.
9. Add conservative compiler support for region-backed extraction traces.
10. Add focused tests for the frontend, backend, and compiler paths.

## Design Review Notes

This design follows RpaClaw's RPA rules:

- Trace-first recording remains the main path.
- Region selection supplies page facts, not experience rules.
- Failure facts and current page state remain authoritative during repair.
- Stability warnings are evidence, not pre-execution blockers.
- Site-specific examples are validation cases, not architecture.
- Raw coordinates are recording evidence only. Replay should prefer locators and structure.
