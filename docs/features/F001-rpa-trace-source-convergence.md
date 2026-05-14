---
doc_kind: feature
id: F001
title: RPA Trace Source Convergence
status: active
feature_ids: [F001]
created: 2026-05-13
updated: 2026-05-13
specs:
  - docs/superpowers/specs/2026-04-28-rpa-trace-first-full-migration-design.md
plans:
  - docs/superpowers/plans/2026-04-28-rpa-trace-first-full-migration.md
decisions:
  - docs/decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md
evidence:
  - docs/evidence/EV-001-rpa-trace-source-convergence.md
---

# F001 RPA Trace Source Convergence

## Vision Anchor

RPA 录制、配置、生成、测试、保存和 MCP/export 的 accepted timeline 必须收敛为唯一事实源：`session.traces` / `RPAAcceptedTrace`。`session.steps`、`recorded_actions`、`recording_diagnostics`、`legacy_steps`、step-index API 和 `failed_step_index` 是迁移对象，不能继续作为新路径接口契约、业务状态、skill metadata 或编译事实源。

## User Problem

当前录制生成 Skill 链路同时记录 trace、step、recorded action 等多种数据源。它们原本是为了兼容旧方案，但 trace-first 架构已经确定，继续保留多事实源会让 timeline、编译器、诊断修复、MCP/export 和未来 Harness 观测读取到不同对象，导致结果不可验收、不可追溯、也难以恢复。

## Desired Outcome

- 新 session 的 accepted timeline 只由 trace 组成。
- 失败或不可接受事件只进入 trace diagnostic。
- 前后端接口、生成、测试、保存、MCP/export 不再依赖或输出 `steps`、`recorded_actions`、`recording_diagnostics`、`legacy_steps`。
- 失败定位、删除、locator promotion 全部使用 `trace_id` 或 `diagnostic_id`。
- 旧开发期 session 和旧 skill metadata 不作为兼容目标。

## Non-goals

- 不做 Harness observability UI、指标面板或事件流功能。
- 不引入 contract-first 录制层。
- 不为单一站点或历史 fixture 反向塑造核心抽象。
- 不做多轮 repair 循环。

## Acceptance

- Removal gate in `docs/superpowers/plans/2026-04-28-rpa-trace-first-full-migration.md` passes.
- Backend targeted tests and frontend type-check/build pass.
- Negative grep for legacy source dependencies is reviewed and allowed hits are justified.
- Manual smoke covers recording, configure, generate, test, save, and MCP/export.
- Subagent implementer, spec reviewer, code-quality reviewer, and final full-diff reviewer records are captured in Evidence.

## Current State

Active. Harness anchors have been created before implementation. Read-only explorer reviews found backend, frontend, and test dependencies that still positively assert legacy source behavior; implementation must update those tests so they prove removal rather than preserve compatibility.

## Next Step

Integrate subagent dependency inventories into the implementation plan, then start Task 1 with TDD and per-task subagent review.
