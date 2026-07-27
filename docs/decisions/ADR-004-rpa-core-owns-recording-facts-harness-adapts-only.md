---
id: ADR-004
doc_kind: adr
status: accepted
scope: project
feature_refs:
  - docs/features/F024-rpa-core-harness-boundary-guard.md
decision_area: rpa-core-harness-boundary
created: 2026-06-02
updated: 2026-06-02
---

# ADR-004: RPA Core Owns Recording Facts, Harness Adapts Only

## Context

Harness v1 需要把真实录制沉淀为可审查、可升级、可回归的资产。为了验证自然语言点击列表项触发下载这类场景，F019 引入了 controlled download side effects。但产品主链路也使用同一套 `RecordingRuntimeAgent`、accepted trace 和 `TraceSkillCompiler`。如果 Harness expected signals、controlled fixture 或报告诉求反向塑造 Core trace，就会破坏 ADR-001 的单一 accepted timeline，也会让 SOP->SKILL 编译链路变成“为了 Harness 通过而变化”。

本次回归的具体表现是：自然语言 simple `click` plan 真实触发下载，但 `RecordingRuntimeAgent` 的 simple click 分支没有 download listener；由于 AI 执行期间普通录制事件被暂停，manager 侧 pending download 合并存在竞态，最终 trace 缺少 `signals.download`，左侧步骤也只显示点击。

## Decision

RPA Core 拥有录制事实，Harness 只能适配和验证事实。

- 产品录制事实必须进入 `RPAAcceptedTrace` / `trace_diagnostics` / `runtime_results`，其中浏览器副作用如 `download` 必须由 Core 执行边界捕获为 trace signals。
- `TraceSkillCompiler` 只消费 accepted trace 及其证据，不消费 Harness expected signals、controlled fixture 或 Harness 报告。
- Harness 资产、expected signals、controlled routes 只能用于 replay/validation/report，不得回写或补写产品 session trace。
- Harness 变更如果触碰 RPA Core 文件，必须同时证明 Harness disabled/enabled 不改变 SOP->SKILL 主链路语义。
- UI timeline 可以投影 trace 上已有的 side-effect signals，但不得从 Harness artifact 合成步骤。

## Alternatives

- 把 Harness 与产品主链路完全 fork 成两套 agent/compiler：拒绝。短期隔离，长期会让 Harness 验证失真，因为它不再验证真实产品链路。
- 在 Harness 中补写 download step 或 expected signal：拒绝。这会制造第二事实源，掩盖 Core 捕获缺口。
- 只在前端 timeline 增加下载文案：拒绝。若 trace 没有 `signals.download`，生成 Skill 仍无法稳定 `expect_download()`。
- 为“点击第一行文件名称”加站点或关键词规则：拒绝。问题是通用浏览器副作用捕获边界缺失，不是某个页面的 selector 经验。

## Consequences

- Core 需要承担 browser side-effect capture 的最小职责；Harness 不能替 Core 修事实。
- Harness PR 的验证成本会上升：触碰 Core 文件时必须跑 focused Core 回归，而不能只跑 Harness asset/replay 测试。
- F019 controlled download 仍然有效，但其地位是“受控 fixture 验证下载副作用”，不是“产品录制下载事实来源”。
- 后续 popup、file chooser、new tab 等副作用也应按同一原则处理：先进入 Core trace，再由 Harness 验证。

## Evidence

- Feature: `docs/features/F024-rpa-core-harness-boundary-guard.md`
- Evidence: `docs/evidence/EV-024-rpa-core-harness-boundary-guard.md`
- Lesson: `docs/lessons/LL-002-harness-must-not-define-rpa-core-facts.md`
- Existing decision: `docs/decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md`
- Existing decision: `docs/decisions/ADR-002-trace-evidence-driven-compiler-strategy.md`
- Related Feature: `docs/features/F019-rpa-harness-controlled-download-side-effects.md`

## Decision Boundary

### Applies To

The decision scope described in the original Context and Decision sections.

### Does Not Apply To

Areas not explicitly covered by the original decision; this migration does not broaden its authority.

## Rejected Options

Existing alternatives remain authoritative where recorded in the original ADR. This migration introduces no new rejected architecture option.

## Before Changing This Decision

Read the original Context, Decision, Consequences, linked Feature, and Evidence. Record a successor ADR or explicit update before changing this durable boundary.
