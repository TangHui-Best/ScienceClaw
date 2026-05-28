---
id: EV-004
doc_kind: evidence
title: Governed Offline Regression Asset Pool Evidence
status: active
scope: project
feature_ids: [F004]
feature_refs:
  - docs/features/F004-governed-offline-regression-asset-pool.md
created: 2026-05-18
updated: 2026-05-18
evidence_level: exhaustive
---

# EV-004 Governed Offline Regression Asset Pool Evidence

## Scope

Evidence for F004: establish the first governed offline regression asset pool
and default report over candidate/golden scenario assets. The slice starts from
F003 governance metadata and keeps the golden path scenario-asset driven.

## Entry Gate

- Start Gate: non-trivial Harness Feature. Required pre-work is this F004
  Feature/Evidence anchor before implementation.
- Knowledge Retrieval: completed against F003, EV-003, `docs/BACKLOG.md`,
  `docs/rpa/harness/golden-evaluation-vision.md`, and ADR-003.
- Vision Gate Entry: ready to implement. The smallest coherent path is a
  governed offline asset selector plus default offline regression report.
- Delegation Gate: not needed for implementation. The first slice is tightly
  coupled across selector/report/tests and is small enough for one TDD loop.
- Vision Anchor: [F004 Governed Offline Regression Asset Pool](../features/F004-governed-offline-regression-asset-pool.md).

## Source Validation

Latest manual Full SOP validation asset:

```text
data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc
```

Observed before implementation:

- Asset validation over a temporary single-asset root: `issue_count=0`,
  `blocking_issue_count=0`.
- Snapshot regression: `3 passed, 0 failed`.
- Compiler regression: `3 passed, 0 failed`.
- Catalog: `step_count=3`, `successful_step_count=3`.
- Step 1 navigation after-capture quality: `status=stable`,
  `ready_state=interactive`, `title_present=true`, `html_bytes=625418`.

This asset is a good seed candidate, but remains `draft/captured` until F004
promotion/governed-pool behavior exists.

## Commands

RED verification will target governed selection and default offline reporting:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_governed_regression.py
```

Focused GREEN verification will include the new tests plus existing Harness
catalog, validation, snapshot, compiler, and blast-radius tests.

Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

## Results

RED result before implementation:

```text
ModuleNotFoundError: No module named 'backend.rpa.harness.governed_regression'
```

The failing test confirmed that the governed offline regression entrypoint did
not exist.

Second RED result during implementation:

```text
AssertionError: assert 'passed' == 'failed'
```

The failing test confirmed that an empty governed asset pool was incorrectly
reported as passing. F004 requires an empty default baseline to fail with
`no-governed-offline-assets`.

GREEN result for F004 tests:

```text
4 passed in 0.50s
```

Focused Harness regression:

```text
35 passed in 0.56s
```

Broader Harness regression:

```text
67 passed, 27 warnings in 1.50s
```

Latest unpromoted Full SOP asset CLI check:

```text
status=failed
failure_category=no-governed-offline-assets
selected_capture_count=0
excluded_capture_count=1
excluded_asset_ids=["hcap-4be6265f43eb42dfa259182207aa64cc"]
```

This is expected because the latest manual capture is still
`draft/captured`, has no core-chain coverage, and has not completed expected
signal or sensitivity review.

## Artifacts

- Feature: [F004 Governed Offline Regression Asset Pool](../features/F004-governed-offline-regression-asset-pool.md)
- Vision: [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Prior Feature: [F003 Golden Scenario Asset Model](../features/F003-golden-scenario-asset-model.md)
- Prior Evidence: [EV-003 Golden Scenario Asset Model Evidence](EV-003-golden-scenario-asset-model.md)
- Backlog: [Backlog](../BACKLOG.md)
- Code:
  - `RpaClaw/backend/rpa/harness/governed_regression.py`
  - `RpaClaw/backend/rpa/harness/run_governed_regression.py`
  - `RpaClaw/backend/rpa/harness/catalog.py`
  - `RpaClaw/backend/rpa/harness/asset_validation.py`
  - `RpaClaw/backend/rpa/harness/snapshot_regression.py`
  - `RpaClaw/backend/rpa/harness/compiler_regression.py`
- Tests:
  - `RpaClaw/backend/tests/test_rpa_harness_governed_regression.py`
- Implementation commit: `a21654c` (`feat: add governed rpa harness offline regression`).

## Implementation Summary

F004 adds `run_governed_offline_regression()` and
`python -m backend.rpa.harness.run_governed_regression`.

The report:

- builds the full catalog to inspect all local assets;
- selects only active, reviewed `candidate` or `golden` assets with
  `offline_core_chain` runner eligibility and non-empty core-chain coverage;
- reports excluded captures with concrete reasons such as
  `asset-status-draft`, `promotion-status-captured`,
  `expected-signals-not-reviewed`, or `offline-core-chain-not-enabled`;
- runs validation, snapshot regression, compiler regression, and blast-radius
  reporting over the selected governed assets;
- fails with `no-governed-offline-assets` when the governed pool is empty.

Existing catalog, validation, snapshot, and compiler runners now accept an
optional `asset_ids` filter so governed regression can reuse the same
components without evaluating every draft capture.

## Notes

- The governed offline pool is metadata-driven. It does not contain GitHub
  special cases or site-specific page rules.
- Draft captures stay useful as diagnostic evidence, but they do not silently
  enter the default blocking baseline.
- `rpa-eval-app` direct Agent chat remains outside this path. Future
  `rpa-eval-app` usage should be as a controlled page/assertion provider for
  Skill Replay E2E.
- The new report reuses existing catalog, validation, snapshot, compiler, and
  blast-radius components instead of introducing a second evaluation stack.

## Residual Risks

- First governed pool behavior should be generic and metadata-driven. GitHub
  assets can validate behavior, but must not shape Harness abstractions.
- Skill Replay E2E remains out of scope until governed offline assets have a
  stable default baseline.
- Real candidate/golden promotion of local captures may still require a later
  curation commit that edits or copies asset metadata; this Feature should make
  the mechanism and report reliable first.

## Closeout Status

- Feature: F004 completed.
- Evidence level: exhaustive for this Harness regression slice.
- Readiness: pass for commit/push with residual independent-review risk noted.
- Completion claim: allowed for F004 Governed Offline Regression Asset Pool.
- ADR: not triggered. ADR-003 already owns the scenario-asset-first golden
  evaluation decision.
- Lesson: not triggered. No new recurring failure mode was found.
- Patch Churn Review: not triggered. F004 has no patch history.
- Residual risks:
  - The latest real Full SOP asset remains `draft/captured`; a later curation
    step should promote or reject it by editing asset metadata or copying it
    into a governed fixture pool.
  - Skill Replay E2E remains out of scope until governed offline assets exist.
  - Independent review is recommended for this non-trivial Harness feature but
    was not run because subagent dispatch requires explicit user authorization.
