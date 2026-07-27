---
id: EV-007
doc_kind: evidence
title: Production Snapshot Core-chain Regression Evidence
status: active
scope: project
feature_ids: [F007]
feature_refs:
  - docs/features/F007-production-snapshot-core-chain-regression.md
created: 2026-05-18
updated: 2026-05-18
evidence_level: exhaustive
---

# EV-007 Production Snapshot Core-chain Regression Evidence

## Scope

Evidence for F007: make governed offline regression snapshot checks exercise
the production DOM/raw/compact snapshot chain over captured HTML assets.

## Entry Gate

- Start Gate: non-trivial Harness core-chain regression change. Primary intake
  outcome was `needs retrieval`; F007 plus this Evidence record are the durable
  pre-work anchors.
- Knowledge Retrieval: completed against the golden evaluation vision,
  ADR-003, F003-F006, EV-006, regression strategy, TraceSkillCompiler
  generalization strategy, and Backlog.
- Vision Gate Entry: ready to implement. The smallest coherent path is a
  production snapshot adapter plus snapshot observability; planner, compiler,
  Skill Replay E2E, GitHub rules, and direct Agent chat remain out of scope.
- Delegation Gate: implementation subagents not used. The change is cohesive
  across one runner, one report layer, tests, and docs; review independence
  will be reconsidered at closeout.
- TDD: required. Snapshot/core-chain tests must fail before production code is
  added.

## Commands

RED verification:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_governed_regression.py
```

Focused Harness regression:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_governed_regression.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_harness_catalog.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py RpaClaw/backend/tests/test_rpa_harness_blast_radius.py
```

Real governed Chinese summary:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_bootstrap --format summary --lang zh
```

Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

## Results

RED result after adding production snapshot/default diagnostics and failure
category tests before production code:

```text
7 failed, 8 passed
KeyError: 'snapshot_source'
AssertionError: 'raw-html-missing-signal' == 'source-html-missing-signal'
KeyError: 'snapshot_quality'
```

Second RED result after adding summary rendering expectations before rendering
code:

```text
2 failed
AssertionError: expected Snapshot quality line in English and Chinese summaries
```

GREEN result for focused snapshot/governed tests:

```text
15 passed in 16.96s
```

Focused Harness regression:

```text
41 passed in 20.21s
```

Real governed Chinese summary:

```text
受治理离线回归：通过

本次评估：1 个 candidate 资产，3 个步骤
覆盖范围：card-list, data-extraction, detail-page, multi-page, semantic-selection
核心链路：html_to_raw_snapshot=1, planner_action_selection=1, raw_to_compact_snapshot=1, trace_to_skill=1
未纳入回归：0 个 capture；原因=无
执行信号：validation 阻塞=0，snapshot 失败=0，compiler 失败=0
Snapshot 质量：source=production-dom-snapshot-v1，检查步骤=3，raw signal 保留=1，compact signal 保留=1，平均 compact/raw=0.3161
影响范围：受影响资产=无；受影响页面形态=无
可信度边界：single-candidate-asset-baseline
```

Real governed JSON snapshot quality:

```text
source=production-dom-snapshot-v1
checked_steps=3
raw_signal_present=1
compact_signal_present=1
raw_signal_missing=0
compact_signal_missing=0
average_compression_ratio=0.3161
```

Strict Harness knowledge validation:

```text
Scanned 167 markdown file(s). Checked 18 knowledge artifact(s). Errors: 0. Warnings: 0.
```

## Artifacts

- Feature: [F007 Production Snapshot Core-chain Regression](../features/F007-production-snapshot-core-chain-regression.md)
- Evidence: [EV-007 Production Snapshot Core-chain Regression Evidence](EV-007-production-snapshot-core-chain-regression.md)

## Notes

- F007 strengthens the existing governed offline runner; it does not create a
  new golden evaluation mode.
- Raw HTML remains the offline asset source. Production snapshot generation
  should run against that captured HTML without treating live URL state as the
  oracle.

## Residual Risks

- The governed baseline still has one candidate asset, so coverage remains
  narrow. The report continues to expose `single-candidate-asset-baseline`.
- The production adapter runs captured HTML in offline Playwright and reuses
  the production DOM snapshot JS plus `compact_recording_snapshot`, but it does
  not replay external network state or iframe subdocuments. That is aligned
  with Offline Core-Chain Regression and does not replace future Skill Replay
  E2E.
- Only snapshot expected text signals are checked in F007. Planner/action
  selection and Skill Replay remain separate future slices.

## Closeout Status

- Feature: F007 completed.
- Evidence level: exhaustive for this core-chain regression slice.
- Implementation commit:
  `b2e43daace22c60b3d572fdb493a7116c14bc274`.
- Reviewer status: self-review allowed after closeout Delegation Gate review
  decision. Independent review is recommended for future broader asset or E2E
  replay expansion, but not required for this focused runner/observability
  slice.
- Readiness: pass. Focused Harness regression, real governed Chinese summary,
  and strict Harness knowledge validation are recorded above.
- Completion claim: allowed after this closeout record is committed and pushed.
- ADR: not triggered at entry. F007 applies ADR-003 rather than changing the
  golden evaluation decision.
- Lesson: not triggered at entry.
- Patch Churn Review: not triggered. F007 starts a new Feature slice.

## Supports Claim

This record supports only the historical implementation and validation claims explicitly documented in its Results and source material. The migration does not add a new completion claim.

## Verification Scope

The original `## Scope`, commands, results, and artifacts define the verification boundary. Unrecorded environments or workflows remain outside scope.

## Checks

The commands, test runs, manual checks, and other proof are preserved in the original sections of this record. This heading makes the check boundary explicit without inventing new execution.

## Limitations

This is a migrated historical record. It proves only the results explicitly recorded at the time; absent checks, environments, or product acceptance must not be inferred as passing.
