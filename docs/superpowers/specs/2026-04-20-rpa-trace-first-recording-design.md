# RPA Trace-first Recording Design

Date: 2026-04-20

Branch: `codex/rpa-trace-first-recording`

Baseline: `upstream/master`

## 1. Problem Statement

The RPA skill recording feature needs to support a mixed workflow:

- Users record precise browser operations manually whenever that is faster and more reliable.
- Users use natural language only for operations that are tedious or inherently semantic, such as finding the repository with the highest star count, selecting the most relevant project, summarizing a page, extracting the top N records, or transferring data from one page to another.
- The final saved Skill should replay reliably and should avoid unnecessary runtime token usage by preferring deterministic Playwright code when possible.

The previous Contract-first recording architecture made recording itself too heavy. A single instruction could trigger multiple LLM calls, repeated snapshots, compilation, validation, repair, and done checks. In practice this made recording slower, less predictable, and more fragile than the upstream direct-agent experience.

The new design therefore moves complexity out of the interactive recording path.

Core principle:

```text
Recording time: run fast, operate the browser, and record rich factual traces.
Skill generation time: analyze traces, generalize, generate stable code, test, and repair.
Replay time: run mostly deterministic Playwright code, with runtime AI only where semantic reasoning is truly required.
```

## 2. Design Goals

- Preserve the upstream direct RPA assistant experience during recording.
- Make natural-language browser operations fast enough for interactive use.
- Do not require generated recording-time code to be fully generalized.
- Record enough factual evidence to generalize after recording completes.
- Support cross-page dataflow, especially extracting data from page A and filling corresponding fields on page B.
- Show users a clear left-side timeline of accepted recorded steps.
- Keep failed attempts out of the primary recorded step list.
- Generate Skills that are more stable than raw traces by applying post-hoc generalization and replay testing.
- Keep architecture simple enough to debug and evolve.

## 3. Non-goals

- Do not reintroduce Contract-first as the default recording-time control loop.
- Do not run multiple Planner/Compiler/Validator LLM rounds for every interactive natural-language command.
- Do not force every recorded step into a perfect final abstraction during recording.
- Do not make local keyword rules the primary semantic classifier.
- Do not optimize every possible RPA scenario in the first implementation. The first implementation must fully support the target scenarios listed in this document and leave clear extension points for later.

## 4. Recommended Architecture

The architecture is split into two stages.

### Stage 1: Trace-first Recording Runtime

Recording runtime is optimized for fast browser operation. It records facts, not final Skill abstractions.

```text
Manual action or natural-language command
        ->
Operate browser using upstream-style direct assistant path
        ->
Record accepted trace with before/after evidence
        ->
Update lightweight runtime results when data is extracted
        ->
Show accepted trace in the left-side timeline
```

Recording runtime may use one LLM call for a natural-language operation. If a generated script fails, one bounded local execution repair is allowed, but repeated planning loops are not part of the default path.

### Stage 2: Post-hoc Skill Compilation

Skill compilation runs after the user clicks recording complete or save/generate.

```text
Trace timeline
        ->
Trace analyzer
        ->
Generalizer and dataflow resolver
        ->
Skill script generator
        ->
Replay tester
        ->
Failure repair loop
        ->
skill.py + optional trace/manifest metadata
```

Compilation may use heavier reasoning, because it does not block the live recording interaction. This is where URL generalization, dataflow inference, validation generation, and replay repair belong.

## 5. Trace Model

The recorder should store accepted traces separately from low-level diagnostics.

### 5.1 Common Trace Fields

Every accepted trace should include:

- `trace_id`
- `trace_type`
- `source`: `manual` or `ai`
- `user_instruction` when applicable
- `status`: accepted traces are successful by definition
- `started_at_ms`
- `ended_at_ms`
- `before_page`: URL, title, optional snapshot summary
- `after_page`: URL, title, optional snapshot summary
- `diagnostics_ref` for failed attempts or raw details

### 5.2 Manual Action Trace

Manual actions should record:

- `action`: `goto`, `click`, `fill`, `press`, `select`, or equivalent existing action
- locator candidates from the existing recorder
- target text, role, href, label, placeholder, and stable CSS hints when available
- typed or selected value for fill/select operations
- whether navigation happened
- before and after URL

The primary timeline should display only the accepted manual action, not internal event noise.

### 5.3 AI Operation Trace

Natural-language operations should record:

- user instruction
- generated code or structured action that actually ran
- execution result
- resulting URL or data output
- before and after page evidence
- whether the step changed the page, extracted data, filled fields, downloaded files, or opened a new tab

The recording-time generated code may contain concrete URLs or selectors. That is acceptable because generalization happens later.

### 5.4 Data Capture Trace

Whenever a step extracts structured data, store a data capture trace:

- `output_key`, such as `customer_info`, `selected_project`, or `top10_prs`
- structured `output`
- source page URL/title
- field provenance when available: nearby label, source text, selector hint, row context, URL, and confidence
- schema inferred from the output shape

Example:

```json
{
  "trace_type": "data_capture",
  "source": "ai",
  "user_instruction": "抓取客户名称、邮箱、电话",
  "output_key": "customer_info",
  "output": {
    "name": "张三",
    "email": "zhangsan@example.com",
    "phone": "13800000000"
  },
  "source_page": {
    "url": "https://example.test/customer/1",
    "title": "客户详情"
  }
}
```

### 5.5 Dataflow Trace

Cross-page workflows require a first-class dataflow trace. When a value is filled into a target page, the recorder should try to link the filled value to prior runtime results.

Record:

- target field locator candidates
- target field label, placeholder, role, and nearby text
- actual filled value
- candidate source refs, such as `customer_info.name`
- selected source ref when the match is exact or high-confidence
- confidence and reason

Example:

```json
{
  "trace_type": "dataflow_fill",
  "source": "manual",
  "target_page": {
    "url": "https://example.test/create-order"
  },
  "target_field": {
    "label": "客户名称",
    "locator_candidates": []
  },
  "value": "张三",
  "source_ref_candidates": ["customer_info.name"],
  "selected_source_ref": "customer_info.name",
  "confidence": "exact_value_match"
}
```

If no confident source ref exists, the trace should keep the literal value and mark the mapping as unresolved. The compilation UI can later ask for confirmation if needed.

## 6. Runtime Results Store

Recording should maintain a lightweight `runtime_results` object for the current session.

It is not a heavy contract blackboard. Its responsibilities are:

- Store structured outputs from accepted data capture traces.
- Allow later natural-language commands to reference previously captured data.
- Support immediate A-to-B workflows, such as "把刚才抓到的信息填到当前表单".
- Provide candidate refs for dataflow trace inference.

Example:

```json
{
  "selected_project": {
    "name": "openai/openai-agents-python",
    "url": "https://github.com/openai/openai-agents-python"
  },
  "customer_info": {
    "name": "张三",
    "email": "zhangsan@example.com"
  }
}
```

## 7. Natural-language Recording Rules

Natural-language commands are recording-time browser assistance, not final Skill compilation.

Rules:

- Prefer the upstream direct assistant/ReAct path for operating the browser.
- A single user instruction should normally use one LLM planning/code-generation call.
- One bounded repair is allowed for execution errors caused by generated code syntax or obvious selector failure.
- Failed attempts are diagnostics, not accepted traces.
- If the operation succeeds, record the successful action/code/result trace.
- Do not run a separate done-check LLM call after every accepted trace.
- Do not force recording-time steps into final generalized Skill code.

Recommended behavior for common examples:

- "打开 star 数量最多的项目": generate and run one script that parses the current list, finds the max star count, and navigates to the selected URL. Record the script, selected target, and after URL.
- "打开和 Python 最相关的项目": use runtime semantic judgment once, navigate, and record selected target with reason.
- "收集当前仓库前 10 个 PR": run deterministic extraction, record array output and source page.
- "把刚才抓取的数据填到当前表单": consume `runtime_results`, fill fields, and record dataflow mappings.

## 8. Left-side Timeline UX

The recorder left panel should show accepted traces, not internal agent attempts.

Suggested card categories:

- Manual operation
- AI browser operation
- Data captured
- Data filled
- Page navigation
- Generated script step

Each card should show a concise human-readable summary.

Examples:

```text
01 手动打开页面
打开 https://github.com/trending

02 AI 操作
打开 star 数量最多的项目
结果：openai/openai-agents-python

03 手动操作
进入 Pull requests 页面

04 AI 提取数据
收集前 10 个 PR
输出：top10_prs，10 条记录

05 数据填写
customer_info.name → 客户名称
customer_info.email → 邮箱
```

Expanded details may show:

- before/after URL
- raw instruction
- generated code preview
- output preview
- locator candidates
- dataflow refs
- diagnostics for failed attempts

The default collapsed timeline should remain simple and confidence-building.

## 9. Post-hoc Skill Compilation

Compilation should transform traces into a replayable Skill.

Compilation tasks:

1. Normalize trace order and remove failed attempts.
2. Identify data-producing traces and data-consuming traces.
3. Replace literal values with runtime result refs when confidence is high.
4. Generalize URLs when a URL came from a previous selected target.
5. Convert successful natural-language logic traces into deterministic Playwright helpers when possible.
6. Preserve runtime AI only when the trace represents semantic judgment that cannot be deterministically encoded.
7. Generate validation checks for important outcomes.
8. Run replay tests and repair generated code when replay fails.

Examples:

- A recorded literal URL `https://github.com/openai/openai-agents-python/pulls` can become `{selected_project.url}/pulls` when `selected_project.url` was captured in a prior trace.
- A literal filled value `"张三"` can become `customer_info["name"]` when it exactly matches a prior captured field.
- A natural-language trace that selected the highest star count can become a deterministic script that parses star counts during replay.
- A semantic trace that selected the most relevant project can remain a runtime AI instruction, but must output structured JSON for downstream steps.

## 10. Validation Strategy

Validation should be strongest during replay and Skill generation, not during interactive recording.

Recording-time validation:

- Did the browser action execute?
- Did URL/title/data output change as expected?
- Was structured data captured when requested?

Generation/replay-time validation:

- Required arrays are not empty unless the user explicitly allowed empty results.
- Required record fields are non-empty.
- Filled form fields equal the intended source values.
- URL contains expected stable subpaths when applicable.
- Extracted text is not generic page chrome such as "Navigation Menu".
- Runtime AI outputs match the required structured schema.

## 11. Error Handling

Recording:

- Keep the UI responsive.
- Record failed attempts in diagnostics only.
- If a natural-language action fails after the bounded repair, show a concise failure and let the user continue manually.
- Do not add failed attempts to the primary timeline.

Compilation:

- If generalization is low confidence, keep the literal action and mark it as a review warning.
- If dataflow mapping is ambiguous, generate a review item instead of guessing silently.
- If replay fails, repair generated code using the original trace and error message.

Replay:

- Fail loudly on validation errors that would produce false success.
- Surface step index, trace source, and repair hint.

## 12. Migration From Current State

The new implementation should start from the upstream-style RPA path.

Keep:

- Existing manual recorder and locator candidate capture.
- Existing `RPAAssistant` / `RPAReActAgent` direct browser operation style as the recording-time base.
- Existing `PlaywrightGenerator` as the initial Skill generation fallback.
- Useful runtime AI helper concepts only when semantic judgment is truly needed.

Do not keep as default recording path:

- Recording-time Contract-first Planner/Compiler/Validator loop.
- Multi-step contract repair for every natural-language instruction.
- Heavy snapshot/re-plan/done-check cycle after every accepted action.

Add:

- Trace store for accepted traces.
- Runtime results store.
- Dataflow trace inference.
- Left-side trace timeline.
- Post-hoc Skill compiler and replay repair loop.

## 13. Target Scenarios For First Complete Implementation

The first implementation should fully support these scenarios:

1. Manual-only Skill:
   - User manually opens pages, clicks, fills, and saves.
   - Timeline shows accepted manual traces.
   - Generated Skill replays successfully.

2. Deterministic natural-language operation:
   - User opens GitHub Trending.
   - User says "打开 star 数量最多的项目".
   - Recording completes quickly with one accepted AI trace.
   - Generated Skill does not hard-code the selected repo URL; it recomputes from the current page.

3. Semantic natural-language operation:
   - User opens GitHub Trending.
   - User says "打开和 Python 最相关的项目".
   - Recording records selected target and reason.
   - Generated Skill preserves runtime semantic selection only for this step.

4. Mixed manual + natural-language extraction:
   - User opens a project.
   - User manually enters PR page.
   - User asks for first 10 PR titles and creators.
   - Timeline shows manual navigation and data capture.
   - Generated Skill replays and returns a non-empty structured array.

5. A-to-B dataflow:
   - User extracts structured data from page A.
   - User navigates to page B manually or by natural language.
   - User fills fields manually or asks AI to fill them.
   - Trace records source data and target field mappings.
   - Generated Skill fills B using extracted values, not recording-time literals.

## 14. Architectural Trade-offs

This design intentionally accepts less abstraction during recording in exchange for better interactive experience.

Benefits:

- Fewer LLM calls during recording.
- Less opportunity for schema/contract mismatch.
- Better alignment with the upstream experience that has proven more usable.
- More complete context for post-hoc generalization because the compiler sees the full trace, not just one current step.
- Easier debugging because accepted traces are factual records.

Costs:

- Skill generation becomes more important and may take longer.
- Some generalization happens later, so the first generated script may need replay repair.
- Dataflow inference requires careful trace capture and may need user review when ambiguous.
- Runtime AI boundaries still need discipline to avoid token-heavy replay.

The trade-off is deliberate: slow work belongs after recording, not in the user's interactive loop.

## 15. Open Extension Points

The design leaves room for:

- More deterministic compilation patterns.
- Field mapping confirmation UI.
- Trace diff and replay diagnostics.
- Domain-specific compilers for common sites.
- Optional advanced Contract manifest generated after recording, not during recording.
- A future optimizer that merges adjacent traces into more compact replay code.

These extension points should not block the first implementation.
