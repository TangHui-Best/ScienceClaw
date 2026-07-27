---
id: EV-013
doc_kind: evidence
title: RPA Harness v1 Asset-Driven User Input Replay Evidence
status: active
scope: project
feature_ids: [F013]
feature_refs:
  - docs/features/F013-rpa-harness-v1-asset-driven-user-input-replay.md
created: 2026-05-28
updated: 2026-05-28
evidence_level: focused
---

# EV-013 RPA Harness v1 Asset-Driven User Input Replay Evidence

## Scope

Evidence for F013: implement RPA Harness v1 Phase 1 deterministic profile as the default script-driven pre-submit evidence path over existing governed assets.

The intended delivery is a small wrapper/report slice over F003-F010 capabilities. It must not expand full/live profile, add CI blocking, automate asset governance decisions, or build an automatic diagnosis platform.

## Entry Gate

Start Gate:

```text
Start Gate: needs feature -> satisfied by docs/features/F013-rpa-harness-v1-asset-driven-user-input-replay.md
Task class: high-risk
Risk triggers:
- Harness architecture and evidence path
- Cross-runner deterministic reporting
- PR/readiness process implication
- Asset governance boundaries
- Possible drift toward full/live, CI blocking, or auto-diagnosis
Delegation decision:
- not needed for Feature/plan creation; re-evaluate before implementation review
Bug attribution:
- not triggered
Required pre-work:
- Feature Anchor, Phase 1 plan, Evidence anchor, deterministic-only scope
Allowed next action:
- implement the deterministic profile slice only after this plan exists
```

Knowledge Retrieval:

- Read `docs/features/F003-golden-scenario-asset-model.md`.
- Read `docs/features/F004-governed-offline-regression-asset-pool.md`.
- Read `docs/features/F005-first-governed-candidate-asset.md`.
- Read `docs/features/F006-observable-governed-regression-report.md`.
- Read `docs/features/F007-production-snapshot-core-chain-regression.md`.
- Read `docs/features/F008-skill-replay-e2e-runner.md`.
- Read `docs/features/F009-stateful-sop-capture-to-skill-regression-runner.md`.
- Read `docs/features/F010-assisted-asset-review-and-promotion-pipeline.md`.
- Read `docs/features/F011-rpa-region-scoped-snapshot.md` for current region-selection boundary and churn context.
- Read `docs/features/F012-live-agent-eval-for-rpa-harness.md` for full/live profile boundary.
- Read `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`.
- Read `docs/rpa/harness/rpa-harness-v0-design.md`.
- Read `docs/rpa/harness/golden-evaluation-vision.md`.
- Read `docs/rpa/harness/usage-and-triage-guide.md`.
- Read `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`.

Retrieval conclusion:

- Governed scenario assets remain the durable evaluation unit.
- Default execution should be script/CLI-based, not outer-Agent UI driving.
- Deterministic profile is the right Phase 1 target.
- Full/live profile is valuable but remains separate and non-default.
- Region selection is one user input context, not a special Harness architecture track.
- Existing governed runner already composes asset validation, snapshot, compiler, Skill Replay, Stateful SOP, candidate-lite observation, and observability; Phase 1 should wrap and label this path instead of rebuilding it.

Vision Gate:

```text
Vision Gate: ready to plan
Mode: Entry Gate
Original intent:
- Make governed assets the default way to verify RPA core-chain changes before readiness claims.
Alignment:
- A thin deterministic profile wrapper/report shape is the smallest coherent path.
Drift risks:
- full/live expansion, CI blocking, automatic diagnosis, region-specific branches.
Vision Anchor:
- F013 Feature plus docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md
Reviewer policy:
- independent review required or conditional before readiness because this is high-risk Harness architecture.
Required next action:
- write implementation plan, then implement only deterministic profile.
```

## Commands

RED test:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_profile_runner.py
```

Result:

```text
ERROR RpaClaw/backend/tests/test_rpa_harness_profile_runner.py
ModuleNotFoundError: No module named 'backend.rpa.harness.profile_runner'
```

Focused GREEN tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_profile_runner.py RpaClaw/backend/tests/test_rpa_harness_governed_regression.py
```

Result:

```text
Initial F013 result: 17 passed in 26.13s
After review follow-up: 18 passed in 19.48s
```

Review follow-up RED test:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_cli_summary_includes_machine_report_path
```

Result:

```text
SystemExit: 2
error: unrecognized arguments: --machine-report ...
```

Review follow-up GREEN test:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_cli_summary_includes_machine_report_path
```

Result:

```text
1 passed in 1.12s
```

Deterministic profile JSON:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile deterministic --output docs\rpa\harness\reports\2026-05-28-f013-deterministic-profile.json
```

Result:

```text
exit code 0
summary.status = passed
selected_asset_count = 2
selected_asset_ids =
- hcap-4be6265f43eb42dfa259182207aa64cc
- hcap-de463b7bb608482e9b5bcdd5b78a224e
first_failure_category = ""
warning_only_observation_count = 0
deterministic.summary.snapshot_failed = 0
deterministic.summary.compiler_failed = 0
deterministic.summary.skill_replay_failed = 0
deterministic.summary.stateful_sop_failed = 0
```

Deterministic profile summary:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile deterministic --format summary --lang zh --output docs\rpa\harness\reports\2026-05-28-f013-deterministic-profile.md --machine-report docs\rpa\harness\reports\2026-05-28-f013-deterministic-profile.json
```

Result:

```text
exit code 0
```

Compatibility runner:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_bootstrap --output tmp-harness-governed-f013-compat.json
```

Result:

```text
exit code 0
schema_version remains rpa-harness-governed-offline-regression-v0
```

Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

Result:

```text
exit code 1
Scanned 199 markdown file(s). Checked 30 knowledge artifact(s). Errors: 18. Warnings: 1.
```

Attribution:

- Existing repo-wide failures remain outside F013 scope: `docs/BACKLOG.md` uses unsupported `doc_kind: backlog`; existing ADR-001/002/003 and EV-001 through EV-012 mostly lack `feature_refs`; old `docs/superpowers/specs` files use unsupported `doc_kind: spec/design`.
- F013-local validator issues were fixed by adding `feature_refs` and the required `## Commands`, `## Artifacts`, and `## Notes` sections. The rerun reports no F013-local errors.
- Per the user constraint, this feature does not broad-fix legacy Harness frontmatter.

Phase 2 recheck:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

Result:

```text
exit code 0
Scanned 199 markdown file(s). Checked 30 knowledge artifact(s). Errors: 0. Warnings: 0.
```

Updated attribution:

- The Phase 1 strict failure is preserved above as historical execution evidence.
- The failure no longer reproduces in the current workspace, and no Phase 2 broad frontmatter cleanup is needed.
- F013 readiness remains conditional on independent review and the F014 report/closeout trust loop, not on a current strict metadata blocker.

## Artifacts

- Feature: `docs/features/F013-rpa-harness-v1-asset-driven-user-input-replay.md`
- Plan: `docs/archive/2026-05/rpa-harness/f013-rpa-harness-v1-phase-1-plan.md`
- Evidence: `docs/evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md`
- Design: `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`
- Profile runner: `RpaClaw/backend/rpa/harness/profile_runner.py`
- Profile CLI: `RpaClaw/backend/rpa/harness/run_harness_profile.py`
- Tests: `RpaClaw/backend/tests/test_rpa_harness_profile_runner.py`
- Usage guide update: `docs/rpa/harness/usage-and-triage-guide.md`
- Machine profile output: `docs/rpa/harness/reports/2026-05-28-f013-deterministic-profile.json`
- Compatibility output: `tmp-harness-governed-f013-compat.json`
- Human summary: `docs/rpa/harness/reports/2026-05-28-f013-deterministic-profile.md`

## Results

Implemented. deterministic profile is now a thin wrapper over existing governed regression.

The wrapper adds:

- profile metadata;
- deterministic-only Phase 1 enforcement;
- status/blocking/first-failure summary;
- selected/excluded asset ids;
- candidate-lite warning-only observation counts;
- CLI output for JSON and summary.
- explicit `--machine-report` support for summary output, so human Markdown can point Agents to the machine JSON evidence.

Existing governed regression remains compatible and keeps its original schema.

Review follow-up:

- Accepted P2: summary output previously lost the machine-report link because `run_harness_profile.py` always passed `machine_report_path=None`. Fixed by adding `--machine-report` and a CLI-level regression test.
- Accepted P3: the Feature page previously recorded the temporary untracked working-tree state of the v1 design document. Replaced it with a stable source-design statement.

## Residual Risk

- Bootstrap governed assets remain narrow and GitHub-focused; passing deterministic profile should not overclaim global RPA health.
- deterministic profile is process-required for readiness claims but not CI-enforced in Phase 1.
- full/live validation remains separate and should be used for Planner/LLM or intranet validation only when needed.
- Independent review/readiness gate remains pending; this closeout is single-agent verified.
- Phase 2 report interpretation and Markdown closeout hardening remain necessary before treating deterministic profile output as a fully trusted handoff package.

## Notes

- Phase 1 intentionally does not touch F012 live-agent eval.
- Phase 1 intentionally does not make CI blocking changes.
- Phase 1 intentionally does not add automatic bug diagnosis beyond report facts and Agent-readable evidence.
- Region selection remains represented as ordinary user input context in the v1 design; no region-specific profile branch was added.

## Closeout

Implementation done. Harness closeout is conditional because independent review is still pending and Phase 2 report/closeout interpretation hardening is tracked by F014. The earlier strict metadata blocker no longer reproduces in the current workspace.

Recommendation for Phase 2: proceed with F014 report interpretation and Markdown closeout generation for Agents. Do not expand full/live profile before the deterministic evidence path is considered stable.

## Supports Claim

This record supports only the historical implementation and validation claims explicitly documented in its Results and source material. The migration does not add a new completion claim.

## Verification Scope

The original `## Scope`, commands, results, and artifacts define the verification boundary. Unrecorded environments or workflows remain outside scope.

## Checks

The commands, test runs, manual checks, and other proof are preserved in the original sections of this record. This heading makes the check boundary explicit without inventing new execution.

## Limitations

This is a migrated historical record. It proves only the results explicitly recorded at the time; absent checks, environments, or product acceptance must not be inferred as passing.
