# RPA Region-Scoped Snapshot Design

## Summary

本设计替代旧分支里“把选区作为独立 `region_context` 塞给 planner”的主路径。

用户框选页面区域后，下一条自然语言指令应该使用 `region-scoped snapshot`：选区内 DOM evidence 获得采集和压缩预算优先权，选区外 DOM 不参与任务候选竞争，只保留页面身份、父级定位、frame/dialog/heading 等最小恢复上下文。

核心判断：

- 现有自然语言执行不准确，主要失败层常在 `raw_snapshot` 采集上限、`compact_snapshot` 过滤、region tiering、TopK 排序和上下文预算分配。
- 因此选区不应只是 prompt 旁路提示，也不应变成截图/VLM/坐标执行路径。
- 选区应进入现有 DOM snapshot 采集与压缩链路，成为当前指令的 scope signal。

## Goals

- 只影响下一条自然语言指令，成功、失败后用户可重新选择，发送成功后默认清空。
- 在页面元素很多时，保证目标区域内 DOM 不被全页采集上限或压缩排序挤掉。
- 复用现有 `snapshot_compression.py` 的 structured region、tiering、`table_views`、`detail_views`、`form_views` 思路，而不是重建一套并行 evidence 模型。
- 让 planner 看到的是一个统一的 snapshot contract 变体，而不是全页 snapshot 加一份 loose `region_context`。
- 保持 Trace-first：录制阶段仍是操作浏览器、记录 accepted trace，编译阶段再做泛化；选区只是当前页面事实输入的 scope。

## Non-Goals

- 不做持续作用域；选区默认不影响多条后续指令。
- 不用截图裁剪或 VLM 作为主路径。
- 不把坐标写进 replay 逻辑。坐标只能作为诊断和重新构建 scope 的 evidence。
- 不把选区外 DOM 全部绝对删除。父级 container、active dialog、nearby heading、frame path、URL/title 等恢复上下文可以保留。
- 不新增经验规则驱动的 planner、站点模板、selector 模板或多轮 repair。
- 不在录制阶段因为 selector 弱、空值、候选多而提前阻断执行；这些只进入诊断与 repair evidence。

## Existing Snapshot Compression Context

当前 `RpaClaw/backend/rpa/snapshot_compression.py` 的主路径大致是：

1. `build_structured_regions(snapshot)`
   - 从 `content_nodes`、`actionable_nodes`、`containers`、frame actions 构建 region。
   - region 类型包括 `label_value_group`、`table`、`action_group`、`record_list`、`text_section`。

2. `tier_regions(regions, instruction)`
   - 用 instruction overlap 和 region rank 选择 `tier1`、`tier2`、`tier3`。
   - `tier1` expand，`tier2` sample，`region_catalogue` 保留全页面摘要。

3. `compact_recording_snapshot(snapshot, instruction, char_budget=60000)`
   - 若 clean payload 没超预算，返回 `clean_snapshot`，包含所有 expanded regions。
   - 若超预算，返回 `tiered_snapshot`，包含 selected expanded/sample regions 和全量 catalogue。
   - 始终保留 compacted `table_views`、`detail_views`、`form_views`。

这个设计已经比 raw DOM 好，但对“页面元素过多”仍有两层风险：

- `assistant_snapshot_runtime.py` 采集阶段有节点上限，目标区域可能在进入 compression 前已经缺失。
- compression 阶段的全页 TopK 和全量 catalogue 仍可能把噪音带给 planner，尤其当用户已经明确选择了目标区域时。

## Proposed Architecture

### Data Flow

```text
user drag selection
  -> RegionScope stored for next instruction
  -> build_page_snapshot(..., region_scope=scope)
  -> raw_snapshot with region-prioritized evidence
  -> compact_recording_snapshot(..., region_scope=scope)
  -> region_scoped_snapshot planner payload
  -> RecordingRuntimeAgent executes current instruction
  -> accepted trace stores region_scope_summary + compact evidence signals
```

### Region Scope Contract

`RegionScope` should be a small factual object, not a mini snapshot:

```json
{
  "region_id": "region-...",
  "tab_id": "tab-...",
  "page_url": "https://example.test/orders",
  "page_title": "Orders",
  "viewport_rect": { "x": 120, "y": 220, "width": 420, "height": 180 },
  "viewport": { "width": 1280, "height": 720 },
  "frame_path": [],
  "frame_rect": { "x": 120, "y": 220, "width": 420, "height": 180 },
  "created_at": "2026-05-19T..."
}
```

The object says where the user pointed. It should not decide what the page means, which selector is correct, or whether the output is valid.

## Capture Layer Extension

Only changing `snapshot_compression.py` is not enough, because raw snapshot collection can already drop nodes before compression sees them.

### `build_page_snapshot`

Extend the snapshot builder path to accept optional `region_scope`.

Recommended shape:

```python
snapshot = await build_page_snapshot(
    page,
    build_frame_path_from_frame,
    region_scope=region_scope,
)
```

When no scope is present, behavior remains unchanged.

When scope is present:

- Continue collecting the normal page identity and enough global context.
- Prioritize or separately collect nodes intersecting the scope before global node caps apply.
- Add scope metadata to raw snapshot:

```json
{
  "region_scope": {
    "region_id": "region-...",
    "viewport_rect": {},
    "frame_path": [],
    "frame_rect": {},
    "warnings": []
  }
}
```

### Region-Aware Raw Node Collection

For `content_nodes` and `actionable_nodes`:

- Collect all visible nodes whose `bbox` intersects the selected `frame_rect`, up to a region-specific cap.
- Then collect normal global nodes with the existing caps.
- Dedupe by node identity, text/bbox key, locator, or existing snapshot identity.
- Mark nodes with a lightweight flag:

```json
{
  "scope_relation": "inside_region|ancestor_context|outside_context"
}
```

The flag is diagnostic and compression input. It is not a selector and should not be exposed as DOM id.

### Parent And Context Nodes

Allow selected-region context to include:

- nearest meaningful container ancestors,
- active dialog container,
- current frame path,
- selected frame element summary if applicable,
- nearby heading or section title,
- URL and title.

These nodes may sit outside the rectangle but explain the selected area. They should be `ancestor_context` or `outside_context`, not task candidates.

## Compression Layer Extension

### API

Extend current compression function conservatively:

```python
def compact_recording_snapshot(
    snapshot: Dict[str, Any],
    instruction: str,
    *,
    char_budget: int = 60000,
    region_scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
```

Implementation may read `region_scope` from the argument or from `snapshot["region_scope"]`; explicit argument should win.

### Mode

When scope is present, return:

```json
{
  "mode": "region_scoped_snapshot",
  "url": "...",
  "title": "...",
  "region_scope": {},
  "page_context": {},
  "table_views": [],
  "detail_views": [],
  "form_views": [],
  "expanded_regions": [],
  "sampled_regions": [],
  "region_catalogue": []
}
```

`region_catalogue` should not be the old full-page catalogue. In scoped mode it should contain only:

- selected-region summaries,
- ancestor/context summaries needed for orientation,
- overflow notes if selected-region evidence was clipped.

### Region Candidate Filtering

Add scoped region grouping before `tier_regions`:

```text
regions
  -> selected_regions
  -> ancestor_context_regions
  -> outside_context_regions
```

Rules:

- `selected_regions` are the only regions that participate in task candidate competition.
- `ancestor_context_regions` may contribute title, summary, frame path, dialog identity, or locator hints for scoping.
- `outside_context_regions` should not be expanded or sampled unless they are page identity/context.

This prevents full-page TopK from overriding the user's explicit selection.

### Budget Allocation

Scoped budget should prefer selected evidence:

- reserve most of `char_budget` for selected-region structured evidence;
- include more rows/fields/actions for selected `table_views`, `detail_views`, `form_views`;
- reduce or omit outside candidates;
- include explicit overflow metadata when selected evidence still exceeds budget.

Suggested first allocation:

```text
page identity/context: small fixed budget
selected structured views: primary budget
selected expanded regions: primary budget
ancestor context: small secondary budget
outside catalogue: none by default
```

### Structured Views

`_compact_table_views`, `_compact_detail_views`, and `_compact_form_views` should become scope-aware.

Table views:

- keep tables/grids that intersect selected region or whose row/cell nodes intersect it;
- preserve more rows/cells for selected tables than global defaults;
- keep header context even if header row is slightly outside selected rect, because it is essential to interpret selected rows.

Detail views:

- keep sections whose fields intersect selected rect;
- keep section title even if title sits just above selected rect;
- prefer complete field pairs inside scope over unrelated page fields.

Form views:

- keep controls inside selected rect and nearby labels/hints;
- keep parent form title or dialog heading for orientation;
- exclude unrelated form fields outside scope from fill candidates.

## `region_context.py` Boundary

### Keep

Keep `region_context.py` as the selection and scope resolver:

- Pydantic models for rect, viewport, analyze request/response.
- One-shot session storage keyed by `region_id`.
- stale validation by session, tab, URL, and preferably frame/page identity.
- top-level viewport rect to frame-local rect resolution.
- iframe dominance resolution and `frame_path` construction.
- user-facing preview summary for the composer.
- warnings when the selected area maps poorly to a frame or visible DOM.

### Downgrade

Downgrade the current standalone evidence collector role:

- `intersecting_elements`, `local_text`, `table_summary`, `list_summary`, `action_summary`, and `locator_candidates` should not be the primary planner input.
- They may remain temporarily for preview/debug compatibility, but the main planner input should come from `region_scoped_snapshot`.
- Classification such as `table_region`, `list_region`, `action_region` should be preview metadata only, not execution routing.

### Remove Or Avoid As Main Path

Avoid growing `region_context.py` into:

- a parallel snapshot system,
- a compiler input format,
- a deterministic extraction planner,
- a selector scoring system,
- a site-specific heuristic library.

If region evidence logic starts duplicating `snapshot_compression.py`, move that logic into scoped snapshot capture/compression instead.

## RecordingRuntimeAgent Integration

Current runtime should pass scope into snapshot building and compression:

```python
snapshot = await _safe_page_snapshot(page, region_scope=region_scope)
compact_snapshot = _compact_snapshot(snapshot, instruction, region_scope=region_scope)
payload = {
    "instruction": instruction,
    "page": before.model_dump(mode="json"),
    "snapshot": compact_snapshot,
    "runtime_results": runtime_results,
}
```

The planner should not need a separate top-level `region_context` in the normal path. If retained during transition, it should be diagnostic or compatibility-only.

Prompt guidance should say:

- When `snapshot.mode == "region_scoped_snapshot"`, treat `expanded_regions`, structured views, and actions as scoped task candidates.
- Do not broaden to page-wide DOM unless the instruction explicitly asks outside the selected area or scoped evidence is empty with warnings.
- Use page context for orientation only.

## Trace And Compiler Boundary

Accepted traces may store a compact scope signal:

```json
{
  "region_scope": {
    "region_id": "region-...",
    "frame_path": [],
    "viewport_rect": {},
    "mode": "region_scoped_snapshot"
  }
}
```

Trace should also keep relevant accepted execution facts: locator candidates, output, AI execution code, structured evidence used, and diagnostics.

Compiler rules:

- Prefer replay locators and structured trace evidence.
- Do not compile raw coordinates.
- Do not infer final generalized logic from the selected text alone.
- Preserve runtime AI or require configure-stage review when scoped evidence is insufficient for deterministic replay.

This keeps selection as recording-time evidence and avoids making it a replay contract.

## Harness And Trace-First Alignment

This design avoids conflict with current Harness and Trace-first direction:

- It does not reintroduce contract-first recording.
- It does not make `region_context` a second accepted timeline source.
- It does not add multi-round repair.
- It keeps failure evidence inspectable through raw snapshot, scoped snapshot, compact snapshot, attempt, and trace diagnostics.
- It supports the project rule: compare raw snapshot and compact snapshot before blaming planner behavior.

Required debug artifacts for scoped runs:

- `raw_snapshot` with `region_scope`;
- `region_scoped_snapshot` or compact snapshot sent to planner;
- `snapshot_scope_metrics` showing selected/ancestor/outside counts and clipping;
- attempt plan and execution result;
- accepted trace `region_scope` signal.

Failure diagnosis order:

1. Did the target appear in raw selected-region evidence?
2. If not, inspect coordinate conversion, iframe resolution, raw snapshot caps, and capture selectors.
3. If raw has it but scoped compact dropped it, fix scoped compression or budget allocation.
4. If scoped compact has it but planner chose wrong, fix planner guidance or deterministic overlay.
5. If planner direction is correct but execution fails, inspect locator/actionability/repair evidence.

## Alternatives Considered

### Prompt-Only Region Context

Rejected as the main path.

It is easy to implement, but full-page compact snapshot still contains noisy candidates, and raw snapshot caps can already lose selected DOM before planner sees it.

### Absolute Outside-DOM Removal

Rejected.

It would reduce noise, but it can remove parent container, dialog title, table header, frame identity, and nearby heading that are required to interpret or locate the selected area.

### Screenshot/VLM Selection

Rejected for the main path.

It may help visual tasks later, but it bypasses DOM/locator/trace evidence and makes replay generalization harder.

## Testing Strategy

Backend compression tests:

- scoped compression expands selected-region evidence even when unrelated regions have better instruction text overlap;
- selected table keeps headers slightly outside rect and rows/cells inside rect;
- selected form keeps nearby labels and controls, excludes unrelated fields;
- outside region does not appear as candidate in `expanded_regions` or `sampled_regions`;
- scoped mode omits full-page `region_catalogue`.

Capture tests:

- selected nodes are collected before global caps;
- iframe rect converts to frame-local rect and records `frame_path`;
- parent container and nearby heading can be retained as context;
- empty selected DOM produces warnings without blocking execution.

Runtime tests:

- `RecordingRuntimeAgent` sends `region_scoped_snapshot` to planner for region-backed commands;
- planner payload does not include broad page candidates as task candidates;
- success trace stores region scope signal and accepted execution evidence.

Frontend tests:

- region applies only to the next natural-language instruction;
- removing attachment prevents scope from being sent;
- successful send clears the attachment;
- failed analysis keeps user in chat mode with retryable error.

## Implementation Slices

1. Normalize `RegionScope` models and keep `region_context.py` focused on scope resolution and one-shot storage.
2. Extend raw snapshot capture with optional region-prioritized collection.
3. Add `region_scope` parameter and `region_scoped_snapshot` mode to `snapshot_compression.py`.
4. Wire `RecordingRuntimeAgent` to pass scope into capture/compression instead of relying on separate planner `region_context`.
5. Preserve trace scope signals and debug metrics.
6. Keep or simplify frontend selection UX, ensuring one-shot behavior and no persistent mode.

Implementation must create or update the active Feature/Evidence records before coding starts, then close Evidence with verification before claiming readiness.

## Acceptance Criteria

- With no selected region, existing snapshot compression behavior remains unchanged.
- With selected region, selected DOM is prioritized during raw capture and compact compression.
- Outside DOM does not participate in task candidate selection, except allowed page identity and parent/context evidence.
- Planner receives one unified `snapshot` payload in `region_scoped_snapshot` mode.
- Accepted traces remain trace-first and do not replay by coordinates.
- Debug artifacts can distinguish capture failure, compression failure, planner failure, and execution failure.
