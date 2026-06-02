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

## Fix

在 `RecordingRuntimeAgent` 中引入 Core download event capture 边界，让 simple `click` 与 `run_python` 共享同一种 `signals.download` 结构；timeline 只投影 trace 已有 download signal。

## Protection

- Regression tests:
  - `test_recording_runtime_agent_records_download_signal_from_simple_click_plan`
  - `test_trace_timeline_projects_download_signal_in_summary`
- Decision: `docs/decisions/ADR-004-rpa-core-owns-recording-facts-harness-adapts-only.md`
- Project rule: `AGENTS.md` 中 Core/Harness boundary 规则要求触碰 Core 文件时跑 Core SOP->SKILL 回归。

## Source

来自 F024 边界修复和用户明确要求：“Harness 功能不能影响原有的 SOP 转义 SKILL 核心链路，务必不能再犯同样的错误”。

## Principle

Harness 暴露问题，但不能拥有主链路语义；主链路先正确记录事实，Harness 再做资产治理和验证。
