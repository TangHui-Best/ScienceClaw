---
id: F002
doc_kind: feature
status: completed
created: 2026-05-18
updated: 2026-06-01
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
| F002.5 | 2026-05-18 | `1a0fa48` | A new Full SOP capture marked an initial navigation `after` state as `stable` even though `ready_state=loading`, `title_present=false`, and HTML was much smaller than the settled next-step page. | Stable classification treated repeated unchanged early navigation samples as reliable page evidence. | Align capture quality with navigation readiness: loading samples are saved as `partial` evidence, not `stable`; validation reports `loading-after-capture` as a non-blocking quality warning. | completed |
| F002.6 | 2026-06-01 | `f8c07c11` | Full SOP Harness assets recorded focus clicks on text inputs but skipped the following `fill`, causing login/search/form SOP assets to lose the actual input step or show step-index gaps. | Manual Harness checkpoint capture excluded `fill`, and full-sop checkpoint indexes followed trace order rather than persisted checkpoint order. | Capture `fill` checkpoints with write-time input parameterization, skip pure text-input focus-click checkpoints, keep full-sop checkpoint indexes contiguous, and compile `{{input:key}}` placeholders as runtime kwargs with sanitized fallback. | completed |
| F002.7 | 2026-06-01 | `b5001bb8` | Real Full SOP recording could lose both the text-input focus click and the following fill checkpoint. | The browser capture script only attaches `harness_before_page_state` to `click` / `press`; F002.6 skipped text-input focus-click checkpoints but only tested a fill event that already carried its own before-state. | Reuse the immediately preceding same-target text-input focus click's before-state when writing the fill checkpoint, and keep folding the focus click out of persisted Harness steps. | completed |
| F002.8 | 2026-06-01 | pending | A real login Full SOP asset missed the username fill checkpoint even though the generated Skill script contained username click/fill traces. | Full SOP checkpoint persistence was an event-arrival side effect. Browser `__rpa_emit` events can be processed out of order, so a fill may be seen before its earlier focus click with before-state; the later focus click was skipped and the existing fill checkpoint was never reconsidered. | Cache manual Harness checkpoint candidates, flush persisted checkpoints by sorted `session.steps`, backfill fill before-state from late same-target focus clicks, and sanitize captured HTML with cumulative known input replacements. | completed |
| F002.9 | 2026-06-01 | pending | A post-fix Full SOP asset had correct 001-006 checkpoints and sanitized trace values, but `steps/003/checkpoint.json.step_intent` still contained the raw username `admin`. | Input replacement was applied to trace events, expected signals, and HTML states, but not to the checkpoint's human-readable `step_intent`. | Apply the same input replacement map to `step_intent` during checkpoint persistence, and extend the fill-capture regression to assert checkpoint intent sanitization. | completed |

## Patch Churn Review

F002 had multiple follow-up slices because the project first built runtime Harness capability, then recovered missing Harness closeout, then used self-bootstrap assets to expose asset-quality gaps. The 2026-06-01 fill-capture follow-ups exposed two additional invariants: Full SOP assets must be persisted from the accepted, sorted trace timeline rather than async browser event arrival order, and every persisted review surface must share the same input sanitization contract. The repeated patches converged on those invariants rather than adding page-specific rules: captured assets must be factual, quality-labeled, order-stable, sanitized, and usable by offline regression runners. No GitHub-specific, login-specific, selector-specific, or business-flow-specific capture behavior was added.

## Next Step

Post-F002 follow-ups:

- Curate high-quality draft captures into active/golden regression assets after sensitivity review.
- Track scenario/page-pattern coverage so the team can answer which page forms are represented.
- Handle `compiler-hardcoded-observed-value` as RPA Agent / `TraceSkillCompiler` generalization work rather than as Harness infrastructure.
- Use F002.5 quality warnings when deciding whether a draft capture can become candidate/golden regression evidence.
