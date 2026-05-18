---
doc_kind: backlog
status: active
updated: 2026-05-18
---

# Backlog

## Active

### F007 Production Snapshot Core-chain Regression

- Feature: `docs/features/F007-production-snapshot-core-chain-regression.md`
- Evidence: `docs/evidence/EV-007-production-snapshot-core-chain-regression.md`
- Vision: `docs/rpa/harness/golden-evaluation-vision.md`
- Decision: `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`
- Status: active.
- Current state: implementation verification passed; closeout pending
  implementation commit hash in EV-007.
- Goal: make governed offline regression snapshot checks use the production
  DOM/raw/compact snapshot chain and report snapshot quality/compression
  signals.
- Non-goals: planner fixes, `TraceSkillCompiler` hard-code fixes, Skill Replay
  E2E, GitHub-specific Harness rules, and `rpa-eval-app` direct Agent chat.

Next actions:

- Create the implementation commit.
- Record the implementation commit hash in EV-007 and close F007.

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

### F006 Observable Governed Regression Report

- Feature: `docs/features/F006-observable-governed-regression-report.md`
- Evidence: `docs/evidence/EV-006-observable-governed-regression-report.md`
- Status: completed.
- Result: governed offline regression now emits a machine-readable
  `observability` contract and `--format summary` human report covering asset
  qualification, coverage, runner signals, blast radius, and confidence risks.

### F005 First Governed Candidate Asset

- Feature: `docs/features/F005-first-governed-candidate-asset.md`
- Evidence: `docs/evidence/EV-005-first-governed-candidate-asset.md`
- Asset: `data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc`
- Status: completed.
- Result: first repo-safe `candidate` asset is selected by the F004 governed
  offline report and passes validation, snapshot, compiler, and blast-radius
  checks.

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
