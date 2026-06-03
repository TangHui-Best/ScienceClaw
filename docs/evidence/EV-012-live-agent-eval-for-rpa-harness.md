---
doc_kind: evidence
id: EV-012
title: Live Agent Eval For RPA Harness Evidence
status: completed
feature_ids: [F012]
feature_refs:
  - docs/features/F012-live-agent-eval-for-rpa-harness.md
created: 2026-05-22
updated: 2026-05-22
scope: RPA Harness live-agent natural-language capture validation
evidence_level: standard
---

# EV-012 Live Agent Eval For RPA Harness Evidence

## Scope

Evidence for F012: add a Harness runner that validates the real natural-language step path:

```text
controlled HTML fixture -> Playwright page -> RecordingRuntimeAgent.run()
-> accepted AI trace -> candidate-lite Harness asset
-> validation / snapshot / compiler / skill replay / stateful SOP checks
```

This Evidence records the local deterministic validation. Internal real-LLM validation is intentionally left as the next operational step because this machine does not use the internal model configuration.

## Entry Gate

- Start Gate: non-trivial Harness behavior change. The user explicitly challenged the offline Harness value because it did not trigger real Planner/LLM decision-making.
- Vision Gate Entry: pass. The smallest coherent path is a separate `live_agent_eval` runner, not changing governed offline regression.
- Delegation Gate: no subagents used; scope was tight and write set was small.
- TDD: used. The first focused test failed with `ModuleNotFoundError` for `backend.rpa.harness.live_agent_eval`, then implementation was added until the tests passed.
- Knowledge boundary: Feature/Evidence required because this adds a new Harness validation mode and future iframe work depends on the distinction between offline regression and live-agent evaluation.

## Commands

Syntax check:

```powershell
$env:PYTHONPATH='RpaClaw'
.\.venv\Scripts\python.exe -m py_compile `
  RpaClaw\backend\rpa\harness\live_agent_eval.py `
  RpaClaw\backend\rpa\harness\run_live_agent_eval.py
```

Focused Harness regression:

```powershell
$env:PYTHONPATH='RpaClaw'
.\.venv\Scripts\python.exe -m pytest -q `
  --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-live-agent-final2 `
  RpaClaw\backend\tests\test_rpa_harness_live_agent_eval.py `
  RpaClaw\backend\tests\test_rpa_harness_asset_validation.py `
  RpaClaw\backend\tests\test_rpa_harness_snapshot_regression.py `
  RpaClaw\backend\tests\test_rpa_harness_compiler_regression.py `
  RpaClaw\backend\tests\test_rpa_harness_skill_replay.py `
  RpaClaw\backend\tests\test_rpa_harness_stateful_sop.py `
  RpaClaw\backend\tests\test_rpa_harness_governed_regression.py
```

Knowledge check:

```powershell
.\.venv\Scripts\python.exe C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root . --docs-path docs
```

Closeout structure check:

```powershell
.\.venv\Scripts\python.exe C:\Users\HUAWEI\.codex\skills\using-harness\scripts\harness_closeout_check.py --file .\tmp-harness-live-agent-closeout.txt
```

## Results

Initial RED:

```text
ModuleNotFoundError: No module named 'backend.rpa.harness.live_agent_eval'
```

Implementation GREEN:

```text
RpaClaw/backend/tests/test_rpa_harness_live_agent_eval.py
2 passed in 5.31s
```

Final focused Harness regression after adding empty-scenario protection:

```text
51 passed in 48.12s
```

Syntax check:

```text
py_compile exit 0
```

Knowledge check:

```text
Scanned 184 markdown file(s). Checked 26 knowledge artifact(s). Errors: 0. Warnings: 0.
```

Closeout structure check:

```text
Harness closeout block structure: pass
```

## Behavior Verified

- The focused live-agent test injects a fake planner and asserts exactly one planner invocation.
- The runner captures the AI operation trace into `steps/001/trace_events.json`.
- The generated scenario asset is active but marked `candidate-lite`.
- The post-capture checks report zero warnings for validation, snapshot, compiler, skill replay, and stateful SOP.
- The CLI writes a failed report for invalid scenarios without calling LLM.
- The CLI fails when no scenario JSON files are present, avoiding false-positive internal validation.

## Artifacts

- Feature: [F012 Live Agent Eval For RPA Harness](../features/F012-live-agent-eval-for-rpa-harness.md)
- Guide: [Live Agent Eval](../rpa/harness/live-agent-eval.md)
- Implementation commit: `bd74cc8 feat: add live rpa agent harness eval`
- Implementation files:
  - `RpaClaw/backend/rpa/harness/live_agent_eval.py`
  - `RpaClaw/backend/rpa/harness/run_live_agent_eval.py`
  - `RpaClaw/backend/tests/test_rpa_harness_live_agent_eval.py`

## Notes

- This runner supplements ADR-003 rather than reversing it. Governed offline regression remains asset-based and deterministic.
- `candidate-lite` is intentionally not a trusted blocking baseline. Human expected-signal, sensitivity, and generalization review are still required before promotion.
- The internal machine should run the CLI without injected fake planner so `RecordingRuntimeAgent` uses the real Planner/LLM configuration.
- iframe repair should start by adding an iframe live-agent fixture so failures are reproducible and attributable.

## Residual Risks

- Real internal LLM behavior has not been validated on this machine.
- The controlled fixture proves the live-agent chain and post-capture integration, but it does not prove live internal-page selectors until internal scenarios are authored.
- The first iframe scenario still needs to be created before `rpa-iframe-frame-context-fix-v2` work starts.

## Closeout Status

Closeout verdict: pass

Completion claim allowed: yes

Backlog/Handoff: updated `docs/BACKLOG.md`; F012 is now the durable anchor for live-agent Harness validation and internal iframe next steps.

Plan lifecycle: no separate plan file was created; implementation was a small TDD slice and is captured by this Feature/Evidence.

Readiness: pass. Focused Harness tests, syntax check, knowledge check, and closeout check passed.

Vision Gate Exit: pass. The deliverable addresses the user pain point by exercising `RecordingRuntimeAgent.run()` while keeping offline governed regression deterministic.

Bugfix attribution: not triggered; this is a new Harness validation capability, not a direct bugfix.

ADR: not triggered. ADR-003 remains valid because Live Agent Eval generates candidate-lite assets and does not replace governed offline evaluation.

Lesson: not triggered. The only process miss was this delayed Feature/Evidence closeout, fixed immediately by F012/EV-012.

Evidence: recorded in this EV-012 document.

Evidence level: standard

Feature: [F012 Live Agent Eval For RPA Harness](../features/F012-live-agent-eval-for-rpa-harness.md) is completed.

Check: passed; `knowledge_check.py --root . --docs-path docs` reported Errors 0 and Warnings 0 during implementation closeout, and this Evidence will be rechecked after the documentation patch.
