---
id: F029
doc_kind: feature
status: active
created: 2026-07-20
updated: 2026-07-20
---

# F029：Browser-use 人工/自然语言混合录制 V1

## Goal

基于已经可以运行的 `codex/rpa-browser-use-recording-runtime` 分支，交付一个 Local 模式下可真实使用的最小混合录制闭环：人工操作继续沿用现有 Trace-first 监听与 Playwright 编译链路，自然语言操作由原生 Browser-use 在同一个 `BrowserHostSession/Page` 中执行，并把用户原始指令保存为现有 `RPAAcceptedTrace` 中的一条 AI 操作，最终在 Skill 中重放为 Browser-use 指令。

本 Feature 优先解决“能否稳定录制、生成并重放”的产品问题，不在 V1 同时重构 CoreTrace、Timeline、Compiler IR、Secret/DataAsset 契约或远程 Runtime。

## Vision Anchor

- 原始请求或来源：用户确认采用渐进式路线，从可运行的 `codex/rpa-browser-use-recording-runtime` 基线迭代，而不是继续一次性落地 `codex/rpa-agent-intent-first-dual-mode` 的 F028 全量重构。
- 用户痛点或工程问题：F028 同时改动 Trace 数据模型、录制时间线、编译器、Runtime 和 UI，步幅过大，短期难以形成可运行、可验证、可回滚的产品增量；旧分支已经具备可运行基础，只存在边界和稳定性缺口。
- 期望结果：一次 Local 录制中，人工精准操作与 Browser-use 逻辑操作能够在同一页面按顺序协作；生成的 Skill 保持该顺序，人工步骤为 Playwright，自然语言步骤为用户原始 Browser-use 指令。
- 非目标或边界：V1 不重构 Trace；不把 Browser-use History 编译为 Playwright；不接入新的 SecretStore/DataAsset 模型；不开发 Docker、Kubernetes 或远程 Runtime；不重新设计 ScienceClaw UI。
- Exit Gate 对照来源：本 Feature、[ADR-008](../decisions/ADR-008-rpa-browser-use-staged-hybrid-recording.md) 与 [V1 实施规格](../superpowers/specs/2026-07-20-rpa-browser-use-hybrid-v1-implementation-design.md)。

## Feature Intake

- Original problem: 自然语言录制能力需要借助 Browser-use 提高逻辑操作成功率，但现有大规模重构路线无法短期交付。
- User pain point: 用户需要尽快在真实本地产品中交替使用人工操作和自然语言操作，并生成可重放 Skill，而不是先等待整套 Trace/Runtime 架构重写完成。
- Capability promise: 在保持旧 Trace、手工录制和 Playwright 编译链路不变的前提下，Browser-use 复用当前录制页面执行自然语言指令；每条自然语言指令只形成一个 AI Trace，并在 Skill 中按原始文本调用 Browser-use。
- Non-goals: History-to-Playwright、Trace 重构、Secret/DataAsset 新契约、远程 Runtime、UI 重构、站点特化规则。
- Acceptance source: 用户确认的 V1 验收标准、Local 真实 UI/浏览器/LLM E2E、现有手工 Trace->Playwright 回归测试、Browser-use 指令重放测试。
- Open questions: 现有 recorder 的最小暂停入口位于 manager、trace recorder 还是 route orchestration；Browser-use 异常退出时现有事件队列是否需要 drain；这些问题应由实现 Spike 和测试回答，不得预先扩大数据模型。

## Capability Contract

- 人工录制继续使用现有监听、`RPAAcceptedTrace`、配置和 `TraceSkillCompiler` 路径。
- 自然语言录制由 Browser-use 作为执行主体；ScienceClaw 只提供用户指令、当前 Page/CDP、现有普通运行结果，并观察最终结果与诊断信息。
- Browser-use 使用当前录制会话的浏览器、页面状态、登录态和 tab 状态，不得为一条指令另起独立浏览器。
- Browser-use 保留原生 Tools、Planner、History、retry 和 done；ScienceClaw 不根据 Trace 或诊断反向控制其规划和完成判定。
- 每条自然语言提交只产生一个可编译的 `AI_OPERATION` Trace；Browser-use 内部 click/input/navigation 不得被人工监听器重复登记为顶层 Trace。
- 用户原始 instruction 是 V1 自然语言步骤的唯一编译权威来源；Browser-use History 只作为诊断证据，不参与 V1 代码生成。
- Skill 中人工步骤编译为 Playwright；Browser-use Trace 始终编译为运行时 Browser-use 调用；两类步骤保持录制顺序。
- 一次录制或一次重放内部共享当前 Page；测试/正式重放必须创建新的浏览器会话，不复用录制会话。
- V1 只支持 Local 模式和普通非敏感 JSON 全局变量。Secret、DataAsset 新契约与安全声明延后，不得在 V1 验收中使用真实密码、Token 或敏感文件。

## Decision Context

### Why

当前产品的最短交付路径不是重建所有 RPA 数据模型，而是保留已经验证过的人工 Trace->Playwright 链路，只替换自然语言浏览器执行内核。这样既能验证 Browser-use 的实际价值，也能把失败范围收敛到会话附着、监听暂停、AI Trace 生成和运行时指令重放四个边界。

### Why Not

- 不继续在 V1 落地 F028 全量重构：它同时改变过多事实源和模块边界，失败时难以归因，回滚成本高。
- 不在 V1 编译 Browser-use History：当前首要目标是语义能力可用；动作重放会引入 locator 稳定性、动态语义冻结和重复动作风险。
- 不在 V1 接入 Secret/DataAsset 新模型：旧分支没有完成该闭环，当前没有对应验收场景，提前接入会扩大故障面。
- 不让人工监听继续记录 Browser-use 动作：这会使同一自然语言步骤同时生成 AI 指令和低层 Playwright 动作，重放时重复执行。
- 不直接基于 F028 分支回退：从大重构中逐项撤销比从已运行旧基线做窄增量更难验证。

### If Modifying This Area, Check

- 先阅读 ADR-001、ADR-002、ADR-005、ADR-008 与本 Feature 的实施规格。
- 修改 `manager.py`、`trace_recorder.py`、`trace_skill_compiler.py`、`route/rpa.py` 或 Recorder/Configure/Test UI 时，必须运行 Core SOP->Skill focused regression。
- 验证自然语言执行的所有退出路径都会恢复监听状态。
- 验证一条自然语言指令只形成一个 AI Trace，且编译结果保留用户原文。
- 不得把 Browser-use History、final result 或站点样本升级为 V1 的第二编译事实源。

## Current Status

Implementation Complete，Pending User Live UI E2E。开发分支 `codex/rpa-browser-use-hybrid-v1` 已完成 V1 最小代码增量与自动化回归：Compiler 保留原始 Browser-use instruction，录制暂停使用 execution token 隔离并发恢复，Browser-use 保留宿主浏览器并释放自身附件资源，Recorder 在 Agent 执行期间阻止人工输入。真实 Local UI/网页/LLM E2E 由用户后续执行，因此本 Feature 继续保持 `active`，尚未达到产品验收完成状态。

## Links

### Evidence

- [EV-027 Browser-use Hybrid V1 自动化验证](../evidence/EV-027-rpa-browser-use-hybrid-v1-automated.md)

### Decisions / ADRs

- [ADR-001 RPA Trace Is The Single Accepted Timeline](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md)
- [ADR-002 Trace Evidence Drives Compiler Strategy](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md)
- [ADR-005 Browser-use Recording Operator Integration Boundary](../decisions/ADR-005-browser-use-recording-operator-integration-boundary.md)
- [ADR-008 Browser-use Staged Hybrid Recording](../decisions/ADR-008-rpa-browser-use-staged-hybrid-recording.md)

### Lessons

- None.

### Specs / Plans

- [Browser-use Hybrid V1 实施规格](../superpowers/specs/2026-07-20-rpa-browser-use-hybrid-v1-implementation-design.md)

### Related Features

- [F001 RPA Trace Source Convergence](F001-rpa-trace-source-convergence.md)
- [F025 Browser-use Recording Operator POC](F025-browser-use-recording-operator-poc.md)

### External Context

- 基线分支：`codex/rpa-browser-use-recording-runtime`
- 基线提交：`3aa97568b78426b75711cff4f9f76ec765b71f99`
- 当前分支：`codex/rpa-browser-use-hybrid-v1`
- `codex/rpa-agent-intent-first-dual-mode` 中的 F028/ADR-007 仅作为被推迟的大重构背景，不是本分支 V1 的实现来源。

## Acceptance Criteria

- [ ] Local 模式真实 Recorder UI 可以先执行人工操作并生成现有手工 Trace。
- [ ] 用户提交自然语言后，Browser-use 在当前同一个 Page/CDP target 上执行，不启动独立浏览器。
- [x] Browser-use 保留原生 planner/tool/retry/done，不受 Trace/History/Settlement 控制（自动化契约通过，待 Live UI 复核）。
- [x] Browser-use 执行期间人工 Trace 入库被作用域暂停，并在成功、失败、取消与并发边界下恢复；宿主级超时由 Live UI 继续验证。
- [x] 每条成功的自然语言指令只生成一个 `AI_OPERATION` Trace，暂停期间 click/input/navigation 不进入人工 Trace。
- [x] Browser-use History 仅保存为诊断信息，V1 编译器不使用 History 生成 Playwright。
- [x] 生成 Skill 保持录制顺序：人工步骤为 Playwright，自然语言步骤为用户原始 Browser-use instruction。
- [ ] 生成 Skill 在新的 Local 浏览器会话和真实 LLM 下可以完整重放。
- [x] Browser-use 使用 `keep_alive=True` 并调用非杀宿主语义的 `stop()`；真实页面持续可操作性待 Live UI 复核。
- [x] 普通非敏感前序 `_results` 已传入后续 Browser-use；Secret/DataAsset 不进入本轮验收。
- [x] Browser-use 失败不会留下假成功的可编译 AI Trace，监听器状态仍恢复。
- [x] 现有手工录制、配置、生成、测试和保存自动化主路径无回归；真实产品主路径待 Live UI 复核。

## Acceptance Map

| Claim | Acceptance | Evidence | Status |
| --- | --- | --- | --- |
| 人工与 Browser-use 可在同一页面协作录制 | Local Live UI 交替操作通过，页面与 target 一致 | EV-027 自动化；Live UI 待用户验证 | partial |
| 自然语言只形成一个 AI Trace | Trace 摘要无重复顶层动作 | EV-027 | automated pass |
| V1 编译策略符合分期 | 生成 Skill 中人工为 Playwright、自然语言为原始指令 | EV-027 | pass |
| Skill 可以真实重放 | 新会话、真实 LLM Local E2E 通过 | Pending F029 Evidence | pending |
| 旧人工链路无回归 | Core SOP->Skill focused regression 通过 | EV-027 | automated pass |

## State Timeline

| Date | State | Trigger | Evidence | Note |
| --- | --- | --- | --- | --- |
| 2026-07-20 | active | 用户确认渐进式 V1 并授权创建分支 | 本 Feature、ADR-008、实施规格 | 从可运行旧基线开始，先完成最小混合录制闭环 |
| 2026-07-20 | active / implementation complete | V1 最小代码增量与自动化回归通过 | EV-027 | 等待用户执行 Local Live UI/真实 LLM E2E 后决定是否完成 F029 |

## Patch History

None yet.

## Evidence

自动化实现证据见 EV-027。当前可声明“V1 代码实现与自动化验证完成”，不得声明“F029 产品验收完成”，因为真实 Local UI/浏览器/LLM E2E 尚未执行。

## Recovery Snapshot

- Read first: 本 Feature、ADR-008、V1 实施规格，然后阅读 ADR-005 与 F025。
- Current capability state: V1 最小实现与自动化回归已完成；History 只作诊断，原始 instruction 编译为 Browser-use runtime 调用，人工输入与 Trace 入库在 Agent 执行期间暂停。
- Known risks: 旧工作目录包含大量未跟踪运行产物；真实 LLM 配额和真实 Browser-use/CDP 生命周期尚需 Live UI 验收；全仓 `vue-tsc` 存在与 F029 无关的既有类型错误。
- Next safe action: 用户按实施规格第 14 节执行 Local Live UI E2E，重点观察同 Page/target、人工-AI-人工交替、宿主 Page 存活和新会话 Skill 重放。
- Unblock condition: Live UI E2E 通过并形成截图、Trace 摘要、生成 Skill 片段与重放结果后，可更新 EV-027/F029 并关闭 V1；不得借验收扩大到 Secret/DataAsset、History-to-Playwright 或 Trace 重构。

## Next Step

由用户执行 Local Live UI/真实 LLM E2E；若失败，按 Browser-use 执行、Page/CDP 附着、监听暂停、Trace 生成、Compiler、Runtime 重放六个边界归因，不扩大数据模型。
