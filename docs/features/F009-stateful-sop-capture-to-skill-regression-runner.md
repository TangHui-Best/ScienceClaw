---
id: F009
doc_kind: feature
status: completed
created: 2026-05-19
updated: 2026-05-19
---

# F009: Stateful SOP Capture-to-Skill Regression Runner

## Goal

实现 Stateful SOP Capture-to-Skill Regression Runner，用受管 Full SOP 场景资产模拟真实人工 SOP 录制输入边界，让 Harness 路径仍经过 recording/session state、accepted trace generation、trace normalization、`TraceSkillCompiler`、generated Skill，以及可选 controlled Skill replay。

## Vision Anchor

- Original request: F002-F008 已完成后，开启 F009，补齐 Harness v1 最后一块基础闭环。
- User pain point: F008 已能验证已生成 Skill 的受控 replay，但仍从已存在 trace/Skill replay 层开始，不能证明历史 Full SOP 资产能驱动与人工录制等效的内部 recording-to-Skill 链路。
- Desired outcome: 一个受管 Full SOP 资产可以作为 stateful scenario provider 逐步驱动录制会话边界，产出新的 accepted trace evidence，再进入 trace normalization、Skill 编译和可选受控 replay；报告能判断该链路是否保持内部等效。
- Non-goals:
  - 不扩充 candidate/golden 资产集；后续由用户手动录制与治理。
  - 不恢复 direct Agent chat 作为 golden runner。
  - 不依赖 live GitHub 或 live URL 作为 oracle。
  - 不实现嵌套 Agent 去点击 RPA 产品 UI。
  - 不把 planner、compiler、extraction bug 修在 Harness 内。
  - 不用 Harness 特定规则替代 RPA Agent 核心链路。
- Exit Gate source: this Feature, [EV-009](../evidence/EV-009-stateful-sop-capture-to-skill-regression-runner.md), [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md), [ADR-003](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md), [F008](F008-skill-replay-e2e-runner.md), and [EV-008](../evidence/EV-008-skill-replay-e2e-runner.md).

## Current Status

Completed. Governed regression now includes Stateful SOP Capture-to-Skill as an independent runner signal over the bootstrap Full SOP candidate asset.

## Links

- Vision: [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Previous Feature: [F008 Skill Replay E2E Runner](F008-skill-replay-e2e-runner.md)
- Previous Evidence: [EV-008 Skill Replay E2E Runner Evidence](../evidence/EV-008-skill-replay-e2e-runner.md)
- Evidence: [EV-009 Stateful SOP Capture-to-Skill Regression Runner Evidence](../evidence/EV-009-stateful-sop-capture-to-skill-regression-runner.md)
- Backlog: [Backlog](../BACKLOG.md)

## Acceptance Criteria

- [x] A Stateful SOP Capture-to-Skill runner contract exists with stable JSON summary, per-asset items, and per-step capture/trace/compile/replay details.
- [x] The runner selects only governed Full SOP assets that opt into the stateful capture-to-skill mode.
- [x] The runner simulates the recording input boundary from scenario assets while keeping the internal path as close as possible to the normal RPA recording chain: session state, accepted traces, trace normalization, compiler input, generated Skill.
- [x] The runner uses the existing trace/recording/Skill compiler components instead of compiling existing trace files directly as the primary path.
- [x] Optional controlled replay reuses the controlled replay boundary without touching live URLs or direct Agent chat.
- [x] Failures are reported with bounded categories that distinguish asset/governance gaps, capture-to-trace regressions, compiler regressions, replay regressions, and unexpected runner errors.
- [x] Governed regression exposes F009 as an independent runner signal and observability metric without making missing opt-in assets a false failure while F009 is introduced.
- [x] Focused backend tests, governed summary/JSON checks, and strict Harness knowledge checks pass.
- [x] EV-009 records RED/GREEN verification, residual risk, reviewer status, and closeout before F009 is marked completed.
- [x] After F009, Harness v1 infrastructure expansion pauses; next work should be user asset recording, exposed bug triage, RPA core fixes, and asset-based regression validation.

## Patch History

None yet.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

See [EV-009 Stateful SOP Capture-to-Skill Regression Runner Evidence](../evidence/EV-009-stateful-sop-capture-to-skill-regression-runner.md).

## Next Step

Pause Harness v1 infrastructure expansion. Next work should be: user records more real assets; Harness exposes regressions; fixes move to RPA Agent core components; assets validate those fixes.
