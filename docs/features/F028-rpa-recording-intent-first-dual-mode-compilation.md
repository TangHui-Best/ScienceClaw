---
id: F028
doc_kind: feature
status: active
created: 2026-07-20
updated: 2026-07-20
---

# F028：RPA 录制意图优先与双模式编译

## Goal

在保留新版 CoreTrace 数据模型的前提下，简化“录制技能 → 生成脚本”的数据链路：恢复旧 ScienceClaw 的即时录制反馈和 Browser-use 原生能力；手工操作直接形成 CoreTrace，自然语言指令立即形成 AIInstructionStep；编译时证据充分则生成 Playwright，证据不足则保留原始意图并生成运行时 AI 指令。

## Vision Anchor

- 原始请求或来源：用户在真实本地 RPA Agent 录制中持续发现手工步骤不及时显示、Browser-use 能力被录制协议削弱、录制结果无法编译为脚本，并于 2026-07-19 至 2026-07-20 连续复盘新旧架构边界。
- 用户痛点或工程问题：当前创建态模型和结算门禁侵入录制热路径；执行成功、捕获完整与可确定性编译被错误绑定；用户体验和能力弱于旧 ScienceClaw。
- 期望结果：手工和自然语言步骤立即可见；Browser-use 原生执行；CoreTrace 忠实保存动作事实；Compiler 自动选择 Playwright 或 Runtime AI；全局变量和副作用跨步骤连续工作。
- 非目标或边界：不修改 Browser-use 上游源码；不恢复旧 RPAAcceptedTrace/TraceSkillCompiler；不迁移旧 Session/Skill；V1 不做部分 Playwright 前缀与残余 AI 自动拆分。
- Exit Gate 对照来源：ADR-007、用户给出的 GitHub Trending / Star / Download 场景、本地非 Docker 真实 LLM E2E、生成 Skill 回放结果。

## Feature Intake

- Original problem: 新版 RPA Agent 虽然改善了 CoreTrace 模型，但录制、结算和编译边界过度耦合，导致实时步骤、Browser-use 能力和脚本生成同时退化。
- User pain point: 用户不能及时确认手工操作是否录制；简单自然语言任务出现额外 Agent 轮次；证据不完整时整个 Skill 无法生成。
- Capability promise: 建立 Action-first 手工路径和 Intent-first 自然语言路径，以同一 CoreTrace 事实模型和双模式 Compiler 完成稳定回放或 AI 降级。
- Non-goals: 不建设通用 DAG、完整调试器、跨 Skill 全局变量、旧数据兼容层或站点专用规则。
- Acceptance source: ADR-007 中的设计原则、数据流和七个验收场景；旧 ScienceClaw UI 行为；真实 Browser-use 本地运行结果。
- Open questions: 手工步骤自动生成的 AI 语义描述需要达到什么证据阈值才能免用户确认；大型 DataAsset 向 Agent 暴露摘要和按需读取接口的具体上限。

## Capability Contract

- `RecordingTimelineItem` 只包含手工 CoreTrace 和 AIInstructionStep，不恢复旧多事实源。
- 手工业务动作捕获后立即投影为左侧 CoreTrace 步骤，异步 BrowserEffect 后续补充。
- 自然语言提交后立即创建 AIInstructionStep，Browser-use 内部动作只作为关联 CoreTrace 证据。
- Browser-use 只接收当前 Page、页面语义、全局变量和允许资源，不接收录制专用工具或完成门禁。
- Settlement 只评估可回放性，不控制 Browser-use 运行态和步骤是否存在。
- Compiler 以时间线项为原子，产生 PlaywrightSegment 或 AgentSegment。
- AI 步骤读取当前 SessionVariableStore/RunContext 全局变量快照，并将声明输出写回。
- Download、Popup、Navigation、Dialog 等副作用由统一旁路监听器捕获并关联为 CoreTrace Effect。
- Recorder、Configure、Test 的主要 UI 交互以旧 ScienceClaw 为准。

## Decision Context

### Why

手工操作能够从浏览器事件直接证明动作事实，自然语言操作只能先证明用户意图。用同一个“必须先结算为可回放 Candidate”的同步门禁处理两者，会让 AI 通道反向改造 Browser-use，也会让 UI 等待不可控的观察完整度。把用户意图、动作事实和执行产物分开后，系统可以在不牺牲交互和 Agent 能力的前提下继续使用清晰的 CoreTrace。

### Why Not

- 不整体回退旧 ScienceClaw：其交互和降级思想正确，但 Trace、signals、runtime_results 和 Compiler 职责混合。
- 不继续修补 F027：`extract_variable` 和 `done` 门禁的方向本身违反 Browser-use 执行主体边界。
- 不为所有动作增加 SOPStep：手工 CoreTrace 已能直接作为用户步骤，包装层没有显著收益。
- 不在证据不足时阻止编译：AgentSegment 是合法运行模式，而不是失败兜底补丁。

### If Modifying This Area, Check

- [ADR-007](../decisions/ADR-007-rpa-recording-intent-first-dual-mode-compilation.md)
- [ADR-006](../decisions/ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md)
- [ADR-002](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md)
- [F027](./F027-rpa-agent-recording-finalization-contract.md) 的被取代门禁和 Patch History。
- 必须运行手工录制即时反馈、Browser-use 原生能力、Download Effect、双模式 Compiler、全局变量和本地真实 LLM/回放验收。
- 不得为测试通过重新加入录制专用 Browser-use Action、站点关键词或旧 Trace 兼容层。

## Current Status

In Progress。设计边界已由用户确认并沉淀为 ADR-007；产品代码、Schema、API、UI 和 Harness 尚未按新方案实施，不能声称能力已恢复。

## Links

### Evidence

- [EV-033 F027 录制结算与 Live UI 验证](../evidence/EV-033-rpa-recording-finalization-live-ui.md)

### Decisions / ADRs

- [ADR-007 RPA 录制采用 Action-first / Intent-first 双通道与双模式编译](../decisions/ADR-007-rpa-recording-intent-first-dual-mode-compilation.md)
- [ADR-006 在 ScienceClaw 宿主内绿地重建 RPA Agent 领域核心](../decisions/ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md)
- [ADR-002 Trace Evidence Drives Compiler Strategy](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md)

### Lessons

- [LL-003 RPA 宿主 UI 回归契约与 Live E2E](../lessons/LL-003-rpa-host-ui-regression-contract-e2e.md)
- [LL-004 录制成功文本不能替代动作结算与输出绑定](../lessons/LL-004-rpa-recording-success-text-must-not-bypass-settlement.md)

### Specs / Plans

- [RPA Trace-first Recording Design](../superpowers/specs/2026-04-20-rpa-trace-first-recording-design.md)
- [CoreTrace 到 SKILL 编译链路设计基线](../superpowers/specs/2026-07-17-RPA-Agent-CoreTrace到SKILL编译链路设计基线.md)
- [业务变量绑定与录制态上下文设计基线](../superpowers/specs/2026-07-17-RPA-Agent业务变量绑定与录制态上下文设计基线.md)

### Related Features

- [F026 RPA Agent 基于 ScienceClaw 宿主重构](./F026-rpa-agent-scienceclaw-host-rebuild.md)
- [F027 RPA Agent 录制动作结算与输出语义闭环](./F027-rpa-agent-recording-finalization-contract.md)

### External Context

- 用户于 2026-07-19 至 2026-07-20 在本地非 Docker、真实 LLM/browser-use 场景中的复现、日志、截图和架构复盘。

## Acceptance Criteria

- [ ] 手工点击、输入、选择后无需等待 Settlement 即可在左侧出现 CoreTrace 步骤。
- [ ] 自然语言提交后立即出现 AIInstructionStep，并始终保留原始指令。
- [ ] Browser-use 不注册录制专用工具、不限制原生 Action 数、不使用 Candidate `done` 门禁。
- [ ] 旁路观察能将动作与 Download、Popup、Navigation 等 BrowserFact 关联为 CoreTrace / Effect。
- [ ] Compiler 对稳定证据生成 PlaywrightSegment，对证据不足的 AI 步骤生成 AgentSegment。
- [ ] 手工证据不足时生成可审查 AI 指令或要求用户确认，不静默猜测。
- [ ] AI 步骤在录制和回放时读取此前全局变量，并将声明输出写回后续步骤可见的变量表。
- [ ] Recorder、Configure、Test 的主要 UI 交互与旧 ScienceClaw 保持一致。
- [ ] 本地非 Docker、真实 LLM/browser-use 完成 GitHub 指令、Star 获取、Download Effect 和生成 Skill 回放验收。

## Acceptance Map

| Claim | Acceptance | Evidence | Status |
| --- | --- | --- | --- |
| 即时录制反馈 | 手工和自然语言步骤不等待 Settlement 即显示 | 待实现后的 UI/API 测试与 Live UI | pending |
| Browser-use 原生能力 | 相同 Page/模型/指令不受录制工具和完成门禁影响 | 待实现后的真实模型执行日志 | pending |
| 双模式编译 | Playwright 与 Agent 两类输出均可生成和运行 | 待实现后的 Compiler/Runtime 回归 | pending |
| 副作用闭环 | click + download 编译为 `expect_download()` | 待实现后的受控页面与 Live E2E | pending |
| 全局变量连续性 | 前序输出可被后续 AI 使用并继续写回 | 待实现后的双用例回放与 Oracle | pending |
| 设计边界 | ADR 覆盖原因、数据流、原则、拒绝方案和修改检查 | ADR-007 | pass |

## State Timeline

| Date | State | Trigger | Evidence | Note |
| --- | --- | --- | --- | --- |
| 2026-07-20 | active / design accepted | 用户确认简化链路、双模式编译、Browser-use 边界、AIInstructionStep、全局变量和副作用监听 | ADR-007；本 Feature | 实现尚未开始 |

## Patch History

None yet.

## Evidence

当前只有设计证据：用户真实复现推翻了 F027 的运行态门禁假设，ADR-007 已固定替代边界。尚无代码、自动化或 Live E2E 证据证明新能力已经实现。

## Recovery Snapshot

- Read first: ADR-007，然后阅读本 Feature、F027、ADR-006、旧 Trace-first Recording Design。
- Current capability state: 设计已接受；当前工作区仍运行 F027 风格的 Browser-use 扩展工具、`done` 门禁、Candidate/Settlement 热路径和现有 Compiler。
- Known risks: 当前 CoreTrace/Timeline 契约假设 Compiler 只消费已结算 CoreTrace；UI/API 仍按 Candidate/CoreTrace 投影；手工 AI 降级确认和大型 DataAsset 上下文上限尚需实现期冻结。
- Next safe action: 先做零基线实现计划和影响面审计，按录制时间线、Browser-use 透明观察、Settlement、Compiler/Runtime、UI/Harness 分层迁移。
- Unblock condition: 不需要额外产品方向确认；进入实现前只需把 ADR-007 的契约转换为可验证增量和回滚点。

## Next Step

基于 ADR-007 制定实施计划：先恢复 Browser-use 原生运行和即时 RecordingTimelineItem，再闭合 ReplayAssessment、双模式 Compiler、全局变量与副作用 E2E。不得从局部删除 `extract_variable` 或放宽 `done` 开始无 Harness 修补。
