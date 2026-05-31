# F016 RPA Harness v1 Phase 4 Plan: Asset-Driven User Input Replay

## Goal

实现 RPA Harness v1 Phase 4 第一切片：从生命周期允许的 Harness 资产中提取
可重放的用户输入事件，用脚本把这些事件送入明确的系统边界，并输出 JSON-first
报告和 Markdown summary。

## Architecture

保持“用户心智模型统一、代码边界清晰”：

- `catalog.py` 继续负责资产事实和生命周期摘要。
- 新增 `user_input_replay.py`，只负责 replay 资产选择、事件提取、边界注入记录、
  report/summary 渲染。
- 新增 `run_user_input_replay.py`，按现有 `run_*` CLI 风格提供稳定入口。
- 测试新增 `test_rpa_harness_user_input_replay.py`，不扩大现有 runner 责任。

Replay 第一切片是 deterministic/scripted mode。它不打开 live URL，不让外层 Agent
点击产品 UI，不调用 LLM 做主路径决策。它读取 checkpoint 和 trace event 事实，
为每个事件生成边界注入记录：

```text
scenario_asset
  -> user_input_event_chain
  -> scripted_user_input_replay_adapter
  -> boundary_injection_records
  -> trace/session/result identifiers
  -> JSON report + Markdown summary
```

## Design Decisions

1. **资产选择**

   - `candidate` 和 `golden`：作为 blocking replay baseline。
   - `candidate-lite`：作为 warning-only replay observation。
   - `draft` / `captured` / `rejected` / inactive assets：默认 excluded，并记录原因。

2. **事件模型**

   通用事件字段：

   ```text
   event_id
   asset_id
   step_index
   step_id
   event_kind
   source
   recording_mode
   user_instruction
   description
   action
   value
   target
   locator_candidates
   region_context
   before_page
   after_page
   injected_boundary
   trace_id
   session_id
   result_id
   output_key
   status
   failure_category
   error
   ```

   每个事件还应有 `injection` 摘要；顶层报告应有 `boundary_injections`，避免
   `injected_boundary` 退化为不可验证的字符串标签。

   `region_context` 来自 `target_evidence.region`、trace event 的 `region`、或
   `signals.region` 等通用事实位置；没有这些字段时为空。代码不为 region
   selection 建特殊 runner 分支。

3. **事件分类**

   - trace `action` 或 checkpoint `expected_action_type` 含 `click` -> `click`
   - 含 `fill` / `type` / `input` -> `type`
   - 含 `select` -> `select`
   - 含 `submit` / `press_enter` -> `submit`
   - trace `source=ai`、`trace_type=ai_operation`、或有 `user_instruction` -> `natural_language_instruction`
   - URL 变化且没有更具体 action -> `navigation`
   - 其它保留为 `unknown_input`

4. **失败日志**

   失败时不吞掉原始事实。报告必须保留：

   - asset id、scenario/checkpoint/trace path；
   - step intent、recording mode、before/after URL/title；
   - failure category；
   - exception type/message；
   - runtime result error；
   - selected/excluded lifecycle reasons。

5. **治理边界**

   报告明确写入：

   - Agent may explain report facts.
   - Agent must not auto-promote assets.
   - Humans govern candidate/golden promotion.
   - Candidate-lite warnings are non-blocking.

## Implementation Tasks

### Task 1: RED tests for lifecycle-aware replay selection

Files:

- Create/modify: `RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py`
- Planned production: `RpaClaw/backend/rpa/harness/user_input_replay.py`

Tests:

- `test_user_input_replay_selects_candidate_and_golden_as_blocking_baseline`
- `test_user_input_replay_keeps_candidate_lite_warning_only`
- `test_user_input_replay_excludes_draft_and_records_reasons`

Expected RED:

```text
ModuleNotFoundError: No module named 'backend.rpa.harness.user_input_replay'
```

### Task 2: Implement selection and asset_pool boundary

Files:

- Create: `RpaClaw/backend/rpa/harness/user_input_replay.py`

Minimal API:

```python
def run_user_input_replay(assets_root: str | Path, *, mode: str = "deterministic") -> dict[str, Any]:
    ...

def render_user_input_replay_summary(report: dict[str, Any], *, machine_report_path: str | Path | None = None, lang: str = "en") -> str:
    ...
```

Implementation:

- call `build_harness_catalog(..., include_catalog equivalent via catalog)` and
  `build_asset_lifecycle_summary(...)`;
- build `selection.blocking_baseline_assets`,
  `selection.warning_only_observation_assets`, and `selection.excluded_assets`;
- include `asset_pool` with lifecycle distribution, blocking baseline,
  warning-only, coverage boundary, and trust limits.

### Task 3: RED tests for event extraction and boundary injection

Tests:

- `test_user_input_replay_extracts_click_and_natural_language_events`
- `test_user_input_replay_preserves_region_context_as_generic_event_fact`
- `test_user_input_replay_report_includes_trace_session_result_ids_and_boundaries`

Expected RED:

```text
AssertionError: missing replayed_input_events / injected_boundary / ids
```

### Task 4: Implement deterministic event extraction

Files:

- Modify: `RpaClaw/backend/rpa/harness/user_input_replay.py`

Implementation:

- load scenario checkpoint refs in step order;
- load checkpoint and selected accepted trace event;
- infer event kind from trace/checkpoint facts;
- build stable `event_id`, `session_id`, and `result_id`;
- set `injected_boundary` to:
  - `scripted_navigation_boundary` for navigation;
  - `scripted_manual_input_boundary` for click/type/select/submit;
  - `scripted_natural_language_instruction_boundary` for natural-language instruction;
  - `scripted_recording_input_boundary` for generic/unknown input.

### Task 5: RED tests for failures and summary/CLI

Tests:

- `test_user_input_replay_failure_retains_checkpoint_and_trace_log_context`
- `test_user_input_replay_cli_writes_json_and_summary`

Expected RED:

```text
ModuleNotFoundError: No module named 'backend.rpa.harness.run_user_input_replay'
```

### Task 6: Implement CLI and Markdown summary

Files:

- Create: `RpaClaw/backend/rpa/harness/run_user_input_replay.py`
- Modify: `RpaClaw/backend/rpa/harness/user_input_replay.py`

CLI:

```powershell
python -m backend.rpa.harness.run_user_input_replay --assets <asset_root> --output <report.json>
python -m backend.rpa.harness.run_user_input_replay --assets <asset_root> --format summary --lang zh --output <summary.md> --machine-report <report.json>
```

Exit code:

- `0` when no blocking replay failures occur.
- `1` when blocking baseline replay has failures.
- warning-only candidate-lite failures do not set exit code `1`.

### Task 7: Verification and bootstrap Evidence

Commands:

```powershell
$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py

$env:PYTHONPATH='RpaClaw'
pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_user_input_replay.py RpaClaw/backend/tests/test_rpa_harness_catalog.py RpaClaw/backend/tests/test_rpa_harness_profile_runner.py

$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_user_input_replay --assets data\rpa_harness_assets_bootstrap --output docs\rpa\harness\reports\2026-05-28-f016-user-input-replay.json

$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_user_input_replay --assets data\rpa_harness_assets_bootstrap --format summary --lang zh --output docs\rpa\harness\reports\2026-05-28-f016-user-input-replay.md --machine-report docs\rpa\harness\reports\2026-05-28-f016-user-input-replay.json

python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

Update EV-016 with command output, report paths, residual risk, and Phase 5
readiness.
