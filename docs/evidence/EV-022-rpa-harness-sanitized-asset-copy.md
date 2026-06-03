---
id: EV-022
doc_kind: evidence
title: RPA Harness Sanitized Asset Copy Evidence
status: active
scope: project
feature_ids: [F022]
feature_refs:
  - docs/features/F022-rpa-harness-sanitized-asset-copy.md
created: 2026-05-30
updated: 2026-05-30
evidence_level: exhaustive
---

# EV-022 RPA Harness Sanitized Asset Copy Evidence

## Scope

F022 的证据：从 raw captured asset 生成脱敏派生资产，并验证脱敏副本仍可被 Harness 脚本扫描、审查和消费。

本切片保留 raw evidence，生成独立 sanitized copy，记录 placeholders / sanitization contract，并运行 focused validation。它不自动提升 sanitized asset 到 candidate/golden，也不声称所有资产都 repo-safe。

## Entry Gate

```text
Start Gate: needs feature -> ready after F022/EV022 creation
Task class: high-risk
Risk triggers:
- derived asset generation
- sensitive data handling
- raw evidence preservation
- replay/profile validity after sanitization
Delegation decision:
- not needed; first slice is bounded and deterministic
Bug attribution:
- new F022 capability slice after F021
Required pre-work:
- create F022 and EV022
- write RED tests before production code
```

## Commands

RED:

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_sanitization.py
```

Result: initial RED failed because `backend.rpa.harness.asset_sanitization` did not exist.

F022.1 RED:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py::test_sensitivity_scan_detects_html_rendered_windows_paths RpaClaw/backend/tests/test_rpa_harness_asset_sanitization.py::test_sanitize_harness_asset_replaces_html_rendered_windows_paths
```

Result: failed as expected. Scanner only detected one local path form, and sanitizer left `C:<span class="pl-cce">\\</span>Users...` in HTML.

F022.2 RED:

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_execution_review.py
```

Result: failed as expected because `backend.rpa.harness.asset_execution_review` did not exist.

GREEN / focused:

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_sanitization.py RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py RpaClaw/backend/tests/test_rpa_harness_asset_review.py
```

F022.2 GREEN:

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_execution_review.py
```

Result: `2 passed in 0.15s`.

F022.3 RED:

```powershell
$env:TMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:TEMP='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTEST_DEBUG_TEMPROOT='E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current'
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_skill_replay.py::test_skill_replay_injects_explicit_model_config_into_generated_skill RpaClaw/backend/tests/test_rpa_harness_stateful_sop.py::test_stateful_sop_injects_explicit_model_config_into_generated_skill
```

Result: failed as expected because `run_skill_replay_e2e()` and `run_stateful_sop_capture_to_skill()` did not accept `model_config`.

F022.3 aggregation RED:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_governed_regression.py::test_governed_offline_regression_passes_model_config_to_replay_runners RpaClaw/backend/tests/test_rpa_harness_governed_regression.py::test_governed_offline_regression_cli_loads_model_config_file RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_cli_passes_model_config_file_to_deterministic_profile
```

Result: failed as expected because governed/profile entrypoints did not pass model config into replay runners, and governed CLI did not accept `--model-config-file`.

F022.3 GREEN:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_skill_replay.py::test_skill_replay_injects_explicit_model_config_into_generated_skill RpaClaw/backend/tests/test_rpa_harness_stateful_sop.py::test_stateful_sop_injects_explicit_model_config_into_generated_skill RpaClaw/backend/tests/test_rpa_harness_governed_regression.py::test_governed_offline_regression_passes_model_config_to_replay_runners RpaClaw/backend/tests/test_rpa_harness_governed_regression.py::test_governed_offline_regression_cli_loads_model_config_file RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_cli_passes_model_config_file_to_deterministic_profile RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_interpretation_without_runner_signals_is_insufficient_evidence
```

Result: `6 passed in 10.76s`.

Real asset:

```powershell
$assetRoot = 'E:\Work-Project\OtherWork\ScienceClaw\data\rpa_harness_assets_bootstrap'
$assetId = 'hcap-fd43c31be477429e9418199e2e557af5'
$targetId = 'hcap-fd43c31be477429e9418199e2e557af5-sanitized'
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_sanitize --assets $assetRoot --asset-id $assetId --target-asset-id $targetId --overwrite --output (Join-Path $assetRoot (Join-Path $targetId 'sanitization_report_cli.json'))
python -m backend.rpa.harness.run_asset_sensitivity_scan --assets $assetRoot --asset-id $targetId
python -m backend.rpa.harness.run_asset_review --assets $assetRoot --asset-id $targetId --output (Join-Path $assetRoot (Join-Path $targetId 'review_generation_report.json'))
python -m backend.rpa.harness.run_asset_execution_review --assets $assetRoot --asset-id $targetId --output (Join-Path $assetRoot (Join-Path $targetId 'execution_review_generation_report.json'))
```

F022.3 real asset rerun used a temporary local model config derived from `.env` aliases (`DS_MODEL`/`DS_API_KEY`/`DS_URL` or `MODEL_NAME`/`API_KEY`/`API_BASE`). The temporary file was deleted after execution and no secret value was written to reports. The rerun wrote:

```text
snapshot_execution_report.json
compiler_execution_report.json
skill_replay_execution_report.json
stateful_sop_execution_report.json
execution_review.md
```

Focused target runner check used a temporary root containing only the sanitized asset:

```powershell
python -m backend.rpa.harness.run_asset_validation --assets <temp-root> --output tmp-harness-validation-f022-target.json
python -m backend.rpa.harness.run_snapshot_regression --assets <temp-root>
python -m backend.rpa.harness.run_compiler_regression --assets <temp-root>
python -m backend.rpa.harness.run_harness_profile --assets <temp-root> --profile deterministic --output tmp-harness-profile-deterministic-f022-target.json
```

## Results

Generated asset:

```text
data/rpa_harness_assets_bootstrap/hcap-fd43c31be477429e9418199e2e557af5-sanitized/
```

Generated reports:

```text
sensitivity_scan.json
review.md
review_generation_report.json
sanitization_report.json
sanitization_report_cli.json
execution_review.md
execution_review_generation_report.json
```

Sensitivity scan summary after F022.1:

```json
{
  "risk_level": "low",
  "recommended_sensitivity": "sanitized",
  "repo_safe_blocked": false,
  "category_counts": {
    "public-web-noise": 89,
    "sanitized-placeholder": 98
  },
  "contract": "preserved"
}
```

Additional literal checks:

```text
NO_LITERAL_C_USERS
NO_HTML_SPAN_C_PATH
```

Focused target runner results:

- validation: exit 0.
- snapshot regression on temp root: exit 0, 5/5 passed.
- compiler regression on temp root: exit 1, 3/5 passed, Step2 and Step4 failed with `compiler-hardcoded-observed-value`.
- deterministic profile on temp root: exit 1, `no-governed-offline-assets`, because sanitized asset remains `candidate-lite`, `asset_status=draft`, `expected_signals_reviewed=false`, `sensitivity_reviewed=false`.
- execution review packet on sanitized asset: exit 0, generated `execution_review.md` and `execution_review_generation_report.json`.
- F022.3 model-config rerun on sanitized asset:
  - snapshot: 5/5 passed.
  - compiler: 3/5 passed, 2 failed.
  - skill_replay: 2/5 passed, 3 failed with `replay-output-shape-mismatch`.
  - stateful_sop: 0/1 passed, failed with `controlled-replay-execution-error`.
  - `runtime_ai_model_config_source=harness_explicit_model_config` for skill/stateful replay.

Interpretation:

- 脱敏副本本身可以被 scan/review/validation/snapshot 脚本消费。
- 脱敏后没有 repo-safe blocking sensitivity findings，且 replay contract 被保留。
- execution review 将 `stateful_sop_execution_report.json`、`skill_replay_execution_report.json`、`compiler_execution_report.json`、`snapshot_execution_report.json` 汇总成人类可读报告。
- stateful replay 的 `Missing credentials` 不等于项目一定没有配置模型凭证；F022.3 已为 Harness 离线 runner 增加显式模型配置注入。真实资产重跑后缺凭证问题消失，说明原失败属于 runner 注入边界，而不是 `.env` 必然缺失。
- F022.3 后的 stateful 失败转为 `Locator.click` timeout，等待 `get_by_role("link", name="Issues 10")`，与 compiler Step4 硬编码现场值同源。
- compiler/profile 失败不是脱敏破坏资产，而是两个独立边界：
  - compiler 仍暴露 Step2/Step4 的既有硬编码问题；
  - deterministic profile 只选择已治理的 blocking baseline，当前资产还未被人工确认。

## Harness Validation

Final closeout run:

- `python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_sanitization.py RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py RpaClaw/backend/tests/test_rpa_harness_asset_review.py`
  - Superseded by F022.2 focused closeout below.
- `python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_execution_review.py RpaClaw/backend/tests/test_rpa_harness_asset_sanitization.py RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py RpaClaw/backend/tests/test_rpa_harness_asset_review.py`
  - Result: `18 passed in 29.58s`
- `python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_skill_replay.py::test_skill_replay_injects_explicit_model_config_into_generated_skill RpaClaw/backend/tests/test_rpa_harness_stateful_sop.py::test_stateful_sop_injects_explicit_model_config_into_generated_skill RpaClaw/backend/tests/test_rpa_harness_governed_regression.py::test_governed_offline_regression_passes_model_config_to_replay_runners RpaClaw/backend/tests/test_rpa_harness_governed_regression.py::test_governed_offline_regression_cli_loads_model_config_file RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_cli_passes_model_config_file_to_deterministic_profile RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_interpretation_without_runner_signals_is_insufficient_evidence`
  - Result: `6 passed in 10.76s`
- Broader runner suite note: `test_rpa_harness_skill_replay.py test_rpa_harness_stateful_sop.py test_rpa_harness_governed_regression.py test_rpa_harness_profile_runner.py` produced `37 passed, 3 failed`; two failures were pre-existing real candidate fixture deletions under `data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc`, and one mock-signature failure was fixed by F022.3.
- `python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict`
  - Result: `Scanned 237 markdown file(s). Checked 48 knowledge artifact(s). Errors: 0. Warnings: 0.`
- `git diff --check -- <F022 touched files>`
  - Result: exit 0; only existing LF/CRLF normalization warnings.

## Artifacts

- Feature: `docs/features/F022-rpa-harness-sanitized-asset-copy.md`
- Evidence: `docs/evidence/EV-022-rpa-harness-sanitized-asset-copy.md`
- Sanitizer: `RpaClaw/backend/rpa/harness/asset_sanitization.py`
- CLI: `RpaClaw/backend/rpa/harness/run_asset_sanitize.py`
- Execution review: `RpaClaw/backend/rpa/harness/asset_execution_review.py`
- Execution review CLI: `RpaClaw/backend/rpa/harness/run_asset_execution_review.py`
- Tests: `RpaClaw/backend/tests/test_rpa_harness_asset_sanitization.py`
- Execution review tests: `RpaClaw/backend/tests/test_rpa_harness_asset_execution_review.py`
- Model config injection: `RpaClaw/backend/rpa/harness/skill_replay.py`, `RpaClaw/backend/rpa/harness/stateful_sop.py`, `RpaClaw/backend/rpa/harness/governed_regression.py`, `RpaClaw/backend/rpa/harness/run_governed_regression.py`, `RpaClaw/backend/rpa/harness/profile_runner.py`, `RpaClaw/backend/rpa/harness/run_harness_profile.py`
- Target asset: `data/rpa_harness_assets_bootstrap/hcap-fd43c31be477429e9418199e2e557af5-sanitized`

## Residual Risk

- Pattern-based sanitization may over-sanitize public examples or miss novel sensitive formats; scanner remains a deterministic guardrail, not a human sensitivity approval.
- Sanitized copy still requires human expected/sensitivity review before candidate/golden promotion.
- Compiler hardcoding remains a separate next slice if this asset is expected to pass blocking compiler regression.
- Harness-only model-config injection is now available, but the runner still does not fetch user database model selection by itself. Use `--model-config-file` or pass `model_config` explicitly for service-equivalent replay.

## Notes

Raw assets remain the evidence source of record. Sanitized assets are derived replay/test artifacts.
