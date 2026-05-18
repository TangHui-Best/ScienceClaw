---
doc_kind: backlog
status: active
updated: 2026-05-18
---

# Backlog

## Active

### F002 RPA Harness v0

- Feature: `docs/features/F002-rpa-harness-v0.md`
- Evidence: `docs/evidence/EV-002-rpa-harness-v0.md`
- Lesson: `docs/lessons/LL-001-harness-feature-evidence-closeout-miss.md`
- Status: active after retrospective Harness recovery.

Next actions:

- Continue triaging current local bootstrap findings:
  - `missing-entry-checkpoint` on two draft Full SOP assets.
  - `empty-after-html` on one draft Full SOP click-navigation step.
  - `shell-like-after-html` / `unstable-after-capture` should be checked on new Full SOP captures after page-state stabilization.
  - `compiler-hardcoded-observed-value` on one selected-step fork extraction asset where the observed value appears in executable fallback locator code.
- Before further F002 feature slices, update both Feature and Evidence records first.
- Keep asset validation as an offline Evidence gate, not a recording-time blocker.

## Recently Recovered

### Harness closeout process miss

- Lesson: `docs/lessons/LL-001-harness-feature-evidence-closeout-miss.md`
- Trigger: user reported F01-F14 implementation lacked Feature/Evidence materials.
- Recovery: create F002, EV-002, LL-001, this Backlog, and a project-level rule.
