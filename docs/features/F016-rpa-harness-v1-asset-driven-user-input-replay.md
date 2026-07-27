---
id: F016
doc_kind: feature
status: ready_for_review
created: 2026-05-28
updated: 2026-05-28
---

# F016: RPA Harness v1 Asset-Driven User Input Replay

## Goal

落地 RPA Harness v1 Phase 4 第一切片：基于已经捕获并治理过的 Harness
资产，脚本化重放接近真人输入的用户输入事件链，包括 click、select、type、
submit、natural language instruction，以及未来资产中出现的 region selection
等输入上下文。

Phase 4 的目标不是做一个新的 Agent 自动操作器，而是让受管资产从“可治理、
可回归”进一步变成“可模拟真实用户输入边界”。执行仍由脚本完成，Agent 只读取
JSON-first 报告和 Markdown summary 做事后解释；promotion 仍由人治理。

## Vision Anchor

- Original request: 在 `codex/rpa-harness-region-integration` 分支上继续
  RPA Harness v1 Phase 4，先创建 F016/EV-016/Phase 4 plan，再实现
  Asset-Driven User Input Replay 的第一切片。
- User pain point: Phase 1/2/3 已经建立 deterministic profile、报告解释闭环和
  资产生命周期治理，但当前 Harness 还主要是读取资产、跑离线链路和报告结果。
  下一步需要让历史资产可以稳定表达“当时的人是如何输入/点击/下达自然语言指令的”，
  并用脚本把这些输入事实送到明确的系统边界，产出可复现、可分析的执行数据。
- Desired outcome: 开发者或 Agent 可以运行稳定 CLI，基于生命周期允许的资产生成
  user-input replay JSON 报告和 Markdown summary。报告必须说明跑了哪些资产、
  资产生命周期分布和 asset_pool 边界、模拟了哪些输入事件、每个事件进入了哪一层
  系统边界、产生了哪些 trace/session/result id、哪里失败，以及为什么 Agent 只能
  解释不能自动 promotion。
- Non-goals:
  - 不做 CI 强阻断。
  - 不做 full/live profile 的完整实现。
  - 不让外层 Agent 直接操控产品 UI。
  - 不做自动 Bug 诊断系统。
  - 不做自动 `candidate` / `golden` promotion。
  - 不为 region selection 建立特例架构；它只是通用 user input event 的一种。
  - 不恢复 direct Agent chat 或 live URL oracle。
  - 不把 replay、选择、事件提取、报告渲染揉成一个巨型模块。
- Core boundary:

```text
Scripts execute.
Agents explain.
Humans govern.
```

- Exit Gate source: this Feature, [EV-016](../evidence/EV-016-rpa-harness-v1-asset-driven-user-input-replay.md),
  [Phase 4 plan](../archive/2026-05/rpa-harness/f016-rpa-harness-v1-phase-4-plan.md),
  [RPA Harness v1 design](../rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md),
  [F015](F015-rpa-harness-v1-asset-lifecycle-operationalization.md),
  [EV-015](../evidence/EV-015-rpa-harness-v1-asset-lifecycle-operationalization.md),
  [ADR-003](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md),
  and [usage guide](../rpa/harness/usage-and-triage-guide.md).

## Current Status

Ready for review. Phase 4 first slice is implemented as a deterministic,
script-driven user-input replay layer over captured asset facts. It extracts
input events, executes a minimal deterministic boundary adapter for each event,
and records both event facts and boundary injection records. It does not drive
the product UI through an outer Agent, call live Planner/LLM during the run,
access live URLs as oracle, or promote assets.

The requested `docs/rpa/harness/RPA-Harness-v1-设计.md` path now exists as a
compatibility index. The current v1 design source remains:

```text
docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md
```

## Entry Gates

Start Gate:

- Task class: high-risk.
- Risk triggers: Harness execution boundary, user input boundary semantics,
  lifecycle/promotion safety, report contract, possible drift toward full/live,
  live Agent UI driving, automatic diagnosis, or region-specific architecture.
- Delegation decision: authorized for read-only sidecar exploration because the
  user explicitly allowed subagents for complex tasks. Implementation integration
  remains local unless a disjoint write scope appears.
- Bug attribution: not triggered; this is a new Phase 4 Feature slice.
- Required pre-work: retrieve v1 design, F015/EV-015, ADR-003, usage guide,
  scenario schema, and related harness code; run Vision Gate; create this
  Feature, EV-016, and Phase 4 plan before code.

Knowledge Retrieval:

- Read `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read `docs/features/F015-rpa-harness-v1-asset-lifecycle-operationalization.md`.
- Read `docs/evidence/EV-015-rpa-harness-v1-asset-lifecycle-operationalization.md`.
- Read `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`.
- Read `docs/rpa/harness/usage-and-triage-guide.md`.
- Read `docs/rpa/harness/scenario-asset-schema.md`.
- Read relevant `RpaClaw/backend/rpa/harness/*` modules for lifecycle summary,
  governed selection, deterministic profile, stateful SOP input conversion,
  CLI style, and tests.

Retrieval conclusion:

- Governed scenario assets remain the durable evaluation unit.
- `candidate-lite` remains warning-only observation and must not become blocking.
- `candidate` and `golden` are the stronger replay baseline when active, reviewed,
  and lifecycle-eligible.
- User input facts already exist in checkpoint intent, recording mode, trace events,
  locator candidates, values, outputs, before/after page state, and optional future
  target evidence such as selected regions.
- The replay slice should preserve and report these facts, not let an Agent decide
  actions during execution.

Vision Gate:

- Mode: Entry Gate.
- Outcome: ready to implement after this Feature and plan exist.
- Original intent: turn captured assets into stable scripted user-input boundary
  replay evidence.
- Alignment: the smallest coherent first slice is a JSON-first replay runner that
  filters lifecycle-eligible assets, extracts replayable input events, records their
  injection boundary, and emits human-readable summary.
- Drift risks: full/live profile expansion, direct Agent UI operation, automatic
  diagnosis, automatic promotion, live URL oracle, or region-specific branching.
- Reviewer policy: independent review recommended or conditional before final
  readiness because this is a high-risk Harness execution/report contract slice.

## Links

- Evidence: [EV-016 RPA Harness v1 Asset-Driven User Input Replay Evidence](../evidence/EV-016-rpa-harness-v1-asset-driven-user-input-replay.md)
- Plan: [F016 Phase 4 implementation plan](../archive/2026-05/rpa-harness/f016-rpa-harness-v1-phase-4-plan.md)
- Previous Feature: [F015 RPA Harness v1 Asset Lifecycle Operationalization](F015-rpa-harness-v1-asset-lifecycle-operationalization.md)
- Previous Evidence: [EV-015 RPA Harness v1 Asset Lifecycle Operationalization Evidence](../evidence/EV-015-rpa-harness-v1-asset-lifecycle-operationalization.md)
- Design: [RPA Harness v1 Asset-Driven User Input Replay](../rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Usage Guide: [RPA Harness 使用与问题定位指南](../rpa/harness/usage-and-triage-guide.md)

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

- [x] A stable script/CLI entrypoint can run user-input replay from Harness assets.
- [x] Replay asset selection obeys lifecycle boundaries.
- [x] `candidate-lite` participates only as warning-only observation.
- [x] `candidate` and `golden` can act as stronger replay baseline.
- [x] Replay extracts click/select/type/submit/natural-language instruction events
  from captured assets when evidence exists.
- [x] Region selection, if present in asset facts, is represented through the same
  generic replay event model rather than a special branch.
- [x] JSON report includes report kind/version, profile/mode, selected assets,
  lifecycle distribution, asset_pool boundary, replayed input events, injected
  system boundary, trace/session/result ids, success/failure summary, trust limits,
  and Agent/human governance boundaries.
- [x] Boundary injection records are produced by a deterministic script adapter,
  so `injected_boundary` is not only a label.
- [x] Markdown summary is generated for Agent and human review.
- [x] Focused tests cover lifecycle selection, candidate-lite warning-only semantics,
  candidate/golden baseline semantics, event chain/report fields, and failure logs.
- [x] A real bootstrap asset replay report is generated and recorded in EV-016.
- [x] `knowledge_check.py --strict` passes.
- [x] EV-016 records verification commands, results, residual risk, reviewer status,
  and whether Phase 5 may start.

## Patch History

None yet.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

See [EV-016 RPA Harness v1 Asset-Driven User Input Replay Evidence](../evidence/EV-016-rpa-harness-v1-asset-driven-user-input-replay.md).

## Next Step

Review F016. Phase 5 may start after human or independent review accepts this
first user-input replay slice and its residual coverage limits.

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
| 2026-07-25 | ready_for_review | AgentMentor schema migration | Existing Feature/Evidence | Historical facts retained; current required structure added |

## Recovery Snapshot

- Read first: `## Goal`, `## Links`, `## Acceptance Criteria`, and `## Evidence`.
- Current capability state: Use the existing `## Current Status`; this migration does not change delivery status.
- Known risks: Historical verification is limited to what the original record explicitly states.
- Next safe action: Read the linked Evidence and ADRs before any follow-up change; update this Feature when the capability boundary or verified state changes.
- Unblock condition: Not blocked by this migration.
