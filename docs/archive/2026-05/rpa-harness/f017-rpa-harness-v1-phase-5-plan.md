# F017 RPA Harness v1 Phase 5 Plan: Full/Live Profile Integration

## Goal

实现 RPA Harness v1 最后一段核心能力：`full-live` profile。它在受控 fixture
或 captured page state 上，基于受管资产中的 natural-language input event，真实触发
`RecordingRuntimeAgent.run()` / Planner / LLM，生成新的 accepted trace，再进入
compiler / skill replay / stateful checks，并输出 v1 风格 JSON-first report 和
Markdown summary。

判断标准不是“多一个 live 命令”，而是统一这三条能力：

```text
deterministic profile: stable default regression
user-input replay: scripted input-boundary evidence
full-live profile: high-fidelity controlled RecordingRuntimeAgent validation
```

## Architecture

保持模块边界清晰：

- `user_input_replay.py` 继续负责从受管资产提取用户输入事件事实。
- `live_agent_eval.py` 继续负责 controlled HTML + Playwright +
  `RecordingRuntimeAgent.run()` + candidate-lite asset + post-capture checks 的执行底座。
- 新增 `full_live_profile.py`，负责把 F016 的 natural-language events 转换为
  F012-compatible scenarios，调用 live execution bottom，并包装为 v1 profile report。
- `profile_runner.py` 只做 profile dispatch、公共 summary/interpretation 渲染。
- `run_harness_profile.py` 扩展 `--profile full-live` 和 `--generated-assets`，不改变
  deterministic 默认行为。

第一切片只支持：

```text
source governed asset
  -> selected natural_language_instruction event
  -> controlled fixture from checkpoint before.html
  -> RecordingRuntimeAgent.run(page, instruction, region_context)
  -> generated candidate-lite/profile artifact in generated-assets root
  -> post-capture checks
  -> full-live profile report
```

## Report Contract

`full-live` profile report must include at least:

- `schema_version`
- `kind`
- `profile.name = full-live`
- `profile.execution_mode`
- `profile.uses_live_planner = true`
- `profile.uses_live_url_oracle = false`
- `profile.uses_outer_agent_ui_control = false`
- source asset ids
- selected input events
- controlled fixture metadata
- planner invocation count
- generated trace ids
- generated asset ids
- post-capture validation / snapshot / compiler / skill replay / stateful SOP summary
- failures and failure categories
- trust limits
- governance boundary: `Scripts execute; Agents explain; Humans govern`
- `agents_may_promote_automatically=false`

## Design Decisions

1. **Reuse F012, do not create a parallel live runner**

   `full_live_profile.py` may add a thin adapter around `run_live_agent_eval`, but the
   browser execution and candidate-lite generation should remain in `live_agent_eval.py`.
   If F012 needs a light extension for region context or in-memory scenarios, keep it
   additive and tested.

2. **Use F016 event extraction**

   The first slice should call `run_user_input_replay` or shared helpers to obtain
   natural-language events. Do not duplicate checkpoint parsing unless a narrow helper
   extraction is required.

3. **Controlled fixture source**

   For each selected event, load checkpoint `before.html` and use it as the controlled
   page. URL and title come from checkpoint `before` facts. No live URL is visited as an
   oracle.

4. **Generated asset isolation**

   Full-live generated assets write to explicit `generated_assets_root`. CLI users pass
   `--generated-assets`; tests may use a temp directory. If the Python API receives no
   generated root, it creates a temp profile artifact directory, never source asset root.

5. **Candidate-lite/profile artifact only**

   Generated assets may be active `candidate-lite` or profile artifacts. They must not
   automatically become `candidate` or `golden`, and candidate-lite remains warning-only.

6. **Region context is generic**

   If the selected event has `region_context`, pass it to `RecordingRuntimeAgent.run()` as
   generic `region_context`. Do not add a region-specific runner branch.

7. **No eligible input is insufficient evidence**

   If no natural-language input event is eligible, report failed/insufficient evidence and
   exit non-zero in CLI. Do not report a passed empty full-live run.

## Implementation Tasks

### Task 1: RED tests for full-live report contract and planner invocation

Files:

- Create: `RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py`
- Planned production: `RpaClaw/backend/rpa/harness/full_live_profile.py`

Tests:

- `test_full_live_profile_invokes_planner_and_returns_v1_report`
- `test_full_live_profile_report_declares_live_planner_without_live_oracle`
- `test_full_live_profile_writes_generated_assets_outside_source_root`

Expected RED:

```text
ModuleNotFoundError: No module named 'backend.rpa.harness.full_live_profile'
```

### Task 2: Implement minimal `full_live_profile.py`

Minimal API:

```python
async def run_full_live_profile(
    assets_root: str | Path,
    *,
    generated_assets_root: str | Path | None = None,
    planner: Planner | None = None,
    model_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ...

def render_full_live_profile_summary(
    report: dict[str, Any],
    *,
    machine_report_path: str | Path | None = None,
    lang: str = "en",
) -> str:
    ...
```

Implementation:

- run/extract user-input events;
- filter `event_kind == natural_language_instruction` and blocking/warning-eligible source assets;
- build F012-compatible controlled scenarios using checkpoint `before.html`;
- call live execution bottom with fake planner only when caller injects one;
- wrap live eval results into full-live profile report.

### Task 3: RED tests for no-input failure and generated governance

Tests:

- `test_full_live_profile_without_natural_language_input_is_insufficient_evidence`
- `test_full_live_generated_assets_remain_candidate_lite`
- `test_candidate_lite_full_live_output_is_warning_only_not_blocking`

Expected RED:

```text
AssertionError: empty full-live run incorrectly passed
```

### Task 4: Implement governance and failure summary

Implementation:

- `summary.status=failed` with `failure_category=no-full-live-input-events` when no
  eligible natural-language events exist.
- report source asset ids, selected input events, generated asset ids, trace ids,
  planner count, and post-capture summaries.
- preserve `agents_may_promote_automatically=false`.

### Task 5: RED tests for profile_runner dispatch and CLI

Tests:

- add to `test_rpa_harness_profile_runner.py` or full-live test file:
  - `test_run_harness_profile_dispatches_full_live`
  - `test_run_harness_profile_cli_writes_full_live_json`
  - deterministic profile tests remain unchanged.

Expected RED:

```text
ValueError: Unsupported RPA Harness profile: full-live
```

### Task 6: Implement profile dispatch and summary

Files:

- Modify: `RpaClaw/backend/rpa/harness/profile_runner.py`
- Modify: `RpaClaw/backend/rpa/harness/run_harness_profile.py`

Implementation:

- add `full-live` dispatch without changing deterministic default;
- add `--generated-assets`;
- call async full-live profile through a sync wrapper or `asyncio.run` in CLI/API wrapper;
- route summary rendering based on `profile.name`.

### Task 7: Region context generic pass-through

Tests:

- `test_full_live_profile_passes_region_context_as_generic_context`

Implementation:

- include event `region_context` in scenario metadata;
- pass it to `RecordingRuntimeAgent.run()` through the live execution bottom;
- assert fake planner payload contains planner region context effects where appropriate,
  or assert injected wrapper receives the exact generic context.

### Task 8: Verification and Evidence

Run:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current `
  RpaClaw/backend/tests/test_rpa_harness_full_live_profile.py `
  RpaClaw/backend/tests/test_rpa_harness_profile_runner.py `
  RpaClaw/backend/tests/test_rpa_harness_live_agent_eval.py `
  RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py
```

Generate JSON report:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile `
  --assets data\rpa_harness_assets_bootstrap `
  --profile full-live `
  --generated-assets docs\rpa\harness\reports\f017-generated-assets `
  --output docs\rpa\harness\reports\2026-05-28-f017-full-live-profile.json
```

Generate Markdown summary:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile `
  --assets data\rpa_harness_assets_bootstrap `
  --profile full-live `
  --generated-assets docs\rpa\harness\reports\f017-generated-assets `
  --format summary `
  --lang zh `
  --output docs\rpa\harness\reports\2026-05-28-f017-full-live-profile.md `
  --machine-report docs\rpa\harness\reports\2026-05-28-f017-full-live-profile.json
```

Run strict Harness validation:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

Update EV-017 with:

- actual commands;
- test results;
- full-live report path;
- generated asset root;
- residual risks;
- reviewer status;
- whether a v1 closeout/stabilization slice is needed.
