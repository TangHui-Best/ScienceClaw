---
id: EV-024
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F024-rpa-core-harness-boundary-guard.md
created: 2026-06-02
updated: 2026-06-02
evidence_level: exhaustive
---

# EV-024: RPA Core Harness Boundary Guard

## Scope

验证本次修复是否把“点击触发下载”归还给 RPA Core 录制事实，而不是由 Harness expected signals、controlled fixture 或前端显示补丁定义事实。范围包括：

- `RecordingRuntimeAgent` simple `click` plan 捕获 download event。
- route trace finalization 在 append accepted trace 前归并 paused pending download，避免 Full SOP Harness capture 改变 SOP->SKILL 主链路事实。
- timeline 投影只展示 trace 已有 `signals.download`。
- 既有 run_python download 捕获和 compiler download 语义保持。
- Harness controlled download 回放仍作为验证层，不反向定义产品录制事实。

## Commands

RED / GREEN focused tests:

```powershell
$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_records_download_signal_from_simple_click_plan RpaClaw/backend/tests/test_rpa_trace_timeline.py::test_trace_timeline_projects_download_signal_in_summary -q
```

F024.1 RED / GREEN focused tests:

```powershell
$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/test_rpa_route_trace.py::test_apply_recording_agent_result_waits_for_paused_download_before_append -q
```

```powershell
$env:PYTHONPATH='RpaClaw'; python -m pytest --basetemp .pytest-tmp-f024-delayed-download RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py::test_full_sop_capture_preserves_delayed_download_signal_in_core_trace -q
```

Focused regression commands to run before closeout:

```powershell
$env:PYTHONPATH='RpaClaw'; python -m pytest --basetemp .pytest-tmp-f024-core RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_records_download_signal_from_ai_code RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_waits_briefly_for_click_triggered_download RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py::test_recording_runtime_agent_records_download_signal_from_simple_click_plan RpaClaw/backend/tests/test_rpa_route_trace.py::test_apply_recording_agent_result_waits_for_paused_download_before_append -q
```

```powershell
$env:PYTHONPATH='RpaClaw'; python -m pytest --basetemp .pytest-tmp-f024-compiler RpaClaw/backend/tests/test_rpa_trace_timeline.py::test_trace_timeline_projects_download_signal_in_summary RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_ai_operation_with_download_signal_compiles_to_expect_download RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_standalone_download_trace_after_ai_operation_merges_into_trigger -q
```

```powershell
$env:PYTHONPATH='RpaClaw'; python -m pytest --basetemp .pytest-tmp-f024-harness RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py::test_full_sop_capture_preserves_delayed_download_signal_in_core_trace RpaClaw/backend/tests/test_rpa_harness_skill_replay.py::test_skill_replay_serves_controlled_download_and_validates_saved_file RpaClaw/backend/tests/test_rpa_harness_live_agent_eval.py::test_live_agent_eval_controlled_download_is_captured_as_trace_signal -q
```

F024.2 live RecorderPage download projection regression:

```powershell
npm.cmd run test -- RecorderPage.test.ts -t "projects download signals"
```

```powershell
npm.cmd run test -- RecorderPage.test.ts
```

```powershell
npm.cmd run type-check
```

Harness structure:

```powershell
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

## Results

- RED focused tests: `2 failed`。`simple click` 缺少 `trace.signals.download`，timeline summary 未展示 download signal。
- RED replay-code guard: `1 failed`。simple `click` trace 捕获 download 后仍缺少可回放 `async def run(page, results)`，会威胁 SOP->SKILL 编译链路。
- F024.1 RED route finalization: `1 failed`。paused pending download 晚于 `_apply_recording_agent_result()` append 时，当前 AI trace 缺少 `signals.download`。
- F024.1 GREEN route finalization: `1 passed`。
- F024.1 Full SOP capture regression: first run failed before业务断言 because Windows default pytest temp root `C:\Users\HUAWEI\AppData\Local\Temp\pytest-of-HUAWEI` was not accessible; rerun with workspace `--basetemp` passed, final rerun: `1 passed`。
- GREEN focused tests: simple click download capture 和 replay-code guard passed。
- Core recording download focused regression: `4 passed in 1.62s`。
- Timeline + compiler download focused regression: `3 passed in 0.92s`。
- Harness controlled download focused regression: first run failed before业务断言 because Windows default pytest temp root `C:\Users\HUAWEI\AppData\Local\Temp\pytest-of-HUAWEI` was not accessible; rerun with workspace `--basetemp` passed, final rerun: `2 passed in 13.40s`。
- F024.1 Harness focused regression: `3 passed in 12.83s`。
- Changed core test files: `99 passed, 30 warnings in 5.28s`。Warnings are existing Python 3.14 / FastAPI deprecation warnings, not F024 behavior failures.
- F024.2 RED live RecorderPage projection test: failed as expected because the SSE `trace_added` raw trace contained `signals.download.filename=export.xlsx`, but the left timeline text did not include `export.xlsx`。
- F024.2 GREEN focused live RecorderPage projection: `1 passed`。The live trace display now shows the click title plus the existing download signal filename.
- F024.2 RecorderPage regression: `27 passed`。
- F024.2 Core recording download focused regression: `4 passed, 29 warnings`。Warnings are existing Python 3.14 / FastAPI deprecation warnings, not F024.2 behavior failures.
- F024.2 Timeline + compiler download focused regression: `3 passed`。
- F024.2 Harness controlled download focused regression: `3 passed, 29 warnings`。Warnings are existing Python 3.14 / FastAPI deprecation warnings.
- F024.2 frontend type-check: failed on pre-existing unrelated TypeScript errors in `ActivityPanel.vue`, `ChatMessage.vue`, `DesktopTitleBar.vue`, `SessionItem.vue`, `ChatPage.vue`, `desktopWindow.ts`, and related files; no reported error referenced `RecorderPage.vue` or `RecorderPage.test.ts`.

## Harness Validation

`knowledge_check.py --strict`: `Scanned 260 markdown file(s). Checked 54 knowledge artifact(s). Errors: 0. Warnings: 0.`

## Artifacts

- Feature: `docs/features/F024-rpa-core-harness-boundary-guard.md`
- ADR: `docs/decisions/ADR-004-rpa-core-owns-recording-facts-harness-adapts-only.md`
- Lesson: `docs/lessons/LL-002-harness-must-not-define-rpa-core-facts.md`
- Code: `RpaClaw/backend/rpa/recording_runtime_agent.py`
- Code: `RpaClaw/backend/rpa/manager.py`
- Code: `RpaClaw/backend/route/rpa.py`
- Code: `RpaClaw/backend/rpa/trace_timeline.py`
- Code: `RpaClaw/frontend/src/pages/rpa/RecorderPage.vue`
- Tests: `RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py`
- Tests: `RpaClaw/backend/tests/test_rpa_route_trace.py`
- Tests: `RpaClaw/backend/tests/test_rpa_harness_ai_capture_integration.py`
- Tests: `RpaClaw/backend/tests/test_rpa_trace_timeline.py`
- Tests: `RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts`
- Project rule: `AGENTS.md`

## Notes

本次修复明确拒绝三类路径：不从 Harness expected signals 合成产品 trace，不恢复 legacy step 作为事实源，不为单一站点或文件列表补关键词规则。Core 负责捕获真实浏览器下载事件；Harness 负责验证和治理。
