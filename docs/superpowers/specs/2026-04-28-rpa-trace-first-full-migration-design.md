# RPA Trace-first Full Migration Design

## Goal

将 RPA 录制系统从 `RPAStep + recorded_actions + traces` 的混合状态，收束为以 `RPAAcceptedTrace` 为唯一 accepted timeline 的 trace-first 架构，同时保证当前已基本可用的录制、配置、生成、测试、保存、MCP 导出能力不回退。

本设计不兼容开发期已有的旧 session、旧 skill metadata、旧 MCP preview payload。当前仍处于开发阶段，旧数据没有长期产品价值，不应为了兼容开发期历史包袱继续维护双主线。

## Current Architecture Facts

当前系统名义上已经偏 trace-first，但实际数据链路仍是 step-first 输入、recorded action 校验、trace 编译的混合形态：

```text
Browser event
  -> RPAStep
  -> ManualRecordedAction / ManualRecordingDiagnostic
  -> RPAAcceptedTrace
  -> TraceSkillCompiler
```

AI 录制路径较接近目标形态：

```text
RecordingRuntimeAgent result
  -> RPAAcceptedTrace / RPATraceDiagnostic
  -> runtime_results
```

这导致 manual 与 AI 两条路径的事实源不一致：manual 仍以 step 为录制事实，AI 以 trace 为录制事实。Configure/Test/Export 又需要动态合并这些事实源。

## Existing Models

### RPAStep

`RPAStep` 是旧录制步骤模型，当前承担三类职责：

- 浏览器事件 DTO：记录 click/fill/press/hover/tab 等现场事件。
- UI timeline item：前端仍能直接展示、删除、promote locator。
- legacy compiler input：没有 trace 时 fallback 给 `PlaywrightGenerator`。

主要字段包括：

- action, target, value, description, url
- frame_path, locator_candidates, validation, element_snapshot
- tab_id, source_tab_id, target_tab_id
- sequence, event_timestamp_ms
- source, prompt, sensitive
- result_key, collection_hint, item_hint, ordinal, assistant_diagnostics

问题在于它既像事件，又像业务步骤，又像编译输入，边界已经模糊。

### ManualRecordedAction

`ManualRecordedAction` 是从 `RPAStep` 重建出来的手动动作标准化结果。它的价值是保留 canonical target 校验和 raw candidates，但它不应该作为 session 顶层业务状态长期存在。

主要字段包括：

- action_kind
- target
- frame_path
- validation
- raw_candidates
- page_state
- value

对应的 `ManualRecordingDiagnostic` 表示手动动作不能被接受，例如缺少可回放 locator。

### RPAAcceptedTrace

`RPAAcceptedTrace` 是目标 accepted timeline 模型。它记录录制事实和编译证据，不是最终抽象。

主要字段包括：

- trace_id, trace_type, source
- user_instruction, action, description
- before_page, after_page
- frame_path, locator_candidates, validation, signals
- value, output_key, output
- ai_execution
- locator_stability, dataflow
- diagnostics_ref, accepted
- started_at, ended_at

目标状态下，所有 accepted 操作都必须进入 `RPAAcceptedTrace`；失败尝试只进入 diagnostics。

## Root Problem

当前最大问题不是模型数量，而是多个模型都在争夺业务事实源：

- 手动录制事实存于 `session.steps`。
- 可回放手动动作存于 `session.recorded_actions`。
- 编译事实存于 `session.traces`。
- UI 通过 `recorded_actions + traces + legacySteps` merge 出展示列表。
- 测试失败定位仍使用 step index。
- 保存和 MCP 导出仍保留 legacy steps。

这会让用户看到的 timeline、编译器读取的 timeline、诊断修复操作的 timeline 不一定是同一个对象。后续每新增 dataflow、repair、snapshot、compiler generalization 都会被迫同步多套状态。

## Architecture Principles

本迁移必须遵守以下不变量：

- `RPAAcceptedTrace` 是唯一 accepted timeline。
- `session.traces` 是录制、配置、测试、保存、导出的唯一业务输入。
- 浏览器事件可以有内部输入 DTO，但不得作为业务 timeline。
- `recorded_actions` 不再作为 session 顶层状态持久化。
- `recording_diagnostics` 合并为 trace diagnostic 或 manual event diagnostic projection，不再形成第二套失败容器。
- UI 编辑、删除、locator promotion、测试失败 retry 均以 `trace_id` 或 `diagnostic_id` 为主键。
- 编译只读 trace；不再从 step 侧补元数据。
- 录制阶段保持 trace-first：真实执行、保留证据、最多一次 repair；泛化留给 compiler。
- 不为了单站点或历史 fixture 反向塑造架构。

## Target Architecture

目标数据链路：

```text
Manual browser event
  -> manual trace normalizer
  -> RPAAcceptedTrace or RPATraceDiagnostic

AI instruction
  -> RecordingRuntimeAgent
  -> RPAAcceptedTrace or RPATraceDiagnostic

Session
  -> traces
  -> trace_diagnostics
  -> runtime_results
  -> trace timeline projection
  -> TraceSkillCompiler
```

目标 session 业务状态：

```python
class RPASession(BaseModel):
    id: str
    user_id: str
    start_time: datetime
    status: str
    traces: list[RPAAcceptedTrace]
    trace_diagnostics: list[RPATraceDiagnostic]
    runtime_results: RPARuntimeResults
    pending_download_events: list[dict]
    sandbox_session_id: str
    paused: bool
    active_tab_id: str | None
```

可短期保留但不作为业务事实源：

- `ManualBrowserEvent`：浏览器注入脚本上报事件后的内部输入 DTO。
- `ManualRecordedAction`：normalizer 内部 canonical target 校验结果。
- `PlaywrightGenerator`：TraceSkillCompiler parity 完成前的参考和临时 fallback。

最终移除：

- `RPAStep` 作为 session 顶层业务状态。
- `recorded_actions` 顶层状态。
- `recording_diagnostics` 顶层状态。
- `legacy_steps` metadata。
- step index based API。
- `PlaywrightGenerator` 主路径。

## Current Step Dependency Inventory

### Backend Session And Recording

当前 `RPASession` 持有 `steps`, `recorded_actions`, `recording_diagnostics`, `traces`, `trace_diagnostics`, `runtime_results`。其中 `steps` 仍用于：

- `add_step()` 创建手动和旧 AI step。
- 事件排序：按 `event_timestamp_ms` 和 `sequence` 插入。
- 连续 fill 合并。
- hover candidate queue 与 click promotion。
- click/press 后 navigation event 升级为 `navigate_click` / `navigate_press`。
- tab switch、close tab、popup 关联。
- `_rebuild_manual_recording_state()` 重建 `recorded_actions` 和 `recording_diagnostics`。
- `_record_manual_trace_for_step()` 将 step 转成 trace。
- `delete_step()` / `delete_step_by_id()`。
- `select_step_locator_candidate()`。
- `_broadcast_step()` websocket 推送。

### Backend Routes

RPA route 当前仍依赖 step：

- `_generate_session_script()` 没有 traces 时 fallback 到 `PlaywrightGenerator`。
- `_session_traces_for_compile()` 从 `steps` 和 `recorded_actions` 合并 trace metadata。
- `_build_session_recording_meta()` 仍输出 `legacy_steps`。
- `/session/{id}/step/{index}` 删除接口。
- `/session/{id}/step/{index}/locator` locator promotion。
- `/session/{id}/test` 用 generator dedupe steps 映射 failed step index。
- 保存 skill 时同时传 recording_meta 和 projected steps。
- 旧 assistant chat 路径仍可能产生 `agent_step_done` step。

### Frontend Recorder

Recorder page 当前依赖：

- `session.steps` fallback timeline。
- `recorded_actions + traces` merge timeline。
- websocket `"step"` 事件。
- `agent_step_done` 里兼容 `data.step`。
- 删除时 fallback `/step/{index}`。
- recorded count 使用 timeline steps 长度。

### Frontend Configure

Configure page 当前依赖：

- `getLegacyRpaSteps(session)`。
- 参数推导从 legacy `fill/select` step 读取。
- 起始 URL 从 timeline step 或 legacy step 读取。
- `/step/{index}/locator` promotion。
- diagnostic 删除 `/step/{index}`。
- diagnostics 通过 legacy step id 查 step index。

### Frontend Test

Test page 当前依赖：

- `mapRpaConfigureDisplaySteps(session)` merge 后作为测试 timeline。
- `failed_step_index` 展示失败步骤。
- retry candidate 调 `/step/{failedStepIndex}/locator`。
- diagnostics 仍来自 `recording_diagnostics` projection。

### MCP And Export

MCP/export 当前依赖：

- `session_to_mcp_steps(session)` 将 recorded actions 和 traces projection 成 step-like data。
- `skill_exporter` 仍写 `legacy_steps` 和 `mcp_steps`。
- `mcp_converter` 接受 step-like payload。
- `mcp_script_compiler` 有 trace-backed steps 分支，否则 fallback `PlaywrightGenerator`。

### Tests

当前测试大量覆盖 step/generator：

- `test_rpa_manager.py` 覆盖 step 录制、排序、合并、tab、hover、navigation upgrade。
- `test_rpa_generator.py` 覆盖 step compiler。
- `test_rpa_route_trace.py` 覆盖 trace + recorded_actions + legacy_steps 合并。
- trace compiler 相关测试已存在，但尚未证明完全覆盖 generator parity。

## Migration Strategy

### Phase 1: Trace Timeline Projection

目标：UI 可以完全从 trace projection 展示当前 timeline，但后端内部仍可暂时由 step 生成 trace。

新增或改造：

- 后端提供 `rpa_timeline_items` projection，输入只允许 `session.traces`, `trace_diagnostics`, `runtime_results`。
- projection 输出 UI 所需字段：id, trace_id, kind, action, title, summary, locator, candidates, validation, url, source, editable, deletable, diagnostic refs。
- Recorder/Configure/Test 先切换读取 projection。
- 停止前端自己 merge `recorded_actions/traces/legacySteps`。

验收：

- 当前手动录制 timeline 显示不回退。
- AI trace timeline 显示不回退。
- diagnostics 仍可见。
- timeline 顺序按 trace recording metadata / started_at 稳定排序。

### Phase 2: Trace-native Timeline APIs

目标：UI 不再使用 step index 操作业务对象。

新增或改造：

- `DELETE /session/{id}/trace/{trace_id}`。
- `POST /session/{id}/trace/{trace_id}/locator`。
- `DELETE /session/{id}/diagnostic/{diagnostic_id}` 或 diagnostic resolution API。
- test endpoint 返回 `failed_trace_id` 和 candidate list，而不是 `failed_step_index`。
- Configure/Test retry candidate 使用 trace API。

验收：

- 删除手动 trace 后，generate/test 不再包含该操作。
- 删除 AI trace 后，runtime_results 依赖风险被明确处理或诊断提示。
- locator promotion 更新 trace locator candidates。
- 测试失败后，左侧能定位到 failed trace 并重试。

### Phase 3: Manual Event To Trace Normalizer

目标：manual event 不再先落入 `RPAStep` 业务状态。

新增或改造：

- 引入 `ManualBrowserEvent` 或等价内部结构，表达浏览器注入脚本上报的原始事件。
- 将 `_step_data_from_event()`, `_make_description()`, `_rebuild_manual_recording_state()`, `manual_step_to_trace()` 合并/重构为 `manual_event_to_trace()`。
- canonical target 校验保留，但输出直接是 `RPAAcceptedTrace` 或 `RPATraceDiagnostic`。
- 连续 fill 合并改为 trace-level update。
- hover promotion 改为 pending manual event -> trace append。
- navigation upgrade 改为更新 predecessor trace。
- tab/popup/close/switch 直接写 trace signals。

验收：

- session 顶层不再新增 `steps` 和 `recorded_actions`。
- 手动 click/fill/press/select/check/uncheck/hover 全部产生 trace。
- 无有效 locator 的手动操作产生 diagnostic，不进入 accepted timeline。
- 修复后的 trace 可被 compiler 使用。

### Phase 4: Frontend Trace-native Rewrite

目标：前端概念彻底从 step 切到 trace。

改造：

- `RpaStepTimeline` 可以保留组件名，但 props 语义改为 timeline item，不再要求 step shape。
- `rpaConfigureTimeline.ts` 改为纯 projection consumer，或删除大部分 merge 逻辑。
- 参数推导从 trace projection / trace payload 中读取 fill/select traces。
- diagnostics 通过 diagnostic id 和 related trace id 展示。
- 删除所有 `/step/{index}` 调用。

验收：

- Recorder/Configure/Test 三页在无 `session.steps` 的 session 上正常工作。
- 参数识别不依赖 legacy step。
- trace_id 删除、locator promotion、failed retry 全部可用。

### Phase 5: Compiler, Test, Export Cleanup

目标：TraceSkillCompiler 成为唯一主编译器，PlaywrightGenerator 退出主路径。

改造：

- generate/test/save/MCP/export 只读 trace。
- `TraceSkillCompiler` 补齐当前 generator 仍独有的能力。
- `PlaywrightGenerator` 暂时保留为参考代码和测试对照。
- 当 removal gate 全部通过后，删除 generator fallback。

验收：

- 录制 -> 配置 -> 生成 -> 测试 -> 保存完整链路通过。
- MCP preview/export 使用 trace-backed projection。
- 不再输出 `legacy_steps`。

## PlaywrightGenerator Retirement Policy

不要把立即删除 `PlaywrightGenerator` 作为迁移前提。它是待退役模块，不是新架构依赖。

短期策略：

- `TraceSkillCompiler` 是新主路径。
- `PlaywrightGenerator` 只作为参考代码和临时 fallback。
- 新功能不得继续扩展 `PlaywrightGenerator`。

删除 `PlaywrightGenerator` 主路径的 gate：

- TraceSkillCompiler 覆盖 click/fill/press/select/check/uncheck/hover。
- 覆盖 navigate_click / navigate_press。
- 覆盖 multi-tab switch/close/popup。
- 覆盖 frame_path。
- 覆盖 locator candidate promotion。
- 覆盖 test failure mapping 和 retry。
- 覆盖 params / sensitive / credential 注入。
- 覆盖 download。
- generate/test/save/MCP/export 均只读 trace。
- 后端和前端相关测试通过。
- 至少一条完整 E2E 通过：录制 -> 配置 -> 生成 -> 测试 -> 保存。

## Functional Non-regression Matrix

| Feature | Current dependency | Target dependency | Acceptance |
| --- | --- | --- | --- |
| Manual click | RPAStep -> recorded action -> trace | Manual event -> trace | click trace compiles and replays |
| Manual fill | RPAStep merge fill | trace-level fill merge | continuous typing produces one final fill trace |
| Press | RPAStep | trace action | press compiles and replays |
| Select/check/uncheck | RPAStep / ManualRecordedAction | trace action | target and value preserved |
| Hover menu | pending hover step | pending manual event | hover + click menu flow preserved |
| Navigation upgrade | predecessor step mutation | predecessor trace mutation | click/press navigation compiles once |
| Multi-tab | step tab fields | trace signals.tab | switch/close/popup replay preserved |
| Frame | step.frame_path | trace.frame_path | iframe actions replay |
| Locator promotion | step index API | trace id API | selected locator updates trace |
| Manual diagnostics | recording_diagnostics | trace_diagnostics | unresolved item visible and actionable |
| AI operation | trace already | trace | unchanged |
| Repair | trace diagnostics | trace diagnostics | failed attempt excluded from timeline |
| Runtime results | runtime_results | runtime_results | output_key writes preserved |
| Dataflow fill | trace dataflow | trace dataflow | dynamic ref used over literal |
| Generate script | trace or generator fallback | trace compiler | generated script behavior preserved |
| Test failure retry | failed_step_index | failed_trace_id | failed trace focused and retryable |
| Save skill | recording_meta + steps | trace metadata | skill.py and SKILL.md saved |
| MCP preview/export | step-like projection | trace-backed projection | no legacy step requirement |

## API Design

Trace-native endpoints:

```text
GET    /api/v1/rpa/session/{session_id}
GET    /api/v1/rpa/session/{session_id}/timeline
DELETE /api/v1/rpa/session/{session_id}/trace/{trace_id}
POST   /api/v1/rpa/session/{session_id}/trace/{trace_id}/locator
DELETE /api/v1/rpa/session/{session_id}/diagnostic/{diagnostic_id}
POST   /api/v1/rpa/session/{session_id}/generate
POST   /api/v1/rpa/session/{session_id}/test
POST   /api/v1/rpa/session/{session_id}/save
```

Deprecated during migration:

```text
DELETE /api/v1/rpa/session/{session_id}/step/{step_index}
POST   /api/v1/rpa/session/{session_id}/step/{step_index}/locator
DELETE /api/v1/rpa/session/{session_id}/timeline-item with kind=manual_step
```

During migration, deprecated APIs may remain for internal comparison tests, but UI must stop calling them.

## Timeline Projection Shape

Projection item should be UI-oriented and trace-backed:

```python
class RPATimelineItem(BaseModel):
    id: str
    trace_id: str | None = None
    diagnostic_id: str | None = None
    kind: Literal["trace", "diagnostic"]
    source: Literal["manual", "ai", "system"]
    trace_type: str | None = None
    action: str
    title: str
    summary: str
    url: str = ""
    frame_path: list[str] = []
    locator: dict[str, Any] = {}
    locator_candidates: list[dict[str, Any]] = []
    validation: dict[str, Any] = {}
    editable: bool = False
    deletable: bool = False
    order_ms: float | None = None
    raw_trace: dict[str, Any] | None = None
    raw_diagnostic: dict[str, Any] | None = None
```

Projection 是 UI contract，不是编译 contract。编译器仍读取原始 trace。

## Diagnostic Policy

失败事实优先：

- Failed manual event: create diagnostic with raw event, locator candidates, page state, reason.
- Failed AI execution: keep original error, traceback, current URL/title, failed code, repair result.
- Diagnostics can point to `related_trace_id` if the failed event attempted to update an existing trace.
- Diagnostics must not become accepted timeline items.
- Stability warnings should be diagnostic evidence, not pre-execution blockers.

## Dataflow Policy

Trace-first migration must preserve dataflow direction:

- Runtime AI writes `runtime_results` through `output_key`.
- Manual fill can infer exact value match from `runtime_results` and write `trace.dataflow`.
- Compiler prefers `_results` / `output_key` references over observed literals when dependency is clear.
- Observed recording values are evidence, not replay logic.

## Testing Strategy

Add or update tests in this order:

1. Projection tests: trace list -> timeline items.
2. Trace API tests: delete, locator promotion, diagnostic deletion.
3. Manual event normalizer tests: one test per action family.
4. Manager tests: no new session step state in new path.
5. Frontend unit tests: configure/test helpers no longer require legacy steps.
6. Trace compiler parity tests for each generator capability.
7. Route tests: generate/test/save read traces only.
8. E2E smoke: manual recording and AI trace mixed flow.

Do not delete generator tests until parity tests exist. After generator retirement, either remove generator tests or convert their fixtures into trace compiler tests.

## Subagent Work Breakdown

This migration is suitable for subagent-driven development after an implementation plan exists. Use one controller agent to preserve architecture boundaries and avoid parallel agents inventing conflicting contracts.

Recommended task ownership:

- Agent A: backend trace timeline projection and trace-native APIs.
- Agent B: manual event -> trace normalizer and manager integration.
- Agent C: frontend Recorder/Configure/Test trace-native rewrite.
- Agent D: TraceSkillCompiler parity and test failure retry.
- Agent E: MCP/export metadata cleanup and tests.
- Review agents: spec compliance review first, code quality review second.

Do not run independent implementation agents against shared contracts until the projection shape and trace mutation APIs are fixed.

## Rollout Plan

Recommended sequence:

1. Land projection and read-only UI switch.
2. Land trace-native mutation APIs and switch UI writes.
3. Land manual event normalizer and stop writing new steps.
4. Land compiler parity improvements.
5. Land export/MCP cleanup.
6. Remove legacy session fields, step APIs, and generator fallback after gates pass.

## Explicit Non-goals

- No migration for development-stage old sessions.
- No support for old skill metadata that depends on `legacy_steps`.
- No new contract-first recording layer.
- No multi-round repair loop.
- No site-specific abstraction hidden in compiler or recorder.
- No pre-execution blocking for selector weakness, empty extraction, or page slowness unless it is a safety risk.

## Open Decisions

1. Whether to rename `RpaStepTimeline` to `RpaTraceTimeline` during frontend migration or keep the component name temporarily.
2. Whether diagnostics should be separate timeline items or grouped under the related trace in UI.
3. Whether `ManualRecordedAction` should remain as a private class or be replaced by plain normalizer functions.
4. Whether MCP preview should consume raw traces directly or a trace-backed step projection.

## Approval Criteria

This design is approved when:

- The accepted timeline single-source rule is accepted.
- Non-compatibility with development-stage old data is accepted.
- Generator retirement gate is accepted.
- Functional non-regression matrix covers all currently valued RPA behavior.
- The next implementation plan can assign file-level tasks without re-litigating architecture.
