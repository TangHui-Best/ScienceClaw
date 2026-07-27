---
id: EV-015
doc_kind: evidence
title: RPA Harness v1 Asset Lifecycle Operationalization Evidence
status: active
scope: project
feature_ids: [F015]
feature_refs:
  - docs/features/F015-rpa-harness-v1-asset-lifecycle-operationalization.md
created: 2026-05-28
updated: 2026-05-28
evidence_level: focused
---

# EV-015 RPA Harness v1 Asset Lifecycle Operationalization Evidence

## Scope

Evidence for F015: implement RPA Harness v1 Phase 3 Asset Lifecycle Operationalization.

The first slice is intentionally narrow:

- asset lifecycle summary;
- golden eligibility report;
- promotion guardrails;
- review/profile/report surfaces that expose lifecycle state and coverage boundary.

The slice must preserve the core boundary:

```text
Scripts execute.
Agents explain.
Humans govern.
```

Phase 3 does not expand full/live profile, add CI blocking, automate diagnosis, drive the RPA product UI from an outer Agent, automatically promote candidate/golden assets, or implement Phase 4 user input replay.

## Entry Gate

Start Gate:

```text
Start Gate: needs retrieval -> satisfied; needs feature/plan -> satisfied by F015 and Phase 3 plan before implementation
Task class: high-risk
Risk triggers:
- Harness asset lifecycle governance
- Promotion safety and human approval boundary
- deterministic profile report contract
- possible drift toward full/live, CI blocking, automatic diagnosis, or Phase 4 user input replay
Delegation decision:
- authorized for read-only sidecar exploration because the user explicitly allowed subagents for complex tasks
Bug attribution:
- not triggered; this is a new Phase 3 Feature slice
Required pre-work:
- retrieve F013/EV-013, F014/EV-014, v1 design, F003-F010, ADR-003, usage guide, scenario schema, and F010 review/promotion plan
- run Vision Gate
- create F015/EV-015 and Phase 3 plan
Allowed next action:
- write RED tests for lifecycle summary, golden eligibility, promotion guardrails, and deterministic profile lifecycle boundary fields
```

Knowledge Retrieval:

- Read `docs/features/F013-rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read `docs/evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read `docs/archive/2026-05/rpa-harness/f013-rpa-harness-v1-phase-1-plan.md`.
- Read `docs/features/F014-rpa-harness-v1-evidence-report-trust-loop.md`.
- Read `docs/evidence/EV-014-rpa-harness-v1-evidence-report-trust-loop.md`.
- Read `docs/archive/2026-05/rpa-harness/f014-rpa-harness-v1-phase-2-plan.md`.
- Read `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`.
- Read `docs/features/F003-golden-scenario-asset-model.md` through `docs/features/F010-assisted-asset-review-and-promotion-pipeline.md`.
- Read `docs/rpa/harness/usage-and-triage-guide.md`.
- Read `docs/rpa/harness/scenario-asset-schema.md`.
- Read `docs/rpa/harness/f010-assisted-asset-review-and-promotion-plan.md`.

Retrieval conclusion:

- Governed scenario assets remain the durable evaluation unit.
- `candidate-lite` is warning-only observation and must not become blocking.
- `candidate` requires reviewed expected signals and sensitivity.
- `golden` is a smaller, stable, human-approved contract asset set.
- F013/F014 already established deterministic profile and JSON-first bounded interpretation; Phase 3 should expose lifecycle and coverage boundary, not add another runner.

Vision Gate:

```text
Vision Gate: ready to implement
Mode: Entry Gate
Original intent:
- Make asset lifecycle governance operational and reviewable without loosening human control.
Alignment:
- A lifecycle summary, golden eligibility report, and promotion guardrails are the smallest coherent first slice.
Drift risks:
- full/live expansion, CI blocking, automatic diagnosis, automatic candidate/golden promotion, region-specific Harness branching, or Phase 4 user input replay.
Vision Anchor:
- F015 Feature plus the v1 design, F014 report contract, F010 review/promotion boundary, and scenario asset schema.
Reviewer policy:
- independent review recommended/conditional before readiness because this is a high-risk Harness process slice.
Required next action:
- write focused RED tests, implement minimal lifecycle/report/guardrail code, run focused verification, update Evidence.
```

## Commands

RED tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_catalog.py::test_asset_lifecycle_summary_reports_distribution_and_review_state RpaClaw/backend/tests/test_rpa_harness_catalog.py::test_golden_eligibility_report_requires_candidate_review_and_human_approval RpaClaw/backend/tests/test_rpa_harness_asset_promotion.py::test_golden_promotion_requires_human_approval_and_candidate_eligibility RpaClaw/backend/tests/test_rpa_harness_asset_promotion.py::test_asset_promote_cli_requires_golden_human_approval RpaClaw/backend/tests/test_rpa_harness_asset_review.py::test_review_packet_includes_lifecycle_and_eligibility_snapshot RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_report_includes_asset_pool_lifecycle_boundary
```

Result:

```text
Initial RED:
ImportError: cannot import name 'build_asset_lifecycle_summary'

Second RED after lifecycle helpers:
4 failed, 2 passed
- golden promotion did not require human approval
- review packet lacked Lifecycle State section
- deterministic profile lacked asset_pool
```

Focused GREEN tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_catalog.py::test_asset_lifecycle_summary_reports_distribution_and_review_state RpaClaw/backend/tests/test_rpa_harness_catalog.py::test_golden_eligibility_report_requires_candidate_review_and_human_approval RpaClaw/backend/tests/test_rpa_harness_asset_promotion.py::test_golden_promotion_requires_human_approval_and_candidate_eligibility RpaClaw/backend/tests/test_rpa_harness_asset_promotion.py::test_asset_promote_cli_requires_golden_human_approval RpaClaw/backend/tests/test_rpa_harness_asset_review.py::test_review_packet_includes_lifecycle_and_eligibility_snapshot RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_report_includes_asset_pool_lifecycle_boundary
```

Result:

```text
6 passed in 4.29s
```

Focused regression tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_catalog.py RpaClaw/backend/tests/test_rpa_harness_asset_review.py RpaClaw/backend/tests/test_rpa_harness_asset_promotion.py RpaClaw/backend/tests/test_rpa_harness_profile_runner.py RpaClaw/backend/tests/test_rpa_harness_governed_regression.py
```

Result:

```text
39 passed in 90.08s
```

Independent review follow-up RED test:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_promotion.py::test_golden_promotion_blocks_when_directory_id_and_scenario_id_diverge
```

Result:

```text
FAILED
Failed: DID NOT RAISE <class 'backend.rpa.harness.asset_promotion.PromotionError'>
```

Independent review follow-up GREEN test:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_promotion.py::test_golden_promotion_blocks_when_directory_id_and_scenario_id_diverge
```

Result:

```text
1 passed in 0.15s
```

Second review follow-up RED tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_catalog.py::test_asset_lifecycle_summary_reports_distribution_and_review_state RpaClaw/backend/tests/test_rpa_harness_catalog.py::test_asset_lifecycle_summary_requires_explicit_catalog_details RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_report_includes_asset_pool_lifecycle_boundary
```

Result:

```text
3 failed
- default lifecycle summary still included catalog
- include_catalog opt-in did not exist
- deterministic profile asset_pool still included catalog
```

Second review follow-up GREEN tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_catalog.py::test_asset_lifecycle_summary_reports_distribution_and_review_state RpaClaw/backend/tests/test_rpa_harness_catalog.py::test_asset_lifecycle_summary_requires_explicit_catalog_details RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_report_includes_asset_pool_lifecycle_boundary
```

Result:

```text
3 passed in 3.48s
```

Real bootstrap lifecycle summary:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_catalog --assets data\rpa_harness_assets_bootstrap --format lifecycle --output docs\rpa\harness\reports\2026-05-28-f015-lifecycle-summary.json
```

Result:

```text
exit code 0
lifecycle_distribution = {"candidate": 2}
blocking_baseline_asset_ids =
- hcap-4be6265f43eb42dfa259182207aa64cc
- hcap-de463b7bb608482e9b5bcdd5b78a224e
warning_only_asset_ids = []
golden_asset_ids = []
trust_limits include narrow bootstrap coverage and candidate-lite warning-only boundary.
```

Real bootstrap golden eligibility:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_catalog --assets data\rpa_harness_assets_bootstrap --format golden-eligibility --output docs\rpa\harness\reports\2026-05-28-f015-golden-eligibility.json
```

Result:

```text
exit code 0
asset_count = 2
eligible_count = 2
eligible_asset_ids =
- hcap-4be6265f43eb42dfa259182207aa64cc
- hcap-de463b7bb608482e9b5bcdd5b78a224e
requires_human_approval = true for eligible assets
agents_may_promote_automatically = false
```

Real bootstrap deterministic profile:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile deterministic --output docs\rpa\harness\reports\2026-05-28-f015-deterministic-profile.json
```

Result:

```text
exit code 0
summary.status = passed
summary.selected_asset_count = 2
asset_pool.summary.lifecycle_distribution = {"candidate": 2}
interpretation.verdict = no meaningful change
```

Real bootstrap deterministic profile Markdown:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile deterministic --format summary --lang zh --output docs\rpa\harness\reports\2026-05-28-f015-deterministic-profile.md --machine-report docs\rpa\harness\reports\2026-05-28-f015-deterministic-profile.json
```

Result:

```text
exit code 0
summary includes lifecycle distribution, blocking baseline assets, warning-only assets, coverage boundary, and machine JSON path.
```

## Artifacts

- Feature: `docs/features/F015-rpa-harness-v1-asset-lifecycle-operationalization.md`
- Evidence: `docs/evidence/EV-015-rpa-harness-v1-asset-lifecycle-operationalization.md`
- Plan: `docs/archive/2026-05/rpa-harness/f015-rpa-harness-v1-phase-3-plan.md`
- Lifecycle summary: `docs/rpa/harness/reports/2026-05-28-f015-lifecycle-summary.json`
- Golden eligibility report: `docs/rpa/harness/reports/2026-05-28-f015-golden-eligibility.json`
- Deterministic profile JSON: `docs/rpa/harness/reports/2026-05-28-f015-deterministic-profile.json`
- Deterministic profile Markdown: `docs/rpa/harness/reports/2026-05-28-f015-deterministic-profile.md`
- Lifecycle helpers / CLI: `RpaClaw/backend/rpa/harness/catalog.py`, `RpaClaw/backend/rpa/harness/run_catalog.py`
- Promotion guardrails: `RpaClaw/backend/rpa/harness/asset_promotion.py`, `RpaClaw/backend/rpa/harness/run_asset_promote.py`
- Review Packet lifecycle section: `RpaClaw/backend/rpa/harness/asset_review.py`
- Profile asset-pool boundary: `RpaClaw/backend/rpa/harness/profile_runner.py`
- Focused tests: `RpaClaw/backend/tests/test_rpa_harness_catalog.py`, `RpaClaw/backend/tests/test_rpa_harness_asset_review.py`, `RpaClaw/backend/tests/test_rpa_harness_asset_promotion.py`, `RpaClaw/backend/tests/test_rpa_harness_profile_runner.py`

## Results

Implemented. F015 adds a read-only asset lifecycle operational layer and promotion safety guardrails without adding a new runner.

New report contracts:

- `rpa-harness-asset-lifecycle-summary-v1` reports lifecycle distribution, review state, blocking baseline asset ids, warning-only asset ids, golden asset ids, coverage boundary, lifecycle warnings, and trust limits.
- `rpa-harness-golden-eligibility-v1` reports candidate-to-golden eligibility without mutating assets and explicitly records that human approval is required.
- deterministic profile JSON now includes `asset_pool` so Agents can see coverage boundaries before interpreting `summary.status` or `interpretation.verdict`.
- `asset_pool` and default lifecycle summary intentionally omit the detailed catalog; detailed captures/steps require explicit internal opt-in via `include_catalog=True`.

Promotion changes:

- `candidate-lite` remains warning-only and does not set expected/sensitivity review.
- `candidate` still requires `--confirm-expected --confirm-sensitivity`.
- `golden` now requires `--human-approved-golden` plus candidate eligibility, unless `--override-golden-eligibility` is explicitly supplied with human approval.
- The promotion report includes `human_approved`, `eligibility_status`, and `eligibility_reasons`.

Review Packet change:

- `review.md` now includes a Lifecycle State section with asset status, promotion state, expected/sensitivity review, runner coverage, core-chain coverage, golden eligibility, human approval requirement, and eligibility blockers.

Current real bootstrap run:

- lifecycle distribution: `candidate=2`;
- blocking baseline assets: 2;
- warning-only assets: 0;
- golden assets: 0;
- golden eligibility: 2 eligible candidates, but both still require human approval;
- deterministic profile status: `passed`;
- interpretation verdict: `no meaningful change`.

## Residual Risk

- Bootstrap assets remain narrow and GitHub-focused; lifecycle summary now exposes that boundary but does not solve coverage breadth.
- deterministic profile remains manual/process enforced, not CI blocking.
- Golden eligibility can advise and guard but does not replace human approval.
- `--override-golden-eligibility` exists for explicit human-governed exceptions; misuse would still be a governance risk, but it is opt-in and recorded in the promotion report.
- Internal/intranet asset sensitivity still requires local policy and protected asset roots outside repo-safe fixtures.
- Independent read-only review found one P1 and one P2. The P1 golden eligibility bypass was reproduced with a failing test and fixed; the P2 closeout inconsistency is resolved in this Evidence.
- A second review found three follow-ups: untracked F015 artifacts, over-broad `asset_pool.catalog` exposure, and a stale focused-test count. The catalog exposure was reproduced with failing tests and fixed by making detailed catalog inclusion explicit opt-in; the stale count is corrected here; F015 artifacts were explicitly staged without staging unrelated untracked files. Human review is still recommended before accepting F015 because this is a high-risk Harness process slice.

## Notes

- Untracked workspace files existed before Phase 3. They are intentionally excluded from this Evidence unless explicitly generated by F015.
- Review Packet and promotion flows remain CLI/script-driven. Agents may summarize reports, but humans govern promotion.
- Two read-only explorer subagents reviewed code and docs constraints before implementation. Their findings matched the implemented direction: lifecycle facts belong in catalog/report helpers, promotion mutation stays centralized, and candidate-lite must remain warning-only.
- One independent read-only reviewer checked the final diff and found no scope drift toward new runners, CI blocking, automatic promotion, or full/live expansion.

## Closeout

Implementation done. Focused tests, real bootstrap reports, JSON parse checks, strict knowledge validation, and independent review follow-up pass. F015 is ready for human review; Phase 4 may start after accepting the Phase 3 governance guardrails.

## Supports Claim

This record supports only the historical implementation and validation claims explicitly documented in its Results and source material. The migration does not add a new completion claim.

## Verification Scope

The original `## Scope`, commands, results, and artifacts define the verification boundary. Unrecorded environments or workflows remain outside scope.

## Checks

The commands, test runs, manual checks, and other proof are preserved in the original sections of this record. This heading makes the check boundary explicit without inventing new execution.

## Limitations

This is a migrated historical record. It proves only the results explicitly recorded at the time; absent checks, environments, or product acceptance must not be inferred as passing.
