---
id: ADR-005
doc_kind: adr
status: superseded
scope: feature
feature_refs:
  - docs/features/F025-browser-use-recording-operator-poc.md
decision_area: rpa-recording-browser-agent
created: 2026-07-05
updated: 2026-07-17
superseded_by: ADR-006
---

# ADR-005: Browser-use Recording Operator Integration Boundary

## Context

ScienceClaw 当前录制技能中的自然语言浏览器操作能力不足，常常无法可靠完成用户输入的业务指令。browser-use 是更成熟的浏览器 Agent 项目，具备 planner/agent loop、复杂页面探索、iframe/scroll/多步操作等能力，适合作为录制期自然语言浏览器操作能力的替换候选。

本次目标不是重写 RPA 体系，也不是替换 TraceSkillCompiler，而是在录制技能中替换“自然语言指令 -> 浏览器操作”这一局部能力。下游仍应围绕 accepted trace 生成 Skill，并保持 ADR-001、ADR-002、ADR-004 建立的事实源和证据边界。

短期使用上用户会尽量输入单步业务指令，但 browser-use 内部允许执行多个 agent step。长期方向是支持复杂多步骤自然语言任务，因此接入方式不能把 browser-use 限制为简单 click/fill/navigate 工具层。

## Decision

引入 browser-use 作为录制期自然语言浏览器操作执行内核的 POC 实现，但 ScienceClaw 仍拥有录制事实、accepted trace 和编译语义。

具体决策：

1. 新增 `BrowserUseRecordingOperator`，作为当前自然语言录制执行器的替代实现之一。
2. browser-use 必须复用当前 ScienceClaw 录制浏览器上下文、登录态、页面和 tab 状态，不得默认启动独立浏览器。
3. 保留 browser-use planner/agent loop，允许一次用户指令内部产生多个 browser-use action。
4. 新增 `BrowserUseTraceAdapter`，将 browser-use action/result/browser state 转换为 ScienceClaw trace evidence。
5. Trace 生成以结果为导向：优先复用现有 Core recorder 捕获；当现有捕获不足以支撑 Skill 编译时，由 Trace Adapter 补齐 browser-use action evidence。
6. browser-use 的 final result、历史消息或执行日志不得成为第二事实源；只有进入 `RPAAcceptedTrace`、`trace_diagnostics` 或明确 runtime result 的证据才可被下游消费。
7. TraceSkillCompiler 可以增加少量字段映射以识别 browser-use 证据，但不得改变“由 trace evidence 决定编译策略”的核心语义。
8. POC 成败以真实业务场景是否能完成录制操作并生成可回放 Skill 为准，而不是仅以 browser-use 当前页面操作成功为准。
9. 真实 E2E 可以使用用户提供的 Qwen3.6-Max-Preview 兼容 OpenAI 接口资源；API Key、API Base 等敏感运行配置必须通过本地环境变量或安全配置注入，不得写入仓库文档、测试 fixture 或生成产物。

## Architecture Boundary

目标架构：

```text
Recorder UI / recording session
        |
        v
RecordingRuntimeAgent
        |
        v
NaturalLanguageRecordingOperator
        |-----------------------------|
        v                             v
ScienceClawNativeOperator       BrowserUseRecordingOperator
                                      |
                                      v
                              browser-use Agent loop
                                      |
                                      v
                         BrowserUseTraceCaptureBridge
                                      |
                         |------------|-------------|
                         v                          v
              Core recorder captured facts   BrowserUseTraceAdapter
                         |                          |
                         |------------|-------------|
                                      v
                              RPAAcceptedTrace
                                      |
                                      v
                              TraceSkillCompiler
                                      |
                                      v
                              generated Skill
```

`BrowserUseRecordingOperator` 只拥有“如何理解指令并驱动浏览器”的职责；不拥有 accepted trace 事实源、不拥有 compiler 策略、不拥有 Harness expected signals。

`BrowserUseTraceAdapter` 只负责证据翻译与补齐；不得绕过 accepted trace 直接生成 Skill 代码。

## Decision Boundary

### Applies To

- ScienceClaw 录制技能中的自然语言浏览器操作入口。
- `RecordingRuntimeAgent` 与其后续 browser action / trace append 边界。
- browser-use 与当前录制 browser/page/context 的集成方式。
- browser-use action/result/browser state 到 ScienceClaw trace evidence 的映射。
- 真实业务场景 POC 的操作成功、Trace 完整和 Skill 回放验收。

### Does Not Apply To

- TraceSkillCompiler 的整体重写。
- 手工录制、SOP 导入、非自然语言驱动的录制路径。
- Harness expected signals 或离线 fixture 的事实定义。
- browser-use 独立运行在非 ScienceClaw 录制会话中的产品能力。
- 用 browser-use final result 直接生成 Skill 的旁路方案。

## Trace Mapping Strategy

browser-use 内部执行多个 action 时，默认映射为多个 accepted trace。UI 可以把它们投影为一次自然语言录制请求下的多条子步骤，但底层事实不应压成一个不可解释的黑盒步骤。

动作映射原则：

- navigation：记录 before/after page、final URL、tab/frame 上下文。
- click：记录目标元素 locator candidates、backend/action id、文本、role、frame_path、点击后副作用。
- fill/type/select：记录目标控件、输入值、label/control 关系、框架事件回放需要的 evidence。
- extraction：记录 extracted value，同时保留 structured snapshot、source element、table/detail/form evidence。
- download/upload/file chooser：记录副作用信号、文件名、路径策略、触发动作和等待边界。
- popup/new tab/dialog：记录触发动作、目标 tab/page、切换关系和关闭/确认语义。
- iframe/shadow/scroll：记录 frame_path、可见性、滚动前后状态、目标元素所在上下文。

操作成功但无法形成可编译 trace evidence 时，状态必须是 `operation_succeeded_trace_incomplete`，不能记为 POC 成功。

## Business Scenario Acceptance Matrix

| 场景 | 录制期操作 | Trace 证据 | Skill 回放 |
| --- | --- | --- | --- |
| 登录后页面操作 | browser-use 使用现有登录态完成操作 | before/after page 与目标 locator 完整 | 可回放 |
| iframe 内操作 | 能进入并操作嵌套 frame | frame_path 与目标证据完整 | 使用 frame locator 回放 |
| 表格搜索/筛选/行内按钮 | 能定位行、列、行内动作 | table row/column/action evidence 完整 | 可回放 |
| 弹窗/抽屉/下拉树 | 能打开、选择、确认 | popup/drawer/tree target evidence 完整 | 可回放 |
| 文件上传/下载 | 能处理 file chooser/download | upload/download side-effect signal 完整 | 可回放 |
| 分页数据提取 | 能翻页或滚动抽取 | extraction source 与分页状态完整 | 可回放或可验证 |
| 多标签页 | 能打开/切换/关闭 tab | tab transition evidence 完整 | 可回放 |
| 日期控件 | 能按控件要求输入/选择日期 | format/value/control evidence 完整 | 可回放 |
| 富文本/复杂组件 | 能输入或操作组件 | 组件目标与输入语义完整 | 可回放 |

## Rejected Options

- 继续增强 ScienceClawNativeOperator：暂不作为 POC 主路径。该路线可能更贴合现有 trace，但短期难以快速补齐 browser-use 已具备的复杂浏览器 Agent 能力。
- 直接用 browser-use final result 生成 Skill：拒绝。这会绕过 accepted trace，制造第二事实源，违反 ADR-001/ADR-002。
- 只调用 browser-use 底层 click/fill/navigate 工具：拒绝。这样无法验证 browser-use planner/agent loop 对复杂业务场景的真实价值。
- 让 browser-use 独立启动浏览器执行任务：拒绝。这样会丢失录制会话、登录态、页面状态和 Core trace 捕获边界。
- 为 browser-use fork 一套 TraceSkillCompiler：拒绝。短期看似隔离，长期会让 Skill 编译语义分裂。

## Consequences

- POC 实现复杂度集中在 browser-use 会话复用、action 事件观测、Trace Adapter 和副作用捕获上。
- 现有 recorder 捕获能力可能不足以覆盖 browser-use 的全部动作，需要补齐 Core capture 或 Adapter evidence。
- TraceSkillCompiler 应保持证据驱动策略；新增字段映射必须有明确 trace evidence 来源。
- Harness 只能验证 browser-use POC 的业务场景，不得合成产品录制事实。
- 若 browser-use 操作成功但生成 Skill 不可回放，问题应归因到 Trace Adapter/Core capture/compiler evidence mapping，而不是简单判定 browser-use 成功。

## Before Changing This Decision

修改或推翻本决策前，必须先检查：

- browser-use 是否仍能复用当前 ScienceClaw 录制浏览器上下文。
- accepted trace 是否仍是唯一可编译事实源。
- TraceSkillCompiler 是否仍由 trace evidence 决定编译策略。
- browser-use final result、日志、历史消息是否被误用为第二事实源。
- 下载、上传、新标签、弹窗、iframe、文件选择器等副作用是否由 RPA Core 捕获，而不是 Harness 或 UI 投影合成。
- 真实业务 POC 是否同时验证操作成功、Trace 完整和 Skill 回放。
- 真实 E2E 所需 LLM 凭据是否仅存在于运行时环境，且没有进入 Git 跟踪文件、Harness asset 或日志产物。

## POC Exit Criteria

POC 通过需要同时满足：

1. browser-use 在当前 ScienceClaw 录制浏览器上下文中完成真实业务场景操作。
2. 每个关键动作和副作用进入 accepted trace 或 trace diagnostics。
3. TraceSkillCompiler 可以基于现有语义生成 Skill。
4. 生成 Skill 在目标业务场景中可回放。
5. 失败报告能区分 browser-use 操作失败、Trace 捕获失败、证据映射失败、编译失败、回放失败。

## Evidence

- Feature: `docs/features/F025-browser-use-recording-operator-poc.md`
- Existing decision: `docs/decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md`
- Existing decision: `docs/decisions/ADR-002-trace-evidence-driven-compiler-strategy.md`
- Existing decision: `docs/decisions/ADR-004-rpa-core-owns-recording-facts-harness-adapts-only.md`
- Context principle: `docs/rpa/RPA-DOM上下文工程评估原则.md`
- Real E2E model: `Qwen3.6-Max-Preview` via OpenAI-compatible runtime environment variables.
