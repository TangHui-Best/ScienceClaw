---
doc_kind: evidence
id: EV-002
title: RPA Harness v0 Evidence
status: active
scope: project
feature_ids: [F002]
feature_refs:
  - docs/features/F002-rpa-harness-v0.md
created: 2026-05-18
updated: 2026-06-02
evidence_level: exhaustive
---

# EV-002 RPA Harness v0 Evidence

## Scope

Evidence for F002: build RPA Harness v0 so captured HTML/checkpoint assets can validate DOM snapshot compression, accepted trace evidence, `TraceSkillCompiler`, and blast radius for core-chain changes.

This Evidence is partly reconstructed because F0-F14 were implemented before the required Feature/Evidence materials were created. The reconstruction itself is an incident recovery action and is linked to `docs/lessons/LL-001-harness-feature-evidence-closeout-miss.md`.

## Commands

Harness closeout recovery uses the bundled validator installed with the system-level `using-harness` skill:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

Relevant F002 code verification uses the focused RPA Harness test set:

```powershell
$env:PYTHONPATH="RpaClaw"
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_pure_navigation_checkpoint_from_page_baseline
```

## Results

Initial bundled validator result before this recovery:

```text
Scanned 155 markdown file(s). Checked 7 knowledge artifact(s). Errors: 39. Warnings: 4.
```

Final bundled validator result after this recovery:

```text
Scanned 155 markdown file(s). Checked 7 knowledge artifact(s). Errors: 0. Warnings: 0.
```

Strict validator result after this recovery:

```text
Scanned 155 markdown file(s). Checked 7 knowledge artifact(s). Errors: 0. Warnings: 0.
```

Focused RPA Harness code verification:

```text
33 passed, 27 warnings in 1.01s
```

Local bootstrap asset validation:

```text
capture_count=4
issue_count=2
blocking_issue_count=0
categories={"missing-entry-checkpoint": 2}
ASSET_VALIDATION_EXIT=0
```

Local bootstrap snapshot regression:

```text
total=8
passed=6
failed=2
failure_category=compact-snapshot-lost-signal
SNAPSHOT_EXIT=1
```

Local bootstrap compiler regression:

```text
total=8
passed=6
failed=2
failure_category=compiler-hardcoded-observed-value
hardcoded_values=["13.4k", "13.7k stars"]
COMPILER_EXIT=1
```

F002 remains active after this recovery because local bootstrap assets still contain residual snapshot/compiler findings that need triage before completion.

## Artifacts

- Feature: [F002 RPA Harness v0](../features/F002-rpa-harness-v0.md)
- Lesson: [LL-001 Harness Feature Evidence Closeout Miss](../lessons/LL-001-harness-feature-evidence-closeout-miss.md)
- Backlog: [Backlog](../BACKLOG.md)
- Design: [RPA Harness v0 Design](../rpa/harness/rpa-harness-v0-design.md)
- Schema: [Scenario Asset Schema](../rpa/harness/scenario-asset-schema.md)
- Strategy: [RPA Harness Regression Strategy](../rpa/harness/regression-strategy.md)

## Notes

This recovery uses system-level bundled Harness resources. ScienceClaw does not need to copy `scripts/` or `templates/` into the project unless future CI, GitHub Actions, or offline policy requires vendoring them.

Artifacts corrected in this recovery:

- `docs/features/F001-rpa-trace-source-convergence.md`
- `docs/features/F002-rpa-harness-v0.md`
- `docs/evidence/EV-001-rpa-trace-source-convergence.md`
- `docs/evidence/EV-002-rpa-harness-v0.md`
- `docs/decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md`
- `docs/decisions/ADR-002-trace-evidence-driven-compiler-strategy.md`
- `docs/lessons/LL-001-harness-feature-evidence-closeout-miss.md`

`docs/BACKLOG.md` was inspected and remains aligned with F002 active status, so no content change was needed in this recovery commit.

## Entry Gate

- Start Gate: high-risk product Harness feature with storage, capture, UI, CLI, and regression-runner behavior.
- Knowledge Retrieval: recovered from `docs/rpa/harness/*`, the implementation plan, recent commits, tests, and user self-bootstrap validation.
- Delegation Gate: user explicitly required subagents for complex work and independent Vision review.
- Vision Anchor: `docs/features/F002-rpa-harness-v0.md`.
- Non-goals: no site-specific architecture, no live URL primary oracle, no default capture when disabled, no contract-first recording layer.

## Feature Evidence Matrix

| Slice | Commit | Verification evidence |
| --- | --- | --- |
| F0 Document and plan anchor | `81e3f67 docs: define rpa harness v0` | Created `docs/rpa/harness/rpa-harness-v0-design.md`, `scenario-asset-schema.md`, `regression-strategy.md`, and implementation plan. |
| F1 Gate and models | `9b396d7 feat: add rpa harness asset gate and models` | Added config/model tests for disabled-by-default gate, capture scope, checkpoint schema, status, and sensitivity defaults. |
| F2 Capture session skeleton | `7b3a2d9 feat: add rpa harness capture session skeleton` | Added backend capture session tests; no HTML capture in disabled or skeleton path. |
| F3 Step checkpoints | `1836d97 feat: capture rpa harness step checkpoints` | Added checkpoint capture tests for before/after HTML, local store, and trace evidence files. |
| F4 Expected signals | `4a40f45 feat: draft expected signals for harness checkpoints` | Added expected-signal tests for natural-language/manual trace-derived signal drafts. |
| F5 Snapshot regression | `e63b3fc feat: add rpa harness snapshot regression` | Added snapshot regression runner and tests over captured HTML/expected signals. |
| F6 Compiler regression | `5dd5d25 feat: add rpa harness compiler regression` | Added compiler regression runner and tests for hardcoded values, dataflow refs, and generated skill checks. |
| F7 AI checkpoint integration | `ca2bddb feat: capture ai recording steps as harness assets` | Added AI capture integration tests for trace-first natural-language steps and disabled-path behavior. |
| F8 Capture controls | `77dcef1 feat: add rpa harness capture controls` | Added RecorderPage controls and tests for config-gated Full SOP / selected-step capture. |
| F9 Asset catalog | `58dc4e9 feat: add rpa harness asset catalog` | Added catalog CLI/tests for asset coverage, status, hosts, URLs, and page-pattern reporting. |
| F10 Blast-radius report | `a62362a feat: add rpa harness blast radius report` | Added blast-radius CLI/tests that combine snapshot/compiler findings with asset catalog context. |
| F11 State sync | `a967d0b fix: sync rpa harness capture state` | Added backend/frontend tests so selected-step state clears from backend capture truth. |
| F12 Scenario manifest | `f1ad336 feat: persist rpa harness scenario manifests` | Added manifest persistence tests preserving lifecycle metadata and checkpoint refs. |
| F13 Manual checkpoints | `74f2ce7 feat: capture manual rpa harness checkpoints` | Added manual checkpoint tests and JS syntax check for pre-event before-state capture. |
| F14 Expected-signal enrichment | `f03ba6f feat: enrich rpa harness expected signals` | Added expected-signal/compiler-regression tests for output keys, dataflow refs, hardcoded observed values, and empty-output evidence. |

## Post-F14 Self-Bootstrap Evidence

| Commit | Purpose | Evidence |
| --- | --- | --- |
| `8335380 fix: emit rpa harness cli reports as utf8` | Keep JSON reports readable for Chinese step intent on Windows console. | `test_rpa_harness_cli.py`. |
| `b6b6bbc fix: capture full sop entry navigation` | Improve Full SOP initial navigation capture. | AI capture integration and expected-signal tests. |
| `b9de022 fix: align harness step capture button state` | Align selected-step UI active/disabled state with Full SOP style. | `RecorderPage.test.ts`. |
| `73c5634 fix: capture full sop pure navigation checkpoints` | Capture pure navigation checkpoints from page baselines. | `test_full_sop_harness_captures_pure_navigation_checkpoint_from_page_baseline`. |
| `f48f2fc feat: validate rpa harness asset completeness` | Add offline asset integrity validation before interpreting regression results. | `test_rpa_harness_asset_validation.py`. |
| `a00b59c docs: document harness asset validation gate` | Document Level 0 asset validation gate. | `git diff --check` on harness docs. |

## F002 Residual Harness Triage Slice

Executed on branch `codex/rpa-trace-first-harness` on 2026-05-18.

Scope boundary:

- Harness captures facts, stores assets, and reports replay/regression evidence.
- This slice does not repair natural-language business extraction behavior.
- This slice does not add GitHub-specific selector or page rules.
- Asset validation remains an offline Evidence gate, not a recording-time blocker.

Implementation changes:

- Asset validation now reports `empty-after-html` when a successful changed-state checkpoint writes a zero-byte `after.html`.
- Checkpoint capture retries page content sampling briefly when `page.content()` is initially empty.
- Snapshot regression now normalizes split HTML text and distinguishes raw-signal absence from compact-snapshot loss.
- Compiler regression now separates executable observed-value hardcodes from comment/example observed-value pollution.

Focused verification:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_pure_navigation_checkpoint_from_page_baseline RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_manual_trace_checkpoint_from_event_before_html
```

Result:

```text
42 passed, 27 warnings in 1.41s
```

Local bootstrap asset validation after this slice:

```text
capture_count=6
issue_count=3
blocking_issue_count=0
categories={"empty-after-html": 1, "missing-entry-checkpoint": 2}
ASSET_VALIDATION_EXIT=0
```

Local bootstrap snapshot regression after this slice:

```text
total=13
passed=13
failed=0
SNAPSHOT_EXIT=0
```

Local bootstrap compiler regression after this slice:

```text
total=13
passed=12
failed=1
failure_category=compiler-hardcoded-observed-value
hardcoded_executable_values=["1.2k"]
hardcoded_comment_values=["13.4k", "1.2k", "13.7k stars"]
COMPILER_EXIT=1
```

Independent review:

- Vision Gate Entry reviewer: Ampere.
- Result: `ready to implement`.
- Key boundary: do not fix GitHub selectors, Planner, or business extraction in this slice; keep failures as Harness evidence.

## F002 Page-State Stabilization Slice

Executed on branch `codex/rpa-trace-first-harness` on 2026-05-18.

Scope boundary:

- Harness may wait briefly for a page state that is better evidence before writing `after.html`.
- Harness must still save the best observed state on timeout instead of blocking recording.
- This slice does not add Full SOP physical deduplication and does not repair business extraction or compiler generalization.

Implementation changes:

- Capture now samples page URL, title, HTML, body-text size, and `document.readyState` over a short window before persisting page state.
- Checkpoint page states now include `capture_quality` metadata such as `status`, `reason`, `attempts`, `settle_ms`, `html_bytes`, `body_text_chars`, `title_present`, and stability flags.
- Asset validation now reports non-blocking `shell-like-after-html` and `unstable-after-capture` findings for successful checkpoints that look like early navigation shells or partial captures.
- Existing hash-based `same_as_before` deduplication remains the only v0 storage optimization; complex Full SOP content-addressed dedupe is intentionally deferred.

Focused verification:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_pure_navigation_checkpoint_from_page_baseline RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_manual_trace_checkpoint_from_event_before_html
```

Result:

```text
44 passed, 27 warnings in 2.90s
```

Local bootstrap asset validation after this slice:

```text
capture_count=7
issue_count=3
blocking_issue_count=0
categories={"empty-after-html": 1, "missing-entry-checkpoint": 2}
ASSET_VALIDATION_EXIT=0
```

Local bootstrap snapshot regression after this slice:

```text
total=16
passed=16
failed=0
SNAPSHOT_EXIT=0
```

Local bootstrap compiler regression after this slice:

```text
total=16
passed=15
failed=1
failure_category=compiler-hardcoded-observed-value
hardcoded_executable_values=["1.2k"]
COMPILER_EXIT=1
```

## F002 Completion Validation

Executed on branch `codex/rpa-trace-first-harness` on 2026-05-18 after commit `2ec5508`.

Manual Full SOP capture used asset:

```text
data/rpa_harness_assets_bootstrap/hcap-ef3f5d7107ef4b1586dd533c6c7f8d41
```

The captured SOP had three consecutive checkpoints:

```text
step 1: navigate to https://github.com/trending
step 2: click link("tinyhumansai / openhuman") and navigate to the repository page
step 3: natural-language extraction of fork count
```

Navigation capture quality evidence:

```text
step 1 after_url=https://github.com/trending
step 1 after_title=Trending repositories on GitHub today - GitHub
step 1 after_html_bytes=662960
step 1 after_quality.status=stable
step 1 after_quality.attempts=4
step 1 after_quality.shell_like=false

step 2 after_url=https://github.com/tinyhumansai/openhuman
step 2 after_title=GitHub - tinyhumansai/openhuman: Your Personal AI super intelligence. Private, Simple and extremely powerful. - GitHub
step 2 after_html_bytes=429789
step 2 after_quality.status=stable
step 2 after_quality.attempts=4
step 2 after_quality.shell_like=false

step 3 after_same_as_before=true
step 3 before_quality.status=stable
step 3 output_key=fork_count
```

Local bootstrap asset validation after the completion capture:

```text
capture_count=8
issue_count=3
blocking_issue_count=0
categories={"empty-after-html": 1, "missing-entry-checkpoint": 2}
ASSET_VALIDATION_EXIT=0
```

The remaining asset-validation findings are historical draft assets and are no longer F002 blockers because the post-stabilization Full SOP capture has complete entry checkpoints and stable navigation `after.html`.

Local bootstrap snapshot regression after the completion capture:

```text
total=19
passed=19
failed=0
SNAPSHOT_EXIT=0
```

Local bootstrap compiler regression after the completion capture:

```text
total=19
passed=18
failed=1
failure_category=compiler-hardcoded-observed-value
hardcoded_executable_values=["1.2k"]
COMPILER_EXIT=1
```

The remaining compiler failure belongs to RPA Agent / `TraceSkillCompiler` generalization work. Harness has fulfilled its boundary by surfacing the failure as replayable regression evidence.

## Latest Verification Commands

Executed on branch `codex/rpa-trace-first-harness` on 2026-05-18:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_pure_navigation_checkpoint_from_page_baseline
```

Result:

```text
33 passed, 27 warnings in 1.01s
```

Local asset validation:

```powershell
$env:PYTHONPATH='.'
python -m backend.rpa.harness.run_asset_validation --assets ..\data\rpa_harness_assets_bootstrap --output ..\tmp-harness-asset-validation.json
```

Result:

```json
{
  "capture_count": 3,
  "issue_count": 2,
  "blocking_issue_count": 0,
  "categories": {
    "missing-entry-checkpoint": 2
  }
}
```

Catalog:

```powershell
$env:PYTHONPATH='.'
python -m backend.rpa.harness.run_catalog --assets ..\data\rpa_harness_assets_bootstrap --output ..\tmp-harness-catalog.json
```

Result summary:

```json
{
  "capture_count": 3,
  "step_count": 5,
  "successful_step_count": 5,
  "failed_step_count": 0,
  "asset_statuses": {
    "draft": 3
  }
}
```

Snapshot regression over local bootstrap assets:

```powershell
$env:PYTHONPATH='.'
python -m backend.rpa.harness.run_snapshot_regression --assets ..\data\rpa_harness_assets_bootstrap
```

Result:

```text
total=5, passed=4, failed=1
failure_category=compact-snapshot-lost-signal
missing_text=["tinyhumansai / openhuman"]
```

Compiler regression over local bootstrap assets:

```powershell
$env:PYTHONPATH='.'
python -m backend.rpa.harness.run_compiler_regression --assets ..\data\rpa_harness_assets_bootstrap
```

Result:

```text
total=5, passed=4, failed=1
failure_category=compiler-hardcoded-observed-value
hardcoded_values=["13.4k"]
```

## Independent Review Records

Independent Vision review during post-F14 asset validation work concluded:

- Direction is valid only if anchored in accepted trace/checkpoint schema and generic Full SOP evidence chain.
- Do not special-case GitHub.
- Full SOP must cover complete accepted timeline evidence, especially entry navigation.
- Asset validation should be offline report/evidence, not runtime hard block.
- Generic failure categories are correct: `missing-entry-checkpoint`, `step-index-gap`, `successful-step-missing-html`, etc.

An additional post-incident audit was requested after the user identified the missing F0-F14 Feature/Evidence records. Its findings should be appended when complete.

## Incident Recovery Evidence

User-reported issue:

```text
F01 到 F14 没有沉淀 Feature 等相关材料，没有遵从 harness 相关 skill。
```

Confirmed facts:

- `docs/features` only had F001 before this recovery.
- `docs/evidence` only had EV-001 before this recovery.
- RPA Harness v0 had design docs and an implementation plan, but no dedicated Feature/Evidence/Lesson closeout record for F0-F14.
- The implementation plan was updated for some later slices, but it was not a substitute for Feature/Evidence closeout.

Recovery actions:

- Created `docs/features/F002-rpa-harness-v0.md`.
- Created this Evidence record.
- Created `docs/lessons/LL-001-harness-feature-evidence-closeout-miss.md`.
- Created `docs/BACKLOG.md` with active recovery/follow-up state.
- Added a project rule requiring Feature/Evidence updates before moving between multi-feature Harness slices.

## Residual Findings

- Current bootstrap assets are useful but not all old draft captures should become golden fixtures.
- Two older draft Full SOP assets are missing entry checkpoint evidence; this remains visible through asset validation.
- One older draft Full SOP asset has an `empty-after-html` issue on a successful click-navigation checkpoint; this remains visible through asset validation.
- The post-stabilization Full SOP asset `hcap-ef3f5d7107ef4b1586dd533c6c7f8d41` has complete entry checkpoints and stable navigation `after.html`.
- Snapshot regression currently passes for all local bootstrap assets after normalized split-text matching.
- One selected-step fork extraction asset still fails compiler regression with executable observed-value hardcoding: `1.2k`; this is follow-up RPA Agent / `TraceSkillCompiler` work rather than F002 Harness infrastructure.
- Comment/example observed-value pollution is reported separately as `hardcoded_comment_values` and no longer fails compiler regression by itself.
- These residuals should be treated as follow-up evidence, not hidden by passing unit tests.

## Closeout Status

- Feature: F002 completed.
- Evidence level: exhaustive, reconstructed.
- ADR: not triggered; no new architecture decision beyond existing Harness v0 design.
- Lesson: LL-001 written because recurrence risk is high.
- Completion claim: allowed for F002 v0. Residual compiler and asset-curation items are follow-up work, not blockers for the Harness v0 infrastructure.
- Implementation readiness for post-F002 slices: start new Feature/Evidence records or update this Evidence only when the follow-up is clearly scoped to F002 maintenance.

## F002.5 Initial Navigation Capture Quality Classification

Started on branch `codex/rpa-trace-first-harness` on 2026-05-18.

Trigger asset:

```text
data/rpa_harness_assets_bootstrap/hcap-62867b45092c428db297312f2b43f4e6
```

Observed symptom:

```text
step 1 after_url=https://github.com/trending
step 1 after_title=
step 1 after_html_bytes=10597
step 1 after_quality.status=stable
step 1 after_quality.ready_state=loading
step 1 after_quality.title_present=false
```

Root cause hypothesis:

`_capture_stable_page_state()` can classify an early navigation shell as stable when URL/title/HTML remain unchanged across samples, even if the browser still reports `document.readyState=loading` and the captured page lacks normal document evidence.

Scope boundary:

- Fix generic capture-quality classification for navigation-like changed page states.
- Do not add GitHub-specific rules.
- Do not block the recording path.
- Do not repair planner, selector, business extraction, or compiler behavior.
- Save best-effort page evidence on timeout, but mark it as `partial` when navigation readiness is not trustworthy.

Planned verification:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_pure_navigation_checkpoint_from_page_baseline
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

RED verification before implementation:

```text
2 failed in 0.47s
```

Failing tests:

- `test_loading_navigation_after_state_is_saved_as_partial_not_stable`
- `test_validation_reports_loading_after_capture_even_if_marked_stable`

Implementation changes:

- `_capture_stable_page_state()` no longer treats `document.readyState=loading` samples as stable, even when URL/title/HTML are unchanged across samples.
- Best-effort loading samples are still saved, but their `capture_quality.status` becomes `partial` with `reason=navigation_after_not_ready`.
- Asset validation reports `loading-after-capture` as a non-blocking warning for successful checkpoints captured while `document.readyState` was still `loading`.
- Existing best-sample scoring remains only a fallback selection mechanism after timeout; it does not decide stable vs partial.

Focused GREEN verification:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_pure_navigation_checkpoint_from_page_baseline RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_manual_trace_checkpoint_from_event_before_html
```

Result:

```text
34 passed, 27 warnings in 1.44s
```

Broader Harness regression verification:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_models.py RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_harness_catalog.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py RpaClaw/backend/tests/test_rpa_harness_blast_radius.py RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_pure_navigation_checkpoint_from_page_baseline RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_manual_trace_checkpoint_from_event_before_html
```

Result:

```text
63 passed, 27 warnings in 1.74s
```

Trigger asset validation after this fix:

```text
capture_count=1
issue_count=1
blocking_issue_count=0
categories={"loading-after-capture": 1}
```

Closeout status:

- Feature patch: F002.5 completed.
- Implementation commit: `1a0fa48`.
- Evidence level: standard for the bugfix, linked from F002's exhaustive Evidence.
- ADR: not triggered; no new architecture decision.
- Lesson: not triggered; F002 already has Patch Churn Review and this fix stays within its invariant.
- Residual risk: real Full SOP recapture should be run before promoting this page shape to golden. Existing draft asset remains valid diagnostic evidence but now reports a quality warning.

## F002.6 Manual Fill Checkpoint Capture And Input Parameterization

Executed on 2026-06-01.

User-reported symptom:

```text
Full SOP Harness recorded the click into an account input, but did not record the subsequent fill value such as test1.
```

Root cause:

- `_capture_manual_harness_checkpoint_for_step()` allowed `click`, `press`, and navigation-like actions, but excluded manual `fill`.
- Pure focus clicks on text inputs could be captured as standalone checkpoints even though their semantic purpose was the following fill.
- Full SOP checkpoint paths followed trace indexes, so skipped actions could leave gaps such as `001`, `002`, `003`, `005`.

Implementation changes:

- Manual `fill` now becomes a Full SOP Harness checkpoint.
- Fill values are parameterized before asset persistence as `{{input:<key>}}`.
- The raw input value is replaced across `trace_events.json`, `before.html` / `after.html`, and generated `expected.json` evidence.
- `expected.json` records `state_signals.sanitized_replay_contract.runtime_input_refs`.
- Text-input focus clicks are not persisted as standalone Harness checkpoints.
- Full SOP checkpoint indexes are allocated from persisted checkpoints, while existing checkpoint rewrites keep their original index.
- `TraceSkillCompiler` compiles `{{input:key}}` values as `kwargs.get("key", "{{input:key}}")`, allowing sanitized assets to replay with either injected runtime input or a controlled sanitized fallback.

Focused RED/GREEN verification:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_manual_fill_with_parameterized_value
```

RED result:

```text
FAILED ... FileNotFoundError ... steps/001/checkpoint.json
```

GREEN result:

```text
1 passed in 0.37s
```

Additional RED/GREEN verification:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_folds_text_input_focus_click_into_fill_checkpoint
python -m pytest -q RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_manual_fill_uses_harness_input_placeholder_runtime_param
```

Initial failures confirmed the old behavior captured both focus click and fill checkpoints, and compiled `{{input:account}}` as a literal value. Final focused result:

```text
3 passed in 0.97s
```

Focused regression:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-harness-fill RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_manual_trace_checkpoint_from_event_before_html RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_pure_navigation_checkpoint_from_page_baseline RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_manual_fill_with_parameterized_value RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_folds_text_input_focus_click_into_fill_checkpoint RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_manual_fill_uses_harness_input_placeholder_runtime_param RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_manual_fill_uses_sensitive_credential_param RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py
```

Result:

```text
33 passed in 1.41s
```

Sensitivity/sanitization/stateful smoke:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-harness-fill-extra RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py RpaClaw/backend/tests/test_rpa_harness_asset_sanitization.py RpaClaw/backend/tests/test_rpa_harness_stateful_sop.py
```

Result:

```text
17 passed, 1 failed
```

The failure was `test_stateful_sop_replays_real_governed_candidate_asset`, where the current local bootstrap pool returned `eligible_capture_count=0` instead of the test's expected `1`. This is a local asset-pool state issue and not a failure in the new fill-capture path.

Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

Result before this Evidence section:

```text
Scanned 256 markdown file(s). Checked 50 knowledge artifact(s). Errors: 0. Warnings: 0.
```

Closeout status:

- Feature patch: F002.6 completed.
- Evidence level: standard for a non-trivial Harness bugfix.
- ADR: not triggered; the patch keeps the existing trace-first and asset-governance boundary.
- Lesson: not triggered; protection is executable tests plus F002 Patch History.
- Residual risk: real internal Full SOP assets should be recaptured/reviewed before promotion so existing assets with missing fill steps are not mistaken for healthy baselines.

## F002.7 Fill Checkpoint Before-State Fallback

Executed on 2026-06-01.

User-reported symptom:

```text
Manual validation showed the account input focus click was no longer captured, and the following test1 fill still did not appear as a Harness step.
```

Root cause:

- The injected browser capture script only attaches `harness_before_page_state` to `click` and `press` actions.
- F002.6 intentionally skipped text-input focus-click checkpoints as noise, but its regression test covered a `fill` event that already carried its own before-state.
- In the real event stream, the skipped focus click held the only before-state that the fill checkpoint needed, so the fill checkpoint writer returned before persisting `steps/001`.

Implementation changes:

- A manual `fill` event without its own before-state now reuses the immediately preceding same-target text-input focus click's `harness_before_page_state`.
- The reused focus click must match source, tab, frame path, locator target, and adjacent sequence or a short timestamp window.
- The text-input focus click is still folded out of persisted Harness steps, so the asset records the semantic fill checkpoint rather than a click-plus-fill noise pair.

Focused RED/GREEN verification:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-harness-fill-followup RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_reuses_focus_click_before_state_for_fill_checkpoint
```

RED result:

```text
FAILED ... FileNotFoundError ... hcap-.../steps
```

GREEN result:

```text
1 passed in 0.41s
```

Focused regression:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-harness-fill-followup RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_manual_trace_checkpoint_from_event_before_html RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_pure_navigation_checkpoint_from_page_baseline RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_manual_fill_with_parameterized_value RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_folds_text_input_focus_click_into_fill_checkpoint RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_reuses_focus_click_before_state_for_fill_checkpoint RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_manual_fill_uses_harness_input_placeholder_runtime_param RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_manual_fill_uses_sensitive_credential_param RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py
```

Result:

```text
34 passed in 1.14s
```

Incident learning:

- Trigger: F002.6 was validated against a synthetic fill event with before-state, while the production browser capture path puts before-state on the preceding click.
- Recurrence protection: the new regression test reproduces the production event shape and asserts that only `steps/001` fill is persisted, with the raw `test1` value sanitized out.
- Lesson: not triggered; the durable protection is an executable test tied to the actual capture event boundary, plus this F002 patch row.

Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

Result:

```text
Scanned 256 markdown file(s). Checked 50 knowledge artifact(s). Errors: 0. Warnings: 0.
```

## F002.8 Full SOP Checkpoint Timeline Flush

Executed on 2026-06-01.

User-provided trigger evidence:

```text
recording session: 95481fbc-0c5b-458c-b898-45d390831c1d
asset: data/rpa_harness_assets_bootstrap/hcap-db57fa877b8a45f6b20125710d0ac496
```

Observed asset symptom:

- The generated Skill script contained the semantic login traces: navigate root, navigate login, click username, fill username, fill password, click submit, click menu item.
- The Harness asset only persisted password fill and later navigation checkpoints; the username click/fill facts were present in the accepted trace timeline but missing from `steps/`.

Root cause:

- Manual Full SOP checkpoint writing was tied to per-event processing time.
- Browser recording events are emitted through async bindings, so the manager can process a later `fill` before the earlier same-target input-focus `click`.
- F002.7 could reuse a preceding focus click only when that click had already been inserted before the fill. In the real asset, the fill arrived first, had no before-state, and was skipped. When the earlier click arrived later, it was inserted before the fill in `session.steps`, but it was intentionally folded out as focus-click noise and did not trigger a revisit of the existing fill.
- This explains why the Skill timeline was correct while the Harness asset was incomplete: Skill compilation used sorted accepted traces, while checkpoint persistence used event arrival side effects.

Implementation changes:

- Manual Full SOP checkpoint capture now records in-memory checkpoint candidates for eligible manual events instead of treating the first arrival as the final persistence decision.
- The flush path iterates sorted `session.steps`, skips text-input focus clicks as standalone checkpoints, and writes persisted checkpoint indexes from the semantic timeline.
- A fill checkpoint without its own before-state can be backfilled from a same-target text-input focus click that arrives later but sorts immediately before the fill.
- Rewriting uses the requested Full SOP checkpoint index so an earlier semantic step can overwrite stale `steps/001` and shift later semantic checkpoints to contiguous indexes.
- Captured HTML is sanitized with cumulative known input replacements through the current semantic step, so later checkpoints do not reintroduce earlier username values in `after.html`.

Focused RED verification:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-harness-flush-red RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_backfills_out_of_order_fill_checkpoint_from_late_focus_click
```

RED result:

```text
FAILED ... AssertionError: Lists differ: ['001'] != ['001', '002']
```

Focused GREEN verification:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-harness-flush-green RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_backfills_out_of_order_fill_checkpoint_from_late_focus_click
```

GREEN result:

```text
1 passed in 0.73s
```

Focused regression:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-harness-focused RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_manual_trace_checkpoint_from_event_before_html RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_pure_navigation_checkpoint_from_page_baseline RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_manual_fill_with_parameterized_value RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_folds_text_input_focus_click_into_fill_checkpoint RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_reuses_focus_click_before_state_for_fill_checkpoint RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_backfills_out_of_order_fill_checkpoint_from_late_focus_click RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_manual_fill_uses_harness_input_placeholder_runtime_param RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_manual_fill_uses_sensitive_credential_param RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py
```

Result:

```text
35 passed in 0.89s
```

Broader manager regression:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-rpa-manager RpaClaw/backend/tests/test_rpa_manager.py
```

Result:

```text
103 passed in 1.74s
```

Incident learning:

- Trigger: manual validation used a realistic login SOP where async browser event delivery did not match semantic action order.
- Patch-chain review: F002.6 fixed fill eligibility, F002.7 fixed missing fill before-state in normal order, and F002.8 moved the persistence boundary upstream to the sorted accepted timeline.
- Recurrence protection: the new regression reproduces a fill event arriving before its earlier focus click and asserts two persisted semantic checkpoints, contiguous scenario refs, username fill first, password fill second, and no raw username in persisted trace/HTML evidence.
- Lesson: not created; the durable protection is an executable regression tied to the Harness timeline invariant plus the F002 Patch Churn Review update.

Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

Result:

```text
Scanned 256 markdown file(s). Checked 50 knowledge artifact(s). Errors: 0. Warnings: 0.
```

## F002.9 Checkpoint Intent Input Sanitization

Executed on 2026-06-01.

User-provided follow-up asset:

```text
data/rpa_harness_assets_bootstrap/hcap-68802fbce2124f10957b3105cf8d9123
```

Asset inspection result:

- `scenario.json` contained contiguous checkpoint refs `001` through `006`.
- Persisted actions matched the provided SOP: root navigation, login navigation, username fill, password fill, login submit navigation, and menu navigation.
- `trace_events.json` had `{{input:login_username}}` and `{{input:login_password}}`.
- HTML search found no raw `admin` or `secret`.
- Residual issue: `steps/003/checkpoint.json.step_intent` still contained `输入 "admin" 到 testid("login-username")`.

Root cause:

- F002.8 sanitized trace events and page states using the input replacement map.
- The checkpoint's human-readable `step_intent` was written from the pre-sanitized trace description, so a non-sensitive runtime input could still appear in the review entry point.

Implementation changes:

- `capture_step_checkpoint()` now applies the same input replacement map to `step_intent`.
- The fill-capture regression now asserts that `checkpoint.json.step_intent` uses the placeholder and that `checkpoint.json` is included in raw-value absence checks.

Focused verification:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-harness-intent RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_manual_fill_with_parameterized_value
```

Result:

```text
1 passed in 1.27s
```

Focused regression:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-harness-focused RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_manual_trace_checkpoint_from_event_before_html RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_pure_navigation_checkpoint_from_page_baseline RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_manual_fill_with_parameterized_value RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_folds_text_input_focus_click_into_fill_checkpoint RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_reuses_focus_click_before_state_for_fill_checkpoint RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_backfills_out_of_order_fill_checkpoint_from_late_focus_click RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_manual_fill_uses_harness_input_placeholder_runtime_param RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_manual_fill_uses_sensitive_credential_param RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py
```

Result:

```text
35 passed in 3.16s
```

Broader manager regression:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-rpa-manager RpaClaw/backend/tests/test_rpa_manager.py
```

Result:

```text
103 passed in 4.68s
```

Asset validation command:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_validation --assets data\rpa_harness_assets_bootstrap --output tmp-harness-validation-bootstrap-current.json
```

Result:

```text
summary.capture_count=6
summary.issue_count=4
summary.blocking_issue_count=0
summary.categories={"unstable-after-capture": 4}
hcap-68802fbce2124f10957b3105cf8d9123 had no validation issue entry.
```

## F002.10 Paste Input Normalization

Executed on 2026-06-01.

User-provided internal trace evidence:

```text
steps/003 action=press value=V target=textbox("W3账号")
steps/004 action=press value=V target=textbox("密码")
```

User confirmed that account, password, and other input fields were filled via
`Ctrl+V` paste. This is a normal user input method and should compile to
replayable `fill` calls, not keyboard `press` steps.

Root cause:

- The browser action recorder filtered `Ctrl+V` only when `event.key` was
  lowercase `v`; an uppercase `V` could leak as `press V`.
- The screencast paste channel used CDP `Input.insertText`, but did not
  explicitly ask the injected recorder to persist the current focused editable
  value as a `fill` trace when the page did not emit a usable input event.
- Once the accepted trace only contained `press V`, Harness review and
  `TraceSkillCompiler` had no replay-safe input value to render as `fill`.

Implementation changes:

- Paste shortcuts are filtered case-insensitively in
  `playwright_recorder_actions.js`.
- Real paste events on editable fields emit semantic `fill` actions with
  `signals.input_method.source_method=paste`.
- `playwright_recorder_capture.js` exposes
  `window.__rpaRecordCurrentEditableFill()` so screencast paste can convert the
  focused editable's final value into a normal recorder `fill` event.
- `SessionScreencastController._dispatch_paste()` calls that helper after
  `Input.insertText`.
- Existing fill merge, input parameterization, password sensitivity, and
  checkpoint flushing remain the downstream normalization path.

Focused RED/GREEN verification:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw\backend\tests\test_rpa_recorder_actions_js.py -q
python -m pytest RpaClaw\backend\tests\test_rpa_screencast.py::SessionScreencastControllerTests::test_dispatch_paste_requests_current_editable_fill_capture -q
```

RED result:

```text
test_ctrl_v_uppercase_does_not_emit_press_action failed with emitted press V
test_paste_on_text_input_emits_fill_action failed because listeners.paste was missing
test_dispatch_paste_requests_current_editable_fill_capture failed because page.evaluate was not called
```

GREEN result:

```text
RpaClaw/backend/tests/test_rpa_recorder_actions_js.py: 3 passed
targeted screencast paste test: 1 passed
```

Focused regression:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw\backend\tests\test_rpa_recorder_actions_js.py RpaClaw\backend\tests\test_rpa_screencast.py -q
python -m pytest RpaClaw\backend\tests\test_rpa_manager.py -k "fill or capture_js or action_runtime or paste or sequence_order" -q
```

Result:

```text
15 passed, 59 warnings
28 passed, 75 deselected
```

Closeout notes:

- Feature patch: F002.10 completed.
- Evidence level: standard for this follow-up bugfix.
- ADR: not triggered; the fix preserves trace-first recording and treats paste
  as another input boundary, not a new contract layer.
- Lesson: not triggered; F002 already has Patch Churn Review, and protection is
  executable regression plus updated Harness docs.
- Residual risk: existing internal assets that already persisted `press V`
  remain diagnostic evidence; they should be recaptured after this fix if they
  are candidates for promotion.

## F002.11 Fill Input Contract Naming

Executed on 2026-06-02.

Scope boundary:

- This slice improves only sanitized fill input contract names such as
  `{{input:w3_account}}`, `{{input:password}}`, and `{{input:textbox_1}}`.
- It does not change recorder event capture, accepted trace sorting,
  `manual_step_to_trace`, `TraceSkillCompiler` action rendering, or download
  side-effect merging.

Root cause:

- The previous key derivation stripped non-ASCII label text, so labels such as
  `W3账号` and `密码` could collapse to `w3` or `input`.
- Weak locators such as `textbox >> nth=0` did not recurse into their base role,
  so they also fell back to generic `input`.
- `manager.py` and `harness/capture.py` carried duplicate key derivation logic,
  increasing the chance of future drift between full-sop cumulative
  sanitization and checkpoint persistence.

Implementation changes:

- Added `backend.rpa.harness.input_contract.derive_fill_input_key()` as a
  deterministic fill-only helper.
- The helper preserves explicit existing `input_contract.input_key`, derives
  names from target evidence and selected locator candidates, maps common
  field-label terms such as account/password/query to stable ASCII tokens, and
  falls back to stable weak-locator names such as `textbox_1`.
- `harness.capture` and `manager` now share this helper for write-time
  parameterization and cumulative input replacements.
- Non-fill traces are untouched; tests assert a click trace's
  `signals.download` remains unchanged while adjacent fill traces are renamed.

Focused RED verification:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-harness-input-names RpaClaw\backend\tests\test_rpa_harness_expected_signals.py -k "semantic_input_keys or weak_nth" -q
```

RED result:

```text
test_fill_parameterization_uses_semantic_input_keys_without_touching_download
  expected {{input:w3_account}}, got {{input:w3}}
test_fill_parameterization_names_weak_nth_textbox_locator_stably
  expected {{input:textbox_1}}, got {{input:input}}
```

Focused GREEN/regression verification:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-harness-input-names RpaClaw\backend\tests\test_rpa_harness_expected_signals.py -k "semantic_input_keys or weak_nth" -q
python -m pytest --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-harness-input-names RpaClaw\backend\tests\test_rpa_harness_expected_signals.py RpaClaw\backend\tests\test_rpa_harness_checkpoint_capture.py RpaClaw\backend\tests\test_rpa_manager.py RpaClaw\backend\tests\test_rpa_recorder_actions_js.py RpaClaw\backend\tests\test_rpa_screencast.py RpaClaw\backend\tests\test_rpa_trace_skill_compiler.py -k "harness or fill or paste or download" -q
```

Result:

```text
2 passed, 8 deselected
56 passed, 191 deselected
```

Closeout notes:

- Feature patch: F002.11 completed.
- Evidence level: standard for this follow-up enhancement.
- ADR: not triggered; this preserves the trace-first boundary and does not add
  a contract-first recording layer.
- Lesson: not triggered; the F002 Patch Churn Review now records the boundary
  that readability improvements belong in fill-only sanitization metadata.
- Residual risk: weak unlabeled inputs still cannot receive true business
  semantics without user/DOM evidence; they now receive stable names such as
  `textbox_1` instead of generic `input`.

## F002.12 Scoped Fill Value Sanitization

Executed on 2026-06-02.

Scope boundary:

- This slice fixes Harness asset persistence only.
- It does not change recorder event capture, RPA manager ordering,
  `RecordingRuntimeAgent`, `TraceSkillCompiler`, Recorder UI, or runtime skill
  replay behavior.
- It keeps fill parameterization as a write-time Harness asset concern rather
  than introducing a contract-first recording layer.

Root cause:

- `harness.capture` reused one `replacements` map for three different
  surfaces: trace nodes, human-readable `step_intent`, and full captured HTML.
- The trace path recursively replaced every string field, so raw input `a`
  could corrupt selector metadata and even the generated placeholder itself.
- The HTML path applied bare `str.replace()` to the whole document, so ordinary
  tags, attribute names, labels, and body text could be rewritten into invalid
  HTML.

Implementation changes:

- `fill` trace parameterization now only changes the structured `value` field
  and adds `signals.input_contract`.
- Human-readable text replacement now uses ASCII token boundaries, so `a` in
  `Fill a into the Name field` is replaced while `Name` is preserved.
- Captured HTML sanitization now only replaces complete recorded values inside
  `input[value]` and `textarea` contents; labels, tag names, attribute names,
  selectors, and other trace metadata are preserved.

Focused RED verification:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp .pytest-tmp-pr59-harness-red RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py::test_fill_parameterization_preserves_trace_metadata_and_html_structure
```

RED result:

```text
expected {{input:name}}, got {{input:n{{input:name}}me}}
```

Focused GREEN/regression verification:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp .pytest-tmp-pr59-harness-green-one RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py::test_fill_parameterization_preserves_trace_metadata_and_html_structure
python -m pytest -q --basetemp .pytest-tmp-pr59-harness-green-checkpoint RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py
python -m pytest -q --basetemp .pytest-tmp-pr59-harness-green-ai RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py
python -m pytest -q --basetemp .pytest-tmp-pr59-harness-green-compiler RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py
python -m pytest -q --basetemp .pytest-tmp-pr59-harness-focused RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_harness_checkpoint_capture.py RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_full_sop_harness_captures_pure_navigation_checkpoint_from_page_baseline
```

Result:

```text
single regression: 1 passed
checkpoint capture: 11 passed
AI capture integration: 6 passed, 29 warnings
trace skill compiler: 109 passed
focused F002 Harness set: 53 passed, 29 warnings
```

Closeout notes:

- Feature patch: F002.12 completed.
- Evidence level: exhaustive for this high-risk Harness asset-fact follow-up,
  because the fix includes RED/GREEN proof plus focused F002 Harness regression.
- ADR: not triggered; the fix preserves the existing Trace-first Recording +
  Post-hoc Skill Compilation boundary.
- Lesson: not triggered; F002 Patch Churn Review now records the new boundary,
  and the protection is executable regression.
- Residual risk: already captured draft assets with globally rewritten HTML
  remain historical evidence; they should be recaptured before any promotion to
  `candidate` or `golden`.
