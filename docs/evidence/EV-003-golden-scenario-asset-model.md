---
id: EV-003
doc_kind: evidence
title: Golden Scenario Asset Model Evidence
status: active
scope: project
feature_ids: [F003]
created: 2026-05-18
updated: 2026-05-18
evidence_level: exhaustive
---

# EV-003 Golden Scenario Asset Model Evidence

## Scope

Evidence for F003: define and implement the Golden Scenario Asset Model so captured RPA Harness assets can be promoted into governed offline regression assets without relying on the old `rpa-eval-app` direct Agent chat runner as the golden path.

This Evidence starts before implementation because the project requires each Harness Feature to have a recoverable Feature/Evidence anchor before code work begins.

## Commands

RED verification before implementation:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_models.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_harness_catalog.py
```

Focused GREEN verification:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_models.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_harness_catalog.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py RpaClaw/backend/tests/test_rpa_harness_blast_radius.py
```

Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

## Results

RED result before implementation:

```text
4 failed, 15 passed in 0.96s
```

The failing tests confirmed the missing behavior:

- `HarnessScenarioAsset` had no `governance` metadata.
- asset validation did not report candidate/golden promotion blockers.
- catalog did not expose promotion, runner mode, or core-chain coverage summaries.

Final focused GREEN result after closeout updates:

```text
37 passed in 0.71s
```

`git diff --check` over the touched files produced no whitespace errors. It only emitted Windows line-ending warnings.

## Harness Validation

Strict Harness validation:

```text
Scanned 159 markdown file(s). Checked 10 knowledge artifact(s). Errors: 0. Warnings: 0.
```

## Artifacts

- Feature: [F003 Golden Scenario Asset Model](../features/F003-golden-scenario-asset-model.md)
- Vision: [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Prior Feature: [F002 RPA Harness v0](../features/F002-rpa-harness-v0.md)
- Prior Evidence: [EV-002 RPA Harness v0 Evidence](EV-002-rpa-harness-v0.md)
- Backlog: [Backlog](../BACKLOG.md)
- Code:
  - `RpaClaw/backend/rpa/harness/models.py`
  - `RpaClaw/backend/rpa/harness/asset_validation.py`
  - `RpaClaw/backend/rpa/harness/catalog.py`
- Tests:
  - `RpaClaw/backend/tests/test_rpa_harness_models.py`
  - `RpaClaw/backend/tests/test_rpa_harness_asset_validation.py`
  - `RpaClaw/backend/tests/test_rpa_harness_catalog.py`
- Implementation commit: `a38b8a3` (`feat: add rpa golden scenario asset governance`).

## Entry Gate

- Start Gate: high-risk Harness feature. Required pre-work is this F003 Feature/Evidence anchor.
- Knowledge Retrieval: completed against `docs/rpa/harness/golden-evaluation-vision.md`, `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`, `docs/features/F002-rpa-harness-v0.md`, `docs/evidence/EV-002-rpa-harness-v0.md`, and `docs/BACKLOG.md`.
- Delegation Gate: not needed for the first slice. The model, validation, and catalog changes are tightly coupled and should be driven by one TDD loop.
- Vision Gate Entry: ready to implement. The smallest coherent path is governed asset metadata plus promotion validation and coverage reporting; direct Agent chat runner work is out of scope.
- Vision Anchor: [F003 Golden Scenario Asset Model](../features/F003-golden-scenario-asset-model.md).

## Notes

- `rpa-eval-app` remains useful as a controlled business page and assertion service provider for future Skill Replay E2E.
- F003 must not make live Agent chat completion the primary golden evaluation oracle.
- Historical F002 draft asset findings remain evidence for governance and promotion checks; they should not be hidden by unit-test-only success.

## Implementation Summary

F003 adds `HarnessScenarioGovernance` to `HarnessScenarioAsset`:

- `promotion_status`: `captured`, `candidate`, `golden`, or `rejected`.
- `runner_modes`: currently `offline_core_chain` and `skill_replay_e2e`.
- `core_chain_coverage`: explicit coverage of snapshot, planner/action, compiler, and replay segments.
- `expected_signals_reviewed` and `sensitivity_reviewed`: promotion review gates.
- `review_notes`: lightweight promotion/rejection context.

Validation now treats `candidate` and `golden` assets as governed promotion surfaces. Draft `captured` assets can remain incomplete without blocking, while governed assets report blocking promotion issues for missing runner modes, missing core-chain coverage, unreviewed expected signals, and unreviewed sensitivity. `golden` assets must also be `asset_status=active`.

Catalog now reports:

- `promotion_statuses`
- `runner_modes`
- `core_chain_coverage`
- per-capture `governance`

No direct Agent chat runner was added or extended.

## Exit Gate

- Vision Gate Exit: pass. The deliverable advances the original F003 goal by making scenario assets governed regression inputs instead of live Agent chat tasks.
- Acceptance-criteria drift: none found. The implementation stayed on model/validation/catalog coverage and did not expand into replay execution or business extraction repair.
- Reviewer policy: independent review recommended for this non-trivial Harness/data-model slice, but not run in-session because subagent dispatch requires explicit user authorization. Residual risk is limited by focused tests, strict knowledge validation, and the backwards-compatible default model.
- ADR: not triggered. ADR-003 already owns the architectural decision to use scenario assets rather than direct Agent chat.
- Lesson: not triggered. No new recurring failure mode was found.
- Patch Churn Review: not triggered. F003 has no patch history.

## Closeout Status

- Feature: F003 completed.
- Evidence level: exhaustive for this slice.
- Readiness: pass for commit/push with residual independent-review risk noted above.
- Completion claim: allowed for F003 Golden Scenario Asset Model.
- Residual risks:
  - The first curated candidate/golden asset set still needs a follow-up Feature slice.
  - Skill Replay E2E remains prepared by the asset model but not implemented in this slice.
  - Existing F002 compiler-hardcoded-observed-value findings remain RPA Agent / `TraceSkillCompiler` generalization work, not F003 infrastructure.
