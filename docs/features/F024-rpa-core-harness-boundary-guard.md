---
id: F024
doc_kind: feature
status: active
created: 2026-06-02
updated: 2026-06-02
---

# F024: RPA Core / Harness Boundary Guard

## Goal

修复并约束 Harness 功能影响 RPA 主链路的问题。RPA 主链路是 `SOP / 自然语言录制 -> accepted trace -> TraceSkillCompiler -> SKILL.md / skill.py`；Harness 只能观察、复制、验证这些事实，不能反向定义或改写主链路事实。

## Vision Anchor

- 原始请求或来源：用户发现“点击列表中第一行的文件名称”会真实触发下载，但录制左侧步骤不再捕获下载事件，并明确要求 Harness 功能不能影响原有 SOP 转义 SKILL 核心链路。
- 用户痛点或工程问题：Harness controlled download / full-live 验证能力与产品录制 Core 共享 `RecordingRuntimeAgent`，边界不清时会让 Harness 验证诉求反向污染主链路。
- 期望结果：下载事件由 Core 录制边界捕获为 `trace.signals.download`；Harness 只验证该事实。Harness 变更若触碰 Core 文件，必须跑 Core SOP->SKILL 回归。
- 非目标或边界：不 fork 两套 RecordingRuntimeAgent / TraceSkillCompiler；不把 Harness expected signals 注入产品录制 trace；不新增站点特例或 legacy step fallback。
- Exit Gate 对照来源：本 Feature、ADR-004、EV-024、AGENTS.md 的 Core/Harness 边界规则。

## Current Status

Done。已修复 simple click plan 缺少 download signal 捕获的问题；已建立 timeline 投影测试、Core/Harness 边界 ADR、Lesson 和项目级规则。Focused Core/Harness 回归与 Harness knowledge check 已通过。

## Links

- ADR: [ADR-004 RPA Core Owns Recording Facts, Harness Adapts Only](../decisions/ADR-004-rpa-core-owns-recording-facts-harness-adapts-only.md)
- Evidence: [EV-024 RPA Core Harness Boundary Guard Evidence](../evidence/EV-024-rpa-core-harness-boundary-guard.md)
- Lesson: [LL-002 Harness Must Not Define RPA Core Facts](../lessons/LL-002-harness-must-not-define-rpa-core-facts.md)
- Related Feature: [F019 RPA Harness Controlled Download Side Effects](F019-rpa-harness-controlled-download-side-effects.md)
- Existing ADR: [ADR-001 RPA Trace Is The Single Accepted Timeline](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md)
- Existing ADR: [ADR-002 Trace Evidence Drives Compiler Strategy](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md)

## Acceptance Criteria

- [x] `RecordingRuntimeAgent` 的 simple `click` plan 能捕获真实 Playwright download event，并写入当前 accepted trace 的 `signals.download`。
- [x] `run_python` 与 simple `click` 使用同一种 Core download capture 结果结构。
- [x] timeline 投影只读取 trace 上已有 `signals.download`，不读取 Harness expected signals 或 controlled fixture。
- [x] 编译器仍只消费 accepted trace；Harness controlled download 仍是 replay/asset 验证能力，不定义产品录制事实。
- [x] AGENTS.md 增加可验证规则：Harness/RPA 变更触碰 Core 文件时必须跑 Core SOP->SKILL 回归。
- [x] 完整 focused Core/Harness 回归命令完成并记录在 EV-024。

## Patch History

None yet.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

见 [EV-024 RPA Core Harness Boundary Guard Evidence](../evidence/EV-024-rpa-core-harness-boundary-guard.md)。

## Next Step

进入人工 review。后续任何 Harness/RPA 变更若触碰 Core 文件，必须按 ADR-004 和 AGENTS.md 规则同时运行 Core SOP->SKILL focused regression。
