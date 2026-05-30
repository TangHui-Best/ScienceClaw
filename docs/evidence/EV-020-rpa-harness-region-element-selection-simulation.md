---
id: EV-020
doc_kind: evidence
title: RPA Harness Region and Element Selection Simulation Evidence
status: active
scope: project
feature_ids: [F020]
feature_refs:
  - docs/features/F020-rpa-harness-region-element-selection-simulation.md
created: 2026-05-30
updated: 2026-05-30
evidence_level: standard
---

# EV-020 RPA Harness Region and Element Selection Simulation Evidence

## Scope

Evidence for F020: region and element-selection simulation in RPA Harness.

This slice proves that selected-region evidence and picked-element acquisition facts can survive Harness capture/replay boundaries and reach full-live as generic `RecordingRuntimeAgent` region context.

It does not prove live-site correctness, does not promote assets automatically, does not introduce `element_context`, and does not reimplement F019 controlled download.

## Entry Gate

Start Gate:

```text
Start Gate: needs feature -> ready after F020/EV020 creation
Task class: high-risk
Risk triggers:
- Harness region_context / region_scope contract
- user-input replay boundary semantics
- full-live planner context
- F019 side-effect boundary
- report overclaiming risk
Delegation decision:
- authorized; user explicitly allowed subagent delegation
Bug attribution:
- new F020 capability slice spanning F016/F017 region evidence gap
Required pre-work:
- retrieve F011/F016/F017/F019/EV018
- create F020 and EV020 before production code
Allowed next action:
- write RED tests for region/element evidence preservation
```

Knowledge Retrieval:

- Read F011/F016/F017/F019 Feature pages.
- Read EV-018 and EV-019 evidence.
- Read `RpaClaw/backend/rpa/harness/user_input_replay.py`.
- Read `RpaClaw/backend/rpa/harness/full_live_profile.py`.
- Read current region-selection frontend/backend boundary in `RecorderPage.vue`, `rpaRegionSelection.ts`, and `route/rpa.py`.

Retrieval conclusion:

- F011 deliberately models element point selection as region acquisition, not as a new backend main path.
- F016 user-input replay should preserve region facts generically, but its current extractor historically read only `target_evidence.region`, `event.region`, and `signals.region`.
- F017 full-live already has a generic runtime region-context path; F020 should feed it better source facts instead of creating a region-specific runner.
- F019 controlled download is complete enough to be composed later as side-effect evidence; F020 must not redefine it.

## Commands

RED:

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
.\.venv\Scripts\python.exe -m pytest -q `
  RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py::test_user_input_replay_preserves_top_level_region_context_scope_and_acquisition
```

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
.\.venv\Scripts\python.exe -m pytest -q `
  RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py::test_full_live_profile_passes_picked_element_acquisition_as_generic_region_context
```

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
.\.venv\Scripts\python.exe -m pytest -q `
  RpaClaw/backend/tests/test_rpa_harness_expected_signals.py::test_region_scoped_trace_expected_signals_preserve_selected_region_semantics
```

GREEN / focused:

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
.\.venv\Scripts\python.exe -m pytest -q `
  RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py::test_user_input_replay_preserves_top_level_region_context_scope_and_acquisition
```

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
.\.venv\Scripts\python.exe -m pytest -q `
  RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py::test_full_live_profile_passes_picked_element_acquisition_as_generic_region_context
```

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
.\.venv\Scripts\python.exe -m pytest -q `
  RpaClaw/backend/tests/test_rpa_harness_expected_signals.py::test_region_scoped_trace_expected_signals_preserve_selected_region_semantics
```

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
.\.venv\Scripts\python.exe -m pytest -q `
  RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py `
  RpaClaw/backend/tests/test_rpa_harness_expected_signals.py `
  RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py `
  RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py
```

Harness structure and diff check:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py `
  --root E:\Work-Project\OtherWork\ScienceClaw `
  --docs-path docs `
  --strict
```

```powershell
git diff --check -- RpaClaw/backend/rpa/harness/user_input_replay.py `
  RpaClaw/backend/rpa/harness/full_live_profile.py `
  RpaClaw/backend/rpa/harness/expected_signals.py `
  RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py `
  RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py `
  RpaClaw/backend/tests/test_rpa_harness_expected_signals.py `
  docs/features/F020-rpa-harness-region-element-selection-simulation.md `
  docs/evidence/EV-020-rpa-harness-region-element-selection-simulation.md `
  docs/rpa/harness/v1.1-region-selection-download-risk-todo.md `
  docs/BACKLOG.md
```

## Results

- RED user-input replay: failed because `event["region_context"]` was `{}` when trace events only carried top-level `region_context`, `region_scope`, and `signals.region_selection`.
- RED full-live profile: failed with `KeyError: 'event'`, proving picked-element acquisition facts never reached the selected input event / full-live source context.
- RED expected signals: failed because `acquisition=picked_element` was not included in `must_preserve_region_scope`.
- GREEN user-input replay focused test: `1 passed`.
- GREEN full-live profile focused test: `1 passed`.
- GREEN expected signals focused test: `1 passed`.
- Focused related suite: `43 passed in 25.92s`.
- Harness structure: `Scanned 229 markdown file(s). Checked 44 knowledge artifact(s). Errors: 0. Warnings: 0.`
- Diff check: passed with line-ending warnings only (`LF will be replaced by CRLF`).

## Harness Validation

`knowledge_check.py --strict` passed:

```text
Scanned 229 markdown file(s). Checked 44 knowledge artifact(s). Errors: 0. Warnings: 0.
```

## Artifacts

- Feature: `docs/features/F020-rpa-harness-region-element-selection-simulation.md`
- Evidence: `docs/evidence/EV-020-rpa-harness-region-element-selection-simulation.md`
- Coverage Matrix: `docs/rpa/harness/f020-region-element-selection-coverage-matrix.md`
- Implementation: `RpaClaw/backend/rpa/harness/user_input_replay.py`, `RpaClaw/backend/rpa/harness/full_live_profile.py`, `RpaClaw/backend/rpa/harness/expected_signals.py`
- Review implementation: `RpaClaw/backend/rpa/harness/asset_review.py`
- Region runtime implementation: `RpaClaw/backend/rpa/recording_runtime_agent.py`
- Regression tests: `RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py`, `RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py`, `RpaClaw/backend/tests/test_rpa_harness_expected_signals.py`, `RpaClaw/backend/tests/test_rpa_harness_asset_review.py`

## F020.2-F020.4 Addendum

2026-05-30 追加完成剩余三个切片：

- F020.2 controlled fixture: user-input replay 与 full-live profile summary 现在报告 `region_context_event_count` 和 `region_acquisitions`，受控测试覆盖 `drag_region` 与 `picked_element`。
- F020.3 captured/candidate-lite review boundary: Review Packet 现在包含 `Region Selection Evidence`，显示 region id、acquisition、kind 与 local evidence；该行为不改变 promotion，仍要求人工 expected/sensitivity review。
- F020.4 coverage matrix: 新增 `docs/rpa/harness/f020-region-element-selection-coverage-matrix.md`，明确 F020/F019 的组合边界、iframe future work、runtime-AI fallback 与 promotion 限制。

新增 RED/GREEN 证据：

```text
RED user-input controlled fixture:
KeyError: 'region_context_event_count'

RED full-live controlled fixture:
KeyError: 'acquisition' in planner payload snapshot.region_scope

RED asset review:
AssertionError: 'Region Selection Evidence' not in review packet

GREEN focused:
test_user_input_replay_reports_controlled_region_and_picked_element_acquisitions: 1 passed
test_full_live_profile_reports_controlled_drag_and_picked_element_acquisitions: 1 passed
test_review_packet_surfaces_region_acquisition_without_promoting_asset: 1 passed
```

Final verification for F020.2-F020.4:

```text
.\.venv\Scripts\python.exe -m pytest -q RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py RpaClaw/backend/tests/test_rpa_harness_expected_signals.py RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py RpaClaw/backend/tests/test_rpa_harness_asset_review.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py
49 passed in 47.22s

.\.venv\Scripts\python.exe -m pytest -q RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py -k "compact_region_context or passes_region_context_to_planner"
3 passed, 83 deselected in 0.15s

python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
Scanned 231 markdown file(s). Checked 44 knowledge artifact(s). Errors: 0. Warnings: 0.

git diff --check
Passed with CRLF warnings only.
```

Reviewer note:

```text
Independent review was attempted with subagent 019e7696-cf63-7543-9c59-391221c1a3f2, but it timed out twice and was closed while still running.
No independent reviewer findings were incorporated.
Residual risk is recorded as review unavailable, mitigated by focused RED/GREEN tests and Harness structural validation.
```

## Residual Risk

- First slice is standard evidence, not exhaustive: it covers replay/profile evidence boundaries with controlled fixtures, not real internal assets or iframe element picking.
- Real candidate/golden promotion remains gated on human expected-signal and sensitivity review. F020.3 only makes region acquisition visible in review packets; it does not auto-promote assets.
- Existing dirty workspace has unrelated deleted bootstrap assets under `data/rpa_harness_assets_bootstrap/**`; F020 should not restore or revert them.
- iframe element picking remains future work and is explicitly excluded from F020 coverage.

## Notes

- F020 uses F019 only as a composable side-effect lane for future region/download scenarios.
- `runtime_status=success` remains insufficient for region/element selection acceptance; reports must show preserved region facts and expected signals.

## Closeout

Closeout verdict: pass.

Completion claim allowed: yes, limited to F020 first-slice scope.

Entry Gate: pass. F020/EV020 were created before production code; F011/F016/F017/F019/EV018 were retrieved.

Vision Anchor: pass. The solution keeps element picking as region acquisition metadata and does not introduce `element_context`.

Evidence: standard. RED/GREEN tests cover user-input replay, full-live planner context, and expected-signal preservation for `acquisition=picked_element`; focused related suite passes.

Feature: F020 active, first slice implemented and ready for review.

ADR: not triggered. This follows existing Trace-first and asset-driven Harness decisions.

Lesson: not triggered. The failure mode is now protected by focused regression tests and EV-020.

Check: pass. Harness structural check and diff check pass; unrelated dirty workspace state remains outside F020.
