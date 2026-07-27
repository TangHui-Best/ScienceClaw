---
id: F005
doc_kind: feature
status: completed
created: 2026-05-18
updated: 2026-05-18
---

# F005: First Governed Candidate Asset

## Goal

Promote the first real, manually validated RPA Harness capture into the governed
offline regression baseline as a `candidate` scenario asset.

This Feature applies F004's governed report to a real capture. It is not a new
runner, not a direct Agent chat evaluation, and not a GitHub-specific Harness
rule.

## Vision Anchor

- Original request: use the F004 report to govern the clean `hcap-4be...`
  capture, formally promote it to `candidate`, and add page-pattern, coverage,
  and review metadata.
- User pain point: F004 can reject ungoverned assets, but the project still
  has no real asset selected by the default governed offline baseline.
- Desired outcome: `hcap-4be6265f43eb42dfa259182207aa64cc` is selected by
  `run_governed_regression` and passes offline validation, snapshot regression,
  compiler regression, and blast-radius checks.
- Non-goals:
  - Do not promote the asset to `golden` yet.
  - Do not add site-specific GitHub rules.
  - Do not implement Skill Replay E2E.
  - Do not fix planner, selector, or `TraceSkillCompiler` behavior.
- Exit Gate source: this Feature, [EV-005](../evidence/EV-005-first-governed-candidate-asset.md),
  [F004](F004-governed-offline-regression-asset-pool.md), and
  [ADR-003](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md).

## Current Status

Completed. The target asset is now an active `candidate` governed offline
regression asset and is selected by the F004 default report.

## Links

- Previous Feature: [F004 Governed Offline Regression Asset Pool](F004-governed-offline-regression-asset-pool.md)
- Previous Evidence: [EV-004 Governed Offline Regression Asset Pool Evidence](../evidence/EV-004-governed-offline-regression-asset-pool.md)
- Vision: [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Evidence: [EV-005 First Governed Candidate Asset Evidence](../evidence/EV-005-first-governed-candidate-asset.md)
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

- [x] Target asset scenario metadata is updated to `asset_status=active` and
  `governance.promotion_status=candidate`.
- [x] Target asset declares `offline_core_chain` runner eligibility and
  relevant core-chain coverage.
- [x] Target asset and steps include generic page-pattern tags suitable for
  coverage reporting.
- [x] Expected-signal and sensitivity review flags are true with review notes.
- [x] `run_governed_regression` selects the asset and returns `passed`.
- [x] Asset validation, snapshot regression, compiler regression, catalog, and
  strict Harness knowledge checks pass.
- [x] EV-005 records before/after governed report evidence, residual risks, and
  closeout status.

## Patch History

None yet.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

See [EV-005 First Governed Candidate Asset Evidence](../evidence/EV-005-first-governed-candidate-asset.md).

## Next Step

Use this candidate as the first default governed offline baseline for core-chain
changes. Promote to `golden` only after broader review or additional assets
confirm the coverage is not overfit to one page shape.

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
