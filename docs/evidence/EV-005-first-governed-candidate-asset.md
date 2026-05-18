---
id: EV-005
doc_kind: evidence
title: First Governed Candidate Asset Evidence
status: active
scope: project
feature_ids: [F005]
created: 2026-05-18
updated: 2026-05-18
evidence_level: exhaustive
---

# EV-005 First Governed Candidate Asset Evidence

## Scope

Evidence for F005: promote the first real Full SOP Harness capture into the
governed offline regression baseline as a candidate scenario asset.

Target asset:

```text
data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc
```

## Entry Gate

- Start Gate: non-trivial Harness asset lifecycle change. Required pre-work is
  this F005 Feature/Evidence anchor.
- Knowledge Retrieval: completed against F004, EV-004, the golden evaluation
  vision, ADR-003, and the target asset metadata.
- Vision Gate Entry: ready to implement. The smallest coherent path is to
  update only the target asset metadata and verify it through the existing F004
  governed report.
- Delegation Gate: not needed. The change is a tightly scoped asset metadata
  curation and verification loop.
- Vision Anchor: [F005 First Governed Candidate Asset](../features/F005-first-governed-candidate-asset.md).

## Pre-Promotion Evidence

F004 governed report before promotion excluded the target asset:

```text
status=failed
failure_category=no-governed-offline-assets
selected_capture_count=0
excluded_capture_count=1
excluded_asset_ids=["hcap-4be6265f43eb42dfa259182207aa64cc"]
reasons=[
  "asset-status-draft",
  "promotion-status-captured",
  "missing-core-chain-coverage",
  "expected-signals-not-reviewed",
  "sensitivity-not-reviewed"
]
```

Prior manual validation from F004/F002.5:

- Asset validation: `issue_count=0`, `blocking_issue_count=0`.
- Snapshot regression: `3 passed, 0 failed`.
- Compiler regression: `3 passed, 0 failed`.
- Step 1 navigation after-capture quality: `status=stable`,
  `ready_state=interactive`, `title_present=true`, `html_bytes=625418`.

## Commands

Post-promotion validation:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_validation --assets <single-asset-root>
python -m backend.rpa.harness.run_snapshot_regression --assets <single-asset-root>
python -m backend.rpa.harness.run_compiler_regression --assets <single-asset-root>
python -m backend.rpa.harness.run_catalog --assets <single-asset-root>
python -m backend.rpa.harness.run_governed_regression --assets <single-asset-root>
```

Focused regression:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_governed_regression.py RpaClaw/backend/tests/test_rpa_harness_asset_validation.py RpaClaw/backend/tests/test_rpa_harness_catalog.py RpaClaw/backend/tests/test_rpa_harness_snapshot_regression.py RpaClaw/backend/tests/test_rpa_harness_compiler_regression.py
```

Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

## Results

Post-promotion asset validation over a temporary single-asset root:

```text
capture_count=1
issue_count=0
blocking_issue_count=0
```

Post-promotion snapshot regression:

```text
total=3
passed=3
failed=0
```

Post-promotion compiler regression:

```text
total=3
passed=3
failed=0
```

Post-promotion catalog:

```text
capture_count=1
step_count=3
asset_statuses={"active": 1}
sensitivity={"repo-safe": 1}
promotion_statuses={"candidate": 1}
runner_modes={"offline_core_chain": 1}
core_chain_coverage={
  "html_to_raw_snapshot": 1,
  "planner_action_selection": 1,
  "raw_to_compact_snapshot": 1,
  "trace_to_skill": 1
}
page_patterns=[
  "card-list",
  "data-extraction",
  "detail-page",
  "multi-page",
  "semantic-selection"
]
```

Post-promotion governed regression over a temporary single-asset root:

```text
status=passed
selected_capture_count=1
excluded_capture_count=0
selected_step_count=3
selected_asset_ids=["hcap-4be6265f43eb42dfa259182207aa64cc"]
snapshot_failed=0
compiler_failed=0
```

Post-promotion governed regression over the real bootstrap asset root:

```text
status=passed
selected_capture_count=1
excluded_capture_count=9
selected_step_count=3
selected_asset_ids=["hcap-4be6265f43eb42dfa259182207aa64cc"]
promotion_statuses={"candidate": 1}
snapshot_failed=0
compiler_failed=0
```

Focused regression:

```text
30 passed in 0.60s
```

## Artifacts

- Feature: [F005 First Governed Candidate Asset](../features/F005-first-governed-candidate-asset.md)
- Evidence: [EV-005 First Governed Candidate Asset Evidence](../evidence/EV-005-first-governed-candidate-asset.md)
- Prior Feature: [F004 Governed Offline Regression Asset Pool](../features/F004-governed-offline-regression-asset-pool.md)
- Prior Evidence: [EV-004 Governed Offline Regression Asset Pool Evidence](EV-004-governed-offline-regression-asset-pool.md)
- Target repo-safe asset:
  - `data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc/scenario.json`
  - `data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc/steps/001/checkpoint.json`
  - `data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc/steps/002/checkpoint.json`
  - `data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc/steps/003/checkpoint.json`

## Notes

- This is a candidate promotion, not a golden promotion.
- The asset is set to `sensitivity=repo-safe` because the capture is from
  public GitHub pages and contains no authenticated or private business data.
  Only this target asset is staged; the broader local `data/` tree remains
  untouched.
- Page-pattern tags describe generic UI shapes and task forms. They must not be
  interpreted as GitHub-specific rules.

## Residual Risks

- One candidate asset is enough to prove the governed baseline path works, but
  not enough to claim broad page-shape coverage.
- A later curation slice should add more assets or decide whether this asset can
  be promoted from `candidate` to `golden`.

## Closeout Status

- Feature: F005 completed.
- Evidence level: exhaustive for this asset lifecycle slice.
- Readiness: pending final strict Harness knowledge check and commit hash
  backfill.
- Completion claim: pending final closeout commit.
- ADR: not triggered. F005 applies ADR-003 rather than changing the decision.
- Lesson: not triggered. No recurring failure mode was found.
- Patch Churn Review: not triggered. F005 has no patch history.
