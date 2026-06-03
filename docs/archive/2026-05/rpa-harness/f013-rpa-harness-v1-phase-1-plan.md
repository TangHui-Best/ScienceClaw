# F013 RPA Harness v1 Phase 1 Implementation Plan

## Goal

实现 RPA Harness v1 Phase 1 的最小 deterministic profile：用一个统一脚本/CLI 入口运行现有 governed assets 的确定性链路，输出机器 JSON 和可读报告，让它成为 RPA core-chain 变更的默认 pre-submit evidence path。

## Architecture

Phase 1 只做收束，不重写 runner。新增的 profile 层应薄封装 `run_governed_offline_regression()`，保留 F003-F010 的治理、筛选、runner、candidate-lite observation 和 observability contract。

核心边界继续保持：

```text
Scripts execute. Agents explain. Humans govern.
```

deterministic profile 不调用真实 Planner/LLM，不打开 live URL，不让外层 Agent 点击 RPA 产品 UI。它消费 governed assets 和 controlled inputs，生成可比较 evidence。Agent 的工作从报告输出之后开始：读取 JSON/Markdown，解释影响和残余风险。

## Source Documents

- `docs/features/F013-rpa-harness-v1-asset-driven-user-input-replay.md`
- `docs/evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md`
- `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`
- `docs/rpa/harness/rpa-harness-v0-design.md`
- `docs/rpa/harness/golden-evaluation-vision.md`
- `docs/rpa/harness/usage-and-triage-guide.md`
- `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`
- `docs/features/F003-golden-scenario-asset-model.md` through `docs/features/F010-assisted-asset-review-and-promotion-pipeline.md`

## Planned Files

- Create `RpaClaw/backend/rpa/harness/profile_runner.py`
  - Owns profile-level orchestration.
  - Supports `deterministic` only in Phase 1.
  - Adds profile metadata and summary fields around the existing governed regression report.
- Create `RpaClaw/backend/rpa/harness/run_harness_profile.py`
  - CLI entrypoint for `--profile deterministic`.
  - Supports JSON output and human summary output.
  - Does not add CI behavior.
- Modify `RpaClaw/backend/rpa/harness/observability.py`
  - Add a narrow renderer or helper only if existing summary rendering cannot expose profile metadata clearly.
- Modify `RpaClaw/backend/rpa/harness/run_governed_regression.py`
  - Preserve compatibility.
  - Optionally delegate internally to deterministic profile only if output schema compatibility remains intact; otherwise leave unchanged and document it as the lower-level governed runner.
- Create or modify `RpaClaw/backend/tests/test_rpa_harness_profile_runner.py`
  - Covers profile metadata, deterministic-only scope, JSON shape, summary rendering, and compatibility boundaries.
- Modify `docs/rpa/harness/usage-and-triage-guide.md`
  - Add the deterministic profile command and interpretation guidance.
  - Do not perform broad encoding/frontmatter cleanup.
- Update `docs/evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md`
  - Record RED/GREEN tests, runner command output, knowledge check attribution, residual risk, and closeout.

## Task 1: RED Test For Deterministic Profile Contract

Add tests before implementation in `RpaClaw/backend/tests/test_rpa_harness_profile_runner.py`.

Assertions:

- `run_harness_profile(tmp_path, profile="deterministic")` returns `schema_version="rpa-harness-profile-run-v1"`.
- `report["profile"]` includes:
  - `name="deterministic"`
  - `execution_mode="scripted-assets"`
  - `uses_live_planner=False`
  - `uses_live_url_oracle=False`
  - `governance_mode="human-governed-assets"`
- `report["deterministic"]` contains the existing governed regression report.
- `report["summary"]` preserves status and first failing category from the governed report.
- Unsupported profiles such as `full` fail with a clear error instead of silently running.

Expected RED command:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_profile_runner.py
```

Expected RED result:

```text
ModuleNotFoundError or ImportError for backend.rpa.harness.profile_runner
```

## Task 2: Minimal Profile Runner

Implement `profile_runner.py` with a small public surface:

```python
def run_harness_profile(
    assets_root: str | Path,
    *,
    profile: str = "deterministic",
) -> dict[str, Any]:
    ...
```

Rules:

- Accept only `deterministic` in Phase 1.
- Call `run_governed_offline_regression(assets_root)`.
- Wrap, do not duplicate, existing governed report data.
- Preserve selected/excluded assets, candidate-lite observation, runner summaries, and observability details from the governed report.
- Add profile metadata and report-level interpretation fields derived from existing facts:
  - status
  - blocking
  - first_failure_category
  - selected_asset_count
  - excluded_asset_count
  - warning_only_observation_count

Run the RED test again and make it pass.

## Task 3: CLI Entrypoint

Add `run_harness_profile.py`.

CLI behavior:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile deterministic --output tmp-harness-profile-deterministic.json
```

Options:

- `--assets` required.
- `--profile deterministic` default.
- `--output` optional JSON/summary destination.
- `--format json|summary` default `json`.
- `--lang en|zh` default `en` for summary.

Exit code:

- `0` when profile summary status is `passed`.
- `1` when profile summary status is `failed`.

Do not add full/live profile options beyond explicit rejection.

## Task 4: Human Summary Shape

Add the smallest summary path needed for humans and Agents to understand the profile run.

The summary must state:

- profile name;
- status;
- selected asset ids;
- excluded asset count;
- first failing runner/category if any;
- candidate-lite warning-only observation status/count;
- where to inspect the machine JSON.

Prefer reusing existing `render_human_summary()` / `render_chinese_summary()` output and adding a short profile header. Do not replace the governed summary renderer unless the existing API makes that impossible.

## Task 5: Backward Compatibility

Keep `run_governed_regression` behavior stable.

Compatibility checks:

- Existing tests in `RpaClaw/backend/tests/test_rpa_harness_governed_regression.py` still pass.
- Existing command still returns the governed report schema:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_bootstrap --output tmp-harness-governed-f013-compat.json
```

If code reuse would force a schema change, reject that path and keep the new profile entrypoint as a wrapper.

## Task 6: Usage Guide Update

Update `docs/rpa/harness/usage-and-triage-guide.md` only in the relevant execution section.

Add:

- deterministic profile as the preferred pre-submit command;
- governed regression as the lower-level existing runner;
- JSON-first analysis guidance for Agents;
- explicit warning that full/live profile and CI blocking are out of Phase 1.

Do not broad-fix legacy encoding/frontmatter or unrelated wording.

## Task 7: Verification

Run focused tests:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_profile_runner.py RpaClaw/backend/tests/test_rpa_harness_governed_regression.py
```

Run focused runner:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile deterministic --output tmp-harness-profile-deterministic-f013.json
```

Run summary:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile deterministic --format summary --lang zh --output docs\rpa\harness\reports\2026-05-28-f013-deterministic-profile.md --machine-report docs\rpa\harness\reports\2026-05-28-f013-deterministic-profile.json
```

Attempt Harness knowledge check:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

If knowledge check fails because of existing old document structure, record the exact failure category in EV-013 and do not perform broad cleanup in this feature.

## Task 8: Evidence And Closeout

Update `docs/evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md` with:

- Start Gate, Knowledge Retrieval, Vision Gate summary.
- RED/GREEN test output.
- Real bootstrap deterministic profile command and result.
- Generated JSON and Markdown report paths.
- Knowledge check result or pre-existing failure attribution.
- Residual risks:
  - bootstrap coverage is still narrow;
  - deterministic profile is process-required but not CI-enforced;
  - full/live remains a separate validation profile;
  - independent review status.
- Exit recommendation for Phase 2.

Only mark F013 completed after the evidence records successful verification or a clear blocker.
