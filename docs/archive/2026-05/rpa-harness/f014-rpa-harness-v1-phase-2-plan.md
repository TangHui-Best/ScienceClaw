# F014 RPA Harness v1 Phase 2 Implementation Plan

## Goal

实现 RPA Harness v1 Phase 2：Evidence / Report 可信闭环。让 deterministic profile 的机器 JSON、Markdown summary、Agent 解读流程、Feature/Evidence closeout 和 knowledge gate 状态能够稳定交接。

## Architecture

Phase 2 只在 F013 `profile_runner.py` 的 profile/report 层增加 bounded interpretation contract。它不重写 `run_governed_offline_regression()`，不新增 full/live profile，不做自动诊断平台。判断语义只从既有 facts 派生：

- `regression`: blocking runner facts show current deterministic profile failed.
- `no meaningful change`: blocking runner facts passed and coverage exists, but no baseline/comparison report is supplied.
- `improvement`: reserved for future explicit baseline comparison; Phase 2 must not infer improvement from a single passing run.
- `insufficient evidence`: no selected governed assets, missing runner facts, or coverage/evidence is too weak to support a pass/fail interpretation.

Agent 解读必须 JSON-first：先读 `interpretation`、`summary`、`profile` 和 `deterministic.observability`，再用 Markdown summary 做人工交接入口。

## Source Documents

- `docs/features/F014-rpa-harness-v1-evidence-report-trust-loop.md`
- `docs/evidence/EV-014-rpa-harness-v1-evidence-report-trust-loop.md`
- `docs/features/F013-rpa-harness-v1-asset-driven-user-input-replay.md`
- `docs/evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md`
- `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`
- `docs/rpa/harness/f013-rpa-harness-v1-phase-1-plan.md`
- `docs/rpa/harness/usage-and-triage-guide.md`
- `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`
- `docs/features/F003-golden-scenario-asset-model.md` through `docs/features/F010-assisted-asset-review-and-promotion-pipeline.md`

## Planned Files

- Modify `RpaClaw/backend/rpa/harness/profile_runner.py`
  - Add a small interpretation builder.
  - Add `report["interpretation"]`.
  - Render interpretation and Agent JSON-first fields in summary output.
- Modify `RpaClaw/backend/tests/test_rpa_harness_profile_runner.py`
  - Add RED tests for passed single-run semantics, failed regression semantics, insufficient evidence semantics, and Markdown summary fields.
- Modify `docs/rpa/harness/usage-and-triage-guide.md`
  - Fix Phase 1 P2 `--machine-report` example.
  - Add Agent interpretation protocol over stable JSON fields.
- Modify `docs/rpa/harness/f013-rpa-harness-v1-phase-1-plan.md`
  - Fix Phase 1 P2 summary command example.
- Update `docs/features/F013-rpa-harness-v1-asset-driven-user-input-replay.md`
  - Add a Patch History row for the P2 doc fix.
- Update `docs/evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md`
  - Record the P2 doc fix and point Phase 2 ownership to F014.
- Update `docs/features/F014-rpa-harness-v1-evidence-report-trust-loop.md`
  - Mark acceptance criteria as completed when verified.
- Update `docs/evidence/EV-014-rpa-harness-v1-evidence-report-trust-loop.md`
  - Record RED/GREEN tests, deterministic profile output paths, knowledge gate result, residual risk, and Phase 3 recommendation.

## Task 1: RED Tests For Interpretation Contract

Add tests to `RpaClaw/backend/tests/test_rpa_harness_profile_runner.py` before implementation.

Assertions:

- Passing deterministic profile with selected assets returns:
  - `interpretation.verdict == "no meaningful change"`
  - `interpretation.bounded == True`
  - `interpretation.comparison_basis == "single-run"`
  - `interpretation.evidence_limits` includes no baseline comparison.
- Failing deterministic profile returns:
  - `interpretation.verdict == "regression"`
  - `interpretation.first_failure_category` matches `summary.first_failure_category`
  - `interpretation.recommended_agent_flow` starts from JSON fields, not summary text.
- No selected governed assets returns:
  - `interpretation.verdict == "insufficient evidence"`
  - `interpretation.evidence_limits` names missing governed assets.

RED command:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_interpretation_passed_single_run_is_no_meaningful_change RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_interpretation_failed_run_is_regression RpaClaw/backend/tests/test_rpa_harness_profile_runner.py::test_profile_interpretation_without_selected_assets_is_insufficient_evidence
```

Expected RED result:

```text
KeyError: 'interpretation'
```

## Task 2: Minimal Interpretation Builder

Implement a private helper in `profile_runner.py`:

```python
def _profile_interpretation(governed_report: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    ...
```

Rules:

- Use only existing `summary` and governed `observability` facts.
- Do not call an LLM.
- Do not infer `improvement` without an explicit baseline/comparison input.
- Put diagnostic detail in `basis` and `evidence_limits`, not in root-cause claims.
- Add `recommended_agent_flow` as stable JSON field paths for Agent reading.

Run the RED tests again and make them pass.

## Task 3: Markdown Summary Hardening

Add test assertions that `render_profile_summary(..., machine_report_path=...)` includes:

- machine report path;
- interpretation verdict;
- comparison basis;
- bounded interpretation note;
- Agent JSON-first fields.

Implement the minimal summary rendering update in `profile_runner.py`.

## Task 4: Documentation Updates

Update only relevant sections:

- `usage-and-triage-guide.md`: add `--machine-report` to deterministic summary example and document `interpretation` fields.
- `f013-rpa-harness-v1-phase-1-plan.md`: add `--machine-report` to Phase 1 summary command.
- F013/EV-013: record the P2 documentation fix and point Phase 2 to F014.
- F014/EV-014: record implementation status and verification.

Do not perform broad encoding cleanup or unrelated frontmatter churn.

## Task 5: Verification

Run focused tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_profile_runner.py RpaClaw/backend/tests/test_rpa_harness_governed_regression.py
```

Run deterministic JSON report:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile deterministic --output docs\rpa\harness\reports\2026-05-28-f014-deterministic-profile.json
```

Run deterministic Markdown summary:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile deterministic --format summary --lang zh --output docs\rpa\harness\reports\2026-05-28-f014-deterministic-profile.md --machine-report docs\rpa\harness\reports\2026-05-28-f014-deterministic-profile.json
```

Run strict Harness knowledge validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

If strict validation still fails because of pre-existing metadata outside F014, record the exact attribution in EV-014 and keep readiness conditional.

## Task 6: Closeout

Update EV-014 with:

- RED/GREEN test output.
- Focused test output.
- deterministic profile JSON and Markdown output paths.
- Interpretation verdict from the real run.
- `knowledge_check.py --strict` result and attribution.
- Residual risks and reviewer status.
- Recommendation on whether Phase 3 Asset Lifecycle Operationalization can start.

Update F014 acceptance criteria and status only after verification evidence exists.
