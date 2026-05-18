---
id: F002
doc_kind: feature
status: completed
created: 2026-05-18
updated: 2026-05-18
---

# F002: RPA Harness v0

## Goal

Build RPA Harness v0 so RPA Agent core-chain changes can be evaluated against captured HTML/checkpoint assets instead of page-specific guesswork. The Harness boundary is: capture facts, store assets, and provide regression judgment. It must not become the place where business extraction, site-specific selector rules, or `TraceSkillCompiler` generalization are silently fixed.

## Vision Anchor

- Original request: add product/runtime Harness capabilities for the RPA Agent, not just local Codex Harness skills.
- User pain point: fixing one page bug can affect other DOM shapes and core chains, but the project lacked observable, reproducible, comparable assets.
- Desired outcome: Full SOP Capture and Selected Step Capture both persist unified step checkpoints; snapshot, compiler, catalog, blast-radius, and asset-validation runners can evaluate core-chain changes against the captured assets.
- Non-goals: no contract-first recording layer, no live URL primary oracle, no GitHub/Baidu/single-site architecture branch, no recording-time hard block for empty output or weak selector.
- Exit Gate source: this Feature, [EV-002](../evidence/EV-002-rpa-harness-v0.md), [LL-001](../lessons/LL-001-harness-feature-evidence-closeout-miss.md), and `docs/rpa/harness/*`.

## Current Status

Completed. RPA Harness v0 now has config-gated capture, Full SOP and selected-step checkpoint assets, expected signals, asset catalog, asset validation, snapshot regression, compiler regression, blast-radius reporting, and page-state capture quality evidence.

The post-stabilization Full SOP asset `hcap-ef3f5d7107ef4b1586dd533c6c7f8d41` confirms navigation-step `after.html` can be captured with stable title and full-page HTML instead of an early shell.

Historical draft assets still contain useful residual evidence:

- `missing-entry-checkpoint` on older draft Full SOP captures.
- `empty-after-html` on an older draft click-navigation checkpoint.
- `compiler-hardcoded-observed-value` on one selected-step fork extraction asset.

These are no longer blockers for F002 completion. The first two are historical draft asset quality findings already covered by newer capture validation. The compiler hardcode is follow-up RPA Agent / `TraceSkillCompiler` generalization work, not Harness infrastructure.

## Links

- Design: [RPA Harness v0 Design](../rpa/harness/rpa-harness-v0-design.md)
- Schema: [Scenario Asset Schema](../rpa/harness/scenario-asset-schema.md)
- Strategy: [RPA Harness Regression Strategy](../rpa/harness/regression-strategy.md)
- Vision: [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Plan: [2026-05-17 RPA Harness v0 Implementation Plan](../superpowers/plans/2026-05-17-rpa-harness-v0-implementation.md)
- Evidence: [EV-002 RPA Harness v0 Evidence](../evidence/EV-002-rpa-harness-v0.md)
- Lesson: [LL-001 Harness Feature Evidence Closeout Miss](../lessons/LL-001-harness-feature-evidence-closeout-miss.md)
- Backlog: [Backlog](../BACKLOG.md)

## Acceptance Criteria

- [x] F0-F14 have a recoverable Feature/Evidence index instead of relying on chat history.
- [x] `RPA_HARNESS_CAPTURE_ENABLED=false` remains a zero-impact gate.
- [x] Harness captures local step checkpoint assets with URL, HTML, step intent, trace evidence, expected signals, and before/after state.
- [x] Snapshot regression, compiler regression, asset catalog, blast-radius, and asset validation runners exist.
- [x] Page-state stabilization records stable `after.html` and `capture_quality` for navigation checkpoints.
- [x] System-level `knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict` passes.
- [x] Residual bootstrap asset findings are triaged before F002 is marked completed.

## Evidence

See [EV-002 RPA Harness v0 Evidence](../evidence/EV-002-rpa-harness-v0.md). It records F0-F14 commits, post-F14 fixes, validator output, focused tests, local bootstrap runner results, the post-stabilization Full SOP asset, and residual risks.

## Patch History

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F002.1 | 2026-05-18 | `2d029d9` | F0-F14 implementation lacked Feature/Evidence closeout. | Implementation plan was treated as Feature/Evidence memory. | Recovered F002/EV-002/LL-001 and added knowledge-check validation. | completed |
| F002.2 | 2026-05-18 | `a762b7e` | Bootstrap assets exposed empty after HTML, snapshot classification noise, and compiler comment noise. | Harness runners needed better asset-quality and regression classification. | Added `empty-after-html`, normalized snapshot matching, and executable-vs-comment compiler hardcode reporting. | completed |
| F002.3 | 2026-05-18 | `2ec5508` | Navigation-step `after.html` could persist early shell HTML. | Capture wrote page content before the browser state had settled. | Added page-state stabilization and `capture_quality` metadata. | completed |
| F002.4 | 2026-05-18 | docs-only closeout commit | F002 remained active after successful post-stabilization Full SOP validation. | Feature status and Evidence had not been closed after manual validation. | Record `hcap-ef3f5d7107ef4b1586dd533c6c7f8d41` and move residuals to follow-up scope. | completed |

## Patch Churn Review

F002 had multiple follow-up slices because the project first built runtime Harness capability, then recovered missing Harness closeout, then used self-bootstrap assets to expose asset-quality gaps. The repeated patches converged on the same invariant rather than adding page-specific rules: captured assets must be factual, quality-labeled, and usable by offline regression runners. No GitHub-specific capture or selector behavior was added.

## Next Step

Post-F002 follow-ups:

- Curate high-quality draft captures into active/golden regression assets after sensitivity review.
- Track scenario/page-pattern coverage so the team can answer which page forms are represented.
- Handle `compiler-hardcoded-observed-value` as RPA Agent / `TraceSkillCompiler` generalization work rather than as Harness infrastructure.
