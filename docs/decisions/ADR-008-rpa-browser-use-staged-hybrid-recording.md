---
id: ADR-008
doc_kind: adr
status: accepted
scope: feature
feature_refs:
  - docs/features/F029-rpa-browser-use-hybrid-v1.md
decision_area: rpa-recording-browser-agent-delivery
created: 2026-07-20
updated: 2026-07-20
updates:
  - doc: ADR-005
    section: Trace Mapping Strategy / POC Exit Criteria
    reason: V1 先以一条原始 AI 指令作为可编译 Trace，Browser-use History 只作诊断；History-to-Playwright 延后到有证据的 V2。
---

# ADR-008：Browser-use 渐进式人工/自然语言混合录制

## Context

ADR-005 和 F025 已经证明 Browser-use 能通过 CDP 复用 ScienceClaw 当前录制浏览器，并形成最小可运行链路。后续 F028 方向进一步提出 Intent-first Timeline、双模式 Compiler、Runtime 契约和 CoreTrace 重构，但把这些变化放在同一迭代后，交付面过大，真实产品闭环难以快速验证，失败也难以归因。

当前首要用户目标不是一次性完成理想化数据模型，而是尽快获得一个可真实使用的 Local 混合录制能力：人工操作承担精准动作，自然语言操作承担逻辑动作，二者在同一个页面按顺序协作并生成可重放 Skill。

## Decision

采用三阶段渐进式路线，当前只实施 V1：

1. V1 保留现有 `RPAAcceptedTrace`、人工监听、配置流程和 `TraceSkillCompiler` 主体，不重构 CoreTrace 或录制 Timeline。
2. 人工操作继续形成现有手工 Trace，并编译为 Playwright。
3. 自然语言操作由 Browser-use 作为执行主体；ScienceClaw 只提供原始指令、当前 Page/CDP 和现有普通上下文，并作为旁路观察者保存诊断。
4. Browser-use 保留原生 Tools、Planner、History、retry 和 done；ScienceClaw 不根据 Trace、候选、证据完整度或编译需要控制其运行态。
5. Browser-use 执行期间，ScienceClaw 作用域暂停人工 Trace 入库，防止 Browser-use 的低层动作重复成为顶层人工 Trace；暂停必须在 `finally` 中恢复。
6. 每条自然语言提交在 V1 只形成一个现有 `AI_OPERATION` Trace，用户原始 instruction 是该 Trace 的编译权威来源。
7. Browser-use History 可以写入诊断字段，但 V1 Compiler 必须忽略其动作代码生成能力；Browser-use Trace 始终编译为运行时 Browser-use instruction。
8. V1 只交付 Local 模式与普通非敏感 JSON 变量。Secret `sensitive_data`、DataAsset `available_file_paths` 的新契约不在本轮接入；旧上传能力不扩展，也不作为验收目标。
9. 同一次录制或同一次重放内部，人工与 Browser-use 共享当前浏览器会话和 Page；测试或正式重放使用新的浏览器会话，不复用录制会话。
10. V2 才引入有条件的 History-to-Playwright：只有稳定、确定性且回放验证通过的动作才能编译为 Playwright；包含“最相关、最佳、风险最高”等动态语义判断的指令必须继续保留 AI。
11. V3 是否重构 Trace 由 V1/V2 的真实证据决定。只有旧模型无法表达执行状态、诊断子动作、编译决策或回放契约时，才启动数据模型重构。

## Decision Boundary

### Applies To

- Local Recorder 中人工与自然语言交替录制。
- `BrowserUseRecordingOperator` 的当前 Page/CDP 附着和运行边界。
- Browser-use 执行期间 recorder 的作用域暂停与恢复。
- Browser-use AI Trace 的 V1 编译和 Skill 重放。
- F029 的验收、回滚和后续 V2/V3 进入条件。

### Does Not Apply To

- 现有手工 Trace 模型和手工 Playwright 编译语义的重写。
- V1 中 Browser-use History 到 Playwright 的转换。
- SecretStore、DataAsset、结构化 Agent output 的新契约。
- Docker、Kubernetes、远程 Runtime。
- ScienceClaw UI 的整体重构。
- Harness 对产品录制事实或 compiler 策略的干预。

## Relationship To Existing Decisions

- ADR-001 继续有效：`RPAAcceptedTrace` 是 V1 唯一 accepted timeline。
- ADR-002 继续有效，但 V1 对 Browser-use Trace 采用显式保守策略：History 证据不参与确定性编译，原始语义指令直接进入 runtime AI。
- ADR-005 的“Browser-use 是自然语言执行内核、复用当前浏览器、不 fork compiler”继续有效。
- 本 ADR 阶段性更新 ADR-005 的 Trace Mapping/Exit Criteria：V1 不要求把 Browser-use 每个动作映射为可编译 accepted trace，也不以 History 动作回放作为交付门槛。
- `codex/rpa-agent-intent-first-dual-mode` 的 ADR-007/F028 不作为本分支 V1 权威来源；其中可独立验证的实践只能按 F029 范围逐项吸收。

## Alternatives

- 继续一次性完成 F028：拒绝作为当前迭代，因为数据模型、编译器、Runtime、会话和 UI 同时变化，超出最小可验证能力增量。
- V1 继续优先编译 Browser-use History：拒绝，因为会冻结动态语义、放大 locator 脆弱性，并可能与完整 AI 指令重复执行。
- Browser-use 执行时继续开启人工 Trace 入库：拒绝，因为同一动作会产生两套顶层重放语义。
- 为避免重复录制而限制 Browser-use Tools 或 Planner：拒绝；重复问题属于 ScienceClaw 观察边界，不应通过削弱执行主体解决。
- V1 同时接入 Secret/DataAsset 新契约：拒绝，因为当前主验收不依赖它们，且旧基线没有形成完整安全闭环。
- 直接从 F028 分支回退：拒绝，因为撤销大重构比从已运行基线做窄增量更难验证和回滚。

## Consequences

- V1 可以较快形成可运行闭环，且每个失败都可归因到 Browser-use 执行、页面附着、监听暂停、Trace 生成、Compiler 或 Runtime 重放。
- V1 生成的自然语言步骤依赖运行时 LLM 和 Browser-use，不具备纯 Playwright 的确定性与低成本。
- Browser-use History 在 V1 中可能包含有价值动作，但只作为诊断保存；这是有意延后的优化，不是遗漏。
- Secret/DataAsset 安全能力不在 V1 承诺范围内，产品和测试必须避免误用并明确提示限制。
- recorder 暂停期间不能同时接受用户人工操作；UI/后端需串行化单条自然语言执行。
- 旧工作目录包含大量本地产物，提交必须显式选择文件，禁止使用 `git add .`。

## Before Changing This Decision

- 检查 F029 的 Local Live UI Evidence 与失败归因。
- 检查一条 AI 指令是否仍会产生重复人工 Trace。
- 检查 Browser-use History 中哪些动作具有稳定定位证据，哪些仍依赖动态语义。
- 检查 V2 是否能按单条 Trace 选择 Playwright 或 AI，而不是全局切换。
- 只有真实案例证明旧 Trace 无法表达必要契约时，才讨论 V3 Trace 重构。
- 任何 Secret/DataAsset 扩展必须另设安全验收，不能以“Browser-use 原生支持”代替产品闭环验证。

## Evidence

- Feature：[F029 Browser-use 人工/自然语言混合录制 V1](../features/F029-rpa-browser-use-hybrid-v1.md)
- 基线 Feature：[F025 Browser-use Recording Operator POC](../features/F025-browser-use-recording-operator-poc.md)
- 既有边界：[ADR-005 Browser-use Recording Operator Integration Boundary](ADR-005-browser-use-recording-operator-integration-boundary.md)
- Trace 边界：[ADR-001](ADR-001-rpa-trace-is-single-accepted-timeline.md)、[ADR-002](ADR-002-trace-evidence-driven-compiler-strategy.md)
- 实施规格：[2026-07-20 Browser-use Hybrid V1](../superpowers/specs/2026-07-20-rpa-browser-use-hybrid-v1-implementation-design.md)
- 分支基线：`3aa97568b78426b75711cff4f9f76ec765b71f99`

## Rejected Options

Existing alternatives remain authoritative where recorded in the original ADR. This migration introduces no new rejected architecture option.
