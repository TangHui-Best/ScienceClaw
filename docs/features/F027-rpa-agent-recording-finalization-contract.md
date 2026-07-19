---
id: F027
doc_kind: feature
status: superseded
created: 2026-07-19
updated: 2026-07-20
superseded_by: F028-rpa-recording-intent-first-dual-mode-compilation
---

# F027：RPA Agent 录制动作结算与输出语义闭环

> 本 Feature 已由 [F028](./F028-rpa-recording-intent-first-dual-mode-compilation.md) 与 [ADR-007](../decisions/ADR-007-rpa-recording-intent-first-dual-mode-compilation.md) 取代。本文保留 2026-07-19 的实现、验证和失败历史，但 `extract_variable`、无 Candidate 禁止 `done`、Settlement 反向约束 Browser-use 等规则不再指导新开发。

## Goal

修复真实 Live UI 录制中“浏览器已完成操作，但时间线长期待结算；数据获取只返回对话文本，没有形成可回放输出动作”的缺口，使 Browser-use 的执行事实严格经过 `TraceCandidate -> SettlementResult -> CoreTrace`，并让 UI 的可回放计数与最终时间线一致。

## Vision Anchor

- 原始来源：用户在本地非 Docker、真实 LLM 的 GitHub Trending 录制验收中发现全部步骤待结算、Star 获取被显示为导航，配置保存返回 422。
- 用户痛点：页面操作看似成功，但录制产物不能配置、编译或准确表达输出。
- 能力承诺：每轮 Browser-use 的候选动作按本轮 ID 精确结算；数据读取必须形成显式输出动作；UI 只统计真正可回放步骤。
- 非目标：不重写 ScienceClaw Recorder/Configure UI；不引入 GitHub 专用规则；不从 `done` 文本伪造 CoreTrace；不绕过 Settlement Engine。
- Exit Gate 来源：F026、ADR-001、ADR-006、阶段一 E2E 设计基线、业务变量绑定设计基线及用户给出的 GitHub Live UI SOP。

## Feature Intake

- Original problem: Browser-use Adapter 注册 Candidate 后，生产路由未统一结算；LLM 还可以在 `done` 文本返回业务值而不调用显式提取工具。
- User pain point: 时间线状态与实际 SOP 不一致，配置保存失败，输出不可编译。
- Capability promise: 生产路由、工具协议、输出绑定和 UI 计数共同闭环。
- Non-goals: 不用关键词或站点模板替代 LLM；不把聊天文本当录制事实；不修改 CoreTrace Schema。
- Acceptance source: 用户复现步骤、F026 Capability Contract、阶段一 E2E 与业务变量设计基线。
- Open questions: 不同真实模型对扩展工具的服从率仍需持续 Live E2E；本次不承诺所有网站的业务选择质量。

## Capability Contract

- 每个 SOP Candidate 只能经 Creation Session 的 Settlement Engine 进入 CoreTrace。
- 每轮执行结束后只结算该轮报告中的 Candidate ID，不得结算历史或并发来源。
- 数据读取必须经 `extract_variable` 记录值、业务变量引用和输出绑定；`done` 仅负责会话完成。
- 当前轮没有 Candidate 时，`done` 必须失败并提示模型先产生可回放动作。
- `done`、等待、观察等非 SOP 动作不得计入可回放步骤。
- 保持 ScienceClaw 既有 Recorder/Configure 交互壳，并使用本地前后端和真实 LLM/browser-use 验收。

## Decision Context

### Why

既有架构已分离候选事实、结算和最终时间线。正确修复点是补齐生产编排与 Agent 工具契约，而不是在配置页放宽校验或在 UI 伪造状态。显式提取动作让输出被变量表、Compiler 和回放共同消费。

### Why Not

- 不在停止录制时无条件接受全部 pending：会掩盖失败并跨来源误结算。
- 不解析 `done` 文本生成输出：文本没有稳定变量名、来源和作用域，会形成第二事实源。
- 不增加 GitHub/Star 关键词分支：GitHub 只是验收样本。
- 不混用 `actual_action_count` 与可回放步骤数：两者语义不同，协议应显式区分。

### If Modifying This Area, Check

- [F026 RPA Agent 基于 ScienceClaw 宿主重构](./F026-rpa-agent-scienceclaw-host-rebuild.md)
- [ADR-001 RPA Trace Is The Single Accepted Timeline](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md)
- [ADR-006 在 ScienceClaw 宿主内绿地重建 RPA Agent 领域核心](../decisions/ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md)
- [LL-004 录制成功文本不能替代动作结算与输出绑定](../lessons/LL-004-rpa-recording-success-text-must-not-bypass-settlement.md)
- 必须同时运行 Adapter、Host、Route、Projection、Configure 与 Recorder 聚焦回归。
- 必须检查配置保存前 `pending_count == 0`，输出 CoreTrace 含显式变量绑定。

## Current Status

Superseded。原实现与自动化回归曾完成，但后续真实模型和 Live UI 验收证明其核心门禁会削弱 Browser-use、延迟时间线并阻断合法 AI 降级。相关实现仍可能存在于工作区，但后续修改必须以 F028 / ADR-007 为准，不再继续补 F027.x。

## Links

### Evidence

- [EV-033 F027 录制结算与 Live UI 验证](../evidence/EV-033-rpa-recording-finalization-live-ui.md)

### Decisions / ADRs

- [ADR-001 RPA Trace Is The Single Accepted Timeline](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md)
- [ADR-006 在 ScienceClaw 宿主内绿地重建 RPA Agent 领域核心](../decisions/ADR-006-rpa-agent-scienceclaw-host-greenfield-core.md)
- [ADR-007 RPA 录制采用 Action-first / Intent-first 双通道与双模式编译](../decisions/ADR-007-rpa-recording-intent-first-dual-mode-compilation.md)

### Lessons

- [LL-003 RPA 宿主 UI 回归契约与 Live E2E](../lessons/LL-003-rpa-host-ui-regression-contract-e2e.md)
- [LL-004 录制成功文本不能替代动作结算与输出绑定](../lessons/LL-004-rpa-recording-success-text-must-not-bypass-settlement.md)

### Specs / Plans

- [RPA Agent 首个阶段一 E2E 验收场景设计基线](../superpowers/specs/2026-07-17-RPA-Agent首个阶段一E2E验收场景设计基线.md)
- [RPA Agent 业务变量绑定与录制态上下文设计基线](../superpowers/specs/2026-07-17-RPA-Agent业务变量绑定与录制态上下文设计基线.md)

### External Context

- 用户于 2026-07-19 提供的本地 Live UI 复现、截图及后端 422 日志。

### Related Features

- [F026 RPA Agent 基于 ScienceClaw 宿主重构](./F026-rpa-agent-scienceclaw-host-rebuild.md)
- [F028 RPA 录制意图优先与双模式编译](./F028-rpa-recording-intent-first-dual-mode-compilation.md)

## Acceptance Criteria

- [x] 生产 instruction 路由在返回成功前结算本轮全部 Candidate。
- [x] 结算失败返回可定位阶段和错误，不把失败 Candidate 伪装为成功。
- [x] 数据获取必须先形成 `extract_variable` Candidate；无 Candidate 的 `done` 被工具边界拒绝。
- [x] UI 的“可回放步骤”只统计已接受 Candidate/CoreTrace。
- [x] Route 回归及真实本地链路证明配置保存不再因 `candidate_pending` 返回 422。
- [ ] 本地非 Docker 使用真实 LLM/browser-use 连续完成 GitHub Trending 三步 SOP、停止录制、配置和成功回放。

## Acceptance Map

| Claim | Acceptance | Evidence | Status |
| --- | --- | --- | --- |
| 生产结算闭环 | 本轮 Candidate 产生 Settlement/CoreTrace，配置可保存 | EV-033；138 项后端回归；Live HTTP 200 | pass |
| 输出语义闭环 | `extract_variable` 映射为 extract CoreTrace，`done` 不能绕过 | EV-033；Host/Adapter 测试；真实模型扩展工具调用轨迹 | pass（代码与轨迹） |
| UI 计数可信 | 非 SOP 动作不计为可回放步骤 | EV-033；Recorder/API 测试；Live UI 显示 0/1/4 的真实计数 | pass |
| 完整 Live UI 可用 | 指定 GitHub SOP 与回放全部成功 | EV-033 | blocked：LLM 免费额度 403；最终回放状态仍为 failed |

## State Timeline

| Date | State | Trigger | Evidence | Note |
| --- | --- | --- | --- | --- |
| 2026-07-19 | active | 用户授权按既有架构修复结算与输出语义缺口 | 用户复现、F026 Patch Churn Review | 新建独立 Feature，不继续堆叠 F026.n |
| 2026-07-19 | implementation_verified | 聚焦回归、构建与本地配置链路通过 | EV-033 | 代码实现可评审 |
| 2026-07-19 | validation_blocked | 最终完整真实 LLM E2E 复跑 | EV-033 | 外部模型免费额度 403，Feature 保持 active |
| 2026-07-20 | superseded | 后续真实运行与架构复盘确认门禁方向违反 Browser-use 执行主体和 AI 合法降级原则 | ADR-007；F028 | 保留历史证据，不再继续 F027.x 修补 |

## Patch History

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F027.1 | 2026-07-19 | pending | 数字开头 UUID 的模型在进入 browser-use 前返回 `rpa_agent.request_invalid` | `model_id` 错误复用要求首字符为字母的业务 `Identifier`，与模型仓库生成的标准 UUID 契约不一致 | 独立 `OpaqueModelRef`；数字开头 UUID 路由回归；非法引用 DTO 负向测试；`test_route.py` 56 项通过 | verified / uncommitted |

## Evidence

见 [EV-033](../evidence/EV-033-rpa-recording-finalization-live-ui.md)。结论为 Partial：核心修复和配置链路已验证，完整真实 LLM 连续 E2E 尚未通过。

## Recovery Snapshot

- Read first: F028、ADR-007，再将本 Feature 和 EV-033 作为失败历史阅读。
- Current capability state: F027 风格实现可能仍在生产路径；其回归只证明符合旧门禁，不证明符合当前产品目标。
- Known risks: 继续修补 `extract_variable`、Candidate `done` 门禁或 Settlement 热路径会重复削弱 Browser-use 和录制体验。
- Next safe action: 按 F028 的纵向增量迁移，不再以完成 F027 Live E2E 作为目标。
- Unblock condition: F028 的即时时间线、Browser-use 原生能力、双模式编译、全局变量和副作用 E2E 通过。

## Next Step

转入 F028。先完成影响面审计与实施计划，再撤回 F027 对 Browser-use 的运行态干预并重建双模式编译闭环。
