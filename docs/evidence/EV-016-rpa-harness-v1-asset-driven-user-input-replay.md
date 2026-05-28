---
id: EV-016
doc_kind: evidence
title: RPA Harness v1 Asset-Driven User Input Replay Evidence
status: active
scope: project
feature_ids: [F016]
feature_refs:
  - docs/features/F016-rpa-harness-v1-asset-driven-user-input-replay.md
created: 2026-05-28
updated: 2026-05-28
evidence_level: focused
---

# EV-016 RPA Harness v1 Asset-Driven User Input Replay Evidence

## Scope

Evidence for F016: implement RPA Harness v1 Phase 4 first slice, Asset-Driven
User Input Replay.

The slice is intentionally narrow:

- lifecycle-aware asset selection for replay;
- deterministic extraction of replayable user input events from captured asset facts;
- script-driven replay adapter that records the input boundary each event entered;
- JSON-first machine report plus Markdown summary;
- focused tests and a real bootstrap report.

It must preserve the core boundary:

```text
Scripts execute.
Agents explain.
Humans govern.
```

Phase 4 first slice does not expand full/live profile, add CI blocking, automate
diagnosis, drive the RPA product UI from an outer Agent, automatically promote
assets, or create region-specific replay architecture.

## Entry Gate

Start Gate:

```text
Start Gate: needs retrieval -> satisfied; needs feature/plan -> satisfied by F016 and Phase 4 plan before implementation
Task class: high-risk
Risk triggers:
- Harness user input boundary semantics
- lifecycle and promotion guardrail preservation
- JSON/Markdown report contract
- possible drift toward full/live, direct Agent UI control, automatic diagnosis, automatic promotion, or region-specific architecture
Delegation decision:
- authorized for read-only sidecar exploration because the user explicitly allowed subagents for complex tasks
Bug attribution:
- not triggered; this is a new Phase 4 Feature slice
Required pre-work:
- retrieve v1 design, F015/EV-015, ADR-003, usage guide, scenario schema, and related harness code
- run Vision Gate
- create F016/EV-016 and Phase 4 plan before code
Allowed next action:
- write RED tests for user-input replay selection, event extraction, report fields, summary, and failure logging
```

Knowledge Retrieval:

- Read `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read `docs/features/F015-rpa-harness-v1-asset-lifecycle-operationalization.md`.
- Read `docs/evidence/EV-015-rpa-harness-v1-asset-lifecycle-operationalization.md`.
- Read `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`.
- Read `docs/rpa/harness/usage-and-triage-guide.md`.
- Read `docs/rpa/harness/scenario-asset-schema.md`.
- Read `RpaClaw/backend/rpa/harness/catalog.py`.
- Read `RpaClaw/backend/rpa/harness/governed_regression.py`.
- Read `RpaClaw/backend/rpa/harness/profile_runner.py`.
- Read `RpaClaw/backend/rpa/harness/stateful_sop.py`.
- Read `RpaClaw/backend/rpa/harness/run_harness_profile.py`.
- Read existing focused harness tests.

Retrieval conclusion:

- Phase 4 should reuse lifecycle facts from `build_asset_lifecycle_summary` and
  existing scenario/checkpoint models rather than reimplement governance.
- Existing stateful SOP code already proves captured trace events can be converted
  toward session-style traces; Phase 4 first slice should expose the input-event
  chain and boundary explicitly, not hide it inside generated Skill execution.
- Bootstrap assets contain navigation, manual click, and natural-language extraction
  facts in `checkpoint.json` and `trace_events.json`.

Vision Gate:

```text
Vision Gate: ready to implement
Mode: Entry Gate
Original intent:
- Make captured governed assets script replay the user input boundary and produce explainable evidence.
Alignment:
- A lifecycle-aware JSON-first replay runner and Markdown summary is the smallest coherent Phase 4 first slice.
Drift risks:
- full/live expansion, direct Agent UI driving, live URL oracle, automatic diagnosis, automatic promotion, region-specific branches.
Vision Anchor:
- F016 Feature plus the v1 design, F015 lifecycle guardrails, ADR-003, and usage guide.
Reviewer policy:
- independent review recommended/conditional before readiness because this is a high-risk Harness execution/report contract slice.
Required next action:
- write focused RED tests, implement minimal replay modules/CLI, run focused verification, run bootstrap report, update Evidence.
```

## Commands

RED tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py
```

Result:

```text
Initial RED:
ModuleNotFoundError: No module named 'backend.rpa.harness.run_user_input_replay'

Second RED after initial GREEN:
3 failed, 4 passed
- missing source_metadata
- missing payload
- missing runtime_result / diagnostics fields
```

Focused GREEN tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py
```

Result:

```text
Initial GREEN: 7 passed in 0.26s
After independent review guardrail fixes: 10 passed in 0.36s
After review follow-up fixes for CLI status and boundary adapter: 12 passed in 0.35s
```

Focused regression tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py RpaClaw/backend/tests/test_rpa_harness_catalog.py RpaClaw/backend/tests/test_rpa_harness_profile_runner.py
```

Result:

```text
Initial result: 25 passed in 10.21s
After independent review guardrail fixes: 28 passed in 12.53s
Final closeout rerun: 28 passed in 12.36s
After review follow-up fixes for CLI status and boundary adapter: 30 passed in 12.82s
Final review follow-up rerun after documentation update: 30 passed in 11.00s
Pre-commit rerun: 30 passed in 10.35s
```

Independent review follow-up RED test:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py::test_user_input_replay_excludes_candidate_without_core_chain_boundary
```

Result:

```text
FAILED
candidate-no-offline was incorrectly selected as a blocking baseline asset.
```

Independent review follow-up GREEN tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py
```

Result:

```text
10 passed in 0.36s
```

Real bootstrap user-input replay JSON:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_user_input_replay --assets data\rpa_harness_assets_bootstrap --output docs\rpa\harness\reports\2026-05-28-f016-user-input-replay.json
```

Result:

```text
exit code 0
summary.status = passed
summary.failure_category = ""
summary.selected_asset_count = 2
summary.blocking_asset_count = 2
summary.warning_only_asset_count = 0
summary.excluded_asset_count = 0
summary.replayed_event_count = 6
summary.boundary_injection_count = 6
summary.boundary_injection_failed_count = 0
summary.blocking_failure_count = 0
summary.event_kinds = {"click": 2, "natural_language_instruction": 2, "navigation": 2}
summary.injected_boundaries = {
  "scripted_manual_input_boundary": 2,
  "scripted_natural_language_instruction_boundary": 2,
  "scripted_navigation_boundary": 2
}
boundary_injections include deterministic adapter records:
- navigation_boundary_adapter
- manual_input_boundary_adapter
- natural_language_instruction_boundary_adapter
selection.blocking_baseline_asset_ids =
- hcap-4be6265f43eb42dfa259182207aa64cc
- hcap-de463b7bb608482e9b5bcdd5b78a224e
asset_pool.summary.lifecycle_distribution = {"candidate": 2}
```

Real bootstrap user-input replay Markdown summary:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_user_input_replay --assets data\rpa_harness_assets_bootstrap --format summary --lang zh --output docs\rpa\harness\reports\2026-05-28-f016-user-input-replay.md --machine-report docs\rpa\harness\reports\2026-05-28-f016-user-input-replay.json
```

Result:

```text
exit code 0
summary includes status, blocking assets, warning-only assets, excluded assets,
lifecycle distribution, replayed event count, boundary injection count, event kinds,
injected boundaries, failure counts, governance boundary, and machine JSON path.
```

Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

Result:

```text
exit code 0
Latest result after compatibility design index:
Scanned 212 markdown file(s). Checked 36 knowledge artifact(s). Errors: 0. Warnings: 0.
```

## Artifacts

- Feature: `docs/features/F016-rpa-harness-v1-asset-driven-user-input-replay.md`
- Evidence: `docs/evidence/EV-016-rpa-harness-v1-asset-driven-user-input-replay.md`
- Plan: `docs/rpa/harness/f016-rpa-harness-v1-phase-4-plan.md`
- Replay runner: `RpaClaw/backend/rpa/harness/user_input_replay.py`
- Replay CLI: `RpaClaw/backend/rpa/harness/run_user_input_replay.py`
- Focused tests: `RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py`
- Design compatibility index: `docs/rpa/harness/rpa-harness-v1-design.md`
- Usage guide: `docs/rpa/harness/usage-and-triage-guide.md`
- Machine report: `docs/rpa/harness/reports/2026-05-28-f016-user-input-replay.json`
- Markdown summary: `docs/rpa/harness/reports/2026-05-28-f016-user-input-replay.md`

## Results

Implemented. F016 adds a script-driven user-input replay layer over captured
asset facts.

New report contract:

- `schema_version=rpa-harness-user-input-replay-v1`;
- `kind=user_input_replay`;
- `profile.execution_mode=scripted-user-input-events`;
- `asset_pool` reuses the Phase 3 lifecycle summary and trust limits;
- `selection` separates blocking `candidate/golden`, warning-only `candidate-lite`,
  and excluded assets with reasons;
- `replayed_input_events` contains event kind, boundary, source metadata, payload,
  region context, trace/session/result ids, diagnostics, runtime result, and failure
  fields;
- `boundary_injections` records deterministic script adapter execution for each
  event, including adapter name, boundary, status, trace/session/result ids, and
  input signal;
- `warning_only_observation` records candidate-lite warning-only behavior;
- `governance_boundary` explicitly states Scripts execute, Agents explain, Humans
  govern, and Agents may not automatically promote assets.
- no eligible blocking baseline assets now report
  `summary.status=failed` and `summary.failure_category=no-replay-baseline-assets`
  instead of treating an empty run as success.
- CLI exit code now follows `summary.status`, so empty or failed blocking baseline
  runs return `1` instead of reporting script success.

Event support in the first slice:

- real bootstrap coverage: `navigation`, `click`, `natural_language_instruction`;
- focused fixture coverage: `type`, `select`, `submit`;
- region selection: represented as generic `region_context` facts when present,
  without region-specific runner branching.

Current real bootstrap run:

- selected assets: 2 candidate assets;
- lifecycle distribution: `candidate=2`;
- warning-only assets: 0;
- excluded assets: 0;
- replayed events: 6;
- boundary injections: 6;
- event kinds: 2 navigation, 2 click, 2 natural-language instruction;
- blocking failures: 0.

Independent review follow-up:

- Accepted P1/P2: initial replay selection allowed active reviewed `candidate/golden`
  assets without requiring `offline_core_chain` and non-empty `core_chain_coverage`,
  which was wider than Phase 3 blocking baseline semantics. Fixed by adding the
  same core-chain boundary checks and a focused regression test.
- Accepted P2: an asset pool with no blocking replay baseline was initially able
  to report `passed`. Fixed by returning `summary.status=failed` with
  `failure_category=no-replay-baseline-assets`.
- Accepted test gap: candidate-lite replay failure now has a focused test proving
  it remains warning-only and does not create blocking failures.
- Accepted P1: CLI exit code previously used `blocking_failure_count`, so a
  no-baseline failed report could exit `0`. Fixed by returning `1` whenever
  `summary.status=failed`, with a focused CLI test.
- Accepted P1/P2: the first implementation only labeled `injected_boundary`.
  Fixed by adding a deterministic `scripted_user_input_replay_adapter` that
  produces per-event `boundary_injections`; failed extraction events get skipped
  injection records rather than fake success.
- Accepted P2: added `docs/rpa/harness/rpa-harness-v1-design.md` as a compatibility
  index pointing to the canonical v1 design source.

## Residual Risk

- Bootstrap assets remain narrow and GitHub-focused.
- Boundary injection is deterministic and record-only in this first slice; it does
  not drive a live product UI or validate browser side effects.
- Bootstrap assets do not currently contain real `type`, `select`, `submit`, or
  region selection captures; those are covered by focused fixtures and the generic
  event schema, not by real bootstrap evidence.
- First slice reports deterministic boundary injection from captured facts; it does
  not prove full/live Planner behavior or real browser side effects.
- Candidate-lite must remain warning-only even when its replay event extraction succeeds.
- Region selection support depends on future assets containing generic region facts.
- Independent review is still recommended before accepting F016 because this is a
  high-risk Harness execution/report contract slice. One independent reviewer found
  the lifecycle-selection and empty-run issues above; both were fixed with RED/GREEN
  tests and rerun verification.

## Notes

- `docs/rpa/harness/rpa-harness-v1-design.md` is a compatibility index. The current
  canonical source design remains
  `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`.
- Existing untracked workspace files predate this slice and are intentionally
  ignored unless created by F016.

## Closeout

Implementation done. Focused tests, adjacent regression tests, real bootstrap
JSON/Markdown reports, and strict knowledge validation pass. F016 is ready for
human or independent review; Phase 5 may start after accepting the residual
coverage limits above.
