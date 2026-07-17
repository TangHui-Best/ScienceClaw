---
id: ADR-006
doc_kind: adr
status: accepted
scope: project
feature_refs:
  - docs/features/F026-rpa-agent-scienceclaw-host-rebuild.md
decision_area: rpa-agent-host-rebuild
created: 2026-07-17
updated: 2026-07-17
invalidates:
  - ADR-005
updates:
  - doc: ADR-001
    section: Decision
    reason: 新 rpa_agent 链路以 CoreTrace 作为唯一已结算时间线，上游对象均为创建态临时对象。
  - doc: ADR-002
    section: Decision
    reason: 证据先由 Settlement Engine 消费并形成 CoreTrace，Compiler 只消费已结算的 CoreTrace。
---

# ADR-006：在 ScienceClaw 宿主内绿地重建 RPA Agent 领域核心

## Context

ScienceClaw 已验证“录制 + 对话”可以共同驱动同一个浏览器，并可把自然语言执行过程沉淀为可回放 Skill。然而技术穿刺版本的旧 RPA 核心以 `RPAAcceptedTrace`、Timeline、`runtime_results` 和 `TraceSkillCompiler` 为中心，录制事实、运行输出、诊断证据和编译提示相互混合。继续在旧模型上兼容式演进，会让新 CoreTrace 反向服从旧链路，而不是服务业务人员自助把 SOP 转换为稳定 Skill 的目标。

与此同时，ScienceClaw 已具备浏览器启动与 CDP、Playwright Context、用户与模型配置、文件与 Skill 存储、Recorder UI、测试页面和工程 Harness。完全创建独立项目会重复建设这些与新领域模型无关的宿主能力。

因此需要在“复用 ScienceClaw 宿主”与“摆脱旧 RPA 领域语义”之间建立明确且可自动验证的边界。

## Decision

1. RPA Agent 继续位于 ScienceClaw 仓库，但在 `RpaClaw/backend/rpa_agent/` 建立新的领域目录和依赖方向。
2. 新链路按 `TraceCandidate / BrowserFact -> SettlementResult -> CoreTrace -> Compiler -> Skill` 组织。CoreTrace 是唯一可进入新 Compiler 的已结算动作时间线。
3. `RpaClaw/backend/rpa/` 在新链路实现期间仅作只读参考。可复用机制必须复制或重构到新边界，并以新契约测试约束；不得让新生产代码长期导入旧领域模型、旧 Manager 或旧 Compiler。
4. 不迁移、不双写、不兼容旧 `RPAAcceptedTrace`、旧 Session Timeline、旧 diagnostics、旧 generated Skill 或旧 metadata；不创建 CoreTrace 与旧 Trace 的转换器。
5. Recorder、Configure、Test UI，以及浏览器、认证、模型、文件、Skill 存储等宿主能力允许选择性复用或移植，但它们必须通过新 API 和新领域契约接入。
6. Browser-use 继续作为自然语言通道的候选执行内核，但一轮 History 必须按实际浏览器动作形成多个创建态候选，并与同一浏览器中的 BrowserFact 共同结算；Browser-use final result 不成为第二事实源。
7. 旧录制核心只在新链路通过明确的能力退出门槛后删除或归档。不得因为新目录出现就机械删除整个 `backend/rpa`，其中与 API Monitor、MCP、Harness 等非录制领域有关的能力需要单独判断。
8. Git 分支和提交历史是本次重构的回滚路径；不通过在运行时保留两套领域模型来换取回滚能力。

## Decision Boundary

### Applies To

- RPA Agent 的创建态录制、自然语言浏览器操作、事实观察、结算、CoreTrace 时间线和 Skill 编译链路。
- 新 `backend/rpa_agent` 对 ScienceClaw 宿主能力的依赖方向。
- Recorder 相关 API/UI 向新链路切换时的边界和退出门槛。
- 与新链路相关的契约测试、离线回归、依赖护栏和验证证据。

### Does Not Apply To

- ScienceClaw 中与录制核心无关的 API Monitor、MCP、通用模型管理、认证和文件平台能力。
- 旧录制数据、旧 Session、旧 Skill 的迁移或兼容。
- 阶段二数据处理的完整脚本化；第一版仍允许把自然语言处理规则固化为 Skill 中的 Agent 能力段。
- 调试工作台、全量可观测平台或永久双轨运行机制。

## Rejected Options

### 原地重构旧 `backend/rpa`

拒绝。旧领域模型已广泛渗透 Manager、Route、Compiler、UI 和 Harness。兼容式修改会迫使 CoreTrace 承担旧字段语义，并长期保留双重事实源。

### 完全创建独立项目

暂不采用。它会重复建设浏览器、UI、认证、模型配置、文件与 Skill 管理等宿主能力，不能以更小成本验证核心产品假设。

### 新旧链路双写并长期共存

拒绝。双写会引入一致性、归因、测试矩阵和维护成本，却不能提升 CoreTrace 本身的正确性。回滚由 Git 和明确切换点承担。

### 为旧数据创建转换器

拒绝。转换器会把旧 `RPAAcceptedTrace` 的混合职责带入新模型，并制造“转换成功即语义等价”的假象。

## Consequences

- 首批工作必须先建立契约、依赖护栏和离线验证，而不是批量复制旧代码。
- Recorder UI 可以较高比例复用，但后端录制核心、结算和 Compiler 预计会重构。
- 旧 POC 的成功与踩坑是设计输入和回归样例，不是新架构的权威实现。
- 新旧链路切换前会存在代码共存期，但不存在数据模型兼容承诺。
- 删除旧录制核心必须以能力覆盖、回放验证和依赖扫描结果为依据。

## Before Changing This Decision

修改本决策前必须回答：

- 新方案是否仍保持 CoreTrace 为唯一可编译时间线？
- 是否把创建态证据、运行结果或 Browser-use final result 引入了 Compiler？
- 新生产代码是否开始依赖 `backend.rpa` 的旧领域对象？
- 所谓兼容是否有明确用户价值，还是只为降低短期改造阻力？
- 回滚是否可以由 Git、Feature Flag 或明确切换点完成，而无需双写领域模型？
- 删除目标是否确属旧录制核心，而不是 `backend/rpa` 下仍被其他产品能力使用的模块？

## Evidence

- [F026 RPA Agent ScienceClaw 宿主重构](../features/F026-rpa-agent-scienceclaw-host-rebuild.md)
- [宿主重构设计基线](../superpowers/specs/2026-07-17-rpa-agent-scienceclaw-host-rebuild-design.md)
- [ADR-001 RPA Trace Is The Single Accepted Timeline](ADR-001-rpa-trace-is-single-accepted-timeline.md)
- [ADR-002 Trace Evidence Drives Compiler Strategy](ADR-002-trace-evidence-driven-compiler-strategy.md)
- [ADR-004 RPA Core Owns Recording Facts, Harness Adapts Only](ADR-004-rpa-core-owns-recording-facts-harness-adapts-only.md)
- [ADR-005 Browser-use Recording Operator Integration Boundary](ADR-005-browser-use-recording-operator-integration-boundary.md)（已被本决策替代）
