---
id: F032
doc_kind: feature
status: active
created: 2026-08-02
updated: 2026-08-02
owned_paths:
  - RpaClaw/backend/rpa_agent
  - RpaClaw/backend/route/rpa_agent_next.py
trigger_terms:
  - rpa-agent-next
  - CoreTrace
  - AIInstructionStep
---

# F032：RPA Agent Next 统一交付架构

## Goal

在 `codex/rpa-agent-next` 建立下一代 RPA 的唯一交付线：人工操作以可验证的浏览器事实形成 `CoreTrace` 并确定性回放；自然语言操作以 `AIInstructionStep` 由 Browser-use 在同一宿主会话中执行；Harness、E2E、测评/观测和 AIO sandbox 同时成为可运行、可验收的分层能力。

目标不是把历史分支逐一合并，而是把其仍有价值的能力迁移到一套单一事实模型、单一运行入口和单一质量闭环中，使旧分支可在迁移验收后安全收敛。

## Vision Anchor

- 原始来源：用户确认 `codex/rpa-agent-next` 是以 F028 与 Hybrid V1 为能力输入的新架构分支，并要求将分支审计识别的五类能力统一交付。
- 用户痛点：现有分支分别承载 RPA Core、Browser-use、Harness、E2E 测评和 AIO runtime，导致事实模型、验证入口与安全边界分散，无法判定哪些分支仍是主线。
- 期望结果：一个受保护的下一代 RPA 主线，既能快速执行自然语言浏览器任务，又能形成可确定回放的人工步骤，并具备隔离运行、真实 E2E 验收、回归资产和可观测性。
- 非目标：不对存量 Skill、Trace、配置、回放产物或评测资产做兼容、读取、适配、自动迁移或跨代回放；不通过整枝 Git merge 继承旧模型；第一阶段不实现 AIInstructionStep 自动提升为 Playwright。
- Exit Gate 对照来源：本 Feature、[ADR-008](../decisions/ADR-008-rpa-agent-next-architecture-baseline.md)、真实 Local/目标 Runtime E2E、受治理 Harness 回归和新生成 Skill 的独立回放 Evidence。

## Scope

### In Scope

统一 vNext 的录制、自然语言执行、Skill 构建、隔离回放、质量资产、指标与 Bad Case 边界；并将五条历史能力线的有效能力迁入同一交付分支。

### Non-goals

不兼容、读取、转换或回放任何存量 Skill、Trace、Harness fixture、Golden Eval 或配置资产；第一阶段不把 AIInstructionStep 自动提升为 Playwright。

## Specification

### Behavior

以下 Architecture、Five Capability Lines 与 Delivery Slices 定义 vNext 的行为、分层和交付顺序。

### Rules and Constraints

RPA Core 只拥有录制事实和构建语义；Runtime Platform 只拥有隔离资源；Quality System 只能引用不可变的 vNext 产物，不得回写或伪造 CoreTrace。真实环境证据是历史来源分支删除的前提。第一阶段 AIInstructionStep 仅支持 OpenAI-compatible 的 `model`、`api_key`、可选 `base_url` 契约；其它模型协议和 Browser-use 的 CLI/MCP/provider 产品面不进入 Next 主路径。

## Architecture

### 分层与所有权

```text
用户 / Recorder UI / Configure UI / Test UI
                 │
                 ▼
RPA Core ────────────────────────────────────────────────┐
  RecordingSession · CoreTraceDraft · CoreTrace            │
  AIInstructionStep · CompileDecision · SkillBuildConfig   │
  Playwright executor · Browser-use runtime                 │
                 │                                        │
                 ▼                                        │
Runtime Platform                                            │
  RuntimeProvider · Session Sandbox · File/Secret policy   │
  BrowserHostSession / Page / CDP lifecycle                 │
                 │                                        │
                 ▼                                        │
RPA Quality System ◄── accepted facts / run events ────────┘
  Harness assets & deterministic replay
  Product E2E acceptance
  Metrics, observability and Bad Case
```

| 层 | 拥有的事实与职责 | 明确不拥有 |
| --- | --- | --- |
| RPA Core | 录制事实、时间线、编译决策、SkillBuildConfig、执行编排 | sandbox 生命周期、Harness 对事实的修补、旧资产兼容 |
| Runtime Platform | 每会话 sandbox、文件/Secret 边界、资源回收、Page/CDP 宿主接口 | CoreTrace 语义、Skill 编译策略、评测结论 |
| RPA Quality System | 资产治理、回放、E2E、指标、失败归因与 Bad Case | 生产录制事实的生成、补写或修改 |

### RPA Core 数据与执行流

1. API 会话先经 `RuntimeProvider` 获得隔离 Runtime Session/Sandbox；RPA 取得对应的 `BrowserHostSession`，并只在该会话内使用 Page/CDP 和受控资源。
2. 手动输入先创建并投影 `CoreTraceDraft`。满足浏览器事实契约后冻结为 `CoreTrace`；旁路 Playwright/CDP 观察到的 navigation、popup、download、dialog 仅在可证明因果关系时作为 `BrowserEffect` 附着。不能关联的事件保留为 orphan evidence。
3. 自然语言提交立即创建 `AIInstructionStep`，并由 Browser-use 在同一宿主 Page/CDP 中运行。其内部行动、History 与最终文本只能作诊断/关联证据，不能成为第二套顶层时间线或自动编译事实。
4. `CompileDecision(CoreTrace, SkillBuildConfig)` 是纯函数：事实足够时生成 Playwright；不足时进入人工审核。用户可编辑原意图并确认创建新的 `AIInstructionStep`，而非静默重放或原地篡改 Draft。
5. 第一阶段的 `AIInstructionStep` 始终由 Browser-use runtime 执行，不自动提升为 Playwright。执行期暂停手工录制监听并在成功、失败、取消和异常路径恢复，避免重复顶层步骤。
6. `SkillBuildConfig` 仅承载新 Skill 的名称、输入/输出、变量/资源许可、运行限制与可选 `OutcomeAssertion`。`OutcomeAssertion` 只能由用户明确声明，不得从 `BrowserEffect` 自动生成。

### Next API 边界

RPA Agent Next 的唯一公开 API 前缀为 `/api/rpa-agent-next/...`。该路由族在业务编排之前校验 `rpa-agent-next/v1` identity，并仅解析 Next 会话、Next timeline 和后续新生 Skill。旧 `/api/rpa-agent/...` 不转发、不代理、不适配，也不读取旧会话、旧请求载荷或旧资产；旧路由继续是旧产品线的独立边界。

### 资产代际边界

新运行路径只接受 vNext schema 和 namespace。下列对象一律不兼容：旧 Skill、`RPAAcceptedTrace`、旧编译配置、旧回放产物、旧 Harness fixture、Golden Eval 资产及其序列化格式。

历史资产可以保留在原分支、tag 或归档中供审计和人工重录参考；它们不得被新 API、Compiler、Runtime、Harness 或 E2E 自动读取。迁移的对象是**能力与测试意图**，不是旧数据本身。

## Five Capability Lines

| 能力线 | 历史来源 | 新主线目标模块 | 迁移方式 | 不迁移内容 |
| --- | --- | --- | --- | --- |
| Browser-use 自然语言运行时 | `rpa-browser-use-hybrid-v1` | RPA Core 的 Browser-use runtime/host adapter | 选择性迁移 Page/CDP 附着、原生 planner/tool/retry/done、监听暂停恢复、取消与资源释放、独立重放闭环 | `RPAAcceptedTrace`、旧 Timeline、旧 TraceSkillCompiler、整枝提交历史 |
| Intent-first CoreTrace 架构 | `rpa-agent-intent-first-dual-mode` 及 CoreTrace 前序分支 | RPA Core 的 recording、contracts、compiler、host | 作为代码基线，收敛为 `CoreTrace + AIInstructionStep + CompileDecision + SkillBuildConfig` | 持久化 ReplayAssessment、自动 ExpectedEffect、第一阶段 AI→Playwright 自动提升 |
| E2E/测评 | `rpa-agent-eval-app-first-e2e`、`rpa-golden-evals*` | RPA Quality System 的 product E2E、评测场景、指标与 Bad Case | 保留真实验收宿主/场景思想，建立新 vNext E2E 合约和报告 | 旧评测数据、以在线聊天成功率替代产品验收、重复 Golden 实验线 |
| AIO sandbox/runtime | `aio-native-chat-runtime` 及其前序分支 | Runtime Platform 的 RuntimeProvider、Session Sandbox、文件/资源策略 | 合入每会话隔离、provider、session 路由、workspace/file policy 等平台能力，并以接口供 RPA 使用 | RPA 自建 sandbox、把 runtime 安全逻辑写入录制/编译模块 |
| Harness 资产与回放 | `rpa-trace-first-with-harness` 及 batch 分支 | RPA Quality System 的资产治理、确定性 replay、回归报告 | 将新 Core 接受的事实生成/治理为 vNext 回放资产，建立捕获、净化、评审、回放和报告闭环 | 由 Harness 制造、补写或变更 CoreTrace；旧 batch/fixture 数据兼容 |

## Delivery Slices

进度以可验证能力增量衡量，不以分支合并数量或自然时间衡量。

1. **S0：边界与 Harness 先行**
   - 固化 vNext contracts、artifact namespace、禁止旧资产入口的架构守卫。
   - 建立最小 Harness/E2E 骨架：可生成受治理空场景、运行契约检查并报告失败归因。

2. **S1：隔离运行底座**
   - RuntimeProvider 创建和释放每会话 sandbox，实施文件/资源边界。
   - RPA 通过接口取得 Runtime Session 与 BrowserHostSession，不直接管理 sandbox。

3. **S2：录制与自然语言纵向切片**
   - 手动 Draft → CoreTrace → BrowserEffect 因果关联。
   - AIInstructionStep → Browser-use 同 Page/CDP 执行，覆盖成功、失败、取消和监听恢复。

4. **S3：构建与独立回放**
   - 实现 CompileDecision、Playwright 编译、Browser-use runtime Skill、SkillBuildConfig 和可选 OutcomeAssertion。
   - 新生成 Skill 在新的独立 Runtime Session 中回放，不能复用录制会话。

5. **S4：质量闭环与收敛依据**
   - 将录制/编译/运行事实进入 Harness 资产、真实 E2E、指标与 Bad Case。
   - 为每条历史能力线建立迁移证据与旧分支删除前提；不以“已复制代码”替代验收。

## Current Status

更新（2026-08-03）：S5 的端侧 Docker Runtime 已完成 deterministic 与真实 Docker 组合校验，并修复了 Compose 隐式网络与运行时网络配置漂移。`docker-compose-edge-runtime.yml` 是唯一会挂载 Docker socket、启用 Next Docker route 的显式 opt-in；默认仍为 `disabled` 并 fail-closed。已试验的 PyPI `browser-use` 0.13.1/0.13.3/0.13.7 与固定的上游 0.13.2 Git commit 均带有与现有依赖图冲突的全量 provider 元数据，故不能作为 Docker 供应策略。现已交付基于 0.13.2 源码的受控兼容制品 `0.13.2+sciclaw.1`，并建立 Next 专属 OpenAI-compatible 模型/宿主适配层；不因依赖冲突另起 Browser-use service。backend 容器已成功构建该制品，并完成真实 session sandbox、AIO CDP、Playwright context/page 和释放 smoke。无 LLM 资源时 Browser-use 仍不具备真实自然语言成功率验收；app-first E2E、Harness capture 持久化和全链路产品验收仍是后续工作。

更新（2026-08-02）：S4 已完成替身验证的质量闭环内核。Quality System 新增只引用 vNext `skill_artifact` identity、source hash 和输入指纹的 `HarnessAsset`，并以 `proposed → accepted` 人工审核状态机阻止未审核资产执行；每次独立回放都会形成不含原始输入的 `HarnessRunReport`，指标按成功率、时延、成本、阶段和失败类别聚合。失败只能先提议为 `BadCase`，经人工接受后才成为回归样本；`outcome_assertion_failed`、执行失败和清理失败被分开归因。真实 AIO/Playwright/Browser-use/产品 E2E 仍未具备证据，故 F032 仍为 `implementation verified / live runtime pending`，不能据此删除任何尚未补齐 live Evidence 的历史能力分支。

更新（2026-08-02）：S1 AIO native lifecycle 的代码级契约已完成并通过 mock 与回归验证。它实现了 ready-only lease、session/user ownership、释放清理与默认拒绝的文件策略；真实 AIO 环境、多实例共享 registry、BrowserHostSession/CDP 与受控文件 API 仍未验收，不能视为“每会话沙箱隔离”已交付。

更新（2026-08-02）：S2 已进入 implementation verified 阶段：新 vNext timeline/Draft 状态机、因果事实冻结关口，以及 Browser-use 同宿主执行协调器均已有 harness 覆盖。真实 Playwright 监听控制、API/UI 接入和真实 AIO + Browser-use E2E 尚未完成，因此 S2 仍为 active。

更新（2026-08-02）：S2.5 已完成替身验证的独立 `/api/rpa-agent-next/...` 会话编排入口。它将 RuntimeProvider lease、宿主浏览器、录制会话与监听门控组成受控生命周期；创建失败和关闭路径均回收资源，且旧 `/api/v1/rpa-agent/...` 不参与该入口。此状态只允许进入 S3 的代码/契约实现；真实 AIO/Browser-use/Playwright 环境证据仍是 S1/S2 的未关闭项。

更新（2026-08-02）：S3 已完成替身验证的构建与独立回放内核。`CompileDecision` 以已冻结 `CoreTrace` 为纯函数输入；`SkillBuildConfig` 独立声明新 Skill 的身份、输入/输出、运行限制、Browser-use 模型和显式 OutcomeAssertion；`CompiledSkill` 只从 Next timeline 构建，且回放必定取得 purpose=`replay` 的新 lease/new host。此状态允许进入 S4 的 harness、评测、观测与 Bad Case 闭环；它不代表真实 Playwright/AIO/Browser-use 生产 E2E 已完成。

In Progress / S0 foundation implemented。`codex/rpa-agent-next` 已从 F028 的 `6967daff` 创建，ADR-008 已确定新架构与不兼容边界；S0 的 vNext ingress guard、provider-neutral runtime port、QualityEvent 和最小 Harness/E2E 骨架已通过自动化验证。尚未接入真实 AIO sandbox、Browser-use、录制/编译/回放，也尚未开始旧分支删除。

## Links

### ADRs

- [ADR-008 RPA Agent Next 架构基线与能力迁移边界](../decisions/ADR-008-rpa-agent-next-architecture-baseline.md)
- [ADR-007 RPA 录制意图优先与双模式编译](../decisions/ADR-007-rpa-recording-intent-first-dual-mode-compilation.md)（历史输入；被 ADR-008 部分更新）
- [ADR-003 RPA Golden Evaluation Uses Scenario Assets](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- [ADR-004 RPA Core Owns Recording Facts](../decisions/ADR-004-rpa-core-owns-recording-facts-harness-adapts-only.md)

### Historical Inputs

- [分支审计材料（2026-08-02）](E:/RPA-Agent/ScienceClaw/docs/分支审计-2026-08-02.md)
- F028 code baseline: `origin/codex/rpa-agent-intent-first-dual-mode@6967daff`
- Hybrid V1 capability source: `origin/codex/rpa-browser-use-hybrid-v1@a661d10c`
- AIO capability source: `origin/codex/aio-native-chat-runtime`
- Harness capability source: `origin/codex/rpa-trace-first-with-harness`

### Lessons

- 暂无新增 Lesson；现有设计约束已由 ADR-008、S4 资产状态机与测试保护。

### Related Features

- [F028 RPA Recording Intent-first Dual-mode Compilation](F028-rpa-recording-intent-first-dual-mode-compilation.md)（历史架构输入，不是兼容目标）

### External Context

- [分支审计材料（2026-08-02）](E:/RPA-Agent/ScienceClaw/docs/分支审计-2026-08-02.md)

### Plans

- [S0 vNext 基础契约与 Harness/E2E 计划](../superpowers/plans/2026-08-02-rpa-agent-next-s0-foundation.md)
- [S1 AIO Native Runtime Platform 计划](../superpowers/plans/2026-08-02-rpa-agent-next-s1-aio-native-runtime-platform.md)
- [S2 录制与自然语言纵向切片计划](../superpowers/plans/2026-08-02-rpa-agent-next-s2-recording-and-natural-language.md)
- [S2.5 Next 会话编排与 API 隔离计划](../superpowers/plans/2026-08-02-rpa-agent-next-s2.5-session-orchestration.md)
- [S3 Next 构建与独立回放计划](../superpowers/plans/2026-08-02-rpa-agent-next-s3-build-and-independent-replay.md)
- [S4 质量闭环与收敛证据计划](../superpowers/plans/2026-08-02-rpa-agent-next-s4-quality-closure.md)
- [S5 端侧 Docker 确定性主链路与提交前收敛计划](../superpowers/plans/2026-08-02-rpa-agent-next-s5-docker-deterministic-delivery.md)

### Evidence

- [EV-038 RPA Agent Next S1 AIO Native Runtime Platform](../evidence/EV-038-rpa-agent-next-s1-aio-native-runtime.md)

- [EV-037 RPA Agent Next S0 基础契约](../evidence/EV-037-rpa-agent-next-s0-foundation.md)

- [EV-039 RPA Agent Next S2.5 会话编排与 API 隔离](../evidence/EV-039-rpa-agent-next-s2-5-session-orchestration.md)

- [EV-040 RPA Agent Next S3 构建与独立回放](../evidence/EV-040-rpa-agent-next-s3-build-and-independent-replay.md)
- [EV-041 RPA Agent Next S4 质量闭环](../evidence/EV-041-rpa-agent-next-s4-quality-closure.md)
- [EV-042 RPA Agent Next S5 Docker 组合根](../evidence/EV-042-rpa-agent-next-s5-docker-composition.md)

## Acceptance Criteria

- [ ] 新 Runtime Session 必须创建独立 sandbox；文件、Secret、工作目录和资源释放可被自动化验证，RPA 不直接管理 sandbox 生命周期。
- [ ] 手工操作能立即显示 Draft，并且仅在满足事实契约后冻结为 CoreTrace；未关联副作用不得伪造归属。
- [ ] AIInstructionStep 在同一宿主 Page/CDP 由 Browser-use 执行；内部动作不产生重复顶层步骤；成功、失败、取消均恢复手工监听。
- [ ] CompileDecision 对 CoreTrace 的可回放性作纯函数判断；可确定步骤生成 Playwright，不确定步骤只在人工审核、编辑和确认后创建新的 AIInstructionStep。
- [ ] 新生成 Skill 在独立 Runtime Session 中完成 Playwright 与 Browser-use 混合回放；第一阶段不得自动将 AIInstructionStep 提升为 Playwright。
- [ ] 新 API、Compiler、Runtime、Harness 和 E2E 不读取、适配、迁移或回放任何存量 Skill、Trace、配置或评测资产，并有架构守卫防止旧 namespace 进入。
- [ ] Harness 能基于 vNext 接受事实治理资产并做确定性回归，但不能生成、补写或修改生产 CoreTrace。
- [ ] 至少一个真实产品 E2E 场景贯穿“隔离会话 → 录制 → 构建 → 新会话回放 → 报告”；报告区分运行时、事实捕获、编译和回放失败。
- [ ] 指标/观测可汇总成功率、时延、成本、失败归因和 Bad Case，并可从一次失败定位到对应 session、timeline item 与受治理资产。
- [ ] 每条历史能力线在被标记为已迁移前，都有对应迁移清单、自动化回归和真实 E2E/回放 Evidence；满足后才讨论删除其来源分支。

## Patch History

- F032.1（2026-08-03）：端侧 Docker 实测暴露两处 runtime 边界缺口：已通过 HTTP readiness probe 的无 `HEALTHCHECK` session 被刷新为 `running`，以及 AIO 反向代理返回 `/cdp/devtools/browser/...` 而非原生路径。修复将就绪探针作为更强事实保留，并仅接受两种明确的 browser CDP 路径；新增回归测试和真实 Docker smoke。该补丁保持 ADR-008 的每会话隔离、同宿主 Page/CDP 和 fail-closed 初衷，不改变模型或资产边界。

## Evidence

F032 已有 S0、S1、S2.5、S3、S4 和 S5 的实现级 Evidence；其共同边界原为 deterministic fake/contract 验证。EV-042 现额外证明：受控 Browser-use 制品可在真实 backend Docker image 中构建，端侧 Docker session 已完成 AIO CDP、Playwright context/page 和释放 smoke。`git worktree` 已确认新分支基于 `6967daff`；分支审计材料记录了五类能力线及已删除/待收敛分支。真实 OpenAI-compatible Browser-use 自然语言任务、完整产品 E2E 以及 Harness capture 持久化仍须逐项新增 live Evidence，不得以当前测试结果或历史分支测试结果宣称 F032 已生产验收。

## Next Step

补至少一个确定性 Playwright 场景贯穿“隔离会话 → 录制 → 构建 → 新会话回放 → 质量报告”，随后补 app-first E2E 评测与 Harness capture 持久化资产；有 LLM 资源后再补 OpenAI-compatible Browser-use 自然语言任务证据。五条历史能力线均具备迁移清单、回归和 live Evidence 后，才讨论收敛来源分支。
