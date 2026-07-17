---
id: F026
doc_kind: feature
status: active
created: 2026-07-17
updated: 2026-07-17
---

# F026：RPA Agent 基于 ScienceClaw 宿主重构

## Goal

在保留 ScienceClaw 宿主和浏览器基础设施价值的前提下，建立不依赖旧 RPA 领域模型的新 `backend/rpa_agent` 核心，使业务人员可通过“录制 + 对话”把浏览器 SOP 沉淀为以 CoreTrace 为唯一中间表示的可回放 Skill。

## Vision Anchor

- 原始问题：精确浏览器操作难以完全用自然语言表达；纯 Agent 执行 Token 成本高、稳定性不足；传统 RPA 又要求 IT 人员理解业务、写脚本和维护。
- 用户痛点：最懂 SOP 的业务人员无法低门槛、自助地把操作过程转成可验证、可重复执行的 Skill。
- 能力承诺：直接操作由事件录制通道采集，逻辑操作由自然语言通道驱动 Browser-use；两条通道共享浏览器与变量上下文，并统一结算为动作级 CoreTrace，再编译为 Playwright 脚本和必要的 LLM Call。
- 非目标：不兼容旧 RPA Trace/Session/Skill；不在第一批工作中实现完整阶段二脚本化；不建设调试工作台；不长期双轨运行。
- 验收来源：已确认的宿主重构设计、CoreTrace 与上游模型规格、离线契约测试、可控浏览器场景回放和用户业务场景验收。

## Feature Intake

- Original problem: ScienceClaw 技术穿刺证明路线可行，但旧录制核心的数据职责混杂，无法作为新 RPA Agent 的长期模型与实现基线。
- User pain point: 如果继续围绕旧模型演进，业务人员看到的步骤、实际浏览器事实和最终脚本会难以保持一致，后续每次扩展都会增加兼容和推理成本。
- Capability promise: 在同一仓库内绿地建立新领域核心，先用 Harness 固定边界和可验收能力，再逐步替换旧录制链路。
- Non-goals: 不迁移旧资产，不创建转换器，不一次性删除整个 `backend/rpa`，不以代码量作为进度。
- Acceptance source: ADR-006、宿主重构设计基线、正式数据模型 Schema 与测试向量、增量证据。
- Open questions: DataAsset 的最小 v0.1 契约及第一个纵向业务切片将在增量 0 通过后单独设计和确认。

## Capability Contract

- 新生产代码位于 `RpaClaw/backend/rpa_agent/`，并可自动证明未导入旧 `backend.rpa` 领域模型或 Compiler。
- CoreTrace 是新 Compiler 的唯一动作时间线；TraceCandidate、BrowserFact、SettlementResult 只存在于创建态。
- 人工录制和 Browser-use 通道操作同一 BrowserContext/Page，并共享变量与 DataAsset 上下文。
- Browser-use 的每个实际浏览器动作可独立形成 TraceCandidate，并与浏览器事实结算；不把整轮 History 压成一条 CoreTrace。
- 页面中的业务可读步骤是 CoreTrace 的投影；下载等副作用可独立展示，但不伪造成第二个动作 Trace。
- 自动化测试默认离线运行，不得因本地模型配置而真实调用 LLM。
- 旧录制核心只在新链路达到能力覆盖、回放、数据与依赖退出门槛后删除或归档。

## Decision Context

### Why

复用宿主可以降低浏览器、UI、认证和存储建设成本；新建领域目录可以避免旧 `RPAAcceptedTrace` 和 Compiler 的兼容负担。两者结合，是当前范围内成本最低且长期边界最清楚的路线。

### Why Not

不原地修改旧核心，因为旧对象已跨越采集、事实、诊断、编译和 UI 职责；不完全新建项目，因为平台能力不是当前需要重新验证的产品假设；不双写，因为它增加一致性成本且没有直接用户价值。

### If Modifying This Area, Check

- [ADR-006](../decisions/ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md)
- [宿主重构设计基线](../superpowers/specs/2026-07-17-rpa-agent-scienceclaw-host-rebuild-design.md)
- 新代码是否绕过 Settlement Engine 直接创建 CoreTrace。
- Compiler 是否读取了 CoreTrace 之外的 BrowserFact、Evidence 或 Browser-use History。
- 测试是否会在未显式标记为 live E2E 时访问真实模型或业务系统。

## Delivery Increments

### 增量 0：宿主重构基线

建立隔离分支、ADR/Feature/规格入口、正式契约的仓库副本、`backend/rpa_agent` 最小包、旧领域依赖护栏、离线测试隔离和可重复基线命令。该增量不实现 CoreTrace 业务逻辑。

### 增量 1：首个动作纵向切片

从一个可控页面的单一人工动作开始，贯通 TraceCandidate、BrowserFact、SettlementResult、CoreTrace、步骤投影、Compiler 与 Playwright 回放。

### 后续增量

按可验证能力依次扩展自然语言通道、下载/弹窗/多页/iframe、副作用与 DataAsset，随后连接阶段二自然语言数据处理和可选通知配置。每个增量单独定义验收矩阵。

## Acceptance Criteria

- [x] 用户确认在 ScienceClaw 宿主内新建 `backend/rpa_agent`，旧 `backend/rpa` 仅作只读参考。
- [x] 已创建隔离分支与独立 worktree，未修改原 ScienceClaw 工作目录中的本地数据。
- [ ] ADR-006、Feature、设计规格和实施计划通过仓库知识校验。
- [ ] 已确认的数据模型文档、JSON Schema 和契约测试向量进入 ScienceClaw 仓库，外部设计目录不再是执行计划的隐式依赖。
- [ ] `RpaClaw/backend/rpa_agent/` 最小领域包存在，并有自动化依赖护栏禁止导入旧领域模型和 Compiler。
- [ ] Route 离线回归不受 `RPA_RECORDING_OPERATOR` 等本地配置影响，不会意外调用真实 LLM。
- [ ] 增量 0 的验证命令、结果和未覆盖范围记录为 Evidence。
- [ ] 首个纵向切片可从浏览器动作形成 CoreTrace，并编译、回放和验证。
- [ ] Browser-use 多动作执行可按实际动作形成多个 CoreTrace，且与 BrowserFact 的结算关系可验证。
- [ ] 下载、弹窗、新标签页、iframe、分页提取和 DataAsset 在业务矩阵中通过回放验收。

## Current Status

In Progress。宿主重构设计和隔离分支已建立；业务实现尚未开始。下一步是执行增量 0，先建立正式契约入口、领域边界、离线测试隔离和依赖护栏。

## Links

### Evidence

- [EV-025 Browser-use Live UI E2E](../evidence/EV-025-browser-use-live-ui-e2e.md)（历史技术穿刺证据）
- [EV-026 Browser-use 真实业务矩阵 Live UI E2E](../evidence/EV-026-browser-use-live-ui-business-matrix.md)（历史技术穿刺证据）

### Decisions / ADRs

- [ADR-006 在 ScienceClaw 宿主内绿地重建 RPA Agent 领域核心](../decisions/ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md)
- [ADR-001 RPA Trace Is The Single Accepted Timeline](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md)
- [ADR-002 Trace Evidence Drives Compiler Strategy](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md)
- [ADR-004 RPA Core Owns Recording Facts, Harness Adapts Only](../decisions/ADR-004-rpa-core-owns-recording-facts-harness-adapts-only.md)

### Lessons

- None. 当前结论来自已确认设计和技术穿刺分析；实现后若出现可复用失败模式，再建立 Lesson。

### Specs / Plans

- [RPA Agent 基于 ScienceClaw 宿主重构设计基线](../superpowers/specs/2026-07-17-rpa-agent-scienceclaw-host-rebuild-design.md)
- [增量 0 实施计划](../superpowers/plans/2026-07-17-rpa-agent-host-rebuild-baseline.md)

### Related Features

- [F025 Browser-use Recording Operator POC](F025-browser-use-recording-operator-poc.md)（历史技术穿刺，不是新链路实现基线）

### External Context

- 已确认的外部设计工作区：`E:\RPA-Agent\docs\design`。增量 0 将正式契约复制进本仓库，后续执行不得隐式依赖该外部目录。

## Acceptance Map

| Claim | Acceptance | Evidence | Status |
| --- | --- | --- | --- |
| 新领域与旧核心隔离 | 新代码目录存在，架构测试阻止旧领域 import | 增量 0 待生成 Evidence | pending |
| 离线验证不依赖真实 LLM | 强制 Browser-use 配置时 Route 单测仍由替身执行 | 增量 0 待生成 Evidence | pending |
| 已确认契约可在仓库内校验 | Schema 正反例与文档链接校验通过 | 增量 0 待生成 Evidence | pending |
| CoreTrace 可形成可回放 Skill | 首个纵向切片完成采集、结算、编译和回放 | 增量 1 待生成 Evidence | pending |
| 双通道可收敛为同一时间线 | 人工录制与 Browser-use 动作通过同一 Settlement/CoreTrace 契约 | 后续纵向切片待生成 Evidence | pending |

## State Timeline

| Date | State | Trigger | Evidence | Note |
| --- | --- | --- | --- | --- |
| 2026-07-17 | active | 用户确认宿主重构设计并授权下一步 | ADR-006、宿主重构设计基线 | 进入增量 0，尚未开始业务实现 |

## Patch History

None yet.

## Recovery Snapshot

- Read first: ADR-006，然后阅读本 Feature 和宿主重构设计基线。
- Current capability state: 已有隔离 worktree 和通过的局部技术穿刺回归；新 `backend/rpa_agent` 尚未创建。
- Known risks: 旧测试受本地 Browser-use 配置影响可能真实调用 LLM；正式数据模型仍位于外部设计目录；旧 RPA 规则可能误导后续 Agent 继续维护兼容链路。
- Next safe action: 按增量 0 实施计划依次修复测试隔离、导入契约、建立依赖护栏和更新仓库入口文档。
- Unblock condition: 增量 0 的离线验证和知识校验通过并形成 Evidence 后，才进入首个 CoreTrace 纵向切片。

## Evidence

- EV-025 与 EV-026 只证明旧 ScienceClaw 技术穿刺路线可行，并暴露整轮 History 压缩、运行时 LLM 回放和测试配置泄漏等风险。
- 本 Feature 的新领域基线证据将在增量 0 完成后记录为 EV-027；当前不得声称 CoreTrace 新链路已经实现。

## Next Step

执行 `docs/superpowers/plans/2026-07-17-rpa-agent-host-rebuild-baseline.md`。完成其中离线隔离、契约导入、领域护栏和 EV-027 后，再为首个“单一人工动作 -> CoreTrace -> Playwright 回放”纵向切片单独设计实施计划。
