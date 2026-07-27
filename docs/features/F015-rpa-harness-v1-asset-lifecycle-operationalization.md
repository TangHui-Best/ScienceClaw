---
id: F015
doc_kind: feature
status: ready_for_review
created: 2026-05-28
updated: 2026-05-28
---

# F015: RPA Harness v1 Asset Lifecycle Operationalization

## Goal

落地 RPA Harness v1 Phase 3：Asset Lifecycle Operationalization。把已有的资产治理能力推进到日常可操作、可审查、可交接的流程，让 `draft` / `candidate-lite` / `candidate` / `golden` 的状态、资格、风险、review packet、promotion 边界和资产池覆盖一眼可查。

Phase 3 第一切片只做最小能力增量：asset lifecycle summary、golden eligibility report、promotion guardrails。它不新增 runner，不扩张 full/live profile，不接 CI blocking。

## Vision Anchor

- Original request: 在 `codex/rpa-harness-region-integration` 上，从已提交的 F013/F014 基础开始 Phase 3，先做资产生命周期摘要、golden eligibility report 和 promotion guardrails。
- User pain point: F003-F014 已经有资产模型、governed runner、review packet、candidate-lite、deterministic profile 和 Evidence/Report 可信闭环，但资产池的日常操作还不够清晰。用户和 Agent 需要稳定知道新资产如何 review、何时 warning-only、何时 blocking、何时能进入 golden，以及哪些决策必须由人确认。
- Desired outcome: 用户或 Agent 可以用稳定命令生成资产生命周期摘要和 golden eligibility report；promotion CLI 能阻止 Agent 自动把不稳定资产升为 blocking baseline；deterministic profile 能说明当前资产池覆盖边界和可信度限制。
- Non-goals:
  - 不扩张 full/live profile。
  - 不接 CI blocking。
  - 不做自动诊断平台。
  - 不让外层 Agent 点击 RPA 产品 UI。
  - 不自动 promotion `candidate` / `golden`。
  - 不重写 governed regression、validation、snapshot、compiler、skill replay 或 stateful SOP runner。
  - 不把 region selection 做成特殊架构线。
  - 不提前做 Phase 4 的真实用户输入模拟深化。
- Core boundary:

```text
Scripts execute.
Agents explain.
Humans govern.
```

- Exit Gate source: this Feature, [EV-015](../evidence/EV-015-rpa-harness-v1-asset-lifecycle-operationalization.md), [Phase 3 plan](../archive/2026-05/rpa-harness/f015-rpa-harness-v1-phase-3-plan.md), [F013](F013-rpa-harness-v1-asset-driven-user-input-replay.md), [F014](F014-rpa-harness-v1-evidence-report-trust-loop.md), [RPA Harness v1 design](../rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md), [ADR-003](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md), and [F010](F010-assisted-asset-review-and-promotion-pipeline.md).

## Current Status

Ready for review. The first Phase 3 slice is implemented: lifecycle summary, golden eligibility report, promotion guardrails, Review Packet lifecycle section, deterministic profile asset-pool boundary fields, focused tests, real bootstrap reports, and usage guidance.

## Entry Gates

Start Gate:

- Task class: high-risk.
- Risk triggers: Harness process semantics, promotion safety boundary, asset governance lifecycle, deterministic profile report contract, and possible drift toward full/live, CI blocking, automatic diagnosis, or Phase 4 input simulation.
- Delegation decision: authorized for read-only sidecar exploration because the user explicitly allowed subagents for complex tasks; implementation integration remains local until a disjoint write scope appears.
- Bug attribution: not triggered; this is a new Phase 3 Feature slice.
- Required pre-work: retrieve F013/EV-013, F014/EV-014, v1 design, F003-F010, ADR-003, usage guide, scenario asset schema, and F010 review/promotion plan; run Vision Gate; create F015/EV-015/Phase 3 plan before code.

Knowledge Retrieval:

- Read F013 / EV-013 and Phase 1 plan.
- Read F014 / EV-014 and Phase 2 plan.
- Read RPA Harness v1 design and ADR-003.
- Read F003-F010 Feature anchors and F010 assisted review/promotion plan.
- Read `usage-and-triage-guide.md` and `scenario-asset-schema.md`.
- Retrieved boundary: governed assets remain the durable unit; default execution is script-driven; Agents explain existing facts; humans decide promotion and long-term contracts.

Vision Gate:

- Mode: Entry Gate.
- Outcome: ready to implement after this Feature and plan exist.
- Original intent: make asset lifecycle governance operational without creating another runner or loosening human governance.
- Alignment: the smallest coherent Phase 3 path is a lifecycle summary, golden eligibility report, and stricter promotion CLI guardrails.
- Drift risks: full/live expansion, CI blocking, automatic diagnosis, automatic candidate/golden promotion, region-specific architecture, or Phase 4 user input replay.
- Reviewer policy: independent review recommended or conditional before final readiness because this is a high-risk Harness process slice.

## Links

- Evidence: [EV-015 RPA Harness v1 Asset Lifecycle Operationalization Evidence](../evidence/EV-015-rpa-harness-v1-asset-lifecycle-operationalization.md)
- Plan: [F015 Phase 3 implementation plan](../archive/2026-05/rpa-harness/f015-rpa-harness-v1-phase-3-plan.md)
- Previous Feature: [F014 RPA Harness v1 Evidence / Report Trust Loop](F014-rpa-harness-v1-evidence-report-trust-loop.md)
- Previous Evidence: [EV-014 RPA Harness v1 Evidence / Report Trust Loop Evidence](../evidence/EV-014-rpa-harness-v1-evidence-report-trust-loop.md)
- Design: [RPA Harness v1 Asset-Driven User Input Replay](../rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Assisted Review / Promotion: [F010 Assisted Asset Review And Promotion Pipeline](F010-assisted-asset-review-and-promotion-pipeline.md)

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

- [x] draft / candidate-lite / candidate / golden lifecycle definitions are consistent in code reports and documentation.
- [x] A stable command can generate an asset lifecycle summary for a selected asset root.
- [x] A stable command can generate a golden eligibility report without promoting assets automatically.
- [x] Review Packet output exposes asset lifecycle state, expected-signal review, sensitivity review, runner coverage, and promotion questions.
- [x] candidate-lite remains warning-only observation and cannot pollute the blocking candidate/golden baseline.
- [x] candidate promotion requires explicit expected-signal and sensitivity confirmation.
- [x] golden promotion requires stricter eligibility and explicit human approval or an explicit override.
- [x] deterministic profile output explains lifecycle distribution, asset pool coverage boundary, and trust limits.
- [x] Focused tests cover lifecycle summary, golden eligibility report, promotion guardrails, and profile lifecycle boundary fields.
- [x] Real bootstrap assets run through the new reports and deterministic profile.
- [x] `knowledge_check.py --strict` passes.
- [x] EV-015 records verification, residual risk, reviewer status, and whether Phase 4 can start.

## Patch History

None yet.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

See [EV-015 RPA Harness v1 Asset Lifecycle Operationalization Evidence](../evidence/EV-015-rpa-harness-v1-asset-lifecycle-operationalization.md).

## Next Step

Review F015. Phase 4 may start after human/independent review accepts the Phase 3 governance slice; it should focus on Asset-Driven User Input Replay deepening and keep the same lifecycle guardrails.

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
| 2026-07-25 | ready_for_review | AgentMentor schema migration | Existing Feature/Evidence | Historical facts retained; current required structure added |

## Recovery Snapshot

- Read first: `## Goal`, `## Links`, `## Acceptance Criteria`, and `## Evidence`.
- Current capability state: Use the existing `## Current Status`; this migration does not change delivery status.
- Known risks: Historical verification is limited to what the original record explicitly states.
- Next safe action: Read the linked Evidence and ADRs before any follow-up change; update this Feature when the capability boundary or verified state changes.
- Unblock condition: Not blocked by this migration.
