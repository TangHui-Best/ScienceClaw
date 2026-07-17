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
- Acceptance source: ADR-006、宿主重构设计基线、首个阶段一 E2E 验收场景、正式数据模型 Schema、双用例回放和后端 Oracle。
- Open questions: Skill 输入参数与共享变量最小契约、Page/Frame/Effect 编译契约、CoreTrace 到 Skill 的产物结构和首个 E2E 的分层实施计划仍需确认；DataAsset 推迟到第二个验收场景。

## Capability Contract

- 新生产代码位于 `RpaClaw/backend/rpa_agent/`，并可自动证明未导入旧 `backend.rpa` 领域模型或 Compiler。
- CoreTrace 是新 Compiler 的唯一动作时间线；TraceCandidate、BrowserFact、SettlementResult 只存在于创建态。
- 人工录制和 Browser-use 通道操作同一 BrowserContext/Page，并共享变量与 DataAsset 上下文。
- Browser-use 的每个实际浏览器动作可独立形成 TraceCandidate，并与浏览器事实结算；不把整轮 History 压成一条 CoreTrace。
- 页面中的业务可读步骤是 CoreTrace 的投影；下载等副作用可独立展示，但不伪造成第二个动作 Trace。
- 自动化测试默认离线运行，不得因本地模型配置而真实调用 LLM。
- 旧录制核心只在新链路达到能力覆盖、回放、数据与依赖退出门槛后删除或归档。
- 首个产品验收以“系统 A 复杂查询与取值 -> 新标签页 -> 系统 B iframe 填写”为闭环；同一 Skill 必须通过两组字段值和目标行位置不同的数据。

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

### 增量 1：首个阶段一 E2E

以已确认的跨系统采购订单验收登记场景为唯一产品验收锚点，先设计共享变量与编译契约，再按可归因层次实现 eval fixture、人工通道、Browser-use 多 Action、结算、CoreTrace、编译、回放和后端 Oracle。新目录、离线测试隔离和旧领域依赖护栏作为该纵向切片的工程前置一起交付，不再作为脱离业务场景的独立增量。

### 增量 2：下载/分页提取与 DataAsset

首个 E2E 通过后，定义第二个验收场景和 DataAsset v0.1，覆盖浏览器下载文件与分页提取表格数据。

### 后续增量

再连接阶段二自然语言数据处理、结果文件写入和可选通知配置。每个增量都先固定业务场景、fixtures 和 Oracle。

## Acceptance Criteria

- [x] 用户确认在 ScienceClaw 宿主内新建 `backend/rpa_agent`，旧 `backend/rpa` 仅作只读参考。
- [x] 已创建隔离分支与独立 worktree，未修改原 ScienceClaw 工作目录中的本地数据。
- [x] 首个阶段一 E2E 场景、非目标、两组 fixtures、硬编码防护和后端 Oracle 已确认。
- [ ] Skill 输入参数、共享变量和 CoreTrace `data_binding` 最小契约已确认。
- [ ] Page Registry、Frame Scope、新 Page Effect 和变量引用的编译契约已确认。
- [ ] CoreTrace -> Playwright 浏览器段 -> Skill 的产物链路已确认。
- [x] eval-app 可重置两组测试数据，并提供随机任务 URL、iframe 表单和受保护 Oracle。
- [ ] `RpaClaw/backend/rpa_agent/` 随首个纵向切片建立，且自动化护栏禁止导入旧领域模型和 Compiler。
- [ ] Route 和新链路离线回归不会因本地 Browser-use 配置意外调用真实 LLM。
- [ ] 创建态可解释展示人工动作、Browser-use 多 Action、新标签页 Effect、iframe Scope 和变量绑定。
- [ ] 同一个生成 Skill 在 Replay A 与 Replay B 中均通过编译产物检查和后端 Oracle。
- [ ] 首个 E2E 通过后，再设计 DataAsset、下载与分页提取场景。

## Current Status

In Progress。宿主重构设计、隔离分支和首个阶段一 E2E 验收场景已经确认；首个 E2E 所需的 eval-app 测评环境已经准备好。CoreTrace、录制/对话采集、编译、SKILL 生成和回放链路仍未实现，下一步仍需用该场景反推并交付这些能力。

## Links

### Evidence

- [EV-025 Browser-use Live UI E2E](../evidence/EV-025-browser-use-live-ui-e2e.md)（历史技术穿刺证据）
- [EV-026 Browser-use 真实业务矩阵 Live UI E2E](../evidence/EV-026-browser-use-live-ui-business-matrix.md)（历史技术穿刺证据）
- [EV-027 首个 RPA Agent 浏览器 E2E 的 eval-app 测评环境](../evidence/EV-027-rpa-eval-app-first-browser-e2e-environment.md)

### Decisions / ADRs

- [ADR-006 在 ScienceClaw 宿主内绿地重建 RPA Agent 领域核心](../decisions/ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md)
- [ADR-001 RPA Trace Is The Single Accepted Timeline](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md)
- [ADR-002 Trace Evidence Drives Compiler Strategy](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md)
- [ADR-004 RPA Core Owns Recording Facts, Harness Adapts Only](../decisions/ADR-004-rpa-core-owns-recording-facts-harness-adapts-only.md)

### Lessons

- None. 当前结论来自已确认设计和技术穿刺分析；实现后若出现可复用失败模式，再建立 Lesson。

### Specs / Plans

- [RPA Agent 基于 ScienceClaw 宿主重构设计基线](../superpowers/specs/2026-07-17-rpa-agent-scienceclaw-host-rebuild-design.md)
- [首个阶段一 E2E 验收场景设计基线](../superpowers/specs/2026-07-17-RPA-Agent首个阶段一E2E验收场景设计基线.md)
- [已失效：宿主重构基线实施计划](../superpowers/plans/2026-07-17-rpa-agent-host-rebuild-baseline.md)

### Related Features

- [F025 Browser-use Recording Operator POC](F025-browser-use-recording-operator-poc.md)（历史技术穿刺，不是新链路实现基线）

### External Context

- 已确认的外部设计工作区：`E:\RPA-Agent\docs\design`。首个 E2E 的仓库内副本已建立；后续实现必须链接仓库内规格，不得只依赖对话历史。

## Acceptance Map

| Claim | Acceptance | Evidence | Status |
| --- | --- | --- | --- |
| 首个业务验收锚点稳定 | 场景、非目标、两组 fixtures、硬编码防护和 Oracle 有明确规格 | 首个阶段一 E2E 验收场景设计基线 | pass |
| eval-app 测评环境可用 | 两套 Profile、后端过滤、随机任务 URL、多 iframe、真实保存和受保护 Oracle 可独立验证 | EV-027 | pass |
| 新领域与旧核心隔离 | 首个纵向切片中的新代码通过架构测试阻止旧领域 import | 待生成 Evidence | pending |
| 离线验证不依赖真实 LLM | 强制 Browser-use 配置时离线单测仍由替身执行 | 待生成 Evidence | pending |
| CoreTrace 可形成可回放 Skill | 同一 Skill 完成 Replay A、Replay B 和后端 Oracle | 待生成 E2E Evidence | pending |
| 双通道共享浏览器和变量 | 人工动作与 Browser-use 多 Action 进入同一 Settlement/CoreTrace，并使用 `source_order.*` | 待生成 E2E Evidence | pending |

## State Timeline

| Date | State | Trigger | Evidence | Note |
| --- | --- | --- | --- | --- |
| 2026-07-17 | active | 用户确认宿主重构设计并授权下一步 | ADR-006、宿主重构设计基线 | 进入增量 0，尚未开始业务实现 |
| 2026-07-17 | active / acceptance revised | 用户指出工程底座先行缺少业务验收锚点 | 首个阶段一 E2E 验收场景设计基线 | 停止执行旧增量 0，改为场景反推契约与纵向实现 |
| 2026-07-17 | active / eval environment ready | 完成首个 E2E 的 eval-app 独立测评底座 | EV-027 | 只证明测评环境就绪，不证明完整 RPA Agent E2E 通过 |

## Patch History

None yet.

## Recovery Snapshot

- Read first: ADR-006，然后阅读本 Feature、首个阶段一 E2E 验收场景和宿主重构设计基线。
- Current capability state: eval-app 已提供两套 Profile、系统 A/B 页面、随机任务 URL、真实保存和受保护 Oracle；新 `backend/rpa_agent` 尚未创建。
- Known risks: 共享变量和 `data_binding` 尚未从场景反推；Page/Frame/Effect 编译契约和 Skill 产物结构尚未确认；完整 E2E 仍缺少录制、编译和回放链路。
- Next safe action: 以 `rpa-eval-app/evals/contracts/rpa_agent_first_browser_e2e.yaml` 为输入，设计 Skill 参数、共享变量和 CoreTrace 编译链路。
- Unblock condition: 上述契约通过用户评审后，再实现首个 RPA Agent 纵向切片；eval-app 不再是阻塞项。

## Evidence

- EV-025 与 EV-026 只证明旧 ScienceClaw 技术穿刺路线可行，并暴露整轮 History 压缩、运行时 LLM 回放和测试配置泄漏等风险。
- 当前新增材料只证明验收边界已明确，不证明 CoreTrace 新链路已经实现；首个产品能力 Evidence 必须来自双用例 E2E 回放和后端 Oracle。
- EV-027 证明 eval-app 测评环境可独立运行和断言，但不证明完整 RPA Agent E2E 已通过。

## Next Step

先基于首个 E2E 设计 Skill 输入参数、共享变量和 CoreTrace 编译链路。旧 `2026-07-17-rpa-agent-host-rebuild-baseline.md` 已失效，不得执行；新的实施计划只能在场景相关契约和 eval-app 测评设计确认后创建。
