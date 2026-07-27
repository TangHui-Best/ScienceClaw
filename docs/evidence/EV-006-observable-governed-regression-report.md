---
id: EV-006
doc_kind: evidence
title: Observable Governed Regression Report Evidence
status: active
scope: project
feature_ids: [F006]
feature_refs:
  - docs/features/F006-observable-governed-regression-report.md
created: 2026-05-18
updated: 2026-05-18
evidence_level: exhaustive
---

# EV-006 Observable Governed Regression Report Evidence

## Scope

Evidence for F006: make governed offline regression explain what was selected,
what was covered, what failed, what was affected, and what confidence limits
remain.

## Entry Gate

- Start Gate: non-trivial Harness report contract change. Required durable
  anchor is F006 plus this Evidence record.
- Knowledge Retrieval: completed against F004, F005, EV-004, EV-005, ADR-003,
  and the golden evaluation vision.
- Vision Gate Entry: ready to implement. The smallest coherent path is to
  derive an observable summary from the current governed regression reports,
  not to add a new runner or scoring model.
- Delegation Gate: not needed. The change is focused in the Harness report
  layer and can be verified with narrow tests.
- TDD: required. Tests must fail before production report code is added.

## Commands

RED verification:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_governed_regression.py
```

Real governed summary:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_bootstrap --format summary
```

Real governed Chinese summary:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_bootstrap --format summary --lang zh
```

Real governed JSON:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_bootstrap
```

Focused Harness regression:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_governed_regression.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_harness_catalog.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py RpaClaw/backend/tests/test_rpa_harness_blast_radius.py
```

Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

## Results

F006.1 RED result after adding `--lang zh` tests before production code:

```text
1 failed, 7 passed
SystemExit: 2 for unrecognized arguments: --lang zh
```

RED result after adding observable-report tests before production code:

```text
3 failed, 3 passed
KeyError: 'observability'
SystemExit: 2 for unrecognized arguments: --format summary
```

GREEN result for governed regression tests:

```text
7 passed in 0.49s
```

Focused Harness regression:

```text
39 passed in 0.62s
```

Real governed Chinese summary:

```text
受治理离线回归：通过

本次评估：1 个 candidate 资产，3 个步骤
覆盖范围：card-list, data-extraction, detail-page, multi-page, semantic-selection
核心链路：html_to_raw_snapshot=1, planner_action_selection=1, raw_to_compact_snapshot=1, trace_to_skill=1
未纳入回归：0 个 capture；原因=无
执行信号：validation 阻塞=0，snapshot 失败=0，compiler 失败=0
影响范围：受影响资产=无；受影响页面形态=无
可信度边界：single-candidate-asset-baseline
```

Strict Harness knowledge validation:

```text
Scanned 165 markdown file(s). Checked 16 knowledge artifact(s). Errors: 0. Warnings: 0.
```

Real governed human summary:

```text
Governed Offline Regression: passed

Evaluated: 1 candidate asset, 3 steps
Coverage: card-list, data-extraction, detail-page, multi-page, semantic-selection
Core chain: html_to_raw_snapshot=1, planner_action_selection=1, raw_to_compact_snapshot=1, trace_to_skill=1
Excluded: 9 captures; reasons=asset-status-draft=9, expected-signals-not-reviewed=9, missing-core-chain-coverage=9, promotion-status-captured=9, sensitivity-not-reviewed=9
Signals: validation blocking=0, snapshot failed=0, compiler failed=0
Blast radius: affected assets=none; affected page patterns=none
Confidence risks: single-candidate-asset-baseline
```

Real governed JSON now includes:

```text
observability.schema_version=rpa-harness-observability-v0
asset_qualification.scanned_capture_count=10
asset_qualification.selected_capture_count=1
asset_qualification.excluded_capture_count=9
asset_qualification.selected_promotion_status_counts={"candidate": 1}
coverage.selected_step_count=3
coverage.coverage_risks=["single-candidate-asset-baseline"]
runner_signals.snapshot_failed=0
runner_signals.compiler_failed=0
blast_radius.affected_assets=[]
confidence.status=passed
```

## Artifacts

- Feature: [F006 Observable Governed Regression Report](../features/F006-observable-governed-regression-report.md)
- Evidence: [EV-006 Observable Governed Regression Report Evidence](EV-006-observable-governed-regression-report.md)

## Notes

- Stable observability fields should survive core-chain implementation changes.
- Runner-specific diagnostics may grow as snapshot, compiler, planner, or replay
  behavior evolves.

## Residual Risks

- The current repo-safe governed baseline still has one candidate asset. The
  report now makes that explicit as `single-candidate-asset-baseline`, but more
  assets are still needed before claiming broad RPA coverage.
- The observability contract currently covers the offline core-chain runner.
  Future Skill Replay E2E should add runner-specific diagnostics without
  breaking the stable asset, coverage, runner-signal, blast-radius, and
  confidence sections.
- F006.1 intentionally localizes only the human summary. JSON field names and
  machine-readable values remain English stable-contract values.

## Closeout Status

- Feature: F006 completed.
- Evidence level: exhaustive for this report-contract slice.
- Implementation commit:
  `d4a6e46fdbe535df16765f496cfe79780f514d98`.
- Patch F006.1 commit:
  `2cf62a08094802ec84d743f04f65e9c9d63610b1`.
- Reviewer status: self-review allowed after Delegation Gate review decision;
  independent review not required for this focused report-contract slice.
- Readiness: pass. Strict Harness knowledge check, focused Harness regression,
  and real governed summary output are recorded above.
- Completion claim: allowed after this closeout record is committed and pushed.
- ADR: not triggered. F006 applies ADR-003 rather than changing it.
- Lesson: not triggered. No recurring failure mode was found.
- Patch Churn Review: not triggered. F006 has one focused localization patch.

## Supports Claim

This record supports only the historical implementation and validation claims explicitly documented in its Results and source material. The migration does not add a new completion claim.

## Verification Scope

The original `## Scope`, commands, results, and artifacts define the verification boundary. Unrecorded environments or workflows remain outside scope.

## Checks

The commands, test runs, manual checks, and other proof are preserved in the original sections of this record. This heading makes the check boundary explicit without inventing new execution.

## Limitations

This is a migrated historical record. It proves only the results explicitly recorded at the time; absent checks, environments, or product acceptance must not be inferred as passing.
