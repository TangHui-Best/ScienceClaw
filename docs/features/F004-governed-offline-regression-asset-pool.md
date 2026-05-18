---
id: F004
doc_kind: feature
status: active
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

Active. Entry Gate passed with a bounded scope: implement governed asset
selection and a default offline regression report over selected assets.

## Links

- Vision: [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Previous Feature: [F003 Golden Scenario Asset Model](F003-golden-scenario-asset-model.md)
- Previous Evidence: [EV-003 Golden Scenario Asset Model Evidence](../evidence/EV-003-golden-scenario-asset-model.md)
- Evidence: [EV-004 Governed Offline Regression Asset Pool Evidence](../evidence/EV-004-governed-offline-regression-asset-pool.md)
- Backlog: [Backlog](../BACKLOG.md)

## Acceptance Criteria

- [ ] Harness can select governed offline regression assets by default:
  `promotion_status in {candidate, golden}`, `asset_status=active`, and
  `offline_core_chain` runner eligibility.
- [ ] Draft or captured assets remain analyzable, but are excluded from the
  default governed regression baseline.
- [ ] A default offline regression report combines asset eligibility, catalog
  coverage, validation, snapshot regression, and compiler regression outcomes.
- [ ] The report exposes excluded asset reasons so recapture/review/rejection
  decisions are visible without blocking recording-time capture.
- [ ] CLI or module entrypoint can run the governed offline report without
  relying on direct Agent chat.
- [ ] Focused backend tests and Harness `knowledge_check.py --strict` pass.
- [ ] EV-004 records RED/GREEN verification, implementation commit hash,
  residual risks, and closeout status before moving to Skill Replay E2E work.

## Patch History

None yet.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

See [EV-004 Governed Offline Regression Asset Pool Evidence](../evidence/EV-004-governed-offline-regression-asset-pool.md).

## Next Step

Implement the first governed offline regression selector and runner report via
TDD. Seed promotion policy should be generic and metadata-driven; any specific
GitHub capture is only validation evidence, not a special rule.
