---
id: F014
doc_kind: feature
status: ready_for_review
created: 2026-05-28
updated: 2026-05-28
---

# F014: RPA Harness v1 Evidence / Report Trust Loop

## Goal

落地 RPA Harness v1 Phase 2：让 deterministic profile 的执行结果形成可信、可审查、可交接的 Evidence / Report 闭环。Phase 2 不新增 runner，不扩张 full/live profile，而是在 F013 deterministic profile 之上补齐机器 JSON、Markdown summary、Agent 解读流程、Feature/Evidence closeout 和 knowledge gate 归因。

## Vision Anchor

- Original request: 在 `codex/rpa-harness-region-integration` 上完成 RPA Harness v1 Phase 2：Evidence / Report 可信闭环，并先修复 Phase 1 剩余 P2 文档问题。
- User pain point: F013 已经能运行 deterministic profile，但可信交接不能只靠一段 summary 文本；Agent 必须有稳定字段读取，Markdown 必须明确指向机器 JSON，Evidence 必须能说明 gate 状态和 residual risk。
- Desired outcome: deterministic profile JSON 包含 bounded interpretation contract，Markdown summary 明确机器 JSON 路径和判断语义，usage guide 给出 Agent JSON-first 解读流程，F014/EV-014 记录测试、profile 输出、knowledge gate 状态和 Phase 3 是否可启动。
- Non-goals:
  - 不扩张 full/live profile。
  - 不接 CI blocking。
  - 不做自动诊断平台。
  - 不让外层 Agent 点击 RPA 产品 UI。
  - 不自动 promotion candidate/golden。
  - 不把 region selection 开成特殊 Harness 架构线。
  - 不重写 governed regression、validation、snapshot、compiler、skill replay 或 stateful SOP runner。
- Exit Gate source: this Feature, [EV-014](../evidence/EV-014-rpa-harness-v1-evidence-report-trust-loop.md), [Phase 2 plan](../archive/2026-05/rpa-harness/f014-rpa-harness-v1-phase-2-plan.md), [F013](F013-rpa-harness-v1-asset-driven-user-input-replay.md), [EV-013](../evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md), [RPA Harness v1 design](../rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md), [ADR-003](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md), and [F003-F010](F003-golden-scenario-asset-model.md).

## Current Status

Ready for review. Phase 1 P2 documentation fix, bounded interpretation contract, Markdown summary hardening, usage guide update, focused tests, deterministic profile artifacts, and strict Harness knowledge validation are complete.

## Entry Gates

Start Gate:

- Task class: high-risk.
- Risk triggers: Harness closeout semantics, report interpretation contract, cross-runner evidence, strict knowledge validation, and possible drift toward full/live or automatic diagnosis.
- Delegation decision: authorized/conditional for read-only parallel strict knowledge triage because the user explicitly allowed subagents for complex tasks; implementation remains local unless a disjoint write scope appears.
- Bug attribution: existing Feature F013 for the Phase 1 P2 documentation finding; F014 owns the Phase 2 interpretation/report contract.
- Required pre-work: retrieval, Vision Gate, Feature/Evidence anchors, Phase 2 plan.

Knowledge Retrieval:

- Read F013, EV-013, v1 design, Phase 1 plan, usage guide, ADR-003, and F003-F010.
- Retrieved boundary: governed assets are the oracle; scripts execute, Agents explain, humans govern.
- Retrieved implementation direction: wrap existing runner facts and report them; do not create a diagnostic platform or runner fork.

Vision Gate:

- Mode: Entry Gate.
- Outcome: ready to implement after this Feature and plan exist.
- Original intent: make deterministic profile evidence readable and trustworthy enough for Agent/human closeout.
- Alignment: the smallest coherent Phase 2 path is a JSON interpretation contract plus Markdown/report/Evidence hardening.
- Drift risks: full/live expansion, CI blocking, automatic diagnosis, metadata churn, or region-specific Harness branching.
- Reviewer policy: independent review recommended/conditional before final readiness because this is a high-risk Harness process slice.

## Links

- Evidence: [EV-014 RPA Harness v1 Evidence / Report Trust Loop Evidence](../evidence/EV-014-rpa-harness-v1-evidence-report-trust-loop.md)
- Plan: [F014 Phase 2 implementation plan](../archive/2026-05/rpa-harness/f014-rpa-harness-v1-phase-2-plan.md)
- Previous Feature: [F013 RPA Harness v1 Asset-Driven User Input Replay](F013-rpa-harness-v1-asset-driven-user-input-replay.md)
- Previous Evidence: [EV-013 RPA Harness v1 Asset-Driven User Input Replay Evidence](../evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md)
- Design: [RPA Harness v1 Asset-Driven User Input Replay](../rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Usage Guide: [RPA Harness usage and triage guide](../rpa/harness/usage-and-triage-guide.md)

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

- [x] Phase 1 P2 documentation finding is fixed: summary command examples include `--machine-report`.
- [x] deterministic profile JSON exposes a stable bounded interpretation field with one of: `regression`, `improvement`, `no meaningful change`, or `insufficient evidence`.
- [x] interpretation is derived only from existing runner facts and explicitly names evidence limits; it does not diagnose root cause or prescribe automatic fixes.
- [x] Markdown summary clearly points to the machine JSON report path and includes the interpretation verdict, basis, and Agent JSON-first reading fields.
- [x] Usage guide documents the stable Agent reading flow and tells Agents not to rely only on summary text.
- [x] Focused tests cover the interpretation contract and Markdown/machine-report behavior.
- [x] deterministic profile is rerun and both JSON and Markdown report paths are recorded in EV-014.
- [x] `knowledge_check.py --strict` is run and passes without broad metadata churn.
- [x] EV-014 records verification, residual risk, reviewer status, and whether Phase 3 can start.

## Patch History

None yet. F014 is ready for review.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

See [EV-014 RPA Harness v1 Evidence / Report Trust Loop Evidence](../evidence/EV-014-rpa-harness-v1-evidence-report-trust-loop.md).

## Next Step

Review F014. If accepted, Phase 3 can start as Asset Lifecycle Operationalization, scoped to asset governance/operations rather than new runner expansion.

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
