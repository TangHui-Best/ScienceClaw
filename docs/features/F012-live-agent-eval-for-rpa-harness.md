---
doc_kind: feature
id: F012
title: Live Agent Eval For RPA Harness
status: completed
feature_ids: [F012]
created: 2026-05-22
updated: 2026-05-22
specs: []
plans: []
decisions:
  - docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md
evidence:
  - docs/evidence/EV-012-live-agent-eval-for-rpa-harness.md
---

# F012 Live Agent Eval For RPA Harness

## Goal

补齐 RPA Harness 的 live-agent 验证入口：在受控 HTML fixture 上真实启动 Playwright，调用 `RecordingRuntimeAgent.run()` 执行自然语言步骤，捕获成功的 AI trace，并把它沉淀为可被现有 Harness runner 消费的 `candidate-lite` 资产。

## Vision Anchor

用户要在内网使用 Harness 验证 RPA Agent 的核心能力：自然语言 SOP 步骤是否能被真实 Agent/Planner 转义成可沉淀、可编译、可回放的 Skill 资产。仅验证“已有 trace -> Skill -> replay”的离线链路不够，因为它不会触发 `RecordingRuntimeAgent`，也不会让 Planner/LLM 基于当前页面重新决策。

F012 的交付目标是提供一个最小但真实的入口：

- 真实调用 `RecordingRuntimeAgent.run()`。
- CLI 默认使用真实 Planner/LLM 配置，测试中才允许注入 fake planner。
- 使用受控 HTML fixture，避免依赖 live GitHub、内网页面状态或外部网络稳定性。
- 将 live-agent 结果捕获为 `candidate-lite`，再复用现有资产校验、snapshot、compiler、skill replay、stateful SOP 检查。
- 为后续 iframe frame context v2 修复提供可复现失败场景入口，而不是直接搬运历史分支补丁。

Exit Gate source: this Feature, [EV-012](../evidence/EV-012-live-agent-eval-for-rpa-harness.md), and [Live Agent Eval guide](../rpa/harness/live-agent-eval.md).

## User Problem

之前的 Harness 能证明已经沉淀的 trace 资产可以编译和回放，但不能证明 RPA Agent 在自然语言步骤下能否现场生成正确执行代码、产生 accepted trace，并进入 Skill 编译链路。

这会影响内网验证：如果不真实触发 Agent/Planner，Harness 只能验证编译器和回放器，无法定位 iframe、区域选择、动态页面等真实录制场景里到底是 snapshot、planner、trace capture、compiler 还是 replay 出了问题。

## Desired Outcome

- 内网可以用一条 CLI 运行 live-agent scenario。
- 成功场景生成 active `candidate-lite` Harness 资产。
- 报告明确记录 `planner_invocation_count`，避免“没有真实触发 LLM/Planner”的假阳性。
- 空 scenario 目录必须失败，避免内网误以为验证通过。
- 生成资产立刻经过 post-capture 检查，暴露 trace-to-skill 后续链路问题。
- 文档清楚说明边界：Live Agent Eval 是对 governed offline regression 的补充，不替代稳定离线回归。

## Current Status

Completed on branch `codex/rpa-harness-region-integration` in commit `bd74cc8` with a follow-up documentation closeout commit pending from this Feature/Evidence update.

The runner, CLI, focused tests, guide, and Backlog recovery context are implemented. Internal real-LLM validation remains the next operational step because this machine uses deterministic fake planner tests instead of the internal model configuration.

## Links

- Implementation: `RpaClaw/backend/rpa/harness/live_agent_eval.py`
- CLI: `RpaClaw/backend/rpa/harness/run_live_agent_eval.py`
- Tests: `RpaClaw/backend/tests/test_rpa_harness_live_agent_eval.py`
- Guide: [Live Agent Eval](../rpa/harness/live-agent-eval.md)
- Evidence: [EV-012 Live Agent Eval For RPA Harness Evidence](../evidence/EV-012-live-agent-eval-for-rpa-harness.md)
- Backlog: [Backlog](../BACKLOG.md)

### Evidence

- Historical links remain in the original record; this migration adds the current navigation category.

### Decisions / ADRs

- Historical links remain in the original record; this migration adds the current navigation category.

### Lessons

- Historical links remain in the original record; this migration adds the current navigation category.

### Specs / Plans

- Historical links remain in the original record; this migration adds the current navigation category.

### Related Features

- Historical links remain in the original record; this migration adds the current navigation category.

### External Context

- Historical links remain in the original record; this migration adds the current navigation category.

## Non-goals

- 不访问 live GitHub 或内网页面作为 oracle。
- 不替代 governed offline regression。
- 不把 live 生成结果直接升为 `candidate` 或 `golden`。
- 不一次性修复 iframe bug；iframe 修复应先用 live-agent iframe fixture 建立可复现失败。
- 不重新规划整套 SOP；F012 验证单个自然语言步骤能否转成可沉淀 trace。

## Acceptance Criteria

- [x] `run_live_agent_eval` 能启动 Playwright 并调用 `RecordingRuntimeAgent.run()`。
- [x] 测试可注入 fake planner，CLI 默认不注入 fake planner。
- [x] 成功 trace 会被捕获为 active `candidate-lite` Harness 资产。
- [x] 生成资产会立即运行 asset validation、snapshot regression、compiler regression、skill replay、stateful SOP capture-to-skill。
- [x] 报告包含 scenario status、asset id、output、failure category、`planner_invocation_count` 和 post-capture 检查摘要。
- [x] 空 scenario 目录返回失败，避免误报通过。
- [x] 文档说明内网运行命令、scenario 格式、资产状态和 iframe 后续接入方式。
- [x] Backlog 记录内网真实 LLM 验证和 iframe v2 后续动作。

## Patch History

None.

## Evidence

See [EV-012 Live Agent Eval For RPA Harness Evidence](../evidence/EV-012-live-agent-eval-for-rpa-harness.md).

## Next Step

在内网创建受控 live-agent scenarios，并使用真实模型配置运行 `python -m backend.rpa.harness.run_live_agent_eval`。iframe 修复开始前，先新增 iframe fixture，使 v2 修复围绕可复现失败推进。

## Feature Intake

- Original problem: The original problem is preserved in `## Goal` and `## Vision Anchor`; this migration does not reinterpret it.
- User pain point: The historical user pain point is preserved in the original Feature narrative and linked Evidence.
- Capability promise: The delivered or intended capability remains the one described in `## Goal` and `## Acceptance Criteria`.
- Non-goals: This migration adds no business scope and does not change the historical Feature boundary.
- Acceptance source: Existing acceptance criteria, linked Evidence, and recorded validation remain the source of truth.
- Open questions: Any historical uncertainty remains unresolved unless the original record or a linked successor answers it.

## Capability Contract

The capability boundary is the historical `## Goal`, `## Vision Anchor`, acceptance criteria, and linked artifacts. This schema migration does not add, remove, or reinterpret RPA behavior.

## Decision Context

### Why

The original Feature and its linked decisions preserve the rationale; this migration only makes that context recoverable through the current template.

### Why Not

Do not infer new product decisions from a document-schema migration or replace historical validation with template text.

### If Modifying This Area, Check

Read this Feature's Goal, Evidence, and linked ADRs before changing its capability boundary or claiming a new verification result.

## Acceptance Map

| Claim | Acceptance | Evidence | Status |
| --- | --- | --- | --- |
| Historical Feature contract | Existing `## Acceptance Criteria` and historical Feature record | Historical evidence documented in `## Evidence` | migrated |

## State Timeline

| Date | State | Trigger | Evidence | Note |
| --- | --- | --- | --- | --- |
| 2026-07-25 | completed | AgentMentor schema migration | Existing Feature/Evidence | Historical facts retained; current required structure added |

## Recovery Snapshot

- Read first: `## Goal`, `## Links`, `## Acceptance Criteria`, and `## Evidence`.
- Current capability state: Use the existing `## Current Status`; this migration does not change delivery status.
- Known risks: Historical verification is limited to what the original record explicitly states.
- Next safe action: Read the linked Evidence and ADRs before any follow-up change; update this Feature when the capability boundary or verified state changes.
- Unblock condition: Not blocked by this migration.
