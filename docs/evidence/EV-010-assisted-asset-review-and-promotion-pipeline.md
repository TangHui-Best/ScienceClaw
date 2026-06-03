---
id: EV-010
doc_kind: evidence
title: Assisted Asset Review And Promotion Pipeline Evidence
status: active
scope: project
feature_ids: [F010]
feature_refs:
  - docs/features/F010-assisted-asset-review-and-promotion-pipeline.md
created: 2026-05-19
updated: 2026-05-19
evidence_level: exhaustive
---

# EV-010 Assisted Asset Review And Promotion Pipeline Evidence

## Scope

Evidence for F010: create a review-and-promotion pipeline that turns newly
captured RPA Harness assets into readable Review Packets and supports
non-blocking `candidate-lite` promotion without changing existing blocking
candidate/golden semantics.

## Entry Gate

- Start Gate: high-risk Harness feature. Primary path is retrieval, Feature /
  Evidence anchor creation, implementation delegation, independent Vision Gate,
  and TDD.
- Knowledge Retrieval: read AGENTS.md, Backlog, F009/EV-009, Harness usage
  guide, scenario schema, model definitions, and available Harness tests.
- Delegation Gate: authorized by user. Implementation may use multiple
  subagents; independent Vision Gate review must be separate from development.
- Vision Gate Entry: independent reviewer returned `ready to implement`.
- Brainstorming gate: satisfied by the user-confirmed F010 goal and explicit
  scope boundaries; no extra clarification is needed before the smallest
  implementation slice.
- TDD: required. Review packet and promotion behavior must have failing tests
  before production code is added.

## Commands

Planned RED verification:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_review.py RpaClaw/backend/tests/test_rpa_harness_governed_regression.py
```

Planned focused Harness regression:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py RpaClaw/backend/tests/test_rpa_harness_skill_replay.py RpaClaw/backend/tests/test_rpa_harness_stateful_sop.py RpaClaw/backend/tests/test_rpa_harness_governed_regression.py RpaClaw/backend/tests/test_rpa_harness_asset_review.py
```

Planned real asset review:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_review --assets data\rpa_harness_assets_bootstrap --asset-id hcap-de463b7bb608482e9b5bcdd5b78a224e
```

Planned real asset promotion:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_promote --assets data\rpa_harness_assets_bootstrap --asset-id hcap-de463b7bb608482e9b5bcdd5b78a224e --level candidate-lite
```

Planned governed check:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_bootstrap --output tmp-harness-governed-f010.json
```

Planned Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

## Results

Entry Vision Gate reviewer:

```text
Vision Gate: ready to implement
Scope is coherent and proportionate. Review Packet directly addresses the
pain point. candidate-lite is correctly framed as observation, not trusted
baseline.
```

RED results before production code:

```text
Review Packet RED:
ModuleNotFoundError: No module named 'backend.rpa.harness.asset_review'

Promotion RED:
ModuleNotFoundError: No module named 'backend.rpa.harness.asset_promotion'

Integration RED after worker handoff:
3 failed, 10 passed
- missing Confidence / source hosts / final output in Review Packet
- candidate-lite did not add observation runner modes and coverage
- Stateful SOP had no explicit candidate-lite observation switch

Auto-check RED:
1 failed, 1 passed
- Review Packet did not include snapshot/compiler regression summaries
```

Focused GREEN results:

```text
RpaClaw/backend/tests/test_rpa_harness_asset_review.py
2 passed

RpaClaw/backend/tests/test_rpa_harness_asset_promotion.py
RpaClaw/backend/tests/test_rpa_harness_governed_regression.py
15 passed

Focused Harness suite:
59 passed in 85.71s
```

Compile check:

```text
python -m compileall -q RpaClaw/backend/rpa/harness/asset_review.py
RpaClaw/backend/rpa/harness/run_asset_review.py
RpaClaw/backend/rpa/harness/asset_promotion.py
RpaClaw/backend/rpa/harness/run_asset_promote.py
RpaClaw/backend/rpa/harness/governed_regression.py
RpaClaw/backend/rpa/harness/stateful_sop.py

exit 0
```

Real asset review:

```text
python -m backend.rpa.harness.run_asset_review --assets data\rpa_harness_assets_bootstrap --asset-id hcap-de463b7bb608482e9b5bcdd5b78a224e --output tmp-harness-asset-review-f010.json

Generated:
data/rpa_harness_assets_bootstrap/hcap-de463b7bb608482e9b5bcdd5b78a224e/review.md

Review Packet key lines:
- Confidence: high
- Source hosts: github.com
- Steps: 3
- Final output: star_count = 18.3k stars
- Asset validation: passed
- Snapshot regression: passed (3/3)
- Compiler regression: passed (3/3)
```

F010.1 Chinese-first Review Packet follow-up:

```text
RED:
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw\backend\tests\test_rpa_harness_asset_review.py

2 failed
- missing "# 资产审查包" because generated output still started with "# Asset Review Packet"
- missing "资产 ID: `asset-1`" because generated output still used "Asset ID"

GREEN:
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw\backend\tests\test_rpa_harness_asset_review.py

2 passed in 3.32s
```

F010.1 real bootstrap asset regeneration:

```text
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_review --assets data\rpa_harness_assets_bootstrap --output tmp-harness-asset-review-cn-f010.json

review_count=2
Generated:
- data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc/review.md
- data/rpa_harness_assets_bootstrap/hcap-de463b7bb608482e9b5bcdd5b78a224e/review.md

Spot check:
- "# 资产审查包（Asset Review Packet）"
- "## 场景身份（Scenario Identity）"
- "## 人类可读 SOP（Human SOP）"
- "资产校验: 通过"
- "candidate-lite"
```

F010.2 human-confirmed blocking promotion:

```text
User confirmation:
"确认 expected 和 sensitivity，可以升 candidate"

Initial promotion command:
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_promote --assets data\rpa_harness_assets_bootstrap --asset-id hcap-de463b7bb608482e9b5bcdd5b78a224e --level candidate --confirm-expected --confirm-sensitivity --output tmp-harness-asset-promote-candidate-f010.json

Observed mismatch:
- promotion_status=candidate
- expected_signals_reviewed=true
- sensitivity_reviewed=true
- asset_status still draft
- governed regression excluded the asset with reason asset-status-draft

Root cause:
Promotion CLI changed governance but did not activate candidate/golden assets,
so a human-confirmed candidate did not actually enter the blocking governed
baseline.
```

F010.2 RED/GREEN fix:

```text
RED:
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw\backend\tests\test_rpa_harness_asset_promotion.py

1 failed, 2 passed
- expected candidate promotion to set asset_status=active
- actual asset_status remained draft

GREEN:
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw\backend\tests\test_rpa_harness_asset_promotion.py

3 passed in 0.18s
```

F010.2 real promotion after fix:

```text
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_promote --assets data\rpa_harness_assets_bootstrap --asset-id hcap-de463b7bb608482e9b5bcdd5b78a224e --level candidate --confirm-expected --confirm-sensitivity --output tmp-harness-asset-promote-candidate-f010.json

promotion_status=candidate
expected_signals_reviewed=true
sensitivity_reviewed=true
review.md spot check:
- 资产状态: `active`
- 治理状态: candidate；expected reviewed=True；sensitivity reviewed=True
```

F010.2 real governed regression:

```text
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_validation --assets data\rpa_harness_assets_bootstrap --output tmp-harness-asset-validation-candidate-f010.json

capture_count=2
issue_count=0
blocking_issue_count=0

$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_bootstrap --output tmp-harness-governed-candidate-f010.json

status=passed
selected_capture_count=2
excluded_capture_count=0
selected_asset_ids=[
  hcap-4be6265f43eb42dfa259182207aa64cc,
  hcap-de463b7bb608482e9b5bcdd5b78a224e
]
snapshot_failed=0
compiler_failed=0
skill_replay_failed=0
stateful_sop_failed=0

Focused tests:
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw\backend\tests\test_rpa_harness_asset_promotion.py RpaClaw\backend\tests\test_rpa_harness_governed_regression.py

15 passed in 27.57s
```

Two upgraded assets execution report:

```text
Report:
docs/rpa/harness/reports/2026-05-19-two-assets-governed-run.md

Source machine reports:
- tmp-harness-asset-validation-run-two-assets.json
- tmp-harness-governed-run-two-assets.json

Summary:
status=passed
selected_capture_count=2
excluded_capture_count=0
snapshot_failed=0
compiler_failed=0
skill_replay_failed=0
stateful_sop_failed=0
```

Precommit verification for F010 delivery:

```text
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw\backend\tests\test_rpa_harness_asset_validation.py RpaClaw\backend\tests\test_rpa_harness_snapshot_regression.py RpaClaw\backend\tests\test_rpa_harness_compiler_regression.py RpaClaw\backend\tests\test_rpa_harness_skill_replay.py RpaClaw\backend\tests\test_rpa_harness_stateful_sop.py RpaClaw\backend\tests\test_rpa_harness_governed_regression.py RpaClaw\backend\tests\test_rpa_harness_asset_review.py RpaClaw\backend\tests\test_rpa_harness_asset_promotion.py

52 passed in 52.75s

python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
Errors: 0
Warnings: 0

python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\harness_closeout_check.py --file docs\evidence\EV-010-assisted-asset-review-and-promotion-pipeline.md
Harness closeout block structure: pass

$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_bootstrap --output tmp-harness-governed-precommit-f010.json

status=passed
selected_capture_count=2
excluded_capture_count=0
snapshot_failed=0
compiler_failed=0
skill_replay_failed=0
stateful_sop_failed=0
```

Real asset promotion:

```text
python -m backend.rpa.harness.run_asset_promote --assets data\rpa_harness_assets_bootstrap --asset-id hcap-de463b7bb608482e9b5bcdd5b78a224e --level candidate-lite --output tmp-harness-asset-promote-f010.json

promotion_status=candidate-lite
expected_signals_reviewed=false
sensitivity_reviewed=false
runner_modes=[
  offline_core_chain,
  skill_replay_e2e,
  stateful_sop_capture_to_skill
]
```

Asset validation:

```text
capture_count=2
issue_count=0
blocking_issue_count=0
```

Governed regression:

```text
summary.status=passed
summary.selected_asset_ids=["hcap-4be6265f43eb42dfa259182207aa64cc"]
summary.excluded_asset_ids=["hcap-de463b7bb608482e9b5bcdd5b78a224e"]
summary.candidate_lite_observed_count=1
summary.candidate_lite_warning_count=0
summary.snapshot_failed=0
summary.compiler_failed=0
summary.skill_replay_failed=0
summary.stateful_sop_failed=0

candidate_lite_observation.summary.status=passed
candidate_lite_observation.summary.observed_asset_ids=["hcap-de463b7bb608482e9b5bcdd5b78a224e"]
candidate_lite_observation.stateful_sop.summary.eligible_capture_count=1
candidate_lite_observation.stateful_sop.summary.failed=0
candidate_lite_observation.skill_replay.summary.total=3
candidate_lite_observation.skill_replay.summary.failed=0
```

Independent Exit review:

```text
Initial verdict: needs revision
P1: EV-010 still said results Not run yet and closeout pending.
P1: F010 status remained active and AC unchecked.
P2: promotion tests covered candidate but did not explicitly cover golden.

Code behavior finding:
No actionable code finding found for candidate-lite blocking behavior.
No live URL, direct chat, or product UI automation path found.
```

Post-review fix:

```text
Added explicit golden rejection/success assertions.
Focused promotion/governed tests: 15 passed in 42.18s
Updated F010 and EV-010 closeout state.
```

## Artifacts

- Feature: [F010 Assisted Asset Review And Promotion Pipeline](../features/F010-assisted-asset-review-and-promotion-pipeline.md)
- Plan: [F010 implementation plan](../rpa/harness/f010-assisted-asset-review-and-promotion-plan.md)
- Target asset: `data/rpa_harness_assets_bootstrap/hcap-de463b7bb608482e9b5bcdd5b78a224e`
- Review Packet: `data/rpa_harness_assets_bootstrap/hcap-de463b7bb608482e9b5bcdd5b78a224e/review.md`
- Real reports:
  - `tmp-harness-asset-review-f010.json`
  - `tmp-harness-asset-review-cn-f010.json`
  - `tmp-harness-asset-review-candidate-f010.json`
  - `tmp-harness-asset-promote-f010.json`
  - `tmp-harness-asset-promote-candidate-f010.json`
  - `tmp-harness-asset-validation-f010.json`
  - `tmp-harness-asset-validation-candidate-f010.json`
  - `tmp-harness-governed-f010.json`
  - `tmp-harness-governed-candidate-f010.json`

## Notes

- F010 should explain captured facts; it should not use a live website as an
  oracle or restore direct Agent chat.
- `candidate-lite` is intentionally non-blocking. It is an observation and
  triage layer for newly recorded assets before expected-signal and sensitivity
  review are complete.
- Blocking `candidate` and `golden` promotion still requires explicit review.

## Residual Risks

- Implementation is ready for F010 commit/push from the current branch; final
  Git hash is recorded by repository history and the delivery response.
- Candidate-lite observation now runs the target asset through governed
  warning-only runners, but it remains outside blocking baseline by design.
- Review Packet inference may be conservative when capture evidence is sparse;
  low confidence should be visible instead of guessed away.
- Target asset has human-confirmed expected signals and sensitivity review,
  and is now active blocking `candidate`. Its `sensitivity` label remains the
  recorded classification unless a future workflow adds an explicit
  sensitivity-class rewrite flag.

## Closeout Status

- Feature: F010 completed.
- Evidence level: exhaustive.
- Implementation commit: this F010 delivery commit.
- Reviewer status: independent Entry Vision Gate passed. Independent Exit
  reviewer returned `needs revision`; P1 closeout gaps and P2 golden promotion
  test coverage were addressed.
- Readiness: conditional pass for F010 commit/push after scoped staging and
  verification.
- Completion claim: allowed for F010 implementation, verification, and scoped
  commit/push once Git operations succeed.
- Vision Gate Exit: pass after revisions. The delivered workflow solves the
  raw-capture readability pain point, keeps candidate-lite non-blocking, and
  does not use live URL oracle, direct Agent chat, or nested product UI
  automation.
- ADR: not triggered at entry unless candidate-lite changes long-term governance
  semantics beyond a non-blocking review layer.
- Lesson: not triggered at entry.
- Patch Churn Review: not triggered; F010 starts a new Feature slice.

## Final Harness Closeout

Closeout verdict: conditional

Completion claim allowed: yes

Backlog/Handoff: updated `docs/BACKLOG.md`; F010 moved to Recently Completed.
F010.2 records the later human expected/sensitivity confirmation and promotion
of the new asset to active blocking `candidate`.

Plan lifecycle: completed; plan recorded at
`docs/rpa/harness/f010-assisted-asset-review-and-promotion-plan.md`.

Readiness: conditional pass. Focused tests, real asset review, real promotion,
governed regression, independent reviewer fixes, strict knowledge check, and
scoped Git staging are the required delivery evidence.

Vision Gate Exit: pass after independent reviewer requested closeout/test
revisions.

Patch Churn Review: not triggered; F010 has no patch history.

ADR: not triggered.

Lesson: not triggered.

Evidence: recorded in this EV-010 document.

Evidence level: exhaustive

Feature: updated
`docs/features/F010-assisted-asset-review-and-promotion-pipeline.md`; status is
completed.

Check: passed; `knowledge_check.py --strict` reported Errors 0 and Warnings 0,
and `harness_closeout_check.py --file docs\evidence\EV-010-assisted-asset-review-and-promotion-pipeline.md`
reported closeout block structure pass.
