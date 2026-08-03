---
id: ADR-008
doc_kind: adr
status: accepted
scope: project
feature_refs:
  - docs/features/F032-rpa-agent-next-architecture.md
decision_area: rpa-agent-next-architecture-baseline-and-capability-migration
created: 2026-08-02
updated: 2026-08-03
applies_to_paths:
  - RpaClaw/backend/rpa_agent
  - RpaClaw/backend/route/rpa_agent_next.py
trigger_terms:
  - rpa-agent-next
  - CoreTrace
  - AIInstructionStep
updates:
  - doc: ADR-007
    section: Recording timeline, compilation, and expected effects
    reason: 新主线保留事实模型与 Browser-use 边界，但收窄编译决策、移除自动 ExpectedEffect，并明确 AI 步骤第一阶段不提升为 Playwright。
---

# ADR-008：RPA Agent Next 架构基线与能力迁移边界

## Context

`codex/rpa-agent-intent-first-dual-mode`（F028）和
`codex/rpa-browser-use-hybrid-v1` 分别验证了不同但互补的能力：前者建立
`CoreTrace`、录制会话、旁路副作用观察、丰富 locator/frame/region/变量事实模型；后者验证了
Browser-use 在宿主 Page/CDP 上执行自然语言指令、避免重复顶层录制步骤的运行闭环。

两者不是需要长期并行维护的产品主线，也不应通过 Git 的整枝合并变成一个混杂模型。整枝合并会同时引入
`RPAAcceptedTrace` 与 `CoreTrace`、两套编译/配置语义和重复的 UI 投影，失去单一事实源。

新的产品目标是“人工操作保留可确定回放的浏览器事实；自然语言操作由 Browser-use 运行；两者在同一 Skill 中按顺序协作”。因此需要创建一个独立架构分支，而不是把 F028 当作未经修改的后续版本，或把 Hybrid V1 当作永久主线。

## Decision

1. 创建并以 `codex/rpa-agent-next` 作为下一代 RPA 的唯一集成候选主线。它的物理代码基线为 `origin/codex/rpa-agent-intent-first-dual-mode@6967daff`，但其产品与架构身份是新的 RPA Agent Next；该分支不继承 F028 或 Hybrid V1 的全部决策。

2. 新主线只保留两类顶层录制时间线项：
   - `CoreTrace`：已证实的浏览器事实，保留 locator、frame path、region/table extraction、变量绑定和经因果关联的副作用。
   - `AIInstructionStep`：用户可见的原始自然语言意图及其执行状态。

   `CoreTraceDraft` 仅是录制创建期的临时状态：可立即投影给 UI，事实满足 CoreTrace 契约后冻结；它不是可编译时间线项。`BrowserEffect` 是由 Playwright/CDP 旁路观察且可因果关联的 navigation、popup、download、dialog 等副作用；无法关联的事件保持为 orphan evidence，不得伪造归属。

3. 手动录制完成或编译时，使用纯函数 `CompileDecision` 判断 `CoreTrace` 是否具备确定性 Playwright 回放所需事实。它不是持久化业务对象，不承担录制准入，也不面向用户形成额外步骤。
   - 可确定回放：编译为 Playwright。
   - 不可确定回放：进入人工审核；用户可将原 Draft 的意图编辑为一条**新的** `AIInstructionStep`，再交 Browser-use 执行。保留原 Draft 与转换审计，不得静默改写或自动重放可能已有副作用的动作。

4. `AIInstructionStep` 在第一阶段固定由 Browser-use runtime 执行，不自动提升为 Playwright。后续若要做 AI 到 Playwright 的提升，必须另行定义可验证证据阈值、人工确认与动态页面风险控制，不能借用本 ADR 的编译决策。

5. 不自动从观察到的 `BrowserEffect` 生成 `ExpectedEffect`。需要业务验收时，才在 `SkillBuildConfig` 或评测场景中由用户明确声明可观测、可判定且失败即代表任务失败的 `OutcomeAssertion`。原 `CompilationConfiguration` 的职责收敛为 `SkillBuildConfig`：Skill 名称、输入/输出契约、允许的变量/资源、运行限制，以及可选的 OutcomeAssertion；这些配置不得污染 `CoreTrace`。

6. 从 Hybrid V1 选择性迁移 Browser-use 的宿主 Page/CDP 附着、原生 planner/tool/retry/done、录制监听作用域暂停与恢复、取消及资源释放、运行时重放闭环。不得整体 cherry-pick 或合并其旧 `RPAAcceptedTrace`、`TraceSkillCompiler`、旧配置和旧 Timeline 语义。

7. Harness、E2E 与指标/观测组成 RPA 质量体系但不拥有录制事实：Harness 治理可回放资产与确定性回归；E2E 验收真实产品流程；指标/观测负责成功率、时延、成本、失败归因和 Bad Case。AIO sandbox/runtime 是独立的平台安全与会话隔离能力，RPA 只能通过 RuntimeProvider/会话接口使用它。

8. RPA Agent Next 不兼容存量 Skill、Trace、配置、回放产物或评测资产。新主线使用独立的 vNext schema、artifact namespace 与运行入口；不得实现旧资产读取器、适配层、自动迁移器或跨代回放。历史资产可在旧分支或归档中保留作审计与人工参考，但不得进入新运行路径或成为新 Feature 的验收依赖。

9. RPA Agent Next 的公开 API 仅使用 `/api/rpa-agent-next/...` 前缀。它在进入业务编排前必须校验 vNext identity；旧 `/api/rpa-agent/...` 路由、旧请求体和旧资产不得被转发、适配、读取或迁移到该入口。Next session id 只在 Next 会话注册表中解析，不能回退到旧会话或旧存储。
10. Quality System 使用独立的 `harness_asset` identity（producer=`quality-system`）治理回归场景。它只引用 vNext `skill_artifact` 的 identity/source hash 与输入指纹；不得保存、修改或从旧 fixture/旧 Skill 读取 `CoreTrace`。失败先形成报告，只有经显式审核才能晋级为 Bad Case。

11. F032 第一阶段的 `AIInstructionStep` 只承诺 OpenAI-compatible 模型契约：`model`、`api_key` 与可选 `base_url`，并由同一宿主会话中的 Browser-use 执行；它不承诺原生 Anthropic、Google、Groq、Ollama、MCP/CLI 或 Browser-use 自带的多 provider 选择。用户已确认其实际模型均满足该协议。`provider=anthropic` 等非该契约的配置在 Next 路径必须 fail-closed，后续若要支持，需另有真实任务 Evidence。

12. `browser-use==0.13.2` 是上游 API 基线，但未发布到 PyPI。上游提交 `2454d3e2551705232333c906ded8fc31ab0fc9f2` 将全部 provider/CLI/MCP 依赖写入主依赖，且强制 `anthropic==0.76.0`、`python-dotenv==1.2.2`；其中 Anthropic 与 `deepagents → langchain-anthropic` 的 `anthropic>=0.78` 不可共存。故不得直接使用上游 PyPI 或 Git URL。F032 从该提交创建受控的 Browser-use 兼容制品（当前仓库内版本 `0.13.2+sciclaw.1`）：Next 实际运行面只使用 OpenAI-compatible；CLI/MCP 和未使用 provider 迁至显式 extras。为保持同一 backend 进程中的既有 Anthropic 路由可导入，基础制品保留与项目依赖图兼容的 `anthropic==0.96.0`，这不扩大 Next 的模型契约。制品使用独立版本与来源 SHA，不得伪装为原始上游发布。其优先交付方式是内部 wheel/私有索引；固定 Git commit 仅可作为构建该制品的源码输入，不是生产 Docker 的在线依赖。

13. Next 的 `NativeBrowserUseRunner` 必须拥有自己的模型与 Page/CDP 适配层，不得继续从旧 `rpa_agent.host.browser_use_agent` 导入模型工厂或聚焦逻辑。复用上游 Browser-use 的 `Agent`/`BrowserSession` API 是能力迁移；复用旧 RPA 宿主的宽泛模型策略会重新引入旧边界，违背 vNext 单一入口和分层所有权。

## Boundary

本 ADR 只定义 RPA Agent Next 的架构身份、模块所有权、资产代际边界和能力迁移原则。它不声明真实 AIO、Browser-use、Playwright 或产品 E2E 已完成；这些必须由 F032 的独立 Evidence 证明。旧分支仅是能力来源和审计历史，不是新运行时的输入。

## Rejected Options

- 直接把 F028 作为不变的下一代主线：拒绝。它保留了本 ADR 已收窄的持久化分类、ExpectedEffect 和 AI/Playwright 自动选择语义。
- 以 Hybrid V1 为代码基线，再迁移 F028：拒绝。新架构最先需要稳定的是事实模型；从旧 Trace 模型开始会把核心迁移变成高风险重写。
- 对两分支执行 Git merge：拒绝。提交历史相加不等于能力集成，会永久保留两套事实源和编译模型。
- 将 Browser-use History 或最终文本自动编译为 Playwright：拒绝。它们只能提供诊断或关联证据，不能替代可验证的浏览器事实。
- 将 invalid Draft 自动直接执行为 AI 指令：拒绝。失败 Draft 可能已造成部分副作用；只能在人工审核、编辑并确认后新建 AIInstructionStep。
- 在新主线实现旧 Skill/Trace 的兼容或自动迁移：拒绝。这会将旧模型的歧义与安全边界带入新架构，并使验收同时背负两代契约。

- 在既有 `/api/rpa-agent/...` 路由上原地替换或新增 Next 行为：拒绝。它会模糊存量调用与新资产的代际边界，并让旧载荷有机会进入新编排。
- 由 `/api/rpa-agent/...` 代理、重定向或转换到 `/api/rpa-agent-next/...`：拒绝。兼容层等同于新入口读取旧语义，违反新资产从零开始的边界。
- 让 Harness 直接保存或补写 CoreTrace，或从旧 fixture 自动转换为新测试：拒绝。这会让质量系统重新成为生产事实的第二所有者，并把旧资产语义带回 vNext。
- 将公开 PyPI `browser-use==0.13.7` 作为小版本替换：拒绝。完整 resolver 证明其 `anthropic==0.76.0` 与项目的 `anthropic>=0.78` 不可共存；0.13.1 与 0.13.3 具有相同约束。
- 直接以固定 Git commit 安装 `browser-use==0.13.2`：拒绝。固定 commit 复现的是同一份冲突的包元数据，不能产生可构建镜像；以 `--no-deps` 绕过 resolver 会使声明的依赖图与实际运行环境分离，不能作为交付方案。
- 在 F032 第一阶段保留 Browser-use 的全部 provider/CLI/MCP 运行面：拒绝。项目实际使用的是 OpenAI-compatible 协议；无差别继承上游产品包会扩张供应链、镜像与冲突面，却不增加当前交付能力。
- 以独立 Browser-use service 解决依赖冲突：拒绝。它会把同宿主 `Page/CDP`、监听暂停恢复和会话资源边界变成跨服务协议，扩大而非收敛 Hybrid V1 的交付风险。

## Alternatives

- 受控 fork/wheel 或私有索引发布最小 Browser-use 兼容制品：采纳。基于 `2454d3e2551705232333c906ded8fc31ab0fc9f2`，仅保留 OpenAI-compatible Next 运行面所需依赖；完整 resolver、同宿主 Page/CDP 与有 LLM 的真实任务均须重新验证。
- 固定 Git commit 安装 0.13.2：拒绝。它可复现源码快照，却仍复现 `anthropic==0.76.0` 的冲突；GitHub 可用性也会额外进入构建供应链。
- 将 Browser-use 放入独立 runtime/service：延后。它可隔离冲突依赖，但会改变当前进程内宿主附着边界，必须另立架构决策并定义 Page/CDP、认证与可观测性契约；不是 F032 第一阶段的替代实现。
- 升级到公开 PyPI `browser-use==0.13.7`：拒绝。虽然公开宿主接口预检与 129 个边界回归通过，但完整依赖解析失败；不得以局部 API 兼容替代可部署性。

## Consequences

- `codex/rpa-agent-next` 从第一天起就有单一架构身份；F028 与 Hybrid V1 保留为可追溯的能力来源和回归输入，而非平行产品主线。
- 迁移工作以“契约和行为切片”为单位，而不是以旧分支提交为单位；每个迁移切片必须证明没有重新引入旧 Trace 语义。
- 第一阶段的双模式更简单：手动事实可被确定性编译为 Playwright；自然语言步骤固定为 Browser-use runtime。它牺牲了 AI 自动升格为脚本的优化，但避免了未证实的编译复杂度。
- `OutcomeAssertion` 不再伪装为自动观察事实，业务验收与录制事实被明确分开。
- 新架构切换是一次明确的资产代际切换；旧资产的保留不等于新运行时支持它们。
- 本 ADR 是架构决策，不是实现验收证据；后续必须由新的 Feature、迁移计划及真实 E2E/回放 Evidence 证明能力已交付。

## Revisit When

- 有多个真实场景证明 AI 步骤可在明确证据阈值下安全提升为 Playwright，并已定义人工确认和回退机制。
- Browser-use 不能在目标宿主会话中可靠复用 Page/CDP，且替代运行时在相同边界下有可复现优势。
- Skill 输入/输出或安全资源模型要求超出 `SkillBuildConfig` 的最小职责，且已有具体场景与验收契约。
- AIO RuntimeProvider 无法提供可验证的会话隔离、资源回收或文件安全边界。
- 所有旧 API 客户端均已按明确产品决策退役，且仍能以独立证据证明不存在旧资产/旧会话向新运行时的输入；在此之前不得缩并两个路由族。
- S4 的 harness asset 无法以 identity/source hash 与输入指纹稳定复现回放，或真实质量闭环需要安全保存额外的受治理数据类型；届时须基于具体场景扩展该契约，而不得复用旧 fixture 格式。
- 出现无法用 OpenAI-compatible 协议接入、且对 F032 有明确交付价值的真实模型场景，并已完成该 provider 的独立 Docker/自然语言任务 Evidence；届时才评估把它作为最小兼容制品的显式 extra，而不是恢复全量 provider 依赖。

## Links / Evidence

- [F028：RPA 录制意图优先与双模式编译](../features/F028-rpa-recording-intent-first-dual-mode-compilation.md)
- [ADR-007：RPA 录制意图优先与双模式编译](ADR-007-rpa-recording-intent-first-dual-mode-compilation.md)
- [ADR-006：ScienceClaw 宿主内 RPA Agent 核心](ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md)
- Hybrid V1 capability source: `origin/codex/rpa-browser-use-hybrid-v1@a661d10c`
- F028 code baseline: `origin/codex/rpa-agent-intent-first-dual-mode@6967daff`

## Evidence

- `python -m pip install browser-use==0.13.7` 可获取 PyPI 分发版，且公开接口预检确认 `BrowserSession` 仍接受 `cdp_url`、`keep_alive`，`Agent` 仍接受 `browser_session`。
- 临时把版本闸门升级到 0.13.7 后，`python -m pytest RpaClaw/backend/tests/rpa_agent/test_browser_use_adapter.py RpaClaw/backend/tests/rpa_agent/test_browser_use_integration_boundary.py RpaClaw/backend/tests/rpa_agent/test_route.py -q`：129 passed。
- 完整 backend image resolver 先报告 `python-dotenv==1.2.1` 与 0.13.7 的 `1.2.2` 冲突；同步后继续报告 0.13.7 的 `anthropic==0.76.0` 与 `deepagents → langchain-anthropic` 的 `anthropic>=0.78` 冲突。因此临时升级已撤回，容器内端侧 Docker smoke 仍未运行。
- 对本地可审计的 `browser-use` 源码提交 `2454d3e2551705232333c906ded8fc31ab0fc9f2` 读取 `pyproject.toml`，确认其为 `0.13.2` 且具有同样的 `python-dotenv==1.2.2`、`anthropic==0.76.0` 强约束。因此没有将 Git URL 写入 `requirements.txt`；这不是可行实现，而是已被包元数据否定的候选。
- 在隔离探针中，以 `anthropic==0.96.0` 覆盖本机的 `0.76.0` 后，`from browser_use import Agent, BrowserSession, ChatAnthropic, ChatOpenAI` 以及两类 Chat 实例构造均成功。该结果只证明导入/构造兼容性，不证明真实 Anthropic 调用；它支持将未使用 provider 移出 F032 最小运行面的决定。
