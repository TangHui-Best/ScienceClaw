---
id: EV-014
doc_kind: evidence
title: RPA Harness v1 Evidence / Report Trust Loop Evidence
status: active
scope: project
feature_ids: [F014]
feature_refs:
  - docs/features/F014-rpa-harness-v1-evidence-report-trust-loop.md
created: 2026-05-28
updated: 2026-05-28
evidence_level: focused
---

# EV-014 RPA Harness v1 Evidence / Report Trust Loop Evidence

## Scope

Evidence for F014: RPA Harness v1 Phase 2 Evidence / Report trust loop over the existing F013 deterministic profile.

This slice must keep the architecture boundary:

```text
Scripts execute. Agents explain. Humans govern.
```

Phase 2 does not expand full/live profile, add CI blocking, automate diagnosis, drive the RPA product UI from an outer Agent, or promote assets automatically.

## Entry Gate

Start Gate:

```text
Start Gate: needs retrieval -> satisfied; needs feature/plan -> satisfied by F014 and Phase 2 plan before implementation
Task class: high-risk
Risk triggers:
- Harness report interpretation contract
- Evidence / closeout semantics
- Strict knowledge validation and possible metadata churn
- Drift risk toward full/live, CI blocking, or automatic diagnosis
Delegation decision:
- authorized/conditional for read-only strict knowledge triage because the user explicitly allowed subagents for complex tasks
Bug attribution:
- F013 owns the Phase 1 P2 command-documentation finding
- F014 owns Phase 2 report/evidence trust loop
Required pre-work:
- retrieve F013/EV-013/v1 design/Phase 1 plan/usage guide/ADR-003/F003-F010
- run Vision Gate
- create F014/EV-014 and Phase 2 plan
Allowed next action:
- implement bounded interpretation/report contract only
```

Knowledge Retrieval:

- Read `docs/features/F013-rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read `docs/evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read `docs/archive/2026-05/rpa-harness/f013-rpa-harness-v1-phase-1-plan.md`.
- Read `docs/rpa/harness/usage-and-triage-guide.md`.
- Read `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`.
- Read `docs/features/F003-golden-scenario-asset-model.md` through `docs/features/F010-assisted-asset-review-and-promotion-pipeline.md`.

Retrieval conclusion:

- Existing governed runner facts are the source of truth.
- F013 deterministic profile is the default script-driven pre-submit evidence path.
- Phase 2 should harden report interpretation and Agent handoff, not add new execution paths.
- Strict knowledge validation had pre-existing repo-wide metadata failures during F013; Phase 2 may triage but should not broad-edit frontmatter without clear semantic preservation.

Vision Gate:

```text
Vision Gate: ready to implement
Mode: Entry Gate
Original intent:
- Make deterministic profile evidence trustworthy and readable enough for human/Agent closeout.
Alignment:
- Add bounded interpretation fields and report guidance over existing runner facts.
Drift risks:
- full/live expansion, CI blocking, automatic diagnosis, metadata churn, region-specific Harness branching.
Vision Anchor:
- F014 Feature plus F013 and the v1 design.
Reviewer policy:
- independent review recommended/conditional before readiness because this is a high-risk Harness process slice.
Required next action:
- write RED tests, implement minimal report contract, run focused verification, update Evidence.
```

## Commands

Phase 1 P2 documentation fix:

```text
Updated docs/rpa/harness/usage-and-triage-guide.md and
docs/archive/2026-05/rpa-harness/f013-rpa-harness-v1-phase-1-plan.md so deterministic
summary examples pass --machine-report and do not produce "not written".
```

RED tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_interpretation_passed_single_run_is_no_meaningful_change RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_interpretation_failed_run_is_regression RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_interpretation_without_selected_assets_is_insufficient_evidence RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_summary_names_profile_and_machine_report_path
```

Result:

```text
4 failed
KeyError: 'interpretation'
AssertionError: summary did not contain Interpretation / Comparison basis / Bounded interpretation / Agent JSON-first fields
```

Focused GREEN tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_interpretation_passed_single_run_is_no_meaningful_change RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_interpretation_failed_run_is_regression RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_interpretation_without_selected_assets_is_insufficient_evidence RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_summary_names_profile_and_machine_report_path
```

Result:

```text
4 passed in 4.81s
```

Focused regression tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_profile_runner.py RpaClaw/backend/tests/test_rpa_harness_governed_regression.py
```

Result:

```text
22 passed in 22.44s
```

Review request follow-up RED test:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_interpretation_without_runner_signals_is_insufficient_evidence
```

Result:

```text
FAILED
AssertionError: assert 'no meaningful change' == 'insufficient evidence'
```

Review request follow-up GREEN test:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_interpretation_without_runner_signals_is_insufficient_evidence
```

Result:

```text
1 passed in 0.25s
```

Deterministic profile JSON:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile deterministic --output docs\rpa\harness\reports\2026-05-28-f014-deterministic-profile.json
```

Result:

```text
exit code 0
summary.status = passed
summary.selected_asset_count = 2
summary.first_failure_category = ""
interpretation.verdict = no meaningful change
interpretation.comparison_basis = single-run
interpretation.bounded = true
```

JSON parse check:

```powershell
python -m json.tool docs\rpa\harness\reports\2026-05-28-f014-deterministic-profile.json
```

Result:

```text
exit code 0
```

PowerShell parse check:

```powershell
$json = Get-Content -Path docs\rpa\harness\reports\2026-05-28-f014-deterministic-profile.json -Raw -Encoding UTF8 | ConvertFrom-Json
$json.interpretation
```

Result:

```text
verdict = no meaningful change
bounded = true
comparison_basis = single-run
recommended_agent_flow starts with interpretation, summary, profile, deterministic.observability
```

Deterministic profile Markdown:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile deterministic --format summary --lang zh --output docs\rpa\harness\reports\2026-05-28-f014-deterministic-profile.md --machine-report docs\rpa\harness\reports\2026-05-28-f014-deterministic-profile.json
```

Result:

```text
exit code 0
Markdown contains:
- Interpretation: no meaningful change
- Comparison basis: single-run
- Bounded interpretation: true
- Basis: summary.status=passed; summary.selected_asset_count=2; summary.first_failure_category=none; deterministic.observability.runner_signals
- 机器报告: docs\rpa\harness\reports\2026-05-28-f014-deterministic-profile.json
- Agent JSON-first fields: interpretation, summary, profile, deterministic.observability
```

Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

Result:

```text
exit code 0
Scanned 203 markdown file(s). Checked 32 knowledge artifact(s). Errors: 0. Warnings: 0.
```

## Artifacts

- Feature: `docs/features/F014-rpa-harness-v1-evidence-report-trust-loop.md`
- Evidence: `docs/evidence/EV-014-rpa-harness-v1-evidence-report-trust-loop.md`
- Plan: `docs/archive/2026-05/rpa-harness/f014-rpa-harness-v1-phase-2-plan.md`
- Profile runner: `RpaClaw/backend/rpa/harness/profile_runner.py`
- Profile CLI: `RpaClaw/backend/rpa/harness/run_harness_profile.py`
- Focused tests: `RpaClaw/backend/tests/test_rpa_harness_profile_runner.py`
- Usage guide: `docs/rpa/harness/usage-and-triage-guide.md`
- Machine report: `docs/rpa/harness/reports/2026-05-28-f014-deterministic-profile.json`
- Markdown summary: `docs/rpa/harness/reports/2026-05-28-f014-deterministic-profile.md`

## Results

Implemented. F014 adds a bounded `interpretation` contract to deterministic profile output without adding a new runner.

The contract records:

- `verdict`: one of `regression`, `improvement`, `no meaningful change`, `insufficient evidence`;
- `bounded`: always true for this Phase 2 interpretation layer;
- `comparison_basis`: currently `single-run`;
- `basis`: stable fact paths and runner counts used for interpretation;
- `evidence_limits`: explicit limits such as missing baseline comparison or narrow coverage;
- `recommended_agent_flow`: JSON-first fields for Agent analysis.

Current real bootstrap run:

- profile: `deterministic`;
- status: `passed`;
- selected assets: 2;
- selected asset ids:
  - `hcap-4be6265f43eb42dfa259182207aa64cc`
  - `hcap-de463b7bb608482e9b5bcdd5b78a224e`
- first failure category: none;
- warning-only observations: 0;
- interpretation verdict: `no meaningful change`;
- interpretation basis: `single-run`.

This means the covered deterministic asset paths showed no meaningful change in a single current run. It does not mean the RPA Agent is globally healthy and does not claim improvement because no baseline comparison report was supplied.

## Residual Risk

- Bootstrap governed assets remain narrow and GitHub-focused.
- `interpretation.verdict=improvement` is reserved for future explicit baseline comparison and is not produced by Phase 2.
- deterministic profile is still manually/process enforced, not CI blocking.
- full/live validation remains separate for Planner/LLM and intranet validation.
- Independent review found and the main agent fixed one P2 issue: Markdown summary acceptance claimed `interpretation.basis`, but the generated summary did not include a `Basis:` line. A focused RED test reproduced the gap, the renderer now includes a concise basis line, and focused tests plus strict knowledge validation passed after the fix.

## Notes

- Phase 1 P2 documentation fix belongs to this delivery sequence but is attributed to F013.
- Strict knowledge validation now passes; no broad legacy Harness metadata cleanup was needed.
- The summary report is an entrypoint for humans. The machine JSON remains the source of truth for Agents.
- `Get-Content` without `-Encoding UTF8` can misparse or display UTF-8 report content in older PowerShell. JSON validity was verified with `python -m json.tool` and PowerShell `Get-Content -Encoding UTF8 | ConvertFrom-Json`.
- Review request P1 was valid: F014 Feature, Evidence, plan, and generated report artifacts were untracked. They must be explicitly staged with the rest of this change, without staging unrelated untracked workspace files.
- Review request P2 was valid: missing `deterministic.observability.runner_signals` was previously treated as zero failures. It is now `insufficient evidence` with an explicit evidence limit.

## Closeout

Implementation done. Harness closeout passes for Phase 2 review readiness. Focused tests, deterministic profile JSON/Markdown generation, JSON parse validation, strict knowledge validation, and independent review follow-up all pass.

Phase 3 recommendation: Asset Lifecycle Operationalization can start. Phase 3 should focus on asset lifecycle operations, governance ergonomics, and report handoff rituals, not new runner expansion or full/live profile.

## Supports Claim

This record supports only the historical implementation and validation claims explicitly documented in its Results and source material. The migration does not add a new completion claim.

## Verification Scope

The original `## Scope`, commands, results, and artifacts define the verification boundary. Unrecorded environments or workflows remain outside scope.

## Checks

The commands, test runs, manual checks, and other proof are preserved in the original sections of this record. This heading makes the check boundary explicit without inventing new execution.

## Limitations

This is a migrated historical record. It proves only the results explicitly recorded at the time; absent checks, environments, or product acceptance must not be inferred as passing.
