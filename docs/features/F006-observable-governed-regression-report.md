---
id: F006
doc_kind: feature
status: completed
created: 2026-05-18
updated: 2026-05-18
---

# F006: Observable Governed Regression Report

## Goal

Turn the governed offline regression output into a stable observable evaluation
contract that explains what was evaluated, what was covered, what failed, and
how much confidence the result should carry.

This Feature builds on the existing F004 runner and F005 candidate asset. It
does not create a new evaluation path and does not revive direct Agent chat as
the golden measurement path.

## Vision Anchor

- Original request: explain exactly what F006 will observe so the report can
  become credible evidence for iterating the RPA core chain.
- User pain point: "passed" is not enough. Without observable and explainable
  signals, a regression run cannot tell whether the system improved, regressed,
  or simply did not cover the changed behavior.
- Desired outcome: governed offline regression produces both a machine-readable
  observability contract and a concise human-readable summary grounded in the
  current core-chain runners.
- Non-goals:
  - Do not change planner, snapshot compression, or `TraceSkillCompiler`
    behavior.
  - Do not implement Skill Replay E2E.
  - Do not add site-specific GitHub rules.
  - Do not use scoring or opaque quality grades.
- Exit Gate source: this Feature, [EV-006](../evidence/EV-006-observable-governed-regression-report.md),
  [F004](F004-governed-offline-regression-asset-pool.md), [F005](F005-first-governed-candidate-asset.md),
  and [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md).

## Current Status

Completed. Governed offline regression now emits a stable `observability`
contract in JSON and can render a concise human-readable summary for terminal,
PR, and Evidence use.

## Links

- Previous Feature: [F005 First Governed Candidate Asset](F005-first-governed-candidate-asset.md)
- Previous Evidence: [EV-005 First Governed Candidate Asset Evidence](../evidence/EV-005-first-governed-candidate-asset.md)
- Vision: [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Evidence: [EV-006 Observable Governed Regression Report Evidence](../evidence/EV-006-observable-governed-regression-report.md)
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

- [x] Governed offline regression includes a stable `observability` section
  derived from the existing asset selection, catalog, validation, snapshot,
  compiler, and blast-radius outputs.
- [x] The observability contract reports asset qualification, coverage, runner
  signals, blast radius, and confidence risks without hiding the underlying raw
  runner reports.
- [x] Excluded asset reasons are aggregated for quick review while retaining
  per-asset exclusion details.
- [x] Coverage risk is explicit when the baseline is too narrow, such as a
  single candidate asset.
- [x] A human-readable summary is available for terminal, PR, and Evidence use.
- [x] The JSON report remains the machine-readable source of truth.
- [x] Focused backend tests and strict Harness knowledge checks pass.
- [x] EV-006 records RED/GREEN verification, implementation commit hash,
  residual risks, and closeout status.

## Patch History

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F006.1 | 2026-05-18 | `2cf62a08094802ec84d743f04f65e9c9d63610b1` | Human-readable summary is English-only, making the report less useful for Chinese Evidence review. | F006 intentionally kept the machine contract stable but did not localize the human rendering layer. | Add `--lang zh` for `--format summary` while keeping JSON and default English output unchanged. | completed |

## Evidence

See [EV-006 Observable Governed Regression Report Evidence](../evidence/EV-006-observable-governed-regression-report.md).

## Next Step

Use the observable summary as the human-facing report for governed offline
regression runs. The next coherent slice is to decide whether this observable
report should become a default local/CI gate once more assets reduce the current
single-candidate coverage risk.

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
