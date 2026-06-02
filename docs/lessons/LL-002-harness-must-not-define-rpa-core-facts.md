---
id: LL-002
doc_kind: lesson
status: active
scope: project
feature_refs:
  - docs/features/F024-rpa-core-harness-boundary-guard.md
applies_to:
  - rpa-core
  - rpa-harness
  - trace-first-recording
created: 2026-06-02
updated: 2026-06-02
---

# LL-002: Harness Must Not Define RPA Core Facts

## Pitfall

Harness 为了让受控资产、full-live 或 replay 报告闭环，容易把 expected signals、controlled fixture 或报告字段当成产品录制事实，进而影响 SOP->SKILL 主链路。

## Root Cause

Harness 和产品录制共享 `RecordingRuntimeAgent`、accepted trace、`TraceSkillCompiler`。缺少明确规则时，验证层的需求会反向推动 Core 行为，而不是先让 Core 正确记录事实、再由 Harness 验证事实。

## Trigger

自然语言指令“点击列表中第一行的文件名称”真实触发下载，但 simple `click` plan 没有 Core download listener；AI 执行期间普通录制被暂停，manager 侧 pending download 合并存在竞态，导致 accepted trace 缺少 `signals.download`，左侧 timeline 也只显示点击。

F024.1 复现了同一边界的第二种形态：不开 Full SOP Harness capture 时，晚到的 download 可能靠 standalone download fallback 被编译器合并；开启 Full SOP capture 后，checkpoint after-state 抓取延长了 paused 窗口，download event 进入 `pending_download_events` 的时间晚于 `append_trace()`，从而错过当前 AI trace 的合并点。

## Fix

在 `RecordingRuntimeAgent` 中引入 Core download event capture 边界，让 simple `click` 与 `run_python` 共享同一种 `signals.download` 结构；timeline 只投影 trace 已有 download signal。

F024.1 在 route/manager 的 Core trace finalization 阶段补上 bounded pending-download settle：自然语言录制结果必须先把 paused pending download 归并到当前 AI trace，再 append accepted trace、写 runtime result 和进入 Harness checkpoint capture。

## Protection

- Regression tests:
  - `test_recording_runtime_agent_records_download_signal_from_simple_click_plan`
  - `test_trace_timeline_projects_download_signal_in_summary`
  - `test_apply_recording_agent_result_waits_for_paused_download_before_append`
  - `test_full_sop_capture_preserves_delayed_download_signal_in_core_trace`
- Decision: `docs/decisions/ADR-004-rpa-core-owns-recording-facts-harness-adapts-only.md`
- Project rule: `AGENTS.md` 中 Core/Harness boundary 规则要求触碰 Core 文件时跑 Core SOP->SKILL 回归。

## Source

来自 F024 边界修复和用户明确要求：“Harness 功能不能影响原有的 SOP 转义 SKILL 核心链路，务必不能再犯同样的错误”。

## Principle

Harness 暴露问题，但不能拥有主链路语义；主链路先正确记录事实，Harness 再做资产治理和验证。
