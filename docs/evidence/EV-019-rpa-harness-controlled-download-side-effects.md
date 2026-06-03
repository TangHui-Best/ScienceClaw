---
id: EV-019
doc_kind: evidence
title: RPA Harness Controlled Download Side Effects Evidence
status: active
scope: project
feature_ids: [F019]
feature_refs:
  - docs/features/F019-rpa-harness-controlled-download-side-effects.md
created: 2026-05-29
updated: 2026-05-30
evidence_level: standard
---

# EV-019 RPA Harness Controlled Download Side Effects Evidence

## Scope

Evidence for F019: controlled download side effects in RPA Harness.

This slice exists to prove that a controlled fixture can model a browser download
side effect for scenarios such as:

```text
点击列表第一行的文件名称
```

It does not prove live-site correctness, does not create a generic mock backend,
and does not promote any assets automatically.

## Entry Gate

Start Gate:

```text
Start Gate: ready
Task class: high-risk
Risk triggers:
- Harness expected-signal shape
- controlled replay route side effects
- browser download event semantics
- generated Skill replay behavior
- report overclaiming risk
Delegation decision:
- not needed; implementation is a tight first slice in one replay path
Bug attribution:
- new F019 capability slice spanning F016/F017 gap
Required pre-work:
- retrieve F016/F017/F018 and existing compiler/replay download support
- create F019 and EV-019 before production code
Allowed next action:
- write RED tests for controlled download replay
```

Knowledge Retrieval:

- Read F016/F017/F018 Feature pages.
- Read EV-018.
- Read `RpaClaw/backend/rpa/trace_skill_compiler.py`.
- Read `RpaClaw/backend/rpa/generator.py`.
- Read `RpaClaw/backend/rpa/harness/skill_replay.py`.
- Read `RpaClaw/backend/rpa/harness/live_agent_eval.py`.

Retrieval conclusion:

- Compiler download wrapping already exists.
- Controlled replay route currently lacks declared attachment responses.
- First implementation should attach download fixtures through expected signals and
  validate generated Skill replay output.

## Commands

RED:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-f019-red-1 `
  RpaClaw/backend/tests/test_rpa_harness_skill_replay.py::test_skill_replay_serves_controlled_download_and_validates_saved_file
```

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-f019-red-2 `
  RpaClaw/backend/tests/test_rpa_harness_live_agent_eval.py::test_live_agent_eval_controlled_download_is_captured_as_trace_signal
```

GREEN / focused:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-f019-green-1 `
  RpaClaw/backend/tests/test_rpa_harness_skill_replay.py::test_skill_replay_serves_controlled_download_and_validates_saved_file
```

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-f019-green-5 `
  RpaClaw/backend/tests/test_rpa_harness_live_agent_eval.py::test_live_agent_eval_controlled_download_is_captured_as_trace_signal
```

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-f019-suite-1 `
  RpaClaw/backend/tests/test_rpa_harness_skill_replay.py `
  RpaClaw/backend/tests/test_rpa_harness_live_agent_eval.py `
  RpaClaw/backend/tests/test_rpa_harness_stateful_sop.py `
  RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py
```

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-f019-suite-2 `
  RpaClaw/backend/tests/test_rpa_harness_skill_replay.py `
  RpaClaw/backend/tests/test_rpa_harness_live_agent_eval.py `
  RpaClaw/backend/tests/test_rpa_harness_stateful_sop.py `
  RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py `
  -k "not real_governed_candidate_asset"
```

Harness structure:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py `
  --root E:\Work-Project\OtherWork\ScienceClaw `
  --docs-path docs `
  --strict
```

## Results

- RED Skill replay: failed with Playwright timeout waiting for `download`, proving the static controlled fixture could click the target but could not produce a browser download event before F019.
- RED full-live scenario: failed before the controlled download route / post-capture path supported attachment side effects.
- GREEN Skill replay focused test: `1 passed`.
- GREEN full-live focused test: `1 passed`.
- Full related suite: `27 passed, 2 failed, 1 warning`. The 2 failures were `real_governed_candidate_asset` tests whose eligible asset count was 0 because tracked files under `data/rpa_harness_assets_bootstrap/**` were already deleted in the working tree before F019 work. F019 did not restore or revert those unrelated deletions.
- Focused related suite excluding the two bootstrap-asset-dependent tests: `27 passed, 2 deselected, 1 warning`.
- Final focused related suite rerun: `27 passed, 2 deselected, 1 warning in 36.28s`.
- Commit-time focused related suite rerun on 2026-05-30: `27 passed, 2 deselected, 1 warning in 51.40s`.
- First Harness structure run failed because the newly created F019/EV-019 pages were missing template-required sections. This evidence page and F019 were updated to include those sections. Final rerun: `Scanned 227 markdown file(s). Checked 42 knowledge artifact(s). Errors: 0. Warnings: 0.`

## Artifacts

- Feature: `docs/features/F019-rpa-harness-controlled-download-side-effects.md`
- Evidence: `docs/evidence/EV-019-rpa-harness-controlled-download-side-effects.md`
- Runtime replay implementation: `RpaClaw/backend/rpa/harness/skill_replay.py`
- Full-live implementation: `RpaClaw/backend/rpa/harness/live_agent_eval.py`
- Stateful post-capture replay implementation: `RpaClaw/backend/rpa/harness/stateful_sop.py`
- Regression tests: `RpaClaw/backend/tests/test_rpa_harness_skill_replay.py`, `RpaClaw/backend/tests/test_rpa_harness_live_agent_eval.py`

## Residual Risk

- Evidence level is `standard`, not exhaustive: this slice proves controlled attachment downloads for one declared URL/body fixture pattern, not every browser download mechanism such as POST downloads, auth-gated downloads, blob URLs, streaming responses, or multiple simultaneous downloads.
- The saved download path in replay output is validated during execution; when a temporary download directory is used, the path should be treated as validation evidence, not a durable retained artifact.
- Full related suite remains blocked from a clean all-pass claim until the pre-existing deleted bootstrap assets are restored or the tests are intentionally updated.

## Notes

- This is intentionally modeled as a Harness controlled side effect. It does not turn static fixture replay into a generic backend simulator and does not claim live-site correctness.
- `runtime_status=success` remains insufficient for acceptance; the report must include controlled download evidence such as filename, saved-file validation, size, and sha256.

## Closeout

Closeout verdict: conditional pass.

Completion claim allowed: yes, limited to the implemented F019 controlled-download slice and its focused verification scope.

Entry Gate: pass. F019/EV-019 created before implementation; F016/F017/F018 and existing compiler/replay behavior were retrieved.

Vision Anchor: pass. The solution models the missing browser side effect in controlled fixtures without expanding into a generic mock backend.

Evidence: standard. RED/GREEN tests cover Skill replay and full-live natural-language controlled download capture; focused related suite passes after excluding two unrelated bootstrap-asset-dependent failures.

Feature: F019 ready_for_review.

ADR: not triggered. This follows existing Trace-first and asset-driven Harness decisions.

Lesson: not triggered. The failure mode is now protected by regression tests and EV-019; no recurring-process lesson is required yet.

Check: conditional. Harness structural check passes; focused related suite passes. Full related suite still has unrelated bootstrap asset failures caused by pre-existing deleted tracked files under `data/rpa_harness_assets_bootstrap/**`.
