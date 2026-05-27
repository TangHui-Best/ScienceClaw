---
id: ADR-001
doc_kind: adr
status: accepted
scope: feature
feature_refs:
  - docs/features/F001-rpa-trace-source-convergence.md
decision_area: rpa-architecture
created: 2026-05-13
updated: 2026-05-27
---

# ADR-001: RPA Trace Is The Single Accepted Timeline

## Context

RPA 录制一度同时维护 `session.steps`、`recorded_actions`、`session.traces`、`recording_diagnostics`、`legacy_steps` 和 step-index API。它们在迁移早期有兼容价值，但在 trace-first 已经成为主方向之后，这种并行事实源会直接破坏验收边界：不同模块会从不同对象读取“真相”，最终谁也说不清 Skill、repair、导出和回放到底依赖什么。

## Decision

`RPAAcceptedTrace` 是唯一 accepted timeline。新路径上的录制、配置、生成、测试、保存和 MCP/export 只允许消费 `session.traces`、`trace_diagnostics` 和 `runtime_results`；`steps`、`recorded_actions`、`recording_diagnostics`、`legacy_steps` 只能作为迁移期私有 DTO、测试夹具或历史材料存在，不能再作为新路径的公共契约或编译事实源。

## Alternatives

- 永久维持 dual-source compatibility：放弃。它会把“迁移未收敛”固化成架构本身。
- 先叠一层 observability 再慢慢收口：放弃。那只是在观察错误架构，而不是修正事实源。
- 一次性硬删所有 step 相关对象：放弃。录制、repair、失败重试和导出仍需要分阶段迁移，直接硬删会让失败不可归因。

## Consequences

- 旧开发期 session、旧 skill metadata 和部分历史 fixture 可能需要丢弃或隔离。
- 测试和 UI 需要把“还支持 step fallback”改成“证明不再依赖 step fallback”。
- 后续任何新增能力都应扩展 trace 模型或 trace diagnostic，而不是重新引入第二事实源。
- 一旦后续补丁出现，也应该先检查 trace 证据传播是否缺失，而不是反向复活 legacy step 通路。

## Evidence

- Feature: `docs/features/F001-rpa-trace-source-convergence.md`
- Evidence: `docs/evidence/EV-001-rpa-trace-source-convergence.md`
- Legacy spec: `docs/superpowers/specs/2026-04-28-rpa-trace-first-full-migration-design.md`
- Legacy plan: `docs/superpowers/plans/2026-04-28-rpa-trace-first-full-migration.md`
- Legacy plan: `docs/superpowers/plans/2026-05-16-rpa-trace-source-final-convergence.md`
