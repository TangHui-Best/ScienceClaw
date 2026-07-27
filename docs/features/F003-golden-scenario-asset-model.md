---
id: F003
doc_kind: feature
status: completed
created: 2026-05-18
updated: 2026-05-18
---

# F003: Golden Scenario Asset Model

## Goal

定义并落地 Golden Scenario Asset Model，让 F002 捕获目录中的事实资产可以被提升为受治理的黄金测评资产，并成为 Offline Core-Chain Regression 的默认输入基础。这个 Feature 的重点是资产模型、生命周期、覆盖标签、推广校验和报告，而不是继续扩展旧的 direct Agent chat runner。

## Vision Anchor

- 原始请求或来源：继续 ScienceClaw 的 RPA Harness 工作，开始 F003：Golden Scenario Asset Model。
- 用户痛点或工程问题：F002 已经能捕获和回归本地资产，但“draft capture directory”还不是可治理、可筛选、可推广、可复用的黄金测评资产集合。
- 期望结果：Scenario Asset 能表达 golden promotion、runner modes、page/core-chain coverage、expected signals completeness、sensitivity review、asset lineage，并能被 catalog/validation/offline runners稳定消费。
- 非目标或边界：不把 `rpa-eval-app` direct Agent chat runner 作为黄金测评主路径；不把 live URL 或实时 Agent task completion 当成唯一 oracle；不在 Harness 内修复 planner、selector、business extraction 或 `TraceSkillCompiler` 泛化问题。
- Exit Gate 对照来源：本 Feature、[EV-003](../evidence/EV-003-golden-scenario-asset-model.md)、[RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md)、[ADR-003](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)、[F002](F002-rpa-harness-v0.md)。

## Current Status

Completed. F003 已补齐受治理 Scenario Asset metadata、promotion validation、catalog coverage 输出和文档闭环。黄金测评主路径保持 Scenario Asset 驱动的 Offline Core-chain Regression；未延续 direct Agent chat runner。

## Links

- Vision: [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Previous Feature: [F002 RPA Harness v0](F002-rpa-harness-v0.md)
- Previous Evidence: [EV-002 RPA Harness v0 Evidence](../evidence/EV-002-rpa-harness-v0.md)
- Evidence: [EV-003 Golden Scenario Asset Model Evidence](../evidence/EV-003-golden-scenario-asset-model.md)
- Backlog: [Backlog](../BACKLOG.md)

### Evidence

- Historical links remain in the original record; this migration adds the current navigation category.

### Decisions / ADRs

- Historical links remain in the original record; this migration adds the current navigation category.

### Lessons

- Historical links remain in the original record; this migration adds the current navigation category.

### Specs / Plans

- Historical links remain in the original record; this migration adds the current navigation category.

### Related Features

- Historical links remain in the original record; this migration adds the current navigation category.

### External Context

- Historical links remain in the original record; this migration adds the current navigation category.

## Acceptance Criteria

- [x] Scenario asset model can distinguish draft captures from candidate/golden governed assets without changing the trace-first recording path.
- [x] Asset metadata records runner eligibility for Offline Core-Chain Regression and future Skill Replay E2E preparation.
- [x] Validation reports missing governance fields as promotion blockers for governed assets while keeping draft captures non-blocking.
- [x] Catalog reports scenario/page-pattern/core-chain coverage needed to compare golden assets.
- [x] Existing snapshot/compiler/blast-radius runners continue to consume the asset model without relying on direct Agent chat.
- [x] Focused backend tests and Harness `knowledge_check.py --strict` pass.
- [x] EV-003 records verification, residual risks, implementation commit hash, and closeout status before the next Feature slice starts.

## Patch History

None yet.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

See [EV-003 Golden Scenario Asset Model Evidence](../evidence/EV-003-golden-scenario-asset-model.md). It records Entry Gate, RED/GREEN TDD evidence, focused verification, strict Harness validation, residual risk, and closeout status.

## Next Step

Next Feature slice should decide how curated assets are promoted from local/bootstrap capture directories into the first candidate/golden asset set. Do not route that through `rpa-eval-app` direct Agent chat.

## Feature Intake

- Original problem: The original problem is preserved in `## Goal` and `## Vision Anchor`; this migration does not reinterpret it.
- User pain point: The historical user pain point is preserved in the original Feature narrative and linked Evidence.
- Capability promise: The delivered or intended capability remains the one described in `## Goal` and `## Acceptance Criteria`.
- Non-goals: This migration adds no business scope and does not change the historical Feature boundary.
- Acceptance source: Existing acceptance criteria, linked Evidence, and recorded validation remain the source of truth.
- Open questions: Any historical uncertainty remains unresolved unless the original record or a linked successor answers it.

## Capability Contract

The capability boundary is the historical `## Goal`, `## Vision Anchor`, acceptance criteria, and linked artifacts. This schema migration does not add, remove, or reinterpret RPA behavior.

## Decision Context

### Why

The original Feature and its linked decisions preserve the rationale; this migration only makes that context recoverable through the current template.

### Why Not

Do not infer new product decisions from a document-schema migration or replace historical validation with template text.

### If Modifying This Area, Check

Read this Feature's Goal, Evidence, and linked ADRs before changing its capability boundary or claiming a new verification result.

## Acceptance Map

| Claim | Acceptance | Evidence | Status |
| --- | --- | --- | --- |
| Historical Feature contract | Existing `## Acceptance Criteria` and historical Feature record | Historical evidence documented in `## Evidence` | migrated |

## State Timeline

| Date | State | Trigger | Evidence | Note |
| --- | --- | --- | --- | --- |
| 2026-07-25 | completed | AgentMentor schema migration | Existing Feature/Evidence | Historical facts retained; current required structure added |

## Recovery Snapshot

- Read first: `## Goal`, `## Links`, `## Acceptance Criteria`, and `## Evidence`.
- Current capability state: Use the existing `## Current Status`; this migration does not change delivery status.
- Known risks: Historical verification is limited to what the original record explicitly states.
- Next safe action: Read the linked Evidence and ADRs before any follow-up change; update this Feature when the capability boundary or verified state changes.
- Unblock condition: Not blocked by this migration.
