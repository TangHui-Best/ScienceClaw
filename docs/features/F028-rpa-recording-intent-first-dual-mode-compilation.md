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
- Open questions: 无阻塞实施的产品问题。手工步骤不自动生成 AI 语义：确定性不足时必须由用户补回退指令或重录；Agent Context/DataAsset 的 V1 byte/token/item 上限和失败行为已在权威实施规格第 6.8 节冻结。

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

In Progress / implementation pending。设计边界已由用户确认并沉淀为 ADR-007；自包含权威实施规格已完成并通过独立冷启动可实施性复核；正式开发分支 `codex/rpa-agent-intent-first-dual-mode` 已从干净基线 `b8c3aedc` 建立。产品代码、Schema、API、UI 和运行 Harness 尚未按新方案实施，不能声称能力已恢复。

## Links

### Evidence

- [EV-034 F028 实施规格冷启动可实施性审阅](../evidence/EV-034-f028-implementation-spec-cold-start-review.md)
- [EV-033 F027 录制结算与 Live UI 验证](../evidence/EV-033-rpa-recording-finalization-live-ui.md)

### Decisions / ADRs

- [ADR-007 RPA 录制采用 Action-first / Intent-first 双通道与双模式编译](../decisions/ADR-007-rpa-recording-intent-first-dual-mode-compilation.md)
- [ADR-006 在 ScienceClaw 宿主内绿地重建 RPA Agent 领域核心](../decisions/ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md)
- [ADR-002 Trace Evidence Drives Compiler Strategy](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md)

### Lessons

- [LL-003 RPA 宿主 UI 回归契约与 Live E2E](../lessons/LL-003-rpa-host-ui-regression-contract-e2e.md)
- [LL-004 录制成功文本不能替代动作结算与输出绑定](../lessons/LL-004-rpa-recording-success-text-must-not-bypass-settlement.md)

### Specs / Plans

- [RPA Agent 意图优先录制与双模式编译实施设计（权威实施规格）](../superpowers/specs/2026-07-20-rpa-agent-intent-first-dual-mode-implementation-design.md)
- [RPA Trace-first Recording Design](../superpowers/specs/2026-04-20-rpa-trace-first-recording-design.md)
- [CoreTrace 到 SKILL 编译链路设计基线](../superpowers/specs/2026-07-17-RPA-Agent-CoreTrace到SKILL编译链路设计基线.md)
- [业务变量绑定与录制态上下文设计基线](../superpowers/specs/2026-07-17-RPA-Agent业务变量绑定与录制态上下文设计基线.md)

### Related Features

- [F026 RPA Agent 基于 ScienceClaw 宿主重构](./F026-rpa-agent-scienceclaw-host-rebuild.md)
- [F027 RPA Agent 录制动作结算与输出语义闭环](./F027-rpa-agent-recording-finalization-contract.md)

### External Context

- 用户于 2026-07-19 至 2026-07-20 在本地非 Docker、真实 LLM/browser-use 场景中的复现、日志、截图和架构复盘。

## Acceptance Criteria

- [x] 手工点击、输入、选择后无需等待 Settlement 即可在左侧出现 CoreTrace 步骤。
- [x] 自然语言提交后立即出现 AIInstructionStep，并始终保留原始指令。
- [x] Browser-use 不注册录制专用工具、不限制原生 Action 数、不使用 Candidate `done` 门禁。
- [x] 旁路观察能将动作与 Download、Popup、Navigation 等 BrowserFact 关联为 CoreTrace / Effect。
- [x] Compiler 对稳定证据生成 PlaywrightSegment，对证据不足的 AI 步骤生成 AgentSegment。
- [x] 手工证据不足时生成可审查 AI 指令或要求用户确认，不静默猜测。
- [x] AI 步骤在录制和回放时读取此前全局变量，并将声明输出写回后续步骤可见的变量表。
- [x] Recorder、Configure、Test 的主要 UI 交互与旧 ScienceClaw 保持一致。
- [ ] 本地非 Docker、真实 LLM/browser-use 完成 GitHub 指令、Star 获取、Download Effect 和生成 Skill 回放验收。

## Acceptance Map

| Claim | Acceptance | Evidence | Status |
| --- | --- | --- | --- |
| 即时录制反馈 | 手工和自然语言步骤不等待 Settlement 即显示 | EV-035；UI/API 自动化 | pass |
| Browser-use 原生能力 | 相同 Page/模型/指令不受录制工具和完成门禁影响 | EV-035；真实模型执行日志与回归 | partial：最终 UI 额度阻塞 |
| 双模式编译 | Playwright 与 Agent 两类输出均可生成和运行 | EV-035；Compiler/Runtime 回归 | pass |
| 副作用闭环 | click + download 编译为 `expect_download()` | EV-035；受控自动化 | pass |
| 全局变量连续性 | 前序输出可被后续 AI 使用并继续写回 | EV-035；双步骤结构化输出回归 | pass |
| 设计边界 | ADR 覆盖原因、数据流、原则、拒绝方案和修改检查 | ADR-007 | pass |
| 实施可执行性 | 零背景工程师/Agent 能从单一规格得到模块、数据、API、迁移、回滚与验收契约 | 权威实施规格；EV-034 | pass |

## State Timeline

| Date | State | Trigger | Evidence | Note |
| --- | --- | --- | --- | --- |
| 2026-07-20 | active / design accepted | 用户确认简化链路、双模式编译、Browser-use 边界、AIInstructionStep、全局变量和副作用监听 | ADR-007；本 Feature | 实现尚未开始 |
| 2026-07-20 | active / implementation branch ready | 当前已提交历史推送后，保存 pre-F028 源码/测试/文档快照，并从 `b8c3aedc` 创建不含旧工作区产品改动的正式分支 | `backup/rpa-agent-v1-coretrace-pre-f028-20260720@d7a01010`；`codex/rpa-agent-intent-first-dual-mode` | 新分支仅携带产品愿景和架构知识，等待影响面审计与实施计划 |
| 2026-07-20 | active / implementation spec reviewed | 面向零背景 Coding Agent 补齐技术/数据架构、API/并发、会话所有权、迁移与验收；独立冷启动审阅发现并关闭 5 个 P0 | 权威实施规格；EV-034 | 规格可实施，不代表产品代码已实现 |
| 2026-07-20 | active / implementation verified, live UI blocked | 核心实现与自动化完成；全新真实 UI 重录遭模型账户余额 403 | EV-035 | 补充额度后必须从新会话重跑附件 1–15，禁止复用旧结果 |

## Patch History

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F028.1 | 2026-07-20 | pending | 实现与 Live UI 验收过程中暴露双模式分类、生产导入、运行提示、客户端超时和重跑状态缺口 | 原规格边界未被同一端到端 Harness 覆盖 | 自动化覆盖分类、导入、提示、超时与重跑；EV-035 保留真实额度阻塞和恢复步骤 | implementation verified; Live UI blocked |
| F028.2 | 2026-07-20 | pending | 真实 glm-4.7 UI 续跑暴露 OpenAI 兼容响应仅返回 `reasoning_content`，且 TestPage 未展示结构化输出 | 结构化响应适配只读取 `message.content`；UI 只显示运行状态和失败信息 | 严格 schema 前增加 `content`/`reasoning_content` 选择；测试完成后直接展示 `run_result.outputs`，不把整份结果持久化到 sessionStorage；EV-035 记录真实成功轨迹与最新欠费阻断 | automated verified; latest Live UI blocked by Arrearage |

## Evidence

- [EV-035 F028 实现验证与真实模型额度阻塞](../evidence/EV-035-f028-implementation-and-live-ui-blocker.md)

EV-034 支撑设计可实施性；EV-035 支撑核心实现、自动化和真实后台回放，但明确不支撑最终 Live UI 通过声明。当前唯一验收缺口是外部模型账户余额不足导致全新录制 403。

## Recovery Snapshot

- Implementation source of truth: `docs/superpowers/specs/2026-07-20-rpa-agent-intent-first-dual-mode-implementation-design.md`。新 Agent 应先阅读该文档，再阅读 ADR-007；不得仅依据 F028 摘要或当前代码推断方案。
- Read first: ADR-007，然后阅读本 Feature、F027、ADR-006、旧 Trace-first Recording Design。
- Development branch: `codex/rpa-agent-intent-first-dual-mode`；独立 worktree 为 `E:\RPA-Agent\.worktrees\rpa-agent-intent-first-dual-mode`。
- Recovery branch: `backup/rpa-agent-v1-coretrace-pre-f028-20260720@d7a01010` 保存 pre-F028 源码、测试、UI 修复和已否决实验；不得整分支合并回正式分支。
- Current capability state: F028 核心实现与自动化已落地；Feature 保持 `active`，因为附件要求的全新 Live UI E2E 尚未通过。
- Known risks: 外部模型余额 `$0.025578` 低于关闭视觉后的单次最小请求 `$0.037968`；后台历史成功回放不能替代 UI 验收。
- Next safe action: 补充足够覆盖至少四次真实 Agent 调用的额度，重启隔离服务，从全新 session/browser/page/generation 严格重走附件 1–15，并独立核对最终仓库和 Star。
- Next safe action: 按权威实施规格“增量 0：契约与 Harness”开工，先建立数据 contract tests、Browser-use 构造参数守卫和迁移清单，再改生产热路径。
- Unblock condition: 不需要额外产品方向确认；进入实现前只需把 ADR-007 的契约转换为可验证增量和回滚点。

## Next Step

执行权威实施规格第 13 节：先完成增量 0 的契约与 Harness，再恢复 Browser-use 原生运行和即时 RecordingTimelineItem，随后闭合 ReplayAssessment、双模式 Compiler、全局变量、副作用和本地真实 LLM E2E。不得从局部删除 `extract_variable` 或放宽 `done` 开始无 Harness 修补。
