# F015 RPA Harness v1 Phase 3 Implementation Plan

## Goal

实现 RPA Harness v1 Phase 3 的第一切片：asset lifecycle summary、golden eligibility report、promotion guardrails，并把这些事实接入 Review Packet、deterministic profile 和 usage guide，让资产池状态、资格、风险和覆盖边界可以日常审查与交接。

## Architecture

Phase 3 不新增 runner。它在已有 asset catalog、review packet、promotion CLI 和 deterministic profile 之上增加治理操作层：

- `catalog.py` 负责资产池 facts 和 lifecycle summary。
- `asset_review.py` 负责把单资产 lifecycle facts 写进 `review.md`。
- `asset_promotion.py` 负责 promotion safety boundary。
- `profile_runner.py` 负责在 deterministic report 中暴露资产池覆盖边界和 lifecycle distribution。

核心边界保持：

```text
Scripts execute.
Agents explain.
Humans govern.
```

## Source Documents

- `docs/features/F015-rpa-harness-v1-asset-lifecycle-operationalization.md`
- `docs/evidence/EV-015-rpa-harness-v1-asset-lifecycle-operationalization.md`
- `docs/features/F014-rpa-harness-v1-evidence-report-trust-loop.md`
- `docs/evidence/EV-014-rpa-harness-v1-evidence-report-trust-loop.md`
- `docs/features/F013-rpa-harness-v1-asset-driven-user-input-replay.md`
- `docs/evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md`
- `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`
- `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`
- `docs/features/F003-golden-scenario-asset-model.md` through `docs/features/F010-assisted-asset-review-and-promotion-pipeline.md`
- `docs/rpa/harness/usage-and-triage-guide.md`
- `docs/rpa/harness/scenario-asset-schema.md`
- `docs/rpa/harness/f010-assisted-asset-review-and-promotion-plan.md`

## Planned Files

- Modify `RpaClaw/backend/rpa/harness/catalog.py`
  - Add lifecycle summary and golden eligibility report helpers derived from existing catalog facts.
  - Keep lifecycle facts read-only; no promotion side effect.
- Modify `RpaClaw/backend/rpa/harness/run_catalog.py`
  - Add CLI output modes for lifecycle summary and golden eligibility if the current CLI can host them cleanly.
- Modify `RpaClaw/backend/rpa/harness/asset_review.py`
  - Add lifecycle/review status and golden eligibility snapshot to Review Packet.
- Modify `RpaClaw/backend/rpa/harness/asset_promotion.py`
  - Add explicit human approval for `golden`.
  - Require candidate eligibility before golden unless an explicit override is supplied.
  - Preserve candidate-lite warning-only behavior.
- Modify `RpaClaw/backend/rpa/harness/run_asset_promote.py`
  - Add `--human-approved-golden` and `--override-golden-eligibility`.
- Modify `RpaClaw/backend/rpa/harness/profile_runner.py`
  - Add deterministic profile `asset_pool` boundary fields.
  - Expose lifecycle distribution, selected blocking baseline, warning-only observation count, and coverage limits.
- Modify focused tests:
  - `RpaClaw/backend/tests/test_rpa_harness_catalog.py`
  - `RpaClaw/backend/tests/test_rpa_harness_asset_review.py`
  - `RpaClaw/backend/tests/test_rpa_harness_asset_promotion.py`
  - `RpaClaw/backend/tests/test_rpa_harness_profile_runner.py`
- Modify docs:
  - `docs/rpa/harness/usage-and-triage-guide.md`
  - `docs/evidence/EV-015-rpa-harness-v1-asset-lifecycle-operationalization.md`
  - `docs/features/F015-rpa-harness-v1-asset-lifecycle-operationalization.md`

## Task 1: RED Tests For Lifecycle Summary

Add tests before implementation in `RpaClaw/backend/tests/test_rpa_harness_catalog.py`.

Assertions:

- `build_asset_lifecycle_summary(tmp_path)` returns `schema_version="rpa-harness-asset-lifecycle-summary-v1"`.
- Summary counts `draft`, `candidate-lite`, `candidate`, and `golden`.
- Summary exposes:
  - expected-signal review counts;
  - sensitivity review counts;
  - runner coverage counts;
  - blocking baseline asset ids;
  - warning-only asset ids;
  - golden asset ids;
  - lifecycle warnings for assets that look promotable but lack review.

RED command:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_catalog.py::test_asset_lifecycle_summary_reports_distribution_and_review_state
```

Expected RED result:

```text
ImportError: cannot import name 'build_asset_lifecycle_summary'
```

## Task 2: Minimal Lifecycle Summary Implementation

Implement `build_asset_lifecycle_summary()` in `catalog.py`.

Rules:

- Use `build_harness_catalog()` as the source of truth.
- Do not write asset files.
- Treat `candidate-lite` as `warning_only_asset_ids`.
- Treat only active `candidate` / `golden` with expected and sensitivity review as `blocking_baseline_asset_ids`.
- Include `coverage_boundary` with page patterns, hosts, runner modes, core-chain coverage, and narrow-coverage limits.

Run the RED test again and make it pass.

## Task 3: RED Tests For Golden Eligibility

Add tests in `test_rpa_harness_catalog.py`.

Assertions:

- `build_golden_eligibility_report(tmp_path)` returns `schema_version="rpa-harness-golden-eligibility-v1"`.
- A reviewed active candidate with runner coverage is eligible but still requires human approval.
- A candidate-lite asset is not eligible for golden.
- An unreviewed candidate is not eligible and records missing expected/sensitivity review.
- The report contains no mutation side effect.

RED command:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_catalog.py::test_golden_eligibility_report_requires_candidate_review_and_human_approval
```

Expected RED result:

```text
ImportError: cannot import name 'build_golden_eligibility_report'
```

## Task 4: Golden Eligibility Implementation

Implement `build_golden_eligibility_report()` in `catalog.py`.

Eligibility rules:

- `promotion_status` must be `candidate`.
- `asset_status` must be `active`.
- `expected_signals_reviewed` must be true.
- `sensitivity_reviewed` must be true.
- `runner_modes` must include `offline_core_chain`.
- `core_chain_coverage` must not be empty.
- The report must include `requires_human_approval=true` for every eligible asset.
- The report must not change `scenario.json`.

Do not infer golden from a passing deterministic run.

## Task 5: RED Tests For Promotion Guardrails

Add tests in `RpaClaw/backend/tests/test_rpa_harness_asset_promotion.py`.

Assertions:

- `candidate` promotion still requires `confirm_expected` and `confirm_sensitivity`.
- `golden` promotion fails without `human_approved_golden=True`.
- `golden` promotion fails when the asset is not currently an eligible active candidate.
- `golden` promotion can proceed with explicit approval after candidate eligibility is satisfied.
- `override_golden_eligibility=True` permits emergency promotion only with human approval and records the override in the report.

RED command:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_promotion.py::test_golden_promotion_requires_human_approval_and_candidate_eligibility
```

Expected RED result:

```text
TypeError: promote_harness_asset() got an unexpected keyword argument 'human_approved_golden'
```

## Task 6: Promotion Guardrail Implementation

Update `promote_harness_asset()` and CLI.

Rules:

- Candidate-lite behavior remains unchanged and does not set expected/sensitivity review.
- Candidate behavior remains explicit expected/sensitivity confirmation.
- Golden behavior requires:
  - `human_approved_golden=True`;
  - current scenario already has `promotion_status=candidate`;
  - current `asset_status=active`;
  - expected/sensitivity review already true or confirmed in this command;
  - runner modes and core-chain coverage present;
  - unless `override_golden_eligibility=True` is also set.
- CLI exposes `--human-approved-golden` and `--override-golden-eligibility`.
- Report includes `human_approved`, `eligibility_status`, and `eligibility_reasons`.

## Task 7: Review Packet And Profile Boundary Tests

Add tests:

- `test_review_packet_includes_lifecycle_and_eligibility_snapshot` in `test_rpa_harness_asset_review.py`.
- `test_profile_report_includes_asset_pool_lifecycle_boundary` in `test_rpa_harness_profile_runner.py`.

Assertions:

- Review Packet names lifecycle state, expected review, sensitivity review, runner coverage, and golden eligibility.
- deterministic profile JSON includes `asset_pool.lifecycle_distribution`, `asset_pool.blocking_baseline_asset_ids`, `asset_pool.warning_only_asset_ids`, `asset_pool.coverage_boundary`, and `asset_pool.trust_limits`.
- Summary output includes lifecycle distribution and coverage boundary.

## Task 8: Minimal Review/Profile Implementation

Update `asset_review.py` to call the new catalog helpers for the selected asset and render a concise lifecycle section.

Update `profile_runner.py` to attach `asset_pool` from `build_asset_lifecycle_summary()` and render a concise summary line.

Keep output factual; do not add diagnosis or promotion recommendations beyond eligibility and required human approval.

## Task 9: Usage Guide Update

Update `docs/rpa/harness/usage-and-triage-guide.md` with:

- asset lifecycle summary command;
- golden eligibility report command;
- internal asset onboarding flow;
- candidate-lite warning-only semantics;
- candidate/golden promotion guardrails;
- deterministic profile asset pool boundary fields;
- explicit prohibition on Agent automatic candidate/golden promotion.

Do not broad-fix unrelated wording or encoding.

## Task 10: Verification

Run focused tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_catalog.py RpaClaw/backend/tests/test_rpa_harness_asset_review.py RpaClaw/backend/tests/test_rpa_harness_asset_promotion.py RpaClaw/backend/tests/test_rpa_harness_profile_runner.py RpaClaw/backend/tests/test_rpa_harness_governed_regression.py
```

Run real bootstrap lifecycle reports:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_catalog --assets data\rpa_harness_assets_bootstrap --format lifecycle --output docs\rpa\harness\reports\2026-05-28-f015-lifecycle-summary.json
python -m backend.rpa.harness.run_catalog --assets data\rpa_harness_assets_bootstrap --format golden-eligibility --output docs\rpa\harness\reports\2026-05-28-f015-golden-eligibility.json
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile deterministic --output docs\rpa\harness\reports\2026-05-28-f015-deterministic-profile.json
```

Run strict Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

## Task 11: Evidence And Closeout

Update EV-015 with:

- RED/GREEN test output.
- Focused test output.
- Lifecycle summary, golden eligibility, and deterministic profile paths.
- Real bootstrap lifecycle distribution and eligibility result.
- Knowledge check result.
- Residual risks.
- Reviewer status.
- Recommendation on whether Phase 4 can start.

Update F015 acceptance criteria and status only after verification evidence exists.
