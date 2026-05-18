---
id: F002
doc_kind: feature
status: active
created: 2026-05-18
updated: 2026-05-18
---

# F002: RPA Harness v0

## Goal

建设 RPA Harness v0，让 RPA Agent 的 DOM snapshot、trace recording、`TraceSkillCompiler` 等核心链路改动能基于沉淀的 HTML/checkpoint 资产做离线回归、影响面分析和知识沉淀，而不是继续“修一个页面 bug，不知道有没有影响其他页面”。

## Vision Anchor

- 原始请求：为 RPA Agent 补齐 product/runtime Harness 能力，而不是只依赖本机 Codex Harness skills。
- 用户痛点：不同页面/DOM 形态的 bug 修复会触碰共享核心链路，但缺少可观测、可复现、可比较的资产集。
- 期望结果：Full SOP Capture 与 Selected Step Capture 都沉淀统一 step checkpoint；核心链路变化可以跑 snapshot/compiler/catalog/blast-radius/asset-validation。
- 非目标：不构建 contract-first 录制层；不把 live URL 当主要 oracle；不为 GitHub、百度或任何单一页面写架构分支；不把空输出/弱 selector 做成录制主路径硬拦截。
- Exit Gate 对照来源：本 Feature、[EV-002](../evidence/EV-002-rpa-harness-v0.md)、[LL-001](../lessons/LL-001-harness-feature-evidence-closeout-miss.md)、`docs/rpa/harness/*`。

## Current Status

Active. F0-F14 代码能力已通过一系列 commit 落地，但 Feature/Evidence/Lesson closeout 是在用户指出过程缺陷后追补的。当前优先级是完成 Harness closeout 恢复，让 F001/F002/ADR/EV/LL 能通过系统级 `knowledge_check.py`，然后再决定是否继续 F002 后续 feature slice。

Current follow-up slice: harden Harness asset integrity and regression classification while preserving the boundary that Harness captures facts, stores assets, and reports replay/regression evidence. This slice does not repair business Agent extraction behavior or add site-specific GitHub rules. Latest focused verification is recorded in [EV-002](../evidence/EV-002-rpa-harness-v0.md).

Current capture-timing slice: add page-state stabilization and `capture_quality` metadata so navigation-step `after.html` is less likely to persist an early shell state. Asset validation reports `shell-like-after-html` and `unstable-after-capture` as offline evidence only; recording remains non-blocking and business extraction behavior remains out of scope.

## Links

- Design: [RPA Harness v0 Design](../rpa/harness/rpa-harness-v0-design.md)
- Schema: [Scenario Asset Schema](../rpa/harness/scenario-asset-schema.md)
- Strategy: [RPA Harness Regression Strategy](../rpa/harness/regression-strategy.md)
- Plan: [2026-05-17 RPA Harness v0 Implementation Plan](../superpowers/plans/2026-05-17-rpa-harness-v0-implementation.md)
- Evidence: [EV-002 RPA Harness v0 Evidence](../evidence/EV-002-rpa-harness-v0.md)
- Lesson: [LL-001 Harness Feature Evidence Closeout Miss](../lessons/LL-001-harness-feature-evidence-closeout-miss.md)
- Backlog: [Backlog](../BACKLOG.md)

## Acceptance Criteria

- [x] F0-F14 have a recoverable Feature/Evidence index instead of relying on chat history.
- [x] `RPA_HARNESS_CAPTURE_ENABLED=false` remains a zero-impact gate.
- [x] Harness captures local step checkpoint assets with URL, HTML, step intent, trace evidence, expected signals, and before/after state.
- [x] Snapshot regression, compiler regression, asset catalog, blast-radius, and asset validation runners exist.
- [x] System-level `knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict` passes.
- [ ] Residual bootstrap asset findings are triaged before F002 is marked completed.

## Evidence

See [EV-002 RPA Harness v0 Evidence](../evidence/EV-002-rpa-harness-v0.md). It records F0-F14 commits, post-F14 fixes, latest validator path/output, and residual risks.

## Patch History

- 2026-05-18: Recovered the F0-F14 Harness v0 closeout into Feature/Evidence/Lesson records and kept status active pending residual bootstrap asset triage.

## Next Step

Continue F002 residual triage: recapture a Full SOP after page-state stabilization to confirm navigation-step `after.html` quality improves; then decide whether remaining executable observed-value hardcode belongs in `TraceSkillCompiler` generalization, AI trace sanitization, or a dedicated compiler-regression follow-up slice. Keep old `missing-entry-checkpoint`, `empty-after-html`, and shell-like findings visible as draft asset quality evidence until new captures replace them.
