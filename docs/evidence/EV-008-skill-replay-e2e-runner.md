---
id: EV-008
doc_kind: evidence
title: Skill Replay E2E Runner Evidence
status: active
scope: project
feature_ids: [F008]
feature_refs:
  - docs/features/F008-skill-replay-e2e-runner.md
created: 2026-05-18
updated: 2026-05-19
evidence_level: exhaustive
---

# EV-008 Skill Replay E2E Runner Evidence

## Scope

Evidence for F008: add the first governed Skill Replay E2E runner slice.

Final slice:

```text
F008.1: Real Governed Candidate Asset Replay
```

## Entry Gate

- Start Gate: non-trivial Harness runner change. Primary intake outcome was
  `needs retrieval`, followed by Vision Gate and this F008 Feature/Evidence
  anchor before implementation.
- Knowledge Retrieval: completed against AGENTS.md, the golden evaluation
  vision, ADR-003, F005-F007 and EV-005-EV-007, Backlog, regression strategy,
  and TraceSkillCompiler generalization.
- Vision Gate Entry: ready to implement. The smallest coherent path is F008.0:
  a controlled fixture replay runner and governed runner signal. F008.1 real
  candidate replay, live GitHub, planner fixes, asset expansion, and direct
  Agent chat are out of scope.
- Delegation Gate: implementation subagents not used. This slice is cohesive
  across one runner contract, governed report wiring, tests, and Harness docs;
  independent review will be reconsidered at closeout.
- TDD: required. Replay runner tests must fail before production runner code is
  added.
- F008.1 Start Gate: non-trivial Harness runner expansion. Existing F008/EV-008
  are the durable anchors; retrieval and Vision Gate were rerun before coding.
- F008.1 Knowledge Retrieval: refreshed against F008/EV-008, Backlog, the real
  candidate asset metadata, step checkpoints, and trace/expected files.
- F008.1 Vision Gate Entry: ready to implement. The smallest coherent path is
  captured-HTML controlled replay for the real candidate asset, not live GitHub,
  not direct Agent chat, and not a stateful GitHub mock.
- F008.1 Delegation Gate: authorized. A read-only explorer subagent inspected
  the current runner and candidate asset; it confirmed the smallest viable path
  is the captured-HTML route provider plus real asset replay eligibility.

## Commands

Planned RED verification:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_skill_replay.py RpaClaw/backend/tests/test_rpa_harness_governed_regression.py
```

Planned focused Harness regression:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_governed_regression.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_harness_catalog.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py RpaClaw/backend/tests/test_rpa_harness_blast_radius.py RpaClaw/backend/tests/test_rpa_harness_skill_replay.py
```

Planned real governed Chinese summary:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_bootstrap --format summary --lang zh
```

Planned Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

## Results

RED result after adding replay runner and governed signal tests before
production runner code:

```text
1 error
ModuleNotFoundError: No module named 'backend.rpa.harness.skill_replay'
```

Intermediate RED result after adding the runner contract:

```text
2 failed, 9 passed
failure_category='replay-execution-error'
Root cause: the controlled fixture test regex was over-escaped and matched a
literal backslash-s instead of whitespace. The test fixture was corrected.
```

GREEN result for Skill Replay and governed regression tests:

```text
11 passed in 22.38s
```

Focused Harness regression:

```text
44 passed in 23.94s
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

Real governed JSON Skill Replay signal:

```text
summary.status=passed
summary.skill_replay_failed=0
skill_replay.schema_version=rpa-harness-skill-replay-e2e-v0
skill_replay.summary.eligible_capture_count=0
skill_replay.summary.total=0
observability.runner_signals.skill_replay_checked=0
observability.runner_signals.skill_replay_failed=0
```

Strict Harness knowledge validation:

```text
Scanned 169 markdown file(s). Checked 20 knowledge artifact(s). Errors: 0. Warnings: 0.
```

F008.1 RED result after adding the real candidate replay test before metadata
and provider changes:

```text
1 failed
AssertionError: assert 0 == 1
report["summary"]["eligible_capture_count"] == 0
```

F008.1 GREEN result for the real candidate replay test:

```text
1 passed in 23.65s
```

F008.1 Skill Replay plus governed regression tests:

```text
12 passed in 26.14s
```

F008.1 focused Harness regression:

```text
45 passed in 24.01s
```

F008.1 real governed JSON Skill Replay signal:

```text
summary.status=passed
summary.skill_replay_failed=0
skill_replay.summary.eligible_capture_count=1
skill_replay.summary.total=3
skill_replay.summary.passed=3
skill_replay.summary.failed=0
skill_replay.assets[2].output_key=fork_count
skill_replay.assets[2].actual_output=Fork 1.3k
observability.runner_signals.skill_replay_checked=3
observability.runner_signals.skill_replay_failed=0
```

Fresh closeout verification after implementation commit:

```text
implementation_commit=5afab4f876daf7e5d8ef392ff9c6ac0fdb97ab01
focused_harness_regression=45 passed in 24.01s
real_governed_summary_status=passed
real_governed_core_chain_includes_skill_replay=1
real_governed_skill_replay_checked=3
real_governed_skill_replay_failed=0
knowledge_check=Errors 0, Warnings 0
```

F008.1 real governed Chinese summary:

```text
受治理离线回归：通过

本次评估：1 个 candidate 资产，3 个步骤
覆盖范围：card-list, data-extraction, detail-page, multi-page, semantic-selection
核心链路：html_to_raw_snapshot=1, planner_action_selection=1, raw_to_compact_snapshot=1, skill_replay=1, trace_to_skill=1
未纳入回归：0 个 capture；原因=无
执行信号：validation 阻塞=0，snapshot 失败=0，compiler 失败=0
Snapshot 质量：source=production-dom-snapshot-v1，检查步骤=3，raw signal 保留=1，compact signal 保留=1，平均 compact/raw=0.3161
影响范围：受影响资产=无；受影响页面形态=无
可信度边界：single-candidate-asset-baseline
```

## Artifacts

- Feature: [F008 Skill Replay E2E Runner](../features/F008-skill-replay-e2e-runner.md)
- Evidence: [EV-008 Skill Replay E2E Runner Evidence](EV-008-skill-replay-e2e-runner.md)
- Target asset:
  `data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc`

## Notes

- F008.0 creates the runner contract and a controlled replay fixture loop. It
  does not claim full Skill Replay E2E coverage for the real governed candidate
  asset.
- F008.1 enables replay eligibility for the first real governed candidate asset
  only after controlled replay passes.
- The controlled replay provider serves captured HTML through Playwright route
  fulfillment. It does not access live GitHub and does not restore direct Agent
  chat.

## Residual Risks

- The runner executes compiled per-step trace evidence against captured
  `before.html` and route-provided `after.html` fixture pages. It does not yet
  execute a full multi-step SOP replay sequence against a stateful provider.
- Runtime semantic AI replay remains outside F008.0. Controlled deterministic
  embedded-code replay is the first contract slice.
- The governed baseline still has one candidate asset, so confidence remains
  bounded by `single-candidate-asset-baseline`.

## Closeout Status

- Feature: F008 completed.
- Evidence level: exhaustive for the F008 governed Skill Replay E2E runner
  slice.
- Implementation commit:
  `5afab4f876daf7e5d8ef392ff9c6ac0fdb97ab01`.
- Reviewer status: self-review for F008.0. Independent review is recommended
  before broadening to F008.1 real-asset replay or treating Skill Replay E2E as
  a release/CI gate.
- F008.1 reviewer status: read-only explorer subagent reviewed the smallest
  implementation path and confirmed the route-provider approach. Self-review
  plus explorer review is sufficient for implementation handoff; independent
  review is recommended before promoting Skill Replay to a CI/release gate.
- Readiness: pass for Feature closeout. Focused Harness regression, real
  governed JSON, real governed Chinese summary, strict Harness knowledge
  validation, and implementation commit hash are recorded above.
- Completion claim: allowed after this closeout record is committed.
- Vision Gate Exit: pass. The deliverable matches the original F008.0 intent:
  a controlled fixture replay runner plus governed runner signal, without live
  GitHub, direct Agent chat, planner fixes, or asset expansion.
- F008.1 Vision Gate Exit: pass. The real candidate asset is now replayed
  through captured HTML controlled replay, not through live GitHub or Agent
  chat.
- ADR: not triggered. F008.0 applies ADR-003 rather than changing the golden
  evaluation decision.
- Lesson: not triggered. No recurring failure mode was found; the escaped-regex
  test fixture issue was local to the new test and corrected before closeout.
- Patch Churn Review: not triggered. F008 starts a new Feature slice and has no
  patch history.

## Final Harness Closeout

Closeout verdict: pass

Completion claim allowed: yes after this closeout record is committed.

Backlog/Handoff: updated `docs/BACKLOG.md`; F008 moved from Active to Recently
Completed.

Plan lifecycle: not triggered; no separate implementation plan document was
created for F008.

Readiness: pass for Feature closeout; independent review remains recommended
before promoting Skill Replay E2E to a CI or release gate.

Vision Gate Exit: pass; F008 stayed within controlled captured-HTML replay and
did not touch live GitHub, direct Agent chat, planner fixes, or asset expansion.

Patch Churn Review: not triggered; F008 has no patch history.

ADR: not triggered; F008 applies ADR-003 rather than changing the golden
evaluation decision.

Lesson: not triggered; no recurring failure mode or process miss required a new
Lesson.

Evidence: recorded in this EV-008 document.

Evidence level: exhaustive

Feature: updated `docs/features/F008-skill-replay-e2e-runner.md`; status is
completed.

Check: passed; `knowledge_check.py --strict` reported Errors 0, Warnings 0.
