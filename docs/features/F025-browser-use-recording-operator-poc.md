---
id: F025
doc_kind: feature
status: partial
created: 2026-07-05
updated: 2026-07-05
---

# F025: Browser-use Recording Operator POC

## Goal

验证 browser-use 能否替换 ScienceClaw 录制技能中“自然语言对话驱动浏览器操作”的局部能力，同时继续产出 ScienceClaw 可编译、可回放的 accepted trace。

本 POC 的目标不是简单接入 browser-use demo，而是在真实录制环境中复用当前浏览器上下文、登录态和页面状态，让 browser-use 保留 planner/agent loop 完成复杂业务操作，并通过 Trace Adapter 将执行过程沉淀为现有 TraceSkillCompiler 可消费的证据。

## Vision Anchor

- 原始问题：ScienceClaw 当前自然语言操作浏览器能力不足，经常无法完成用户输入的业务指令，需要引入 browser-use 这类成熟浏览器 Agent 能力提升操作成功率。
- 用户痛点：录制技能的自然语言入口不能可靠完成登录后页面操作、iframe 内操作、复杂表格、弹窗、下拉树、上传下载、多标签、分页抽取、日期控件、富文本等业务场景，导致后续 Trace->Skill 链路即使存在也拿不到有效录制事实。
- 能力承诺：browser-use 接管录制期自然语言理解、任务规划和浏览器操作；ScienceClaw 继续拥有 accepted trace、TraceSkillCompiler 和 Skill 回放语义。
- 非目标：不 fork TraceSkillCompiler；不把 browser-use final result 当作第二事实源；不要求第一阶段与 ScienceClawNativeOperator 做严格公平对照；不为了适配而把 browser-use 降级成 click/fill/navigate 工具集合。
- 验收来源：真实业务场景 POC、生成 Skill 的回放结果、Trace 证据完整性检查、ADR-001/ADR-002/ADR-004 的事实源与证据边界。

## Feature Intake

- Original problem: ScienceClaw 当前录制技能中的自然语言浏览器操作能力不足，难以稳定完成用户业务指令。
- User pain point: 用户录制业务流程时，经常因为自然语言操作失败而无法获得有效 Trace，导致后续 Skill 生成链路没有可用事实。
- Capability promise: 用 browser-use 替换录制期自然语言浏览器操作局部能力，同时把 browser-use 执行过程转成 ScienceClaw 可编译、可回放的 accepted trace。
- Non-goals: 不重写 TraceSkillCompiler；不 fork 一套 browser-use 专用 Skill 编译器；不让 Harness 或 browser-use final result 合成产品事实；不阉割 browser-use planner/agent loop。
- Acceptance source: 用户确认的真实业务 POC 场景、生成 Skill 的回放结果、ADR-005、ADR-001、ADR-002、ADR-004。
- Open questions: browser-use 与现有 Playwright page/context 的最佳绑定方式、browser-use action 事件粒度、复杂组件的 Trace evidence 完整性仍需代码 Spike 验证。真实 E2E 可使用用户提供的 Qwen3.6-Max-Preview 兼容 OpenAI 接口资源，但 API Key 不得写入仓库。

## Capability Contract

- 录制技能可以选择 `BrowserUseRecordingOperator` 作为自然语言浏览器操作执行器。
- browser-use 必须复用当前录制浏览器上下文、登录态、页面状态和 tab 状态。
- browser-use 可以保留 planner/agent loop，并可在一次用户指令内执行多个实际浏览器动作。
- 每个关键动作、页面状态变化和浏览器副作用都必须进入 accepted trace、trace diagnostics 或 runtime result。
- TraceSkillCompiler 继续基于 trace evidence 编译 Skill，不能消费 browser-use final result 作为第二事实源。
- POC 结果必须同时报告录制期操作成功、Trace 完整性和 Skill 回放结果。

## Decision Context

### Why

browser-use 已经在通用浏览器 Agent 场景中投入了 planner loop、DOM/AX/CDP 观察、iframe/scroll/多步操作等能力。ScienceClaw 当前更强的是 Trace/Skill 资产化链路，而不是自然语言浏览器操作本身。因此合理边界是让 browser-use 承担录制期浏览器智能执行，让 ScienceClaw 继续拥有录制事实与编译语义。

### Why Not

不继续把主要投入放在增强现有 ScienceClawNativeOperator 上，因为短期很难追平 browser-use 的通用浏览器 Agent 能力。不直接用 browser-use final result 生成 Skill，因为这会绕过 accepted trace，制造第二事实源。不把 browser-use 限制为固定工具调用，因为这样无法验证其 planner/agent loop 的真实价值。

### If Modifying This Area, Check

- 检查 ADR-001、ADR-002、ADR-004、ADR-005。
- 检查 `RecordingRuntimeAgent`、accepted trace、TraceSkillCompiler 的事实源边界。
- 检查下载、上传、新标签、弹窗、iframe、分页提取等副作用是否由 Core trace 捕获。
- 修改 compiler 映射前，必须证明新增字段来自 trace evidence，而不是 browser-use 日志或 Harness expected signals。

## POC Scope

browser-use 必须复用 ScienceClaw 当前录制浏览器上下文，不得独立启动新浏览器破坏录制状态、登录态或 Trace 捕获边界。

短期用户输入按单步业务指令使用，但允许 browser-use 内部执行多个微动作或多个 agent step。Trace 端可以记录为多个 TraceStep；必要时可引入复合步骤投影，但 accepted trace 中仍必须能解释每个可回放动作和关键副作用。

第一阶段业务场景至少覆盖：

- 登录后页面操作。
- iframe 内操作。
- 表格搜索、筛选、点击行内按钮。
- 弹窗、抽屉、下拉树。
- 文件上传与下载。
- 分页数据提取。
- 多标签页。
- 日期控件。
- 富文本或复杂组件。

## Acceptance Criteria

- [ ] browser-use 可以在 ScienceClaw 录制会话中复用当前 browser/page/context 和登录态执行任务。
- [ ] browser-use planner/agent loop 保留，不被限制为固定 click/fill/navigate 工具调用。
- [ ] browser-use 每个实际浏览器动作、关键页面状态变化和副作用可以进入 ScienceClaw accepted trace 或 trace diagnostics。
- [ ] 下载、弹窗、新标签、iframe、文件选择器等副作用由 RPA Core 事实边界捕获，不由 Harness 或 UI 投影合成。
- [ ] TraceSkillCompiler 不改变核心编译语义；允许增加少量 browser-use trace evidence 字段映射。
- [ ] 真实业务场景 POC 可以完成录制期操作，并生成可回放 Skill。
- [ ] 操作成功但 Trace 不完整时不得判定为 POC 通过，必须归因为 Trace Adapter 或 Core capture 缺口。

## Proposed Components

- `BrowserUseRecordingOperator`：录制期自然语言执行入口，负责把用户指令交给 browser-use，并约束其使用当前录制浏览器上下文。
- `BrowserUseTraceAdapter`：把 browser-use action/result/browser state 映射为 ScienceClaw trace evidence。
- `BrowserUseTraceCaptureBridge`：协调现有 recorder 捕获结果与 browser-use action 事件，去重并归并为 accepted trace。
- `BrowserUsePocHarness`：面向真实业务场景的验收矩阵，验证操作成功、Trace 完整、Skill 可回放。

## Open Questions

- browser-use 当前源码是否能直接绑定既有 Playwright page/context，还是需要通过 CDP/browser session 适配。
- browser-use action 历史中可获取的元素证据是否足以补齐 ScienceClaw locator、frame_path、table/detail/form evidence。
- 多标签页、文件上传下载、iframe 内动作的 browser-use 事件粒度是否与现有 TraceStep 模型一致。
- 对 browser-use 内部多步执行，应默认落多个 accepted trace，还是允许在 UI 上投影为一个复合录制步骤。

## Current Status

Partial。第一阶段已打通 browser-use 复用 local 录制浏览器并生成 accepted trace 的最小主链路，但真实业务矩阵 live UI E2E 未通过。当前不能声明 browser-use 已经可替换 ScienceClaw 录制技能中的自然语言操作能力。

## Links

### Evidence

- [EV-025 Browser-use Live UI E2E](../evidence/EV-025-browser-use-live-ui-e2e.md)
- [EV-026 Browser-use 真实业务矩阵 Live UI E2E](../evidence/EV-026-browser-use-live-ui-business-matrix.md)

### Decisions / ADRs

- [ADR-005 Browser-use Recording Operator Integration Boundary](../decisions/ADR-005-browser-use-recording-operator-integration-boundary.md)
- [ADR-001 RPA Trace Is The Single Accepted Timeline](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md)
- [ADR-002 Trace Evidence Drives Compiler Strategy](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md)
- [ADR-004 RPA Core Owns Recording Facts, Harness Adapts Only](../decisions/ADR-004-rpa-core-owns-recording-facts-harness-adapts-only.md)

### Lessons

- None.

### Specs / Plans

- [RPA-DOM上下文工程评估原则](../rpa/RPA-DOM上下文工程评估原则.md)

### Related Features

- [F024 RPA Core / Harness Boundary Guard](F024-rpa-core-harness-boundary-guard.md)

### External Context

- browser-use local source: `E:\RPA-Agent\browser-use`
- Real E2E LLM resource: `MODEL_NAME=Qwen3.6-Max-Preview` with OpenAI-compatible `API_BASE` and `API_KEY` supplied through local environment variables, not committed files.

## Acceptance Map

| Claim | Acceptance | Evidence | Status |
| --- | --- | --- | --- |
| browser-use can act as the recording natural-language browser operator | It reuses the current ScienceClaw recording browser context and completes the POC scenario set | Pending implementation evidence | pending |
| browser-use execution remains trace-first | Key actions and side effects enter accepted trace, trace diagnostics, or runtime result | Pending trace evidence | pending |
| Skill generation remains compatible | Existing TraceSkillCompiler semantics generate replayable Skill from browser-use-backed traces | Pending replay evidence | pending |

## State Timeline

| Date | State | Trigger | Evidence | Note |
| --- | --- | --- | --- | --- |
| 2026-07-05 | draft | Feature created | This Feature and ADR-005 | Browser-use POC boundary captured before implementation |
| 2026-07-05 | partial | Minimal integration implemented | EV-025 | GitHub trending live UI path produced a browser-use accepted trace |
| 2026-07-05 | blocked for business matrix | Real business matrix live UI failed | EV-026 | Browser-use only completed login and did not generate browser-use accepted trace for the matrix |
| 2026-07-05 | POC validated with deterministic replay | Real business matrix live UI passed | EV-026 | Recorder UI produced 14 business Trace entries; compiler now replays browser-use action evidence deterministically; direct SKILL replay returned `ALL_SCENARIOS_PASS` |

## Patch History

None yet.

## Evidence

- EV-025 proves the minimal live UI integration path can produce a browser-use accepted trace.
- EV-026 proves the full business matrix POC can complete recording and deterministic SKILL replay, while noting that the running backend process must reload before `/generate` uses the new compiler logic.

## Recovery Snapshot

- Read first: ADR-005, then this Feature.
- Current capability state: browser-use integration can complete the real business matrix in Recorder UI, and recorded browser-use action evidence can compile to a deterministic SKILL replay that returns `ALL_SCENARIOS_PASS`.
- Known risks: active backend processes may need reload/restart to pick up compiler changes; new browser-use recordings still depend on available LLM quota; action-evidence replay depends on stable element evidence such as id/data-* attributes, with fallback to browser-use only when evidence is insufficient.
- Next safe action: restart/reload the backend and rerun `/generate` + `/test` through the product API on a fresh session once LLM quota is available for new recording.
- Unblock condition: product API `/generate` and `/test` pass on a fresh Recorder UI session using the new deterministic browser-use action replay path.

## Next Step

先修复 F025 的诊断与 Harness：保留失败 history、复现滚动/schema 问题，并分别验证 `qwen3.6-max-preview` 与 `qwen3.6-35b-a3b` 的 action schema 合规率。
