---
doc_kind: evidence
id: EV-001
title: RPA Trace Source Convergence Evidence
status: active
feature_ids: [F001]
created: 2026-05-13
updated: 2026-05-17
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

### Task 3I Plain Parameter Defaults Apply During Test Execution

- Trigger:
  - User verified credential parameters configured on Configure are effective, but changing a plain captured value from `JE` to `JET` still filled `JE` during Test.
- Root cause:
  - `TraceSkillCompiler` already generated ordinary fill code as `kwargs.get(param_name, default_value)`, so generated scripts could represent the configured default.
  - During Test, `inject_credentials()` also injects non-sensitive ordinary params into runtime kwargs. That function used `original_value`, so it passed `kwargs[param_name]="JE"` and overrode the compiler fallback `JET`.
  - Credential params worked because they use the separate `credential_id` decrypt branch.
- Fix:
  - Changed non-sensitive param injection to prefer `default_value` and fall back to `original_value` only when default is empty or missing.
  - Preserved explicit runtime kwargs precedence.
  - Added direct regression coverage in `test_credential_vault.py`.
- Verification:
  - Backend focused command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_credential_vault.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -k "injects_configured_default_value or preserves_explicit_runtime_kwargs or configured_default_value_as_runtime_fallback or plain_param_default" -q`
  - Backend focused result: `4 passed, 63 deselected`.
  - Backend regression command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_credential_vault.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q`
  - Backend regression result: `67 passed`.
  - Frontend command: `npm.cmd --prefix RpaClaw/frontend test -- ConfigurePage TestPage rpaSkillConfigDraft`
  - Frontend result: first run hit two 5s test timeouts with no assertion failure; rerun with `--testTimeout=15000` passed: `3 passed`, `13 passed` tests.
  - Diff check command: `git diff --check -- RpaClaw/backend/credential/vault.py RpaClaw/backend/tests/test_credential_vault.py`
  - Diff check result: passed; only existing CRLF normalization warnings from Git.
- Review:
  - Independent reviewer Erdos was asked to review the focused runtime param injection diff.
  - Erdos verdict: APPROVED. `inject_credentials()` now matches the compiler contract while credential params remain on the credential path.
- Residual risk:
  - Intentionally empty `default_value` still falls back to `original_value`, matching the current Configure behavior where blank defaults are treated as "use recorded value".

### Task 3J Assistant Run Trace Count Uses Run Scope

- Trigger:
  - User reported that a single natural-language command on GitHub, `获取start数`, showed `已记录 4 步`.
- Root cause:
  - The trace-first chat route emitted `trace_count=len(session.traces)` in `agent_done`, so the current assistant message displayed the cumulative session trace count rather than the traces accepted during this run.
  - RecorderPage already ignored legacy `total_steps`, visible timeline length, and accepted trace array fallbacks, but the backend field it trusted still used the wrong scope.
- Fix:
  - Changed trace-first `agent_done.trace_count` to count only traces whose `trace_id` did not exist before the current `RecordingRuntimeAgent.run()`.
  - Added `session_trace_count` for callers that need the cumulative session count.
  - Removed `total_steps` from the trace-first `agent_done` payload.
  - Changed the RecorderPage assistant copy from `已记录` to `本次记录` for run-scoped counts.
- Verification:
  - Frontend focused command: `npm.cmd --prefix RpaClaw/frontend test -- RecorderPage rpaAssistantRun`
  - Frontend focused result: `2 passed`, `9 passed` tests.
  - Backend focused command attempted: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_route_trace.py -q -k chat_agent_done_reports_run_trace_count_not_session_total`
  - Backend focused result: blocked during collection because the active Python environment is missing `langchain_core`.
  - Diff check command: `git diff --check -- RpaClaw/backend/route/rpa.py RpaClaw/backend/tests/test_rpa_route_trace.py RpaClaw/frontend/src/pages/rpa/RecorderPage.vue RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts`
  - Diff check result: passed; only existing CRLF normalization warnings from Git.
- Residual risk:
  - The new backend regression test still needs to be run in the project backend environment with `RpaClaw/backend/requirements.txt` installed.

## Required Final Verification

### 2026-05-16 Final Convergence Strategy

- Trigger:
  - Read-only removal grep found that frontend RPA pages are mostly trace-projection based, but backend production code still treats legacy fields as public or semi-public facts in session response, compile input selection, saved metadata, MCP/export projection, and step-index routes.
- Strategy:
  - New plan created: `docs/superpowers/plans/2026-05-16-rpa-trace-source-final-convergence.md`.
  - The plan intentionally converges from external contracts inward: API response projection, generate/test/save compile inputs, saved skill metadata, MCP/export projection, public step API removal, then manager-internal DTO shrink/quarantine.
  - The plan rejects a one-shot deletion of all Step/Action strings because `RPAStep` still carries manual browser-event normalization risk. The accepted boundary is stricter and safer: transitional step-like DTOs may exist only inside manager internals and must not feed public APIs, compiler inputs, saved metadata, or MCP/export.
- Initial grep evidence:
  - Command: `rg -n "session\\.steps|recorded_actions|recording_diagnostics|legacy_steps|failed_step_index|/step/|source_step_index" RpaClaw/backend/rpa RpaClaw/backend/route RpaClaw/frontend/src -S`
  - Result: production hits remain in `RpaClaw/backend/route/rpa.py`, `RpaClaw/backend/rpa/manager.py`, `RpaClaw/backend/rpa/mcp_step_projection.py`, `RpaClaw/backend/rpa/skill_exporter.py`, `RpaClaw/backend/rpa/mcp_converter.py`, `RpaClaw/backend/rpa/mcp_semantic_inferer.py`, and `RpaClaw/backend/rpa/executor.py`. Frontend hits are primarily poison tests or display naming after prior UI cleanup.
- Current verdict:
  - F001 remains active.
  - Completion claim allowed: no.
  - Next implementation task: Task 1 from the 2026-05-16 plan, "Session API Contract Stops Leaking Legacy Facts".

### Task 1K Session API Contract Stops Leaking Legacy Facts

- Plan:
  - `docs/superpowers/plans/2026-05-16-rpa-trace-source-final-convergence.md`, Task 1.
- Implementation:
  - Added `_build_session_response(session)` in `RpaClaw/backend/route/rpa.py`.
  - Changed `GET /rpa/session/{session_id}` to return the projected session response plus trace timeline instead of returning the raw `RPASession`.
  - The projection removes `steps`, `recorded_actions`, `recording_diagnostics`, and `legacy_steps`, and adds `trace_count` / `diagnostic_count`.
  - Added poison route coverage and a helper-level `legacy_steps` projection test in `RpaClaw/backend/tests/test_rpa_trace_timeline.py`.
- Verification:
  - Worker RED: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_trace_timeline.py -q`
  - Worker RED result: `1 failed, 6 passed`; failure was the expected `steps` leak in the raw session response.
  - Worker GREEN: same command, result `7 passed, 25 warnings`.
  - Controller focused rerun: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_trace_timeline.py RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py -q`
  - Controller focused result after `legacy_steps` fix: `16 passed, 25 warnings`.
- Review:
  - Implementer: Carver.
  - Spec reviewer Newton first result: FAIL because `legacy_steps` was not deny-listed or tested.
  - Fix: added `legacy_steps` to `_build_session_response()` deny-list and added direct helper coverage.
  - Spec re-review Kuhn: PASS.
  - Code-quality reviewer Feynman: APPROVED.
- Residual risk:
  - `stop_rpa_session()` still returns the raw session object and should be handled in a later API-contract cleanup if that endpoint is treated as a frontend/public session contract.
  - Compile/save/MCP/export legacy dependencies remain and are covered by later tasks in the 2026-05-16 plan.

### Task 2-4K Generate/Test/Save, Skill Metadata, And MCP Projection Are Trace-backed

- Plan:
  - `docs/superpowers/plans/2026-05-16-rpa-trace-source-final-convergence.md`, Tasks 2, 3, and the trace-backed projection portion of Task 4.
- Implementation:
  - `RpaClaw/backend/route/rpa.py`
    - Removed the `PlaywrightGenerator` route fallback.
    - `_session_traces_for_compile(session)` now orders and returns only `session.traces`.
    - `_generate_session_script()` always calls `TraceSkillCompiler.generate_script(...)`.
    - `generate`, `test`, and `save` reject empty trace inputs before script generation, executor use, or export.
    - `_build_session_recording_meta(session)` no longer derives trace facts from `session.steps` and no longer exports `legacy_steps`, `recorded_actions`, or `recording_diagnostics`.
  - `RpaClaw/backend/rpa/trace_recorder.py`
    - `manual_step_to_trace()` preserves `signals.recording.sequence` and `signals.recording.event_timestamp_ms`, so trace ordering does not need to read step state.
  - `RpaClaw/backend/rpa/mcp_step_projection.py`
    - `session_to_mcp_steps(session)` projects only accepted traces and no longer reads `session.steps` or `recorded_actions`.
  - `RpaClaw/backend/rpa/skill_exporter.py`
    - Trace-source `skill.meta.json` strips legacy recording facts and omits top-level `steps`.
  - `RpaClaw/backend/rpa/mcp_converter.py` and `RpaClaw/backend/rpa/mcp_semantic_inferer.py`
    - Inferred MCP params now carry `source_trace_id` / `source_trace_output_key` instead of `source_step_index` / `source_step_id`.
- Regression tests:
  - Added/updated poison tests in:
    - `RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py`
    - `RpaClaw/backend/tests/test_rpa_route_trace.py`
    - `RpaClaw/backend/tests/test_rpa_trace_recorder.py`
    - `RpaClaw/backend/tests/test_skill_exporter.py`
    - `RpaClaw/backend/tests/test_rpa_mcp_route.py`
    - `RpaClaw/backend/tests/test_rpa_mcp_converter.py`
  - `RpaClaw/backend/tests/test_rpa_route_trace.py` now stubs optional LangChain/DeepAgents imports so the route trace tests are collectible in this local environment.
- Verification:
  - RED example:
    - Command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py::test_save_skill_exports_trace_metadata_without_legacy_source_facts -q`
    - Result before implementation: `1 failed`; failure showed `recording_meta` still contained `legacy_steps`.
  - Focused route/export checks:
    - Command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_route_trace.py -q`
    - Result: `40 passed, 25 warnings`.
    - Command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_mcp_converter.py -q`
    - Result: `10 passed`.
  - Combined backend convergence set:
    - Command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_route_trace.py RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py RpaClaw/backend/tests/test_rpa_trace_recorder.py RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_skill_exporter.py RpaClaw/backend/tests/test_rpa_mcp_route.py RpaClaw/backend/tests/test_rpa_mcp_converter.py -q`
    - Result: `253 passed, 185 warnings`.
- Review:
  - Spec/quality reviewer Confucius: PASS for Tasks 2-4 boundary.
  - Reviewer confirmed compile traces are `session.traces` only, route generation uses trace compiler, save/test/generate reject empty traces, metadata excludes legacy source facts, MCP projection reads only traces, and trace-source export strips legacy recording facts.
- Residual risk:
  - Public step-index routes still exist in `RpaClaw/backend/route/rpa.py` and are Task 5.
  - `RpaClaw/backend/rpa/executor.py` still uses internal/local `failed_step_index` variable names and a "Step N failed" log while returning `failed_trace_index`; this is naming cleanup for a later residual pass unless it leaks to a public contract.
  - `RpaClaw/backend/rpa/mcp_converter.py` still imports `PlaywrightGenerator` for legacy non-trace preview normalization and utility helpers; trace-backed inputs bypass that normalization.
  - Manager-internal `RPAStep`, `recorded_actions`, and `recording_diagnostics` still exist as transitional recording DTOs and are Task 6.

### Task 5K Public Step-index APIs Removed From The New Path

- Plan:
  - `docs/superpowers/plans/2026-05-16-rpa-trace-source-final-convergence.md`, Task 5.
- Implementation:
  - Removed public route definitions from `RpaClaw/backend/route/rpa.py`:
    - `DELETE /session/{session_id}/step/{step_index}`
    - `POST /session/{session_id}/step/{step_index}/locator`
    - `WEBSOCKET /session/{session_id}/steps`
  - `delete_timeline_item` now accepts trace timeline deletion only through `kind="trace"`; `kind="manual_step"` is rejected.
  - Removed dead route-level helper code that still described merging `recorded_actions` with `session.steps`.
- Regression tests:
  - Added router registration coverage in `RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py` proving no public `/step/` or `/steps` endpoints are registered.
  - Updated `RpaClaw/backend/tests/test_rpa_route_trace.py` so `manual_step` timeline deletion is rejected instead of treated as a generation-input mutation.
- Verification:
  - RED examples:
    - `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py::test_router_does_not_register_public_step_index_endpoints -q`
    - Result before implementation: `1 failed`; router still registered `/step/`.
    - `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_route_trace.py::test_delete_timeline_rejects_manual_step_kind -q`
    - Result before implementation: `1 failed`; `manual_step` did not raise.
  - GREEN focused checks:
    - Same two commands after implementation: both `1 passed`.
  - Backend convergence set:
    - Command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_route_trace.py RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py RpaClaw/backend/tests/test_rpa_trace_recorder.py RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_skill_exporter.py RpaClaw/backend/tests/test_rpa_mcp_route.py RpaClaw/backend/tests/test_rpa_mcp_converter.py -q`
    - Result: `254 passed, 183 warnings`.
  - Frontend RPA/MCP route-call checks:
    - Command: `npm.cmd --prefix RpaClaw/frontend test -- ConfigurePage RecorderPage TestPage McpToolEditorPage.view`
    - Result: `4 passed` test files, `19 passed` tests.
  - Grep:
    - Command: `rg -n "/step/|/steps" RpaClaw/frontend/src/pages/rpa RpaClaw/frontend/src/pages/tools RpaClaw/backend/route/rpa.py -S`
    - Result: no production hits; remaining hits are tests asserting `/step/` is not called.
- Review:
  - Independent reviewer Russell: PASS.
- Residual risk:
  - `RpaClaw/backend/route/rpa.py` still passes `session.steps` to explicitly requested `legacy_react` / `legacy_chat` modes. That is isolated legacy mode behavior, not the default trace-first recording path.
  - Manager-internal `delete_step`, `select_step_locator_candidate`, `recorded_actions`, and `recording_diagnostics` remain for Task 6 quarantine/removal.

### Task 6K Manager DTO Quarantine Decision

- Plan:
  - `docs/superpowers/plans/2026-05-16-rpa-trace-source-final-convergence.md`, Task 6.
- Decision:
  - Do not hard-delete manager-internal `RPAStep`, `recorded_actions`, and `recording_diagnostics` in this pass.
  - They remain as transitional, private manual browser-event normalization DTOs inside `RpaClaw/backend/rpa/manager.py`.
  - Reason: manual event ordering, fill merge/debounce, diagnostic candidate resolution, and manual-trace construction still depend on this state. Removing it now would turn a source-convergence task into a broader recorder rewrite with higher regression risk.
- Additional quarantine fix:
  - `stop_rpa_session()` now returns `_build_session_response(session)` instead of the raw `RPASession`.
  - Added a poison test proving stop response no longer exposes `steps`, `recorded_actions`, `recording_diagnostics`, or `legacy_steps`.
- Current allowed production residuals:
  - `RpaClaw/backend/rpa/manager.py`: private transitional recording DTO state and helpers.
  - `RpaClaw/backend/route/rpa.py`: `session.steps` is passed only to explicitly requested `legacy_react` / `legacy_chat` modes.
  - `RpaClaw/backend/rpa/executor.py`: local variable/log naming still says `failed_step_index` / `Step N failed`, while public route response drops `failed_step_index` and uses trace retry context.
  - `RpaClaw/backend/rpa/skill_exporter.py`: non-trace direct-export fallback still supports legacy `steps`; trace-source exports strip legacy facts.
- Verification:
  - RED example:
    - Command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_trace_timeline.py::test_stop_rpa_session_response_hides_legacy_sources -q`
    - Result before implementation: `1 failed`; stop response exposed `steps`.
  - GREEN focused result:
    - Same command after implementation: `1 passed`.
  - Backend final convergence set:
    - Command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_trace_timeline.py RpaClaw/backend/tests/test_rpa_route_trace.py RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py RpaClaw/backend/tests/test_rpa_trace_recorder.py RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_skill_exporter.py RpaClaw/backend/tests/test_rpa_mcp_route.py RpaClaw/backend/tests/test_rpa_mcp_converter.py -q`
    - Result: `263 passed, 183 warnings`.
  - Frontend route-call convergence set:
    - Command: `npm.cmd --prefix RpaClaw/frontend test -- ConfigurePage RecorderPage TestPage McpToolEditorPage.view`
    - Result: `4 passed` test files, `19 passed` tests.
- Final status:
  - External trace-source convergence for API response, generate/test/save, saved metadata, MCP/export projection, and public step-index routes is implemented and verified.
  - Full F001 release readiness still requires optional broader frontend build/type-check and manual smoke from the plan's final gate.

### Task 9A Evidence-driven Trace Compilation Gate

- Trigger:
  - User compared same-scene generated scripts from trace-first and trace-source and found that a GitHub star-count extraction could compile into an internal `aui-form-item` style field lookup.
  - Architecture analysis found the root cause class: trace convergence was being confused with one-size-fits-all deterministic compilation.
- Decision:
  - ADR-002 records that trace is the accepted timeline carrier, while compiler strategy must be chosen from explicit evidence profile.
  - Output labels alone are not replay locators.
- Required regression protection:
  - Positive: structured `signals.extract_snapshot.fields` with field evidence still compiles to deterministic snapshot extraction.
  - Negative: empty/weak `extract_snapshot.fields` plus `trace.output` such as `{"Star count": "48.2k"}` must not generate `aui-form-item` XPath code and should fall back to runtime AI or embedded AI code.
  - Navigation: click traces with navigation evidence must compile with navigation waiting rather than fixed timeout.
- Status:
  - Implemented on 2026-05-15.
- Implementation:
  - `TraceSkillCompiler` now renders deterministic snapshot extraction only when `signals.extract_snapshot.fields` has usable structured fields.
  - Removed the fallback that turned `trace.output` labels into snapshot/detail field locators.
  - Weak or empty `extract_snapshot` signals now fall through to runtime AI or embedded AI code, depending on the remaining trace evidence.
  - `trace_requires_runtime_ai_replay()` now treats weak snapshot traces as runtime-AI candidates instead of assuming snapshot extraction is deterministic.
- Tests:
  - Added a negative GitHub-shaped star-count regression: `output={"Star count": "48.2k"}` with empty `extract_snapshot.fields` must not generate `aui-form-item` XPath extraction and must not hard-code observed output.
  - Updated the previous output-label fallback test so output keys alone are evidence, not replay locators.
  - Preserved positive structured snapshot extraction coverage where fields contain real field evidence.
- Verification:
  - Worker RED/GREEN focused command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q -k "snapshot or star or navigation_signal"`
  - Worker focused result: `7 passed, 57 deselected`.
  - Worker safety command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q`
  - Worker safety result: `64 passed`.
  - Controller focused rerun result: `7 passed, 57 deselected`.
  - Controller full compiler rerun result: `64 passed`.
  - Diff check command: `git diff --check -- RpaClaw/backend/rpa/trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py docs/decisions/ADR-002-trace-evidence-driven-compiler-strategy.md docs/features/F001-rpa-trace-source-convergence.md docs/evidence/EV-001-rpa-trace-source-convergence.md docs/superpowers/plans/2026-04-28-rpa-trace-first-full-migration.md`
  - Diff check result: passed; only existing LF/CRLF normalization warnings from Git.
- Review:
  - Implementer: Carson.
  - Spec-compliance reviewer: Singer, PASS.
  - Code-quality reviewer: Sagan, APPROVED.
- Residual risk:
  - Negative tests assert generated-script strings, which is acceptable for this compiler slice but should not become the only long-term replay proof.
  - Weak snapshot traces with non-empty embedded `ai_execution.code` are not separately covered in this slice; current intended behavior is to preserve embedded code when runtime-AI preservation is not triggered.

## Task 7K - Navigating link replay with dynamic counter text

- User report:
  - A directly clicked GitHub repository replay failed on `get_by_role('link', name='Issues', exact=True)`.
  - The recording intentionally preserved the concrete repo (`tinyhumansai / openhuman`) because the user clicked it manually; this fix must not reinterpret direct clicks as semantic project selection.
- Root cause:
  - GitHub repository navigation tabs expose accessible text such as `Issues\n112` and `Pull requests\n28`.
  - The compiler defaulted manual `role=link` locators to `exact=True`, so a recorded name like `Issues` could fail even though the intended link was visible.
- Decision:
  - Keep exact defaults for ordinary manual locators.
  - Only relax `exact` for manual `navigate_click` / `navigate_press` traces whose target locator is `role=link`.
  - Do not broaden direct-click traces into runtime AI or semantic project selection.
- Implementation:
  - `TraceSkillCompiler._preferred_locator_for_trace()` now applies exact defaults first, then removes `exact` only for navigating role-link locators.
  - Nested/nth locators are handled recursively so the relaxation stays attached to the link target.
- Tests:
  - Added compiler regression that `click link("Issues")` with navigation evidence compiles to `get_by_role('link', name='Issues').click()` while ordinary manual link clicks still default to `exact=True`.
  - Added Playwright E2E replay with link markup `Issues <span>112</span>` and asserted final URL reaches `/issues`.
- Verification:
  - Focused compiler command: `$env:PYTHONPATH='RpaClaw'; pytest -q RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -k "manual_navigate_link_locator_does_not_default_to_exact or manual_link_locator_defaults_to_exact_when_unspecified or manual_navigation_signal_click_compiles_to_expect_navigation"`
  - Focused compiler result: `3 passed, 62 deselected`.
  - Focused E2E command: `$env:PYTHONPATH='RpaClaw'; pytest -q RpaClaw/backend/tests/test_rpa_trace_e2e.py -k "navigating_link_tolerates_dynamic_counter_text"`
  - Focused E2E result: `1 passed, 10 deselected`.
  - Full compiler command: `$env:PYTHONPATH='RpaClaw'; pytest -q RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py`
  - Full compiler result: `65 passed`.
  - Trace regression command: `$env:PYTHONPATH='RpaClaw'; pytest -q RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_e2e.py RpaClaw/backend/tests/test_rpa_trace_recorder.py RpaClaw/backend/tests/test_rpa_trace_timeline.py RpaClaw/backend/tests/test_rpa_route_trace.py`
  - Trace regression result: `136 passed, 23 warnings`.
  - Diff check command: `git diff --check -- RpaClaw/backend/rpa/trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_e2e.py`
  - Diff check result: passed; only LF/CRLF normalization warnings from Git.
- Residual risk:
  - The fix intentionally does not solve semantic selection. If the user describes "open the most relevant trending repo" in natural language, that remains the runtime AI / semantic trace path.
  - If a site has several visible navigating links whose accessible names contain the same recorded prefix, future work should prefer recorded href or locator candidates rather than globally relaxing link matching further.

## Task 7L - Empty embedded extraction evidence must not be frozen as deterministic replay

- User report:
  - After the navigating-link fix, a generated script could still return an empty star count.
  - The failing trace generated recording-time Python that selected `page.locator('a[href$="stargazers"]').first`; on the recorded page the first matching link can be an empty README badge link, while the visible repository statistic appears later.
  - The user explicitly rejected a blanket "empty value is failure" rule because empty outputs can be valid business results.
- Trace-first comparison:
  - A previous debug run under `data/rpa_recording_snapshots/03183a10-b588-4b3e-b9fd-5780da0fe1ae` generated the more specific `a[href="/tinyhumansai/openhuman/stargazers"]` locator and returned `9k stars`.
  - The newer failing debug run under `data/rpa_recording_snapshots/74b0c609-d5cd-4b7e-a831-2808cee5c2f1` generated broad `.first` selector code and recorded `{"star_count": ""}`.
  - The raw snapshots contained visible `Star 9k` / `Star 9.1k` facts in both runs, so the failure is not a GitHub-specific missing-data problem; it is a weak candidate-selection / weak evidence-freezing problem.
- Root cause:
  - The compiler preserved recording-time embedded AI Python whenever `trace.ai_execution.code` existed and runtime-AI preservation was not otherwise required.
  - An embedded extraction code block that produced only empty output, with no explicit empty-output contract, had not proven itself as stable deterministic replay evidence.
- Decision:
  - Do not add a global non-empty validator.
  - Do not add a GitHub/star-count template.
  - Treat empty embedded extraction output as weak compiler evidence unless the trace explicitly records that the user allowed empty output.
  - Keep explicitly allowed empty outputs valid and deterministic when the trace carries `signals.output_contract.allow_empty=true`.
- Implementation:
  - `RecordingRuntimeAgent._accepted_trace()` now records `signals.output_contract.allow_empty=true` only when the planner explicitly sets `allow_empty_output`.
  - `TraceSkillCompiler` now routes embedded AI extraction traces with observed empty output and no allow-empty contract through runtime semantic replay instead of freezing the embedded Python code.
  - The recording planner prompt now includes a generic instruction for count/stat/value extraction: do not default to broad multi-match locators plus `.first`; inspect visible candidates and prefer text-shape matches.
- Tests:
  - Added compiler regression that an empty embedded extraction trace with broad `stargazers`-style code compiles to `_execute_runtime_ai_instruction(...)`, without preserving the weak selector.
  - Added compiler regression that explicitly allowed empty output still preserves embedded deterministic code.
  - Added recording runtime regressions for persisting and omitting the allow-empty output contract.
- Verification:
  - Focused compiler command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q -k "empty_embedded_extract or star_count_output_label"`
  - Focused compiler result: `3 passed, 64 deselected`.
  - Focused recording runtime command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py -q -k "empty_extract_when_plan_explicitly_allows_empty or does_not_mark_empty_output_allowed_by_default"`
  - Focused recording runtime result: `2 passed, 58 deselected`.
  - Full compiler command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q`
  - Full compiler result: `67 passed`.
  - Trace E2E command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_trace_e2e.py -q`
  - Trace E2E result: `11 passed`.
  - Full recording runtime command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py -q`
  - Full recording runtime result: `56 passed, 4 failed`; the failures are existing environment dependency import failures for `langchain_openai` in default-planner tests, not failures in the new allow-empty contract path.
- Residual risk:
  - Runtime semantic replay still depends on the recording runtime planner selecting better candidates. The prompt now discourages broad `.first` extraction, but the longer-term architectural fix is still a stronger candidate/action evidence layer between raw snapshot facts and planner code generation.

## 2026-05-16 Upstream Master Integration Branch

- Branch:
  - Source branch prepared from latest `upstream/master`: `codex/rpa-trace-source-to-master`.
  - Cherry-picked trace-source commits: `f599dde`, `4d7fc64`, `7f9cd33`, `700716d`, `e7deb5c`, `87d1084`, `6441cb6`, `88dda0c`, `01eebf4`, `0e1ee72`, `a5a6fb5`.
  - Additional integration commit: `test: align trace tab replay assertions`, aligning route-level tab replay assertions with the `_ensure_recorded_tab()` compiler contract already present on `upstream/master` through PR #52.
- Verification:
  - Diff hygiene command: `git diff --check upstream/master..HEAD`
  - Diff hygiene result: passed.
  - Backend trace convergence command: `$env:PYTHONPATH="RpaClaw"; python -m pytest RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_route_trace.py RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py RpaClaw/backend/tests/test_rpa_trace_recorder.py RpaClaw/backend/tests/test_rpa_trace_timeline.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_e2e.py RpaClaw/backend/tests/test_skill_exporter.py RpaClaw/backend/tests/test_rpa_mcp_route.py RpaClaw/backend/tests/test_rpa_mcp_converter.py -q`
  - Backend trace convergence result: `282 passed, 183 warnings`.
  - Frontend focused command: `npm.cmd --prefix RpaClaw/frontend test -- ConfigurePage RecorderPage TestPage McpToolEditorPage.view rpaConfigureTimeline rpaAssistantRun`
  - Frontend focused result: `6 passed` test files, `30 passed` tests.
  - Frontend build command: `npm.cmd --prefix RpaClaw/frontend run build`
  - Frontend build result: passed with existing duplicate-key, CSS, Browserslist, and chunk-size warnings.
  - Frontend type-check command: `npm.cmd --prefix RpaClaw/frontend run type-check`
  - Frontend type-check result: failed on existing global TypeScript errors in files such as `ActivityPanel.vue`, `ChatMessage.vue`, `SessionItem.vue`, locale files, and `desktopWindow.ts`; no reported error pointed to the RPA files touched by this integration.
- Publish status:
  - Pushed to `origin/codex/rpa-trace-source-to-master`.
  - PR creation from this environment is blocked because GitHub CLI `gh` is not installed.

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

## 2026-05-17 PR #53 Review Fixes

- Trigger:
  - PR #53 owner review reported three regressions in the trace-source convergence branch: manual `set_input_files` traces compiled to no-op, UI timeline ordering could diverge from replay ordering for same-millisecond events, and `POST /rpa/session/start` still returned raw `RPASession` legacy fields.
- Root cause:
  - `TraceSkillCompiler._render_manual_action_trace()` did not include `set_input_files` even though the recorder and legacy generator supported it.
  - Trace replay/export/MCP ordering used `event_timestamp_ms + sequence`, but `build_trace_timeline_items()` sorted only by `order_ms + item.id`.
  - `start_rpa_session()` bypassed `_build_session_response()` and returned the raw session model.
- Fix:
  - Added trace compiler rendering for single and multiple `set_input_files` inputs, using structured `signals.set_input_files.files` first and `trace.value` as fallback.
  - Added shared `backend.rpa.trace_ordering` helpers and reused them from route compile ordering, MCP projection, and timeline projection.
  - Changed start session response to return the projected session response plus an empty/new trace timeline instead of raw legacy fields.
- RED verification:
  - Command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_compiler_renders_manual_set_input_files_trace RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_compiler_renders_multiple_manual_set_input_files_trace RpaClaw/backend/tests/test_rpa_trace_timeline.py::test_trace_timeline_orders_same_millisecond_traces_by_recording_sequence RpaClaw/backend/tests/test_rpa_route_trace.py::test_start_rpa_session_response_hides_legacy_sources -q`
  - Result before fix: `4 failed`; failures matched missing upload rendering, sequence-blind timeline ordering, and missing `timeline` / raw start response contract.
- GREEN verification:
  - Focused command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_compiler_renders_manual_set_input_files_trace RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_compiler_renders_multiple_manual_set_input_files_trace RpaClaw/backend/tests/test_rpa_trace_timeline.py::test_trace_timeline_orders_same_millisecond_traces_by_recording_sequence RpaClaw/backend/tests/test_rpa_route_trace.py::test_start_rpa_session_response_hides_legacy_sources -q`
  - Focused result: `4 passed, 23 warnings`.
  - Backend trace convergence command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_route_trace.py RpaClaw/backend/tests/test_rpa_trace_mutation_routes.py RpaClaw/backend/tests/test_rpa_trace_recorder.py RpaClaw/backend/tests/test_rpa_trace_timeline.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_e2e.py RpaClaw/backend/tests/test_skill_exporter.py RpaClaw/backend/tests/test_rpa_mcp_route.py RpaClaw/backend/tests/test_rpa_mcp_converter.py -q`
  - Backend trace convergence result: `286 passed, 183 warnings`.
  - Diff hygiene command: `git diff --check`
  - Diff hygiene result: passed with line-ending warnings only.
- Rejected paths:
  - Did not fallback from `TraceSkillCompiler` to legacy `PlaywrightGenerator`, because that would reintroduce a second accepted compile source.
  - Did not patch only the frontend timeline sort, because the accepted timeline ordering invariant belongs in shared backend trace ordering.
  - Did not remove manager-internal `RPASession.steps` / `recorded_actions` in this patch, because the review issue is public response leakage, not private DTO quarantine.

## Task 7M - Random-like testid locator evidence must not become stable replay fact

- User report:
  - A previously stable manual recording now generated a trace-first script that recorded successfully but failed in test replay.
  - The failing step compiled to chained `get_by_test_id(...)` calls using values such as `DIV-_standingActiveManage_standingBook-id-611090413` and `DIV-_standingActiveManage_standingBook-id-1064443668`.
  - The user correctly identified these as likely random/generated UI identifiers rather than stable business locators.
- Attribution:
  - Existing Feature: F001.
  - Vision Anchor: keep `session.traces` / `RPAAcceptedTrace` as the single compile source; fix evidence quality instead of restoring legacy generator fallback.
- Root cause:
  - `RPASessionManager._locator_instability_penalty()` only penalized CSS selectors, so `method="testid"` values with generated numeric suffixes could remain selected.
  - `TraceSkillCompiler._best_locator()` trusted the selected trace locator without a shared stability check.
  - `region_context._has_stable_scope_locator_candidate()` treated every test id as a stable scope, including generated container ids.
- Decision:
  - Do not ban all `testid` locators. Semantic test ids such as `login-username`, `order-card`, and `search-button` remain valid evidence.
  - Do not add a site-specific Huawei/Jalor rule.
  - Do not post-process generated script strings.
  - Add a shared conservative locator stability classifier and use it at the locator evidence boundary.
- Implementation:
  - Added shared `locator_instability_penalty()` / `locator_has_unstable_identity()` helpers in `RpaClaw/backend/rpa/trace_locator_utils.py`.
  - Manager candidate scoring now penalizes random-like `testid`, nested random `testid`, CSS `[data-testid=...]`, `data-v-*`, deep CSS, and positional locator shapes through the same helper.
  - Compiler fallback now replaces a selected unstable locator only when there is exactly one candidate with zero instability penalty.
  - Region context pruning no longer preserves oversized containers merely because they have a random-like test id.
- RED verification:
  - Command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_handle_event_prefers_stable_candidate_over_random_like_testid RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_manual_action_prefers_stable_candidate_over_selected_random_like_testid RpaClaw/backend/tests/test_rpa_region_context.py::test_region_evidence_pruning_does_not_keep_oversized_container_for_random_like_testid -q`
  - Result before fix: `3 failed`. Failures showed manager kept the nested random `testid`, compiler emitted the random `get_by_test_id(...)` chain, and region pruning kept the oversized generated-id container.
- GREEN verification:
  - Focused regression command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_manager.py::RPASessionManagerTabTests::test_handle_event_prefers_stable_candidate_over_random_like_testid RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_manual_action_prefers_stable_candidate_over_selected_random_like_testid RpaClaw/backend/tests/test_rpa_region_context.py::test_region_evidence_pruning_does_not_keep_oversized_container_for_random_like_testid -q`
  - Focused regression result: `3 passed`.
  - Broader related command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_region_context.py -k "not analyze_region_route and not chat_ and not resolve_chat_region_context" -q`
  - Broader related result: `209 passed, 6 deselected`.
  - Full related-file attempt: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_region_context.py -q`
  - Full related-file result: `209 passed, 6 failed`; all six failures import `backend.route.rpa` and stop on missing local dependency `langchain_openai`, not on the changed locator stability path.
  - Diff hygiene command: `git diff --check -- RpaClaw/backend/rpa/trace_locator_utils.py RpaClaw/backend/rpa/manager.py RpaClaw/backend/rpa/trace_skill_compiler.py RpaClaw/backend/rpa/region_context.py RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_region_context.py`
  - Diff hygiene result: passed with line-ending warnings only.
- Residual risk:
  - The classifier is intentionally conservative. Some generated ids may still be preserved when no unique stable replacement exists; that is preferable to inventing replay locators or globally rejecting numeric business ids.
- 2026-05-25 follow-up:
  - User reran the scenario and generated script still contained chained random `get_by_test_id(...)` calls with new generated ids such as `DIV-_standingActiveManage_standingBook-id-1213867279`.
  - Local HEAD reproduction confirmed the first Task 7M fix only handled the case where a unique stable replacement candidate existed. If a trace carried only the random test id chain, the compiler still emitted it.
  - Additional decision: a random-like locator with no stable replacement must not become an accepted manual replay fact. During recording it should route to locator diagnostic/repair; during compilation of old traces it should produce the existing explicit "missing valid target locator" failure instead of a 60s Playwright timeout.
  - Added RED tests:
    - `test_build_outcome_routes_random_like_testid_to_diagnostic`
    - `test_handle_event_routes_only_random_like_testid_to_diagnostic`
    - `test_manual_action_rejects_selected_random_like_testid_without_stable_candidate`
  - RED result: `3 failed`, showing the random-only target was accepted and compiled.
  - Implementation follow-up:
    - `manual_recording_normalizer` now rejects canonical targets with unstable identity while still accepting weaker but non-random locators such as `nth(role(...), 0)`.
    - `trace_locator_utils.locator_has_unstable_identity()` is now separated from scoring penalty so `nth` can be downgraded without being treated as random identity.
    - `TraceSkillCompiler._best_locator()` now returns no locator when the selected locator has random identity and no unique stable replacement exists.
  - GREEN command: `$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_manual_recording_normalizer.py RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_region_context.py -k "not analyze_region_route and not chat_ and not resolve_chat_region_context" -q`
  - GREEN result: `221 passed, 6 deselected`.

## Current Evidence

2026-05-17:

- PR #53 review fixes are implemented on `codex/rpa-trace-source-to-master`.
- Latest backend trace convergence evidence: `286 passed, 183 warnings`.
- `scripts/knowledge_check.py` and `scripts/harness_closeout_check.py` are not present in this repository, so Harness artifact validation is currently manual.

## Closeout

Closeout verdict: conditional for the PR #53 review-fix patch; broader F001 remains active until any remaining trace-source follow-ups are explicitly accepted or split out.

Completion claim allowed: yes for the 2026-05-17 review-fix patch only.
