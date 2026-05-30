# F022 脱敏资产副本实现计划

**目标：** 生成 sanitized Harness asset copy，并验证脱敏副本仍可被脚本消费。

**架构：** 新增 sanitizer module，将源资产目录复制为派生 asset id，确定性替换支持文本文件中的敏感值，更新 `scenario.json`，写入 `sanitization_report.json`，并向 expected files 注入 `state_signals.sanitization_contract`。CLI 包装该模块，且不修改 raw asset。

**技术栈：** Python、pytest、现有 `backend.rpa.harness` CLI/report 约定。

## Task 1: Sanitizer Tests

Files:

- Create: `RpaClaw/backend/tests/test_rpa_harness_asset_sanitization.py`

- [x] Write RED tests for sanitized copy creation, raw asset preservation, placeholder contract, and scan unblock behavior.
- [x] Run focused test and confirm it fails because the sanitizer module does not exist.

## Task 2: Sanitizer Module And CLI

Files:

- Create: `RpaClaw/backend/rpa/harness/asset_sanitization.py`
- Create: `RpaClaw/backend/rpa/harness/run_asset_sanitize.py`

- [x] Implement deterministic copy and replacement.
- [x] Update `scenario.json` and expected `sanitization_contract`.
- [x] Write `sanitization_report.json`.
- [x] Implement CLI.

## Task 3: Real Asset Verification

Files:

- Generated: `data/rpa_harness_assets_bootstrap/<asset_id>-sanitized/`

- [x] Generate sanitized copy for the current raw asset.
- [x] Run `run_asset_sensitivity_scan`.
- [x] Run `run_asset_review`.
- [x] Run validation/snapshot/compiler/profile on the sanitized asset.

## Task 4: F022.1 HTML/JSON Escaped Path Coverage

Files:

- Modify: `RpaClaw/backend/rpa/harness/sensitivity_scan.py`
- Modify: `RpaClaw/backend/rpa/harness/asset_sanitization.py`
- Modify: `RpaClaw/backend/tests/test_rpa_harness_sensitivity_scan.py`
- Modify: `RpaClaw/backend/tests/test_rpa_harness_asset_sanitization.py`

- [x] Add RED tests for `C:\\Users...` and `C:<span>\\</span>Users...` forms.
- [x] Teach scanner to block unsanitized escaped/rendered local paths.
- [x] Teach sanitizer to replace those paths as whole semantic placeholders.
- [x] Regenerate the real sanitized asset and confirm no literal `C:\\Users` or HTML-span path remains.

## Task 5: Evidence And Docs

Files:

- Modify: `docs/features/F022-rpa-harness-sanitized-asset-copy.md`
- Modify: `docs/evidence/EV-022-rpa-harness-sanitized-asset-copy.md`
- Modify: `docs/rpa/harness/资产录制与审查最小流程.md`

- [x] Record commands and results.
- [x] Document that sanitization creates derived assets, not in-place raw edits.
