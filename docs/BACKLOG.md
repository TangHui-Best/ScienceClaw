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
- Status: follow-up backlog after F002 completion.

Next actions:

- Curate high-quality draft captures into active/golden regression assets after sensitivity review.
- Add page-pattern coverage tags so the team can answer which page forms are represented.
- Keep asset validation as an offline Evidence gate, not a recording-time blocker.
- Treat historical draft asset findings as asset-governance evidence:
  - `missing-entry-checkpoint` on two older draft Full SOP assets.
  - `empty-after-html` on one older draft click-navigation step.
- Route `compiler-hardcoded-observed-value` to a separate RPA Agent / `TraceSkillCompiler` generalization feature; do not count it as unfinished F002 Harness infrastructure.

## Recently Completed

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
