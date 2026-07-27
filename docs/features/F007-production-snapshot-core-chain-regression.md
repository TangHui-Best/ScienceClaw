---
id: F007
doc_kind: feature
status: completed
created: 2026-05-18
updated: 2026-05-18
---

# F007: Production Snapshot Core-chain Regression

## Goal

Make governed offline regression exercise the production DOM/raw/compact
snapshot chain for captured HTML assets instead of using an identity HTML
snapshot. This Feature strengthens Level 1 Snapshot Regression so future DOM
extractor and snapshot compression changes can be judged against governed
assets.

## Vision Anchor

- Original request: continue ScienceClaw RPA Harness work after F006 and make
  the snapshot part of governed offline regression call the production snapshot
  builder/compactor path.
- User pain point: current snapshot regression can pass while bypassing the
  real DOM extraction and compact snapshot compression chain, so it cannot
  distinguish whether task-critical facts were lost before raw snapshot,
  during raw snapshot construction, or during compact compression.
- Desired outcome: governed offline regression reports production raw and
  compact snapshot sizes, expected-signal preservation, and snapshot quality /
  compression diagnostics for the current governed candidate asset.
- Non-goals:
  - Do not fix planner behavior.
  - Do not fix `TraceSkillCompiler` hard-coded observed values.
  - Do not implement Skill Replay E2E.
  - Do not add GitHub-specific Harness rules.
  - Do not restore `rpa-eval-app` direct Agent chat as a golden runner.
- Exit Gate source: this Feature, [EV-007](../evidence/EV-007-production-snapshot-core-chain-regression.md),
  [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md),
  [ADR-003](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md),
  [F006](F006-observable-governed-regression-report.md), and
  [EV-006](../evidence/EV-006-observable-governed-regression-report.md).

## Current Status

Completed. Governed offline snapshot regression now uses the production
DOM/raw/compact snapshot chain and reports snapshot quality/compression
signals.

## Links

- Vision: [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Previous Feature: [F006 Observable Governed Regression Report](F006-observable-governed-regression-report.md)
- Previous Evidence: [EV-006 Observable Governed Regression Report Evidence](../evidence/EV-006-observable-governed-regression-report.md)
- Evidence: [EV-007 Production Snapshot Core-chain Regression Evidence](../evidence/EV-007-production-snapshot-core-chain-regression.md)
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

- [x] Snapshot regression uses a production snapshot adapter that invokes the
  current DOM/raw snapshot builder and `compact_recording_snapshot` path over
  captured HTML.
- [x] Snapshot report records raw snapshot size, compact snapshot size, and
  compression ratio/source diagnostics for every checked step.
- [x] Snapshot report can distinguish source HTML missing signal, raw snapshot
  missing signal, and compact snapshot signal loss.
- [x] Governed observability includes snapshot quality / compression signals.
- [x] Existing candidate asset still passes governed offline regression while
  showing real production compression effects.
- [x] Focused backend tests, governed summary, and strict Harness knowledge
  checks pass.
- [x] EV-007 records verification, commit hash, reviewer status, residual risk,
  and closeout status before the next Feature slice starts.

## Patch History

None yet.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

See [EV-007 Production Snapshot Core-chain Regression Evidence](../evidence/EV-007-production-snapshot-core-chain-regression.md).

## Next Step

F008 should remain the separate Skill Replay E2E slice: compile governed
scenario assets into Skills and replay them against a controlled page/provider.

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
