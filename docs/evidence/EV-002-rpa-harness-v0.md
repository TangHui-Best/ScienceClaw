---
doc_kind: evidence
id: EV-002
title: RPA Harness v0 Evidence
status: active
scope: project
feature_ids: [F002]
created: 2026-05-18
updated: 2026-05-18
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
