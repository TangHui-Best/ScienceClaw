---
doc_kind: backlog
status: active
updated: 2026-05-18
---

# Backlog

## Active

### Post-F002 RPA Harness Follow-ups

- Source Feature: `docs/features/F002-rpa-harness-v0.md`
- Evidence: `docs/evidence/EV-002-rpa-harness-v0.md`
- Vision: `docs/rpa/harness/golden-evaluation-vision.md`
- Decision: `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`
- Status: follow-up backlog after F002 completion.

Next actions:

- Curate the first candidate/golden asset set using the F003 governance metadata, not the existing direct Agent chat runner.
- Curate high-quality draft captures into candidate/golden regression assets after sensitivity review.
- Add page-pattern and core-chain coverage tags so the team can answer which page forms and RPA core paths are represented.
- Make runner defaults consume governed scenario assets for Offline Core-Chain Regression and prepare them for future Skill Replay E2E.
- Keep asset validation as an offline Evidence gate, not a recording-time blocker.
- Treat historical draft asset findings as asset-governance evidence:
  - `missing-entry-checkpoint` on two older draft Full SOP assets.
  - `empty-after-html` on one older draft click-navigation step.
- Route `compiler-hardcoded-observed-value` to a separate RPA Agent / `TraceSkillCompiler` generalization feature; do not count it as unfinished F002 Harness infrastructure.

## Recently Completed

### F004 Governed Offline Regression Asset Pool

- Feature: `docs/features/F004-governed-offline-regression-asset-pool.md`
- Evidence: `docs/evidence/EV-004-governed-offline-regression-asset-pool.md`
- Vision: `docs/rpa/harness/golden-evaluation-vision.md`
- Decision: `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`
- Status: completed.
- Result: Offline Core-Chain Regression now has a governed default report over
  active reviewed candidate/golden assets, with explicit excluded-asset reasons
  and a `no-governed-offline-assets` failure when the baseline is empty.

### F003 Golden Scenario Asset Model

- Feature: `docs/features/F003-golden-scenario-asset-model.md`
- Evidence: `docs/evidence/EV-003-golden-scenario-asset-model.md`
- Vision: `docs/rpa/harness/golden-evaluation-vision.md`
- Decision: `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`
- Status: completed.
- Result: Scenario assets now have governance metadata for promotion status, runner eligibility, core-chain coverage, expected-signal review, and sensitivity review; validation and catalog reporting consume those fields.

### F002 RPA Harness v0

- Feature: `docs/features/F002-rpa-harness-v0.md`
- Evidence: `docs/evidence/EV-002-rpa-harness-v0.md`
- Lesson: `docs/lessons/LL-001-harness-feature-evidence-closeout-miss.md`
- Status: completed after post-stabilization Full SOP validation.
- Completion asset: `data/rpa_harness_assets_bootstrap/hcap-ef3f5d7107ef4b1586dd533c6c7f8d41`

### Harness closeout process miss

- Lesson: `docs/lessons/LL-001-harness-feature-evidence-closeout-miss.md`
- Trigger: user reported F01-F14 implementation lacked Feature/Evidence materials.
- Recovery: create F002, EV-002, LL-001, this Backlog, and a project-level rule.
