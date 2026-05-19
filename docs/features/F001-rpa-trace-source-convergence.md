---
id: F001
doc_kind: feature
status: active
created: 2026-05-13
updated: 2026-05-18
---

# F001: RPA Trace Source Convergence

## Goal

把 RPA 录制、配置、生成、测试、保存和 MCP/export 的 accepted timeline 收敛到唯一事实源：`session.traces` / `RPAAcceptedTrace`。`session.steps`、`recorded_actions`、`recording_diagnostics`、`legacy_steps`、step-index API 和 `failed_step_index` 只能作为迁移对象或私有 DTO，不能继续作为新路径业务事实、接口契约、Skill metadata 或编译事实源。

## Vision Anchor

- 原始问题：RPA 录制链路同时维护 trace、step、recorded action 等多种事实源，导致 generate/test/save/MCP/export 读取不同对象。
- 用户痛点：多事实源让结果不可验收、不可追溯、难以恢复，也会污染未来 Harness 可观测链路。
- 期望结果：新 session 的 accepted timeline 只由 trace 组成；失败事实进入 trace diagnostics；公共接口和 Skill 输出不再依赖旧事实源。
- 非目标：不做 Harness observability UI；不引入 contract-first 录制层；不为单一站点塑造核心抽象；不做多轮 repair 循环。
- Exit Gate 对照来源：本 Feature、[ADR-001](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md)、[ADR-002](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md)、[EV-001](../evidence/EV-001-rpa-trace-source-convergence.md)。

## Current Status

Active. 2026-05-16 已完成公共 session projection、generate/test/save compile input、saved trace metadata、trace-source skill export、MCP trace projection、MCP param source metadata、公共 step-index API 移除/隔离，以及 manager 内部 `RPAStep` / `recorded_actions` / `recording_diagnostics` 的私有 DTO 隔离。F001 仍保持 active，因为最终 release readiness 仍需完整 evidence closeout、负向 grep、manual smoke 和剩余迁移项确认。

## Links

- Spec: [2026-04-28 RPA Trace-first Full Migration Design](../superpowers/specs/2026-04-28-rpa-trace-first-full-migration-design.md)
- Plan: [2026-04-28 RPA Trace-first Full Migration](../superpowers/plans/2026-04-28-rpa-trace-first-full-migration.md)
- Plan: [2026-05-16 RPA Trace Source Final Convergence](../superpowers/plans/2026-05-16-rpa-trace-source-final-convergence.md)
- ADR: [ADR-001 RPA Trace Is The Single Accepted Timeline](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md)
- ADR: [ADR-002 Trace Evidence Drives Compiler Strategy](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md)
- Evidence: [EV-001 RPA Trace Source Convergence Evidence](../evidence/EV-001-rpa-trace-source-convergence.md)

## Acceptance Criteria

- [ ] Removal gate in `docs/superpowers/plans/2026-04-28-rpa-trace-first-full-migration.md` passes.
- [ ] Backend targeted tests and frontend type-check/build pass, or residual unrelated failures are explicitly recorded.
- [ ] Negative grep for legacy source dependencies is reviewed and allowed hits are justified.
- [ ] Manual smoke covers recording, configure, generate, test, save, and MCP/export.
- [ ] Subagent implementer, spec reviewer, code-quality reviewer, and final full-diff reviewer records are captured in Evidence.

## Evidence

Primary verification and reviewer records live in [EV-001 RPA Trace Source Convergence Evidence](../evidence/EV-001-rpa-trace-source-convergence.md). ADR context lives in [ADR-001](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md) and [ADR-002](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md).

## Patch History

- 2026-05-18: Restored this Feature page to the current Harness artifact shape and kept status active pending final release-readiness evidence.

## Next Step

Continue F001 closeout from `EV-001`: confirm remaining migration risks, rerun targeted backend/frontend checks, and only mark F001 completed after the evidence record contains the final knowledge-check result and release-readiness proof.
