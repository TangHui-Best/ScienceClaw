---
id: EV-021
doc_kind: evidence
title: RPA Harness Asset Sensitivity Scan Evidence
status: active
scope: project
feature_ids: [F021]
feature_refs:
  - docs/features/F021-rpa-harness-asset-sensitivity-scan.md
created: 2026-05-30
updated: 2026-05-30
evidence_level: standard
---

# EV-021 RPA Harness Asset Sensitivity Scan Evidence

## Scope

Evidence for F021: deterministic sensitivity scanning for RPA Harness assets, review packet integration, and sanitized replay contract reporting.

This slice proves that Harness can scan asset files for common sensitive data classes and surface the conclusion in `review.md`. It also proves that sanitized assets can express replay value through placeholders, semantic types, runtime secret references, or controlled fixture contracts.

It does not automatically rewrite existing assets, does not certify malware safety, and does not promote assets automatically.

## Entry Gate

Start Gate:

```text
Start Gate: needs feature -> ready after F021/EV021/Plan creation
Task class: high-risk
Risk triggers:
- Harness asset governance and promotion boundary
- sensitive data handling
- repo-safe and local-only classification
- sanitized replay contract semantics
Delegation decision:
- not needed; first slice is bounded and can be implemented inline with focused tests
Bug attribution:
- new F021 capability slice after F010/F015 lifecycle governance
Required pre-work:
- retrieve F010/F015/F020 and asset review flow
- create F021/EV021/Plan before production code
- write RED tests before implementation
```

Knowledge Retrieval:

- F010/F015 provide review/promotion/lifecycle boundaries but no sensitivity scanner.
- Current `run_asset_promote --confirm-sensitivity` records human confirmation; it does not scan asset content.
- `docs/rpa/harness/资产录制与审查最小流程.md` states `sensitivity` is a classification, not automatic proof that no sensitive data exists.

## Commands

RED:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py RpaClaw/backend/tests/test_rpa_harness_asset_review.py::test_review_packet_includes_sensitivity_scan_summary_and_sanitized_replay_status
```

GREEN / focused:

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py RpaClaw/backend/tests/test_rpa_harness_asset_review.py
```

真实资产扫描：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_sensitivity_scan --assets "E:\Work-Project\OtherWork\ScienceClaw\data\rpa_harness_assets_bootstrap" --asset-id "hcap-fd43c31be477429e9418199e2e557af5"
```

Sidecar 输出行为补丁：

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py::test_sensitivity_scan_cli_writes_sidecar_report_by_default
```

Sidecar 自扫描修复：

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py::test_sensitivity_scan_ignores_existing_generated_sidecar_report
```

Review render-safe 修复：

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_review.py::test_review_packet_keeps_generated_markdown_render_safe_for_long_evidence
```

Suggested Promotion 消费扫描结论：

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_review.py::test_suggested_promotion_references_sensitivity_scan_blockers
```

Review packet 更新：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_review --assets "E:\Work-Project\OtherWork\ScienceClaw\data\rpa_harness_assets_bootstrap" --asset-id "hcap-fd43c31be477429e9418199e2e557af5" --output "tmp-harness-asset-review-with-sensitivity-hcap-fd43.json"
```

## Results

- RED: failed during collection with `ModuleNotFoundError: No module named 'backend.rpa.harness.run_asset_sensitivity_scan'`, proving the new CLI/module did not yet exist.
- GREEN focused suite: `8 passed in 9.06s`.
- Real asset `hcap-fd43c31be477429e9418199e2e557af5` scan result:
  - `risk_level=medium`
  - `recommended_sensitivity=local-only`
  - `repo_safe_blocked=true`
  - categories: `PII=24`, `auth/session=3`, `local-path=8`, `public-web-noise=89`
  - `sanitized_replay_contract.status=needs-contract`
- The asset `review.md` now includes a `Sensitivity Scan` section with those conclusions.
- F021.1 sidecar output patch:
  - RED failed because `sensitivity_scan.json` was not created under the asset directory and the report was only printed to stdout.
  - GREEN focused test passed after the CLI wrote per-asset reports to `<asset_dir>/sensitivity_scan.json` when `--output` is omitted.
  - Explicit `--output` remains available for aggregate reports.
- F021.2 sidecar self-scan patch:
  - RED failed with `finding_count=2` when an existing `sensitivity_scan.json` contained a prior generated finding.
  - GREEN focused test passed after generated reports were excluded from scanner input.
  - Real asset rerun returned `finding_count=124` and `has_self_scan=false`.
- F021.3 review render-safe patch:
  - RED failed with a generated review line length of `2349` for long output/region evidence.
  - GREEN focused test passed after display summaries and generated lines were capped.
  - Real asset review now has `max_line=360` and preserves detailed facts in trace/HTML/scan JSON sidecars.
- F021.4 Suggested Promotion patch:
  - RED failed because Suggested Promotion still said blocking candidate only needed explicit expected/sensitivity confirmation despite scan blockers.
  - GREEN focused test passed after Suggested Promotion consumed `repo_safe_blocked` and `sanitized_replay_contract`.
  - Real asset review now says blocking candidate / repo-safe / golden are not recommended until sensitivity blockers are handled.

## Harness Validation

`knowledge_check.py --strict` passed:

```text
Scanned 234 markdown file(s). Checked 46 knowledge artifact(s). Errors: 0. Warnings: 0.
```

## Artifacts

- Feature: `docs/features/F021-rpa-harness-asset-sensitivity-scan.md`
- Evidence: `docs/evidence/EV-021-rpa-harness-asset-sensitivity-scan.md`
- Plan: `docs/rpa/harness/f021-asset-sensitivity-scan-plan.md`
- Scanner: `RpaClaw/backend/rpa/harness/sensitivity_scan.py`
- CLI: `RpaClaw/backend/rpa/harness/run_asset_sensitivity_scan.py`
- Review integration: `RpaClaw/backend/rpa/harness/asset_review.py`
- Tests: `RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py`, `RpaClaw/backend/tests/test_rpa_harness_asset_review.py`

## Residual Risk

Pattern-based scanning can miss novel secrets or over-report public web noise. Human review remains required before `candidate` / `golden` promotion or `repo-safe` classification. This slice reports sanitized replay contracts but does not automatically rewrite raw assets into sanitized copies.

## Notes

`run_asset_sensitivity_scan` is a deterministic evidence generator. `--confirm-sensitivity` remains a human governance confirmation and should be based on the scan report plus any required manual review.
