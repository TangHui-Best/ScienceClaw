---
id: F020
doc_kind: feature
status: active
created: 2026-05-30
updated: 2026-05-30
---

# F020: RPA Harness Region and Element Selection Simulation

## Goal

让 RPA Harness 能够模拟并验收“区域选择”和“元素点选转区域选择”这两类输入边界，从 Harness capture 开始一路贯通到 user-input replay、full-live、expected signals、compiler 与 Skill replay。

核心目标不是新增一条 `element_context` 后端主链路，而是把元素点选视为更精确的 `region_context` acquisition 方式：拖拽区域与点选元素都进入同一条 `region_context` / `region_scope` 证据链，并在 Harness 报告中保留足够事实，方便判断 Agent 是否真的在用户选定范围内完成自然语言指令。

## Vision Anchor

- 原始请求：用户认可 F019 已经承接 controlled download side effect，要求开启 F020，用 Harness skill 完成区域选择、元素选择模拟能力的整体补齐。
- 用户痛点：当前 Harness v1 能记录输入边界和 full-live 调用，但真实 region selection capture 缺少 governed asset 覆盖，且 `user_input_replay` 对顶层 `region_context` / `region_scope` / `signals.region_selection` 的读取不完整，可能导致 full-live 重放时丢失选区语义。
- 期望结果：Harness 能证明 selected region / picked element acquisition 事实没有在 capture -> replay/profile 之间丢失，并能与 F019 的 controlled download 组合，但不把下载能力本身重新纳入 F020。
- 非目标或边界：不新增 Harness v2；不新增 `element_context` 主链路；不做自动 candidate/golden promotion；不把 iframe 内精确点选混入第一切片；不修改 F019 的 controlled download contract。
- Exit Gate 对照来源：本 Feature、[EV-020 RPA Harness Region and Element Selection Simulation Evidence](../evidence/EV-020-rpa-harness-region-element-selection-simulation.md)、[F011 RPA Region-Scoped Snapshot](F011-rpa-region-scoped-snapshot.md)、[F016 RPA Harness v1 Asset-Driven User Input Replay](F016-rpa-harness-v1-asset-driven-user-input-replay.md)、[F017 RPA Harness v1 Full/Live Profile Integration](F017-rpa-harness-v1-full-live-profile-integration.md)、[F019 RPA Harness Controlled Download Side Effects](F019-rpa-harness-controlled-download-side-effects.md)。

## Current Status

Active。

2026-05-30 第一切片已实现并本地验证。Harness replay/profile 现在会保留顶层 `region_context`、`region_scope`、`signals.region_selection` 和 `acquisition=picked_element` 事实；expected signals 也会保留 acquisition。第一切片不录制真实内网 asset，不做 iframe 内元素点选，不改变 compiler 的区域提取策略。

## Entry Gates

Start Gate:

- Task class: high-risk.
- Risk triggers: Harness asset schema/report interpretation、region context contract、full-live planner context、F019 side-effect boundary、未来 candidate/golden promotion 治理。
- Delegation decision: authorized. 用户明确允许复杂任务拆分并委托 subagent；本轮已委托只读 explorer 审查代码边界，主代理负责实现与集成。
- Bug attribution: new F020 capability slice. 已知缺口横跨 F016/F017，但不是对已完成 Feature 的窄修补；F019 下载副作用已独立收敛。
- Required pre-work: 创建 F020/EV020；检索 F011/F016/F017/F019/EV018；按 TDD 写 RED tests 后实现。

Knowledge Retrieval:

- F011 说明元素点选只是 region acquisition 方式，不新增 `element_context`。
- F016 说明 user-input replay 第一切片是 record-only boundary injection，region selection 应作为通用 event fact。
- F017 说明 full-live 应把 `region_context` 作为通用 `RecordingRuntimeAgent` context 透传，不建立 region-specific runner。
- F019 说明 controlled download 是 side-effect lane，F020 只组合引用，不重写下载模拟。
- EV-018 说明 bootstrap assets 不包含真实 region-selection captures，v1 review-ready 不代表区域/元素选择全覆盖。

## Links

- Evidence: [EV-020 RPA Harness Region and Element Selection Simulation Evidence](../evidence/EV-020-rpa-harness-region-element-selection-simulation.md)
- Coverage Matrix: [F020 区域与元素选择 Harness 覆盖矩阵](../rpa/harness/f020-region-element-selection-coverage-matrix.md)
- Risk TODO: [Harness v1.1 区域选择与下载动作风险待办](../rpa/harness/v1.1-region-selection-download-risk-todo.md)
- Region Feature: [F011 RPA Region-Scoped Snapshot](F011-rpa-region-scoped-snapshot.md)
- User-input Replay: [F016 RPA Harness v1 Asset-Driven User Input Replay](F016-rpa-harness-v1-asset-driven-user-input-replay.md)
- Full-live Profile: [F017 RPA Harness v1 Full/Live Profile Integration](F017-rpa-harness-v1-full-live-profile-integration.md)
- Controlled Download: [F019 RPA Harness Controlled Download Side Effects](F019-rpa-harness-controlled-download-side-effects.md)

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

## Acceptance Criteria

- [x] `user_input_replay` can preserve top-level `region_context`, `region_scope`, and `signals.region_selection` from captured trace events.
- [x] `full_live_profile` receives normalized runtime `region_context` from replayed events without needing a region-specific runner branch.
- [x] `picked_element` is represented only as selection acquisition metadata on generic region facts; no backend `element_context` main path is introduced.
- [x] Focused tests cover drag-region and picked-element evidence preservation through user-input replay.
- [x] Focused tests prove full-live planner payload receives picked-element region evidence as generic region context.
- [x] F019 `controlled_download` remains a separate side-effect contract; F020 tests may compose with it only through expected signals, not by redefining download replay.
- [x] EV-020 records RED/GREEN commands, residual risks, and Harness structural validation.
- [x] F020.2 controlled fixture reports both `drag_region` and `picked_element` acquisition coverage through user-input replay and full-live profile.
- [x] F020.3 asset review packets surface region acquisition facts while preserving captured/candidate-lite governance boundaries.
- [x] F020.4 coverage matrix records covered, composed, and future capability boundaries without overclaiming F020 scope.

## Patch History

None yet.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

See [EV-020 RPA Harness Region and Element Selection Simulation Evidence](../evidence/EV-020-rpa-harness-region-element-selection-simulation.md).

## Next Step

进入人工 review。下一步若继续扩展，建议在真实内网录制一个 captured/candidate-lite region-selection asset，并由人工确认 expected signals / sensitivity 后再评估是否进入 blocking candidate。

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
| 2026-07-25 | active | AgentMentor schema migration | Existing Feature/Evidence | Historical facts retained; current required structure added |

## Recovery Snapshot

- Read first: `## Goal`, `## Links`, `## Acceptance Criteria`, and `## Evidence`.
- Current capability state: Use the existing `## Current Status`; this migration does not change delivery status.
- Known risks: Historical verification is limited to what the original record explicitly states.
- Next safe action: Read the linked Evidence and ADRs before any follow-up change; update this Feature when the capability boundary or verified state changes.
- Unblock condition: Not blocked by this migration.
