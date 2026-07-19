---
id: F026
doc_kind: feature
status: complete
created: 2026-07-17
updated: 2026-07-19
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

### F026.3 ScienceClaw 录制 UI 回归验收

- [x] Recorder 保留原 ScienceClaw 的流程导航、左侧步骤时间线、中部浏览器工作区和右侧 AI 录制助手，不以新版领域模型重写主要交互。
- [x] 自然语言输入保留模型选择、运行状态和对话反馈，并通过新版 `/rpa-agent` 会话调用真实 browser-use。
- [x] 停止录制后的 Configure 保留原双栏工作流：左侧复核录制步骤，右侧填写 Skill 信息并渐进配置输入、Secret、输出和 DataAsset。
- [x] 新版 Candidate/CoreTrace/Effect 仅作为既有步骤组件的 ViewModel 投影，不把内部技术概念作为页面主文案。
- [x] 本地非 Docker 启动前后端后，以真实 LLM 完成 GitHub Trending 的“打开和 skill 最相关的项目”与“获取 star 数”，并成功停止录制、配置、编译、回放和保存 Skill。

### F026.4 录制会话浏览器生命周期隔离

- [x] 每个新录制会话都创建独立、全新的 Playwright BrowserContext 与 Page，不复用上一个已退出或已停止录制会话的 Context、Page 或页面状态；底层 Chromium 进程可以作为中立宿主共享，但不能成为会话状态边界。
- [x] “退出录制”“停止录制后重新录制”和再次点击“录制技能”都会释放旧会话拥有的浏览器资源；清理完成后旧页面不能继续成为新会话的活动页面。
- [x] 跨会话回归测试必须证明浏览器资源身份不同、旧资源只清理一次，并且旧会话的 URL、Cookie、Storage 与页面历史不会进入新会话。
- [x] 使用本地非 Docker 前后端完成至少一次“退出/重新录制 -> 新会话”的真实浏览器验证。

## Current Status

Complete。独立 `backend/rpa_agent` 已实现创建态双通道、Settlement、Build Readiness、CoreTrace Timeline、录制后配置、确定性 Compiler、四文件 Publisher、默认 ScienceClaw CDP 宿主与首个 Runtime。真实 Live E2E 从人工 Playwright 事件及 `browser_use.Agent.run`/Tools 开始，形成 22 条 accepted CoreTrace，仅编译一次；同一 SKILL 的 Replay A/B 各 22/22 步成功并通过隐藏后端 Oracle。F026.3/F026.4 已恢复 ScienceClaw 录制 UI，并以 EV-031/EV-032 验证真实模型闭环与录制会话 BrowserContext/Page 隔离。

## Links

### Evidence

- [EV-025 Browser-use Live UI E2E](../evidence/EV-025-browser-use-live-ui-e2e.md)（历史技术穿刺证据）
- [EV-026 Browser-use 真实业务矩阵 Live UI E2E](../evidence/EV-026-browser-use-live-ui-business-matrix.md)（历史技术穿刺证据）
- [EV-027 CoreTrace 到 SKILL 编译链路设计基线验证](../evidence/EV-027-coretrace-skill-compiler-design-baseline.md)（只证明设计规格已确认，不证明实现或回放）
- [EV-028 首个 E2E CoreTrace 到 Playwright SKILL Golden Sample 验证](../evidence/EV-028-first-e2e-coretrace-to-playwright-skill-golden-sample.md)（只证明样例静态自洽，不证明动态回放）
- [EV-029 新版 RPA Agent 首个阶段一纵向 Live E2E](../evidence/EV-029-rpa-agent-first-stage-one-live-e2e.md)（本 Feature 完成证据）
- [EV-030 新版 RPA Agent 本地 CDP 宿主修复](../evidence/EV-030-rpa-agent-local-cdp-host-fix.md)（F026.1 修复与真实本地浏览器证据）
- [EV-031 新版 RPA Agent ScienceClaw 录制 UI 与真实 Live E2E](../evidence/EV-031-rpa-agent-scienceclaw-ui-live-e2e.md)（F026.3 UI 回归、真实模型、编译回放与保存证据）
- [EV-032 RPA 录制会话浏览器隔离](../evidence/EV-032-rpa-recording-session-browser-isolation.md)（F026.4 新 Context、停止/退出释放与本地连续会话证据）

### Decisions / ADRs

- [ADR-006 在 ScienceClaw 宿主内绿地重建 RPA Agent 领域核心](../decisions/ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md)
- [ADR-001 RPA Trace Is The Single Accepted Timeline](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md)
- [ADR-002 Trace Evidence Drives Compiler Strategy](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md)
- [ADR-004 RPA Core Owns Recording Facts, Harness Adapts Only](../decisions/ADR-004-rpa-core-owns-recording-facts-harness-adapts-only.md)

### Lessons

- [LL-003 RPA 宿主 UI 被最小联调页替换时必须用产品契约与 Live E2E 保护](../lessons/LL-003-rpa-host-ui-regression-contract-e2e.md)

### Specs / Plans

- [RPA Agent 基于 ScienceClaw 宿主重构设计基线](../superpowers/specs/2026-07-17-rpa-agent-scienceclaw-host-rebuild-design.md)
- [F026.1 新版 RPA Agent 本地 CDP 宿主修复设计](../superpowers/specs/2026-07-19-rpa-agent-local-cdp-host-fix-design.md)
- [F026.1 新版 RPA Agent 本地 CDP 宿主修复实施计划](../superpowers/plans/2026-07-19-rpa-agent-local-cdp-host-fix.md)
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
| Windows local 模式可启动新版录制会话 | 默认 Provider 不访问 SessionRuntimeManager，真实本地 Chromium/CDP 路由返回 201 并完成 Registry/cleanup | EV-030 | pass |
| ScienceClaw 录制交互保持连续且真实模型闭环可用 | 原三栏 Recorder、双栏 Configure、真实 Qwen/browser-use、四文件编译、回放与保存全部可验证 | EV-031 | pass |
| 不同录制会话之间浏览器状态隔离 | 每次录制独占新 BrowserContext/Page；退出、停止与重新录制释放旧资源；真实连续会话不继承旧 Cookie/页面 | EV-032 | pass |

## State Timeline

| Date | State | Trigger | Evidence | Note |
| --- | --- | --- | --- | --- |
| 2026-07-17 | active | 用户确认宿主重构设计并授权下一步 | ADR-006、宿主重构设计基线 | 进入增量 0，尚未开始业务实现 |
| 2026-07-17 | active / acceptance revised | 用户指出工程底座先行缺少业务验收锚点 | 首个阶段一 E2E 验收场景设计基线 | 停止执行旧增量 0，改为场景反推契约与纵向实现 |
| 2026-07-17 | active / variable contract accepted | 用户确认业务语义变量、会话级 Store、双通道来源与运行态隔离原则 | 业务变量绑定与录制态上下文设计基线 | 共享变量不再是未决项，进入编译契约设计 |
| 2026-07-17 | active / compiler contract accepted | 用户确认非兼容新链路、RunContext、Page/Frame/Effect、Action Matrix、校验失败规则和 Skill 产物边界 | CoreTrace 到 SKILL 编译链路设计基线 | 编译规格不再是未决项，后续 Goal 可进入首个纵向切片实现 |
| 2026-07-17 | active / golden sample added | 用户要求用首个 E2E 串出完整 CoreTrace 到 Playwright SKILL 示例 | EV-028、首个 E2E 完整示例 | 形成静态目标样例；动态实现和双用例回放仍待完成 |
| 2026-07-18 | complete | 两次连续真实创建、编译、Replay A/B 与隐藏 Oracle 全部通过 | EV-029 | 首个阶段一纵向切片完成；后续能力不并入本 Feature |
| 2026-07-19 | complete / patched | Windows local 默认配置的新版录制会话恢复 | EV-030 | F026.1 以中立 Local CDP 宿主和模式矩阵回归封堵复发 |
| 2026-07-19 | complete / patched | ScienceClaw 录制交互恢复并完成真实 GitHub Live UI 闭环 | EV-031、LL-003 | F026.3 以 UI 产品契约、服务端最终投影和真实模型 E2E 封堵复发 |
| 2026-07-19 | complete / patched | 用户验收发现退出或重新录制复用了旧 Playwright 浏览器状态 | EV-032、LL-003 | F026.4 将 BrowserContext/Page 所有权收敛到单个录制会话，并补停止/废弃释放与真实连续会话验证 |

## Patch History

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F026.1 | 2026-07-19 | `b5ee3149`, `389c4697`, `e6dc0710`, `745cc262` | Windows 本地模式点击录制时，新版会话返回 503 | 新版 Provider 未按 `STORAGE_BACKEND=local` 分流，把 CDP 宿主错误解析为 `http://sandbox:8080` | 中立 Local CDP 宿主层、local/非 local 模式回归和真实本地冒烟验收（EV-030） | verified / complete |
| F026.2 | 2026-07-19 | pending | 人工验收发现 eval-app 主侧栏无法进入系统 A | 集成期前端契约测试错误地禁止 `/system-a/orders` 导航，覆盖了最初已有的菜单入口 | 恢复“采购订单综合查询”菜单及标题映射；保留系统 B 动态入口；增加组件点击和页面契约回归 | verified / uncommitted |
| F026.3 | 2026-07-19 | pending | 用户验收发现 Recorder 与录制后 Configure 已与原 ScienceClaw 交互明显不同 | 新版纵向切片以最小 API 联调页替换了既有产品页面，测试只断言“三栏存在”和技术配置能力，未保护历史交互壳层 | 恢复既有流程导航、浏览器工作区、AI 对话和双栏配置；增加 UI 契约测试、停止投影与本地生成包保护，并执行真实 Qwen/browser-use Live UI E2E（EV-031、LL-003） | verified / uncommitted |
| F026.4 | 2026-07-19 | pending | 退出录制或从 Configure 重新录制后，新会话继续复用旧 Playwright 页面与状态 | 宿主租约默认选择首个已有 BrowserContext/Page；停止录制只解除监听且 Recorder 离开时没有废弃会话，导致资源所有权延迟到 TTL | 每次录制强制新建独占 BrowserContext/Page；停止即时释放宿主端口；退出调用废弃会话 API；以真实 Chromium Cookie 隔离和两条本地 UI 路径验证（EV-032、LL-003） | verified / uncommitted |

## Patch Churn Review

F026.1、F026.2、F026.3 与 F026.4 分别暴露宿主模式选择、eval 导航、产品 UI 和录制会话资源所有权四个边界。F026.4 与 F026.3 共享“纵向切片偏重后端/API、未完整保护 ScienceClaw 宿主产品契约”的上位原因，但不是继续增加 UI 场景分支：修复已上移到每录制会话必须独占 BrowserContext/Page 的资源不变量，并用 stop/delete 释放协议和真实连续会话封堵。现有抽象能够统一解释“退出后再次录制”和“停止后重新录制”两条失败路径，因此本轮无需新 ADR 或独立 Feature；LL-003 已补充会话生命周期保护。若后续再次出现宿主 UI 或会话生命周期验收回归，应停止继续添加 F026.n，重新评估并为“宿主产品兼容与会话所有权契约”建立独立 Feature/ADR。

## Recovery Snapshot

- Read first: ADR-006，然后阅读本 Feature、首个阶段一 E2E 验收场景、业务变量绑定与录制态上下文设计基线、CoreTrace 到 SKILL 编译规格和首个 E2E Golden Sample。
- Current capability state: 新 `backend/rpa_agent` 纵向链路已实现；默认宿主、Compiler、Runtime、录制 UI、eval fixture 和同一 SKILL 双 Replay 均有验证证据；每个录制会话独占 BrowserContext/Page，停止或退出会即时释放。
- Known risks: scripted model 证明的是 Browser-use Agent/Tools 集成而非外部 LLM 语义质量；完整 DataAsset、分页循环及运行期自愈不在本 Feature；eval-app 仍有 EV-029 记录的两个非阻断 P2；仓库既有 CoreTrace schema 锁定哈希不一致独立记录于 EV-030，未混入本修复。
- Next safe action: F026.1 已关闭；其他后续需求仍须新建业务验收增量，不应在 F026 上堆叠完整 DataAsset、阶段二或兼容层。若修改宿主模式选择，必须同时运行 local/非 local provider 回归和 opt-in local browser smoke。
- Recovery evidence: 先阅读 EV-029、EV-031 与 EV-032；原始 Live JSON 与生成四文件产物位于 EV-029/EV-031 Artifacts 所列目录，会话隔离验证命令与结果见 EV-032。

## Evidence

- EV-025 与 EV-026 只证明旧 ScienceClaw 技术穿刺路线可行，并暴露整轮 History 压缩、运行时 LLM 回放和测试配置泄漏等风险。
- EV-027 只证明 CoreTrace 到 SKILL 的设计规格已经确认并可恢复，不证明新 Compiler、Runtime 或生成 Skill 已经实现。
- EV-028 只证明首个 E2E Golden Sample 的 Schema、基础语义、语法、来源摘要和硬编码扫描通过，不证明它已经可执行。
- EV-029 证明新链路已从实际人工事件与 Browser-use Agent/Tools 形成 CoreTrace，并以同一编译产物完成双用例回放和后端 Oracle；它不扩展证明非目标能力。
- EV-030 证明 Windows local 默认配置使用中立本地 CDP 宿主启动新版录制会话，并保留非 local Session Runtime 路径；它不证明容器 runtime 的真实部署状态。
- EV-031 证明 ScienceClaw 录制 UI 在本地非 Docker 模式使用真实 Qwen/browser-use 完成 GitHub 录制、编译、回放和保存；它不证明 Docker 模式或任意网站泛化能力。
- EV-032 证明本地连续录制会话使用不同 BrowserContext/Page，停止或退出后旧页面关闭且 Cookie 不跨会话；它不证明 Docker runtime 或多进程部署拓扑。

## Next Step

关闭 F026。后续若进入下载/DataAsset、阶段二处理、通知或运行期修复，应以新的业务场景、Harness 和 Feature 单独立项；继续禁止为了复用旧代码增加 Trace/Compiler/Skill 兼容层。
