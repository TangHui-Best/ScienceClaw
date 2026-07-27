---
id: F004
doc_kind: feature
status: completed
created: 2026-05-18
updated: 2026-05-18
---

# F004: Governed Offline Regression Asset Pool

## Goal

Establish the first governed offline regression asset pool so RPA Harness
runners can default to reviewed `candidate` and `golden` scenario assets
instead of ad hoc draft capture directories.

This Feature turns the F003 asset model into an operational regression baseline.
It is about selecting and consuming governed assets, not creating a manual
approval ritual.

## Vision Anchor

- Original request: continue the RPA Harness work after F003 and the F002.5
  capture-quality fix, while checking that the next slice still serves the
  original Harness goal.
- User pain point: the project can capture and validate individual assets, but
  it still cannot answer which governed scenario assets form the default
  offline regression baseline for core-chain changes.
- Desired outcome: a default Harness entrypoint can run offline regression
  against governed assets and report coverage, failures, and asset eligibility.
- Non-goals:
  - Do not revive the old `rpa-eval-app` direct Agent chat runner as the golden
    path.
  - Do not implement full Skill Replay E2E in this slice.
  - Do not fix planner, selector, business extraction, or `TraceSkillCompiler`
    generalization behavior inside Harness.
  - Do not add site-specific GitHub rules.
- Exit Gate source: this Feature, [EV-004](../evidence/EV-004-governed-offline-regression-asset-pool.md),
  [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md),
  [ADR-003](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md),
  and [F003](F003-golden-scenario-asset-model.md).

## Current Status

Completed. F004 adds a governed offline regression selector, default report,
and CLI entrypoint. Offline Core-Chain Regression can now default to active,
reviewed candidate/golden assets while reporting excluded draft or unreviewed
captures with explicit reasons.

## Links

- Vision: [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Previous Feature: [F003 Golden Scenario Asset Model](F003-golden-scenario-asset-model.md)
- Previous Evidence: [EV-003 Golden Scenario Asset Model Evidence](../evidence/EV-003-golden-scenario-asset-model.md)
- Evidence: [EV-004 Governed Offline Regression Asset Pool Evidence](../evidence/EV-004-governed-offline-regression-asset-pool.md)
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

- [x] Harness can select governed offline regression assets by default:
  `promotion_status in {candidate, golden}`, `asset_status=active`, and
  `offline_core_chain` runner eligibility.
- [x] Draft or captured assets remain analyzable, but are excluded from the
  default governed regression baseline.
- [x] A default offline regression report combines asset eligibility, catalog
  coverage, validation, snapshot regression, and compiler regression outcomes.
- [x] The report exposes excluded asset reasons so recapture/review/rejection
  decisions are visible without blocking recording-time capture.
- [x] CLI or module entrypoint can run the governed offline report without
  relying on direct Agent chat.
- [x] Focused backend tests and Harness `knowledge_check.py --strict` pass.
- [x] EV-004 records RED/GREEN verification, implementation commit hash,
  residual risks, and closeout status before moving to Skill Replay E2E work.

## Patch History

None yet.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

See [EV-004 Governed Offline Regression Asset Pool Evidence](../evidence/EV-004-governed-offline-regression-asset-pool.md).

## Next Step

Use F004's governed report to curate the first real candidate/golden asset
metadata. After at least one governed pool exists, the next coherent feature is
Skill Replay E2E preparation over scenario assets, not direct Agent chat.

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
