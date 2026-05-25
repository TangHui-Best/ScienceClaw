---
doc_kind: feature
id: F001
title: RPA Trace Source Convergence
status: active
feature_ids: [F001]
created: 2026-05-13
updated: 2026-05-16
specs:
  - docs/superpowers/specs/2026-04-28-rpa-trace-first-full-migration-design.md
plans:
  - docs/superpowers/plans/2026-04-28-rpa-trace-first-full-migration.md
  - docs/superpowers/plans/2026-05-16-rpa-trace-source-final-convergence.md
decisions:
  - docs/decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md
  - docs/decisions/ADR-002-trace-evidence-driven-compiler-strategy.md
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

2026-05-15 update: trace-source convergence also needs an evidence-driven compiler gate. Trace is the single accepted timeline carrier, but compiler strategy must still distinguish navigation evidence, structured snapshot evidence, runtime semantic evidence, embedded AI code, dataflow, and output-only evidence. Output labels alone must not become replay locators.

## Next Step

Continue the active migration plan with a focused compiler gate: prevent weak/output-only extraction traces from compiling into invented deterministic field locators, preserve positive structured snapshot extraction, and record verification in EV-001 before broader generator retirement work.

2026-05-16 update: final convergence should proceed from external contracts inward. The next implementation route is `docs/superpowers/plans/2026-05-16-rpa-trace-source-final-convergence.md`: first stop public session responses from leaking legacy facts, then make generate/test/save compile inputs trace-only, then remove legacy saved metadata and MCP/export dependencies, then retire step-index APIs, and only after those gates decide whether manager-internal `RPAStep` state is removed or quarantined as a private DTO.

2026-05-16 progress update: session API projection, generate/test/save compile inputs, saved trace metadata, trace-source skill export, MCP trace projection, and MCP param source metadata now converge on trace-backed facts. Evidence is recorded in `docs/evidence/EV-001-rpa-trace-source-convergence.md` under "Task 2-4K". Remaining work is public step-index API removal/isolation and manager-internal `RPAStep` quarantine/removal.

2026-05-16 Task 5 update: public step-index routes and raw steps websocket have been removed from `RpaClaw/backend/route/rpa.py`, and `manual_step` timeline deletion is no longer a new-path API. Evidence is recorded under "Task 5K". Remaining work is Task 6: decide whether to fully remove manager-internal `RPAStep` / `recorded_actions` / `recording_diagnostics` or quarantine them as private transitional recording DTOs.

2026-05-16 Task 6 update: manager-internal `RPAStep`, `recorded_actions`, and `recording_diagnostics` are quarantined rather than hard-deleted in this pass. They remain private transitional browser-event normalization DTOs inside `RpaClaw/backend/rpa/manager.py`; public API responses, generate/test/save, saved metadata, MCP/export, and public step-index routes no longer use them as new-path facts. `stop_rpa_session()` now also uses the projected session response.

2026-05-16 Task 7L update: weak embedded AI extraction code that only produced empty output is no longer frozen as deterministic replay unless the trace explicitly carries an allow-empty output contract. This addresses the latest star-count regression as a generic evidence-quality issue rather than a GitHub-specific rule or a global "empty means failure" validator. Evidence is recorded under "Task 7L".

2026-05-25 Task 7M update: manual replay no longer treats random-like `data-testid` / `testid` values as stable trace facts. The fix keeps trace-first as the only compile source, preserves semantic test ids such as `login-username`, and moves the protection into shared locator stability scoring used by recording normalization, compiler fallback, and region context pruning. Evidence is recorded in `docs/evidence/EV-001-rpa-trace-source-convergence.md` under "Task 7M".
