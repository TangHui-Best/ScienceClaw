---
id: F026
doc_kind: feature
status: complete
created: 2026-07-17
updated: 2026-07-18
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
- Open questions: 本 Feature 的首个 E2E 纵向切片已完成；完整 DataAsset、分页循环、Outcome Contract、阶段二执行器和通知模型继续作为后续 Feature，不从本次完成结论外推。

## Capability Contract

- 新生产代码位于 `RpaClaw/backend/rpa_agent/`，并可自动证明未导入旧 `backend.rpa` 领域模型或 Compiler。
- CoreTrace 是新 Compiler 的唯一动作时间线；TraceCandidate、BrowserFact、SettlementResult 只存在于创建态。
- 人工录制和 Browser-use 通道操作同一 BrowserContext/Page，并共享变量与 DataAsset 上下文。
- Browser-use 的每个实际浏览器动作可独立形成 TraceCandidate，并与浏览器事实结算；不把整轮 History 压成一条 CoreTrace。
- 页面中的业务可读步骤是 CoreTrace 的投影；下载等副作用可独立展示，但不伪造成第二个动作 Trace。
- 自动化测试默认离线运行，不得因本地模型配置而真实调用 LLM。
- 旧录制核心只在新链路达到能力覆盖、回放、数据与依赖退出门槛后删除或归档。
- 首个产品验收以“系统 A 复杂查询与取值 -> 新标签页 -> 系统 B iframe 填写”为闭环；同一 Skill 必须通过两组字段值和目标行位置不同的数据。
- 新 Compiler 不兼容旧 Trace、旧 Compiler、旧 Skill 产物或旧运行参数协议；ScienceClaw 只提供宿主与已验证底层机制。
- 新 Skill 采用 `RunContext`、逻辑 PageRef、稳定 FramePath、显式 Effect 和业务变量引用，并生成可读 Playwright 浏览器段。

## Decision Context

### Why

复用宿主可以降低浏览器、UI、认证和存储建设成本；新建领域目录可以避免旧 `RPAAcceptedTrace` 和 Compiler 的兼容负担。两者结合，是当前范围内成本最低且长期边界最清楚的路线。

### Why Not

不原地修改旧核心，因为旧对象已跨越采集、事实、诊断、编译和 UI 职责；不完全新建项目，因为平台能力不是当前需要重新验证的产品假设；不双写，因为它增加一致性成本且没有直接用户价值。

### If Modifying This Area, Check

- [ADR-006](../decisions/ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md)
- [宿主重构设计基线](../superpowers/specs/2026-07-17-rpa-agent-scienceclaw-host-rebuild-design.md)
- [CoreTrace 到 SKILL 编译链路设计基线](../superpowers/specs/2026-07-17-RPA-Agent-CoreTrace到SKILL编译链路设计基线.md)
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
- [x] 业务变量绑定、录制态会话上下文和 CoreTrace `data_binding` 最小契约已确认。
- [x] Skill 外部输入参数与运行时命名空间的最小契约已确认。
- [x] Page Registry、Frame Scope、新 Page Effect 和变量引用的编译契约已确认。
- [x] CoreTrace -> Playwright 浏览器段 -> Skill 的产物链路已确认。
- [x] eval-app 可重置两组测试数据，并提供随机任务 URL、iframe 表单和不可见 Oracle。
- [x] `RpaClaw/backend/rpa_agent/` 随首个纵向切片建立，且自动化护栏禁止导入旧领域模型和 Compiler。
- [x] Route 和新链路离线回归不会因本地 Browser-use 配置意外调用真实 LLM。
- [x] 创建态可解释展示人工动作、Browser-use 多 Action、新标签页 Effect、iframe Scope 和变量绑定。
- [x] 同一个生成 Skill 在 Replay A 与 Replay B 中均通过编译产物检查和后端 Oracle。
- [x] 本增量未提前扩展 DataAsset、下载与分页提取场景；后续能力保持独立验收边界。

## Current Status

Complete。独立 `backend/rpa_agent` 已实现创建态双通道、Settlement、Build Readiness、CoreTrace Timeline、录制后配置、确定性 Compiler、四文件 Publisher、默认 ScienceClaw CDP 宿主与首个 Runtime。真实 Live E2E 从人工 Playwright 事件及 `browser_use.Agent.run`/Tools 开始，形成 22 条 accepted CoreTrace，仅编译一次；同一 SKILL 的 Replay A/B 各 22/22 步成功并通过隐藏后端 Oracle。完整结果见 EV-029。

## Links

### Evidence

- [EV-025 Browser-use Live UI E2E](../evidence/EV-025-browser-use-live-ui-e2e.md)（历史技术穿刺证据）
- [EV-026 Browser-use 真实业务矩阵 Live UI E2E](../evidence/EV-026-browser-use-live-ui-business-matrix.md)（历史技术穿刺证据）
- [EV-027 CoreTrace 到 SKILL 编译链路设计基线验证](../evidence/EV-027-coretrace-skill-compiler-design-baseline.md)（只证明设计规格已确认，不证明实现或回放）
- [EV-028 首个 E2E CoreTrace 到 Playwright SKILL Golden Sample 验证](../evidence/EV-028-first-e2e-coretrace-to-playwright-skill-golden-sample.md)（只证明样例静态自洽，不证明动态回放）
- [EV-029 新版 RPA Agent 首个阶段一纵向 Live E2E](../evidence/EV-029-rpa-agent-first-stage-one-live-e2e.md)（本 Feature 完成证据）

### Decisions / ADRs

- [ADR-006 在 ScienceClaw 宿主内绿地重建 RPA Agent 领域核心](../decisions/ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md)
- [ADR-001 RPA Trace Is The Single Accepted Timeline](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md)
- [ADR-002 Trace Evidence Drives Compiler Strategy](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md)
- [ADR-004 RPA Core Owns Recording Facts, Harness Adapts Only](../decisions/ADR-004-rpa-core-owns-recording-facts-harness-adapts-only.md)

### Lessons

- None. 当前结论来自已确认设计和技术穿刺分析；实现后若出现可复用失败模式，再建立 Lesson。

### Specs / Plans

- [RPA Agent 基于 ScienceClaw 宿主重构设计基线](../superpowers/specs/2026-07-17-rpa-agent-scienceclaw-host-rebuild-design.md)
- [F026.1 新版 RPA Agent 本地 CDP 宿主修复设计](../superpowers/specs/2026-07-19-rpa-agent-local-cdp-host-fix-design.md)
- [首个阶段一 E2E 验收场景设计基线](../superpowers/specs/2026-07-17-RPA-Agent首个阶段一E2E验收场景设计基线.md)
- [业务变量绑定与录制态上下文设计基线](../superpowers/specs/2026-07-17-RPA-Agent业务变量绑定与录制态上下文设计基线.md)
- [CoreTrace 到 SKILL 编译链路设计基线](../superpowers/specs/2026-07-17-RPA-Agent-CoreTrace到SKILL编译链路设计基线.md)
- [首个 E2E：CoreTrace 到 Playwright SKILL 完整示例](../superpowers/specs/examples/first-e2e-coretrace-to-playwright-skill/README.md)
- [已失效：宿主重构基线实施计划](../superpowers/plans/2026-07-17-rpa-agent-host-rebuild-baseline.md)

### Related Features

- [F025 Browser-use Recording Operator POC](F025-browser-use-recording-operator-poc.md)（历史技术穿刺，不是新链路实现基线）

### External Context

- 已确认的外部设计工作区：`E:\RPA-Agent\docs\design`。首个 E2E 与业务变量基线的仓库内副本已建立；对应变量契约验证记录为 `E:\RPA-Agent\docs\evidence\EV-004-business-variable-binding-v0.1-contract-validation.md`。后续实现必须链接仓库内规格，不得只依赖对话历史。

## Acceptance Map

| Claim | Acceptance | Evidence | Status |
| --- | --- | --- | --- |
| 首个业务验收锚点稳定 | 场景、非目标、两组 fixtures、硬编码防护和 Oracle 有明确规格 | 首个阶段一 E2E 验收场景设计基线 | pass |
| 新领域与旧核心隔离 | 首个纵向切片中的新代码通过架构测试阻止旧领域 import | EV-029、473 项新领域/契约回归 | pass |
| 离线验证不依赖真实 LLM | 强制 Browser-use 配置时离线单测仍由替身执行 | EV-029、Route/Host 测试 | pass |
| CoreTrace 可形成可回放 Skill | 同一 Skill 完成 Replay A、Replay B 和后端 Oracle | EV-029 | pass |
| 业务变量契约稳定 | 变量使用业务语义引用，创建态值与 CoreTrace 引用、运行态值分离 | 业务变量绑定与录制态上下文设计基线 | pass |
| CoreTrace 编译契约稳定 | Compiler 只消费 CoreTrace，RunContext、Page/Frame/Effect、Action Matrix、失败规则和 Skill 产物有明确规格 | EV-027、CoreTrace 到 SKILL 编译链路设计基线 | pass |
| 首个 E2E 编译目标可检查 | Skill Definition、24 条 CoreTrace、双 Replay Input 与四文件 SKILL 构成静态自洽 Golden Sample | EV-028、首个 E2E 完整示例 | pass |
| 双通道共享浏览器和变量 | 人工动作与 Browser-use 多 Action 进入同一 Settlement/CoreTrace，并使用 `purchase_order.*` | EV-029 | pass |

## State Timeline

| Date | State | Trigger | Evidence | Note |
| --- | --- | --- | --- | --- |
| 2026-07-17 | active | 用户确认宿主重构设计并授权下一步 | ADR-006、宿主重构设计基线 | 进入增量 0，尚未开始业务实现 |
| 2026-07-17 | active / acceptance revised | 用户指出工程底座先行缺少业务验收锚点 | 首个阶段一 E2E 验收场景设计基线 | 停止执行旧增量 0，改为场景反推契约与纵向实现 |
| 2026-07-17 | active / variable contract accepted | 用户确认业务语义变量、会话级 Store、双通道来源与运行态隔离原则 | 业务变量绑定与录制态上下文设计基线 | 共享变量不再是未决项，进入编译契约设计 |
| 2026-07-17 | active / compiler contract accepted | 用户确认非兼容新链路、RunContext、Page/Frame/Effect、Action Matrix、校验失败规则和 Skill 产物边界 | CoreTrace 到 SKILL 编译链路设计基线 | 编译规格不再是未决项，后续 Goal 可进入首个纵向切片实现 |
| 2026-07-17 | active / golden sample added | 用户要求用首个 E2E 串出完整 CoreTrace 到 Playwright SKILL 示例 | EV-028、首个 E2E 完整示例 | 形成静态目标样例；动态实现和双用例回放仍待完成 |
| 2026-07-18 | complete | 两次连续真实创建、编译、Replay A/B 与隐藏 Oracle 全部通过 | EV-029 | 首个阶段一纵向切片完成；后续能力不并入本 Feature |

## Patch History

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F026.1 | 2026-07-19 | pending | Windows 本地模式点击录制时，新版会话返回 503 | 新版 Provider 未按 `STORAGE_BACKEND=local` 分流，把 CDP 宿主错误解析为 `http://sandbox:8080` | 中立 Local CDP 宿主层、local/非 local 模式回归和真实本地冒烟验收 | design accepted / implementation pending |

## Recovery Snapshot

- Read first: ADR-006，然后阅读本 Feature、首个阶段一 E2E 验收场景、业务变量绑定与录制态上下文设计基线、CoreTrace 到 SKILL 编译规格和首个 E2E Golden Sample。
- Current capability state: 新 `backend/rpa_agent` 纵向链路已实现；默认宿主、Compiler、Runtime、录制 UI、eval fixture 和同一 SKILL 双 Replay 均有验证证据。
- Known risks: scripted model 证明的是 Browser-use Agent/Tools 集成而非外部 LLM 语义质量；完整 DataAsset、分页循环及运行期自愈不在本 Feature；F026.1 正在补齐 `STORAGE_BACKEND=local` 的真实产品启动覆盖；eval-app 仍有 EV-029 记录的两个非阻断 P2。
- Next safe action: 按 F026.1 设计以 TDD 修复本地 CDP 宿主分流并形成独立 Evidence；其他后续需求仍须新建业务验收增量，不应在 F026 上堆叠完整 DataAsset、阶段二或兼容层。
- Recovery evidence: 先阅读 EV-029；原始 Live JSON 与生成四文件产物位于其 Artifacts 所列 `.tmp/task13-agent-live-evidence*` 目录。

## Evidence

- EV-025 与 EV-026 只证明旧 ScienceClaw 技术穿刺路线可行，并暴露整轮 History 压缩、运行时 LLM 回放和测试配置泄漏等风险。
- EV-027 只证明 CoreTrace 到 SKILL 的设计规格已经确认并可恢复，不证明新 Compiler、Runtime 或生成 Skill 已经实现。
- EV-028 只证明首个 E2E Golden Sample 的 Schema、基础语义、语法、来源摘要和硬编码扫描通过，不证明它已经可执行。
- EV-029 证明新链路已从实际人工事件与 Browser-use Agent/Tools 形成 CoreTrace，并以同一编译产物完成双用例回放和后端 Oracle；它不扩展证明非目标能力。

## Next Step

关闭 F026。后续若进入下载/DataAsset、阶段二处理、通知或运行期修复，应以新的业务场景、Harness 和 Feature 单独立项；继续禁止为了复用旧代码增加 Trace/Compiler/Skill 兼容层。
