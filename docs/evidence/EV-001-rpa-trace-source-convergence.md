---
doc_kind: evidence
id: EV-001
title: RPA Trace Source Convergence Evidence
status: active
feature_ids: [F001]
created: 2026-05-13
updated: 2026-05-13
evidence_level: exhaustive
---

# EV-001 RPA Trace Source Convergence Evidence

## Scope

Evidence for F001: remove `step` / `recorded_actions` / `recording_diagnostics` / `legacy_steps` as RPA business facts and make trace the sole accepted timeline across backend, frontend, generate/test/save, and MCP/export.

## Entry Gate

- Start Gate: high-risk architecture migration.
- Vision Gate Entry: pass condition is source convergence, not observability feature work.
- Delegation Gate: user explicitly required subagent implementation and review.
- Durable anchors: `docs/features/F001-rpa-trace-source-convergence.md`, `docs/decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md`, the existing spec, and the implementation plan.

## Subagent Records

Read-only exploration:

- Backend dependency inventory: completed by Averroes on 2026-05-13.
- Frontend dependency inventory: completed by Franklin on 2026-05-13.
- MCP/export/compiler inventory: replacement explorer pending after first explorer disconnected.
- Harness/test strategy review: completed by Godel on 2026-05-13.

Implementation and review records will be appended per task:

### Task 1 Backend Trace Timeline Projection

- Implementer: Nietzsche.
- RED verification:
  - Command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_trace_timeline.py -q`
  - Result: `ModuleNotFoundError: No module named 'backend.rpa.trace_timeline'`.
- Implementation:
  - Added `RpaClaw/backend/rpa/trace_timeline.py`.
  - Added trace-only `_build_session_timeline(session)` and timeline route wiring in `RpaClaw/backend/route/rpa.py`.
  - Added `RpaClaw/backend/tests/test_rpa_trace_timeline.py`.
- Spec-compliance reviewer: Confucius.
  - First result: FAIL because helper parameter was named `diagnostics` instead of explicit `trace_diagnostics`.
  - Fix: renamed helper contract and callers to `trace_diagnostics`.
  - Re-review: PASS.
- Code-quality reviewer: Bacon.
  - First result: CHANGES_REQUESTED, Important mutation-isolation issue on nested projected payloads.
  - Fix: deep-copied mutable projection payloads and added mutation-isolation test.
  - Re-review: APPROVED.
- GREEN verification:
  - Command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_trace_timeline.py -q`
  - Implementer result: `5 passed, 24 warnings`.
  - Controller rerun result: `5 passed, 24 warnings in 6.84s`.
- Residual risk:
  - Route test currently stubs `langchain_*` import-time dependencies to import `backend.route.rpa`. Reviewer marked this as Minor and non-blocking for Task 1; future route-support extraction may reduce brittleness.

### Task 2 Trace-native Backend Mutation APIs

- Implementer: Noether.
- Initial blocker:
  - Command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_route_trace.py -q -k "delete_trace_route_ignores_legacy_step_fallback_poison or promote_trace_locator_route_selects_candidate_by_trace_id"`
  - Result: collection failed because local environment lacks `langchain_core` required by module-level `backend.route.chat` import.
  - Resolution: moved Task 2 tests into focused `RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py` with local import stubs, keeping production code untouched for the dependency issue.
- RED verification:
  - Command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py -q`
  - Result: `1 failed, 2 passed`; `test_delete_trace_route_uses_trace_id_and_ignores_legacy_poison` showed stale `runtime_results["deleted"]` after trace deletion.
- Implementation:
  - Removed `delete_trace()` detour from manual `trace-*` ids back into `delete_step_by_id()`.
  - Added poison-pill trace mutation route tests for trace delete, trace locator promotion/dataflow update, and diagnostic delete.
- Spec-compliance reviewer: Dewey.
  - Result: PASS.
- Code-quality reviewer: Mill.
  - Result: APPROVED.
- GREEN verification:
  - Implementer command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py -q`
  - Implementer result: `3 passed, 24 warnings`.
  - Controller command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py RpaClaw/backend/tests/test_rpa_trace_timeline.py -q`
  - Controller result: `8 passed, 24 warnings in 5.24s`.
- Residual risk:
  - Broader `test_rpa_route_trace.py` still cannot collect in this local environment without `langchain_core`; this is an environment/dependency blocker already present before Task 2.

### Task 3A Frontend Timeline Utility Projection-only Mapping

- Implementer: Rawls.
- RED verification:
  - Command: `npm.cmd --prefix RpaClaw/frontend test -- rpaConfigureTimeline`
  - Result: `3 failed, 2 passed`; failures showed `mapRpaConfigureDisplaySteps()` still fell back to legacy sources and did not use projection ids as required.
- Implementation:
  - Changed `RpaClaw/frontend/src/utils/rpaConfigureTimeline.ts` so display steps map from `session.timeline` only.
  - `getLegacyRpaSteps()` returns `[]` for the new path.
  - Diagnostic mapping uses `diagnosticId` instead of step indexes.
  - Added poison-pill tests proving `steps`, `recorded_actions`, and `recording_diagnostics` markers are ignored.
- Spec-compliance reviewer: Parfit.
  - Result: PASS.
- Code-quality reviewer: Hilbert.
  - First result: CHANGES_REQUESTED, Important diagnostic identity ambiguity because diagnostic rows also set primary `traceId`.
  - Fix: diagnostic rows now keep `diagnosticId` and do not set primary `traceId`.
  - Re-review: APPROVED.
- GREEN verification:
  - Implementer command: `npm.cmd --prefix RpaClaw/frontend test -- rpaConfigureTimeline`
  - Implementer result after identity fix: `6 passed`.
  - Controller rerun result: `6 passed` in focused test.
- Type-check:
  - Command: `npm.cmd --prefix RpaClaw/frontend run type-check`
  - Result: failed on existing unrelated frontend errors across multiple files.
  - Task-related `src/utils/rpaConfigureTimeline.ts(139,35): TS6133 'session' is declared but never read` was fixed and no longer appears.
- Residual risk:
  - Vue pages still need follow-up tasks to stop calling legacy delete/promotion/failure APIs; Task 3A only updates the shared utility.

### Task 3B ConfigurePage Projection-only Consumption

- Implementer: Worker agent from subagent-driven workflow.
- RED verification:
  - Command: `npm.cmd --prefix RpaClaw/frontend test -- ConfigurePage`
  - Result: failed because a projected item without `trace_id` still fell back to `/rpa/session/{session_id}/step/{index}/locator`.
- Implementation:
  - Removed `getLegacyRpaSteps` / `legacySteps` consumption from `RpaClaw/frontend/src/pages/rpa/ConfigurePage.vue`.
  - Changed ConfigurePage parameter and start-URL inference to use `session.timeline` projection only.
  - Removed locator promotion fallback to `/step/{index}/locator`.
  - Removed diagnostic deletion fallback to `/step/{index}`.
  - Preserved diagnostic-specific related `traceId` for locator promotion without exposing diagnostic rows as primary trace timeline rows.
  - Added ConfigurePage poison-pill tests for ignored legacy sources and no `/step/` mutation calls.
- Spec-compliance reviewer: Hubble.
  - Result: PASS.
- Code-quality reviewer: Locke.
  - First result: CHANGES_REQUESTED because diagnostic projection dropped related `trace_id`, disabling valid diagnostic locator promotion.
  - Fix: `getManualRecordingDiagnostics()` now preserves `item.trace_id` as diagnostic-specific `traceId`, while `mapRpaTimelineProjection()` still keeps diagnostic display rows without primary `traceId`.
  - Added page-level test for diagnostic locator promotion through `/trace/{traceId}/locator`.
  - Re-review: APPROVED by Pascal.
- GREEN verification:
  - Command: `npm.cmd --prefix RpaClaw/frontend test -- ConfigurePage rpaConfigureTimeline`
  - Controller result: `2 passed`, `13 passed` tests.
- Residual risk:
  - `promotingStepIndex` uses `-1` as a coarse diagnostic mutation lock, so multiple diagnostic buttons share loading state during one diagnostic operation. Reviewer marked this non-blocking for Task 3B.

### Task 3C RecorderPage Trace-only Recording Display and Completion Count

- Implementer: controller.
- Implementation:
  - Changed `RpaClaw/frontend/src/pages/rpa/RecorderPage.vue` polling refresh so recorder display uses `session.timeline` projection, with raw `traces` only as accepted-trace fallback, and no longer uses `session.steps` / `recorded_actions`.
  - Removed delete fallback to `/step/{index}` and `timeline-item` manual step deletion; recorder deletion now requires `traceId` or `diagnosticId`.
  - Removed `data.step` UI push from assistant SSE handling.
  - Changed assistant completion count to use only `trace_count` or run-owned `traceCount`, not `total_steps`, visible timeline length, or accepted trace array length.
  - Changed `RpaClaw/frontend/src/utils/rpaAssistantRun.ts` so `agent_done` ignores legacy `total_steps`.
  - Added `RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts` and extended `RpaClaw/frontend/src/utils/rpaAssistantRun.test.ts`.
- Systematic debugging notes:
  - First page-level SSE poison test failed because the test sent assistant events through screencast WebSocket instead of the chat SSE `fetch` reader. Root cause fixed in the test by mocking the chat SSE stream.
  - Second failure came from splitting `event:` and `data:` across mock chunks while the current parser stores event type per read loop. Test fixture changed to emit one valid SSE event frame.
  - Third failure was an assertion mismatch: the UI renders localized completion copy, while the English `accepted N trace(s)` string is appended to hidden/unused message text. Test now asserts the visible completion count.
- Spec-compliance reviewers:
  - Sagan: FAIL, found `total_steps` fallback through `applyRpaAssistantRunEvent()`.
  - Cicero: FAIL, found `steps.value.length - 1` fallback in RecorderPage completion text.
  - Tesla: FAIL, found `acceptedTraces.value.length` fallback through `getRunTraceCount()`.
  - Planck: PASS after all fixes.
- Code-quality reviewers:
  - Hume: APPROVED before the final `getRunTraceCount()` fix.
  - Dirac: APPROVED for the updated SSE mock and completion count path; no blocking quality issues.
- GREEN verification:
  - Command: `npm.cmd --prefix RpaClaw/frontend test -- RecorderPage rpaAssistantRun`
  - Controller result: `2 passed`, `9 passed` tests.
- Removal grep:
  - Command: `rg -n "recorded_actions|recording_diagnostics|session\\?\\.steps|mapServerSteps|/step/|timeline-item|data\\.step|total_steps|acceptedTraces\\.value\\.length|steps\\.value\\.length - 1" RpaClaw/frontend/src/pages/rpa/RecorderPage.vue RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts RpaClaw/frontend/src/utils/rpaAssistantRun.ts RpaClaw/frontend/src/utils/rpaAssistantRun.test.ts -S`
  - Result: production files clean for the checked legacy patterns; matches only remain in poison tests.

### Task 3D TestPage Trace-first Failure Retry

- Implementer: controller.
- Implementation:
  - Changed `RpaClaw/frontend/src/pages/rpa/TestPage.vue` so replay failure retry requires `failed_trace_id` and posts only `/rpa/session/{session_id}/trace/{trace_id}/locator`.
  - Removed frontend retry fallback to `/step/{failedStepIndex}/locator`.
  - Changed failed display index fallback to `failed_trace_index`, not `failed_step_index`.
  - Changed `RpaClaw/backend/rpa/executor.py` failure results from `failed_step_index` to `failed_trace_index`.
  - Added `_failed_trace_retry_context(session, result)` in `RpaClaw/backend/route/rpa.py` to build `/test` retry metadata from trace locator candidates.
  - Sanitized `/test` response `result` to remove any legacy `failed_step_index` before returning.
  - Added frontend `RpaClaw/frontend/src/pages/rpa/TestPage.test.ts` and extended backend focused route/executor tests.
- Review feedback and fixes:
  - Gauss: initial spec PASS for frontend-only change.
  - Avicenna: CHANGES_REQUESTED because current backend `/test` contract did not yet return `failed_trace_id`, and the first frontend test could flake after retry-triggered auto test rerun.
    - Fix: backend `/test` now emits `failed_trace_id` / `failed_trace_index` from trace retry context; frontend test removed fake timers and waits deterministically for locator POST.
  - Hooke: CHANGES_REQUESTED because `_failed_trace_retry_context()` still accepted `failed_step_index` as fallback and raw `result.failed_step_index` could leak through `/test`.
    - Fix: executor now emits `failed_trace_index`; route only reads `failed_trace_index`; route strips `failed_step_index` from returned result.
  - Curie: CHANGES_REQUESTED because retry candidate sorting could raise `TypeError` for `score: None` mixed with numeric scores.
    - Fix: normalized candidate sort score to float with invalid values sorted last; added score-null coverage.
  - Ampere: final spec PASS.
  - Nash: final quality APPROVED.
- GREEN verification:
  - Backend command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_executor.py RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py -q`
  - Backend result: `10 passed, 24 warnings`.
  - Frontend command: `npm.cmd --prefix RpaClaw/frontend test -- TestPage`
  - Frontend result: `1 passed`, `2 passed` tests.
- Residual risk:
  - Some backend internals still use `STEP_FAILED:` string parsing to extract an index from generated scripts, but the API-facing result is now `failed_trace_index`. Full removal of step terminology from generated runtime error strings should be handled with compiler/runtime cleanup tasks.

### Task 3E Configure Generation Gate Uses Trace Diagnostics

- Trigger:
  - Internal validation found Configure could show trace-backed unresolved diagnostics for manual confirmation, while `/generate` still blocked on legacy `recording_diagnostics`.
  - User-facing symptom: after recording completed, Configure could display `生成脚本失败: 2 unresolved diagnostics must be resolved before generation` instead of keeping the user in the manual diagnostic confirmation/repair flow.
- Root cause:
  - Frontend timeline and diagnostic UI had moved to trace projection / `trace_diagnostics`, but backend `_ensure_no_unresolved_manual_diagnostics()` still checked legacy `recording_diagnostics`.
  - This created two competing diagnostic sources after trace-first migration.
- Fix:
  - Changed backend generation/test/save diagnostic gate to use `trace_diagnostics`.
  - Added poison coverage proving legacy `recording_diagnostics` no longer blocks generation.
  - Kept trace diagnostics as the blocking source, so manual confirmation/repair still happens before script generation.
- Verification:
  - Backend command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py -q`
  - Backend result: `6 passed, 24 warnings`.
  - Frontend command: `npm.cmd --prefix RpaClaw/frontend test -- ConfigurePage rpaConfigureTimeline`
  - Frontend result: `2 passed`, `13 passed` tests.
- Recurrence protection:
  - Test protection is sufficient for this incident class: generation must block on trace diagnostics and ignore legacy `recording_diagnostics` poison.

### Task 3F Timeline Projection Restores Sensitive Credential Configuration

- Trigger:
  - User reported Configure no longer allowed choosing configured credentials after trace-first UI cleanup.
  - Audit also found `McpToolEditorPage` still had a `/step/{index}/locator` fallback and `source_step_index` param confirmation path.
- Root cause:
  - Manual recording events carried `sensitive`, and sensitive values were normalized to `{{credential}}`, but `RPAAcceptedTrace` and timeline projection did not expose `sensitive` / `value` as first-class fields.
  - Frontend `rpaConfigureTimeline` therefore read `raw_trace.value` and hard-coded `sensitive: false`, which hid the credential selector.
  - MCP editor kept a step-index fallback for locator promotion and param source metadata after the trace-first UI path was introduced.
- Fix:
  - Added `sensitive` to `RPAAcceptedTrace`.
  - Changed `manual_step_to_trace()` so sensitive fill steps emit `value="{{credential}}"` and `sensitive=True`.
  - Added top-level `value` and `sensitive` to `RPATimelineItem`.
  - Changed `rpaConfigureTimeline` to consume top-level projection `value` / `sensitive`, not `raw_trace`.
  - Added Configure coverage proving sensitive fill traces show the credential selector and ignore `raw_trace` poison.
  - Removed MCP editor locator fallback to `/step/{index}/locator`; promotion now requires trace id / `rpa_trace.trace_id`.
  - Removed MCP editor `source_step_index` confirmation writes.
- Verification:
  - Backend command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_trace_timeline.py RpaClaw/backend/tests/test_rpa_trace_recorder.py RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py -q`
  - Backend result: `22 passed, 24 warnings`.
  - Frontend command: `npm.cmd --prefix RpaClaw/frontend test -- rpaConfigureTimeline ConfigurePage McpToolEditorPage.view TestPage RecorderPage`
  - Frontend result: `5 passed`, `26 passed` tests.
  - Removal grep command: `rg -n "raw_trace\\?\\.value|item\\.raw_trace\\?\\.value|source_step_index|sourceStepIndex|/step/locator|/step/\\$\\{" RpaClaw/frontend/src/pages/rpa RpaClaw/frontend/src/utils/rpaConfigureTimeline.ts RpaClaw/frontend/src/pages/tools/McpToolEditorPage.vue -S`
  - Removal grep result: no production matches.
  - Frontend build command: `npm.cmd --prefix RpaClaw/frontend run build`
  - Frontend build result: passed with existing bundle-size/CSS warnings.
  - Frontend type-check command: `npm.cmd --prefix RpaClaw/frontend run type-check`
  - Frontend type-check result: failed on pre-existing unrelated TypeScript errors in non-RPA files such as `ActivityPanel.vue`, `ChatMessage.vue`, `SessionItem.vue`, and `desktopWindow.ts`.
- Review:
  - Frontend UI flow audit used independent explorer Boyle.
  - Backend projection/API audit used independent explorer Franklin.
  - MCP editor implementation was started by worker Helmholtz, then controller completed the implementation after worker shutdown.
- Residual risk:
  - Backend still has legacy step endpoints and export/MCP compatibility paths outside this focused UI contract fix. They remain follow-up cleanup for the broader “remove step / recorded_actions” acceptance target.

### Task 3G Manual Locator Diagnostics Stay Trace-first

- Trigger:
  - User reproduced a recording where Configure showed unresolved locator diagnostics for `点击 None`, but script generation could still produce a runtime `raise RuntimeError('Recorded click action is missing a valid target locator...')`.
  - The desired behavior is not to compile a broken accepted trace; the unresolved locator must stay in the trace diagnostic repair flow.
- Root cause:
  - Manual recording rebuild produced legacy `recording_diagnostics`, but the trace timeline did not receive an equivalent `trace_diagnostics` entry with a stable future `trace_id`.
  - `_record_manual_trace_for_step()` still converted the same bad manual step into an accepted trace, so the compiler emitted a runtime error placeholder instead of keeping the user in locator repair.
  - `/trace/{traceId}/locator` could only mutate existing accepted traces; it could not promote a trace diagnostic created from a bad manual step.
- Fix:
  - Projected `ManualRecordingDiagnostic` into `RPATraceDiagnostic(source="manual_recording")` with deterministic `diagnostic_id=diag-{step_id}` and future `trace_id=trace-{step_id}`.
  - Synchronized manual trace diagnostics whenever manual recording state is rebuilt.
  - Blocked `_record_manual_trace_for_step()` from appending accepted traces while a manual trace diagnostic exists for that step.
  - Extended `select_trace_locator_candidate()` so selecting a candidate on a manual diagnostic promotes the backing step through the existing normalization path, then returns the newly accepted trace.
  - Changed manual diagnostic deletion to delete the backing bad step, matching the UI's "delete step" semantics and preventing legacy step fallback from compiling the unresolved action.
  - Preserved navigation-upgrade behavior by rebuilding manual state before recording `navigate_click` / `navigate_press`, and by not treating URL-backed navigation composites as unresolved locator diagnostics.
- Verification:
  - Backend focused command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_manager.py -k "manual_diagnostic or select_step_locator_candidate_rebuilds_manual_recording_outcomes or select_trace_locator_candidate_promotes_manual_diagnostic_to_trace or delete_step_rebuilds_manual_recording_outcomes" -q`
  - Backend focused result: `4 passed, 83 deselected`.
  - Backend route command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py -k "delete_manual_diagnostic or delete_diagnostic_route_uses_diagnostic_id or promotes_manual_diagnostic" -q`
  - Backend route result: `3 passed, 5 deselected, 24 warnings`.
  - Backend regression command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py -q`
  - Backend regression result: `95 passed, 24 warnings`.
  - Frontend command: `npm.cmd --prefix RpaClaw/frontend test -- ConfigurePage rpaConfigureTimeline`
  - Frontend result: `2 passed`, `15 passed` tests.
  - Diff check command: `git diff --check -- RpaClaw/backend/rpa/manager.py RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py`
  - Diff check result: passed; only existing CRLF normalization warnings from Git.
- Review:
  - Independent review requested from subagent Erdos for the focused manager/route/test diff.
  - Erdos found P1: deleting a manual diagnostic only removed `trace_diagnostics`, leaving the bad legacy step available for fallback compilation.
  - Fix added route coverage proving manual diagnostic deletion removes the backing bad step and clears both legacy and trace diagnostics.
  - Erdos re-review verdict: APPROVED. P1 bypass repro now leaves `steps/traces/recorded_actions/recording_diagnostics/trace_diagnostics` all empty after deleting the manual diagnostic.
- Residual risk:
  - Legacy step locator endpoint still exists for compatibility, but this regression path no longer requires the frontend to use it.
  - `recording_diagnostics` still exists as an internal normalization byproduct until the broader removal work deletes it completely; generation/UI contracts are trace diagnostic based.

### Task 3H Playwright Locator String Candidates Promote From Diagnostics

- Trigger:
  - User verified unresolved manual diagnostics are visible again, but clicking `使用此定位器` failed with `Locator candidate is missing locator payload`.
  - User noted the older version had no visible error because clicking the button did not take effect.
- Root cause:
  - The diagnostic candidate from recorder carried only a `playwright_locator` string, not a normalized `locator` payload.
  - Backend trace locator promotion had reached the right `/trace/{traceId}/locator` path, but `_parse_playwright_locator_expression()` only handled a narrow double-quoted subset and did not parse common recorder output such as `page.get_by_role('textbox', name='请输入').first`.
- Fix:
  - Extended Playwright locator expression parsing to support single-quoted literals.
  - Added `.first` support by converting it to the existing canonical `nth(index=0)` locator form.
  - Added regression coverage for promoting a manual diagnostic candidate with `page.get_by_role('textbox', name='请输入').first`.
- Verification:
  - Backend focused command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_manager.py -k "single_quoted_playwright_first or select_trace_locator_candidate_promotes_manual_diagnostic_to_trace" -q`
  - Backend focused result: `2 passed, 86 deselected`.
  - Backend regression command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py -q`
  - Backend regression result: `96 passed, 24 warnings`.
  - Frontend command: `npm.cmd --prefix RpaClaw/frontend test -- ConfigurePage rpaConfigureTimeline`
  - Frontend result: `2 passed`, `15 passed` tests.
  - Diff check command: `git diff --check -- RpaClaw/backend/rpa/manager.py RpaClaw/backend/tests/test_rpa_manager.py`
  - Diff check result: passed; only existing CRLF normalization warnings from Git.
- Review:
  - Independent reviewer Erdos was asked to review the focused parser/test diff.
  - Erdos verdict: APPROVED. The reported `page.get_by_role('textbox', name='请输入').first` path now promotes to a canonical `nth(role(...), 0)` locator.
- Residual risk:
  - Parser remains intentionally bounded to recorder-style Playwright locator strings, not arbitrary Playwright expressions such as regex/lambda names.
  - Escaped apostrophes inside single-quoted literals may need a later parser hardening if such candidates appear in real recordings.

## Required Final Verification

Backend:

```powershell
$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_route_trace.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_e2e.py RpaClaw/backend/tests/test_rpa_mcp_route.py -q
```

Frontend:

```powershell
npm.cmd --prefix RpaClaw/frontend run type-check
npm.cmd --prefix RpaClaw/frontend run build
```

Removal grep:

```powershell
rg -n "session\\.steps|recorded_actions|recording_diagnostics|legacy_steps|failed_step_index|/step/|source_step_index" RpaClaw/backend RpaClaw/frontend/src -S
```

Manual smoke:

1. Start backend and frontend.
2. Create a recording.
3. Record manual click/fill/press and one AI trace.
4. Open Configure.
5. Generate script.
6. Run Test.
7. Save skill.
8. Verify timeline, failure retry, saved metadata, and MCP/export are trace-backed.

## Current Evidence

2026-05-13:

- Created Harness anchors and tightened spec/plan removal gates.
- No implementation tests have been run yet.
- `scripts/knowledge_check.py` is not present in this repository, so Harness artifact validation is currently manual.

## Closeout

Closeout verdict: blocked until implementation, verification, final reviewers, Vision Gate Exit, and Readiness Dashboard are complete.

Completion claim allowed: no.
