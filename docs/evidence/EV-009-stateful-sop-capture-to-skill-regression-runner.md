---
id: EV-009
doc_kind: evidence
title: Stateful SOP Capture-to-Skill Regression Runner Evidence
status: active
scope: project
feature_ids: [F009]
created: 2026-05-19
updated: 2026-05-19
evidence_level: exhaustive
---

# EV-009 Stateful SOP Capture-to-Skill Regression Runner Evidence

## Scope

Evidence for F009: implement Stateful SOP Capture-to-Skill Regression Runner as the final Harness v1 infrastructure closure slice.

## Entry Gate

- Start Gate: high-risk Harness runner feature. Primary outcome was `needs retrieval`, followed by Feature/Evidence anchor creation and Vision Gate before implementation.
- Knowledge Retrieval: completed against AGENTS.md, Backlog, F008/EV-008, Golden Evaluation Vision, ADR-003, governed regression runner, Skill Replay runner, Harness asset model, and relevant tests.
- Delegation Gate: authorized by user. Parallel read-only subagents were dispatched for runner architecture, asset/test contract, and independent Vision Gate review.
- Vision Gate Entry: ready to implement. Independent Vision Gate reviewer returned `ready to implement`, with drift warnings against direct Agent chat, live URL oracle, nested UI automation, asset expansion, and Harness-specific planner/compiler repair.
- Brainstorming gate: satisfied by the explicit F009 brief plus durable Vision/ADR artifacts; no extra user clarification is required before the smallest implementation slice.
- TDD: required. New runner behavior must be captured by failing tests before production runner code is added.

## Commands

Planned RED verification:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_stateful_sop.py RpaClaw/backend/tests/test_rpa_harness_governed_regression.py
```

Planned focused Harness regression:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_harness_catalog.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py RpaClaw/backend/tests/test_rpa_harness_blast_radius.py RpaClaw/backend/tests/test_rpa_harness_skill_replay.py RpaClaw/backend/tests/test_rpa_harness_stateful_sop.py RpaClaw/backend/tests/test_rpa_harness_governed_regression.py
```

Planned real governed JSON check:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_bootstrap
```

Planned Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

## Results

RED result after adding stateful runner and governed signal tests before production runner code:

```text
1 error
ModuleNotFoundError: No module named 'backend.rpa.harness.stateful_sop'
```

Initial GREEN result for the new Stateful SOP runner and governed regression signal:

```text
13 passed in 17.61s
```

Focused Harness regression:

```text
49 passed in 28.91s
```

Independent Exit reviewer result:

```text
needs revision
P1: missing/malformed checkpoint or trace files could escape or silently pass
instead of bounded categories.
P1: accepted=false trace events could count toward accepted_trace_count and
enter TraceSkillCompiler.
P2: Feature/Backlog completion status was inconsistent with conditional EV
closeout.
```

Post-review RED results:

```text
2 failed, 3 passed
missing trace_events was incorrectly passing
accepted=false trace event was incorrectly passing
```

Post-review focused Stateful SOP runner tests:

```text
7 passed in 8.03s
```

Post-review focused Harness regression:

```text
53 passed in 52.12s
```

Post-review real governed English summary:

```text
Governed Offline Regression: passed
Stateful SOP: checked=1, failed=0
Confidence risks: single-candidate-asset-baseline
```

One earlier post-review summary attempt timed out in Playwright
`Page.set_content` while building snapshot evidence. The same command was
rerun immediately as a single command and passed with the summary above.

Real governed JSON check:

```text
summary.status=passed
summary.selected_capture_count=1
summary.selected_step_count=3
summary.core_chain_coverage.stateful_capture_to_skill=1
summary.skill_replay_failed=0
summary.stateful_sop_failed=0
stateful_sop.summary.eligible_capture_count=1
stateful_sop.summary.total=1
stateful_sop.summary.passed=1
stateful_sop.assets[0].accepted_trace_count=3
stateful_sop.assets[0].runtime_result_keys=["fork_count"]
stateful_sop.assets[0].replay.actual_output.fork_count="Fork 1.3k"
observability.runner_signals.stateful_sop_checked=1
observability.runner_signals.stateful_sop_failed=0
```

Real governed English summary:

```text
Governed Offline Regression: passed
Evaluated: 1 candidate asset, 3 steps
Core chain: html_to_raw_snapshot=1, planner_action_selection=1, raw_to_compact_snapshot=1, skill_replay=1, stateful_capture_to_skill=1, trace_to_skill=1
Skill replay: checked=3, failed=0
Stateful SOP: checked=1, failed=0
Confidence risks: single-candidate-asset-baseline
```

Strict Harness knowledge validation:

```text
Scanned 171 markdown file(s). Checked 22 knowledge artifact(s). Errors: 0. Warnings: 0.
```

Harness closeout structural validation:

```text
Harness closeout block structure: pass
```

Intermediate implementation finding:

```text
Temporary real-asset opt-in initially failed with
controlled-replay-output-shape-mismatch because full SOP replay results are a
dictionary, while earlier no-output navigation step signals carried a
single-step null output shape. The runner now ignores state signals that have no
output_key and no required text during full-SOP final-result validation.
```

Post-review fix trajectory:

```text
Bounded asset failure handling:
- missing trace_events.json -> missing-trace-events
- malformed trace_events.json -> invalid-trace-events
- missing checkpoint.json -> missing-checkpoint
- malformed checkpoint.json -> invalid-checkpoint

Accepted trace semantics:
- _selected_event only returns trace events whose accepted field is not false.
- accepted=false events no longer enter session traces or TraceSkillCompiler.
- rejected-trace fixture now fails with missing-accepted-trace and
  accepted_trace_count=2.
```

## Artifacts

- Feature: [F009 Stateful SOP Capture-to-Skill Regression Runner](../features/F009-stateful-sop-capture-to-skill-regression-runner.md)
- Evidence: [EV-009 Stateful SOP Capture-to-Skill Regression Runner Evidence](EV-009-stateful-sop-capture-to-skill-regression-runner.md)
- Target asset baseline: `data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc`

## Notes

- F009 should add a runner boundary and regression signal, not fix RPA Agent planner/compiler/extraction defects inside Harness.
- F009 should not promote additional assets. Opt-in eligibility may be tested with temporary test fixtures and may update the existing bootstrap candidate only if the controlled F009 path passes.
- Missing stateful opt-in assets during introduction should be observable, not a global governed-regression failure.

## Residual Risks

- The governed baseline remains one candidate asset, so confidence is still bounded by `single-candidate-asset-baseline`.
- Natural-language replay is driven from captured runtime result evidence through `RecordingRuntimeAgent._accepted_trace`; it avoids LLM variance by design, but still uses a private method because that is the current product boundary for accepted runtime traces.
- F009 does not fix planner, compiler, selector, or extraction defects. It exposes those failures through bounded runner categories for follow-up RPA core work.
- Harness v1 infrastructure should pause expansion here; additional value now comes from recording more assets and using this runner to expose core-chain regressions.

## Closeout Status

- Feature: F009 completed.
- Evidence level: exhaustive planned.
- Implementation commit: `649515ab338c080b373b6d5378f5d9be2874b9d0`.
- Reviewer status: independent Vision Gate Entry passed. Independent Exit reviewer returned `needs revision`; the two P1 code findings and P2 documentation inconsistency were addressed with tests and Evidence updates. Follow-up re-review confirmed the code findings are addressed and only the documentation status inconsistency remained before this final update.
- Readiness: pass.
- Completion claim: allowed.
- Vision Gate Exit: pass. The implementation stays within governed Full SOP asset input, session-style accepted trace generation, full SOP Skill compilation, controlled replay, and no live URL/direct Agent chat/product-UI automation.
- ADR: not triggered at entry; F009 applies ADR-003 unless implementation changes the golden evaluation decision.
- Lesson: not triggered at entry.
- Patch Churn Review: not triggered; F009 starts a new Feature slice.

## Final Harness Closeout

Closeout verdict: pass

Completion claim allowed: yes

Backlog/Handoff: updated `docs/BACKLOG.md`; F009 is in Recently Completed and next work shifts to asset recording plus RPA Agent core fixes validated by assets.

Plan lifecycle: not triggered; no separate implementation plan document exists yet.

Readiness: dashboard pass. Independent Exit review findings were addressed and verification reran: `53 passed`, real governed summary passed, strict knowledge check passed, and closeout structure check passed.

Vision Gate Exit: pass.

Patch Churn Review: not triggered; F009 has no patch history.

ADR: not triggered at entry.

Lesson: not triggered at entry.

Evidence: recorded in this EV-009 document.

Evidence level: exhaustive

Feature: updated `docs/features/F009-stateful-sop-capture-to-skill-regression-runner.md`; status is completed.

Check: passed; `knowledge_check.py --strict` reported Errors 0, Warnings 0, and `harness_closeout_check.py --file docs\evidence\EV-009-stateful-sop-capture-to-skill-regression-runner.md` reported closeout block structure pass.
