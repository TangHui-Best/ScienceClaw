---
id: F013
doc_kind: feature
status: ready_for_review
created: 2026-05-28
updated: 2026-05-28
---

# F013: RPA Harness v1 Asset-Driven User Input Replay

## Goal

落地 RPA Harness v1 Phase 1：基于 Asset-Driven User Input Replay 设计，把现有受管资产执行能力收束成默认 deterministic profile 的统一执行入口和报告闭环雏形，让 RPA core-chain 变更在 PR/readiness 声明前可以通过脚本运行、生成机器证据，并由 Agent 解读，人类治理资产状态。

Phase 1 的目标不是再造 runner，而是把 F003-F010 已有能力包装成一个更清晰的默认 pre-submit evidence path。

## Vision Anchor

- Original request: 在 `codex/rpa-harness-region-integration` 上开启 RPA Harness v1 Phase 1，先创建正式 Feature Anchor 和实施计划，再实现最小 deterministic profile 收束。
- User pain point: F003-F010 已经有 asset validation、snapshot、compiler、Skill Replay、Stateful SOP、Review Promotion 等能力，但对开发者和 Agent 来说还缺少一个统一的“我改了 RPA core-chain 后该跑什么、报告怎么看、是否能作为 pre-submit evidence”的入口。
- Desired outcome: 开发者可以运行一个 deterministic asset profile，看到哪些 governed assets 被执行或排除、哪个 runner 最先失败、结果是否说明 regression/improvement/no meaningful change/insufficient evidence，并把 JSON/Markdown 结果纳入 Evidence 或 PR closeout。
- Non-goals:
  - 不扩张 full/live profile；F012 live-agent eval 仍是专项/内网验收补充。
  - 不接 CI blocking；deterministic profile 当前是默认人工/Agent 执行的 pre-submit evidence path。
  - 不做自动诊断平台；Bug 分析只是 evidence 副产物，由 Agent 解释已有事实。
  - 不让外层 Agent 点击 RPA 产品 UI 作为默认执行路径。
  - 不自动 promotion `candidate` / `golden`；人类继续治理资产状态。
  - 不把 region selection 变成特殊架构线；它只是 user input context 的一种。
- Exit Gate source: this Feature, [EV-013](../evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md), [Phase 1 plan](../rpa/harness/f013-rpa-harness-v1-phase-1-plan.md), [RPA Harness v1 design](../rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md), [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md), [ADR-003](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md), and [F010](F010-assisted-asset-review-and-promotion-pipeline.md).

## Current Status

Ready for review. The deterministic profile wrapper, CLI entrypoint, focused tests, real bootstrap run, and Evidence update are complete. Strict Harness knowledge validation remains blocked by pre-existing repo-wide metadata issues outside F013 scope, not by F013-local artifacts.

The v1 design document is the source design for this Feature:

```text
docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md
```

## Entry Gates

Start Gate:

- Task class: high-risk.
- Risk triggers: Harness architecture boundary, cross-runner evidence path, future PR/readiness process, asset governance semantics, and possible drift toward full/live or auto-diagnosis.
- Delegation decision: not needed for the Feature/plan slice because the immediate work is tightly coupled documentation and scope anchoring. Re-evaluate before implementation review; independent review is required or conditional for readiness because this is high-risk Harness architecture.
- Bug attribution: not triggered.
- Required pre-work: Feature Anchor, implementation plan, deterministic-only scope, Evidence anchor.

Knowledge Retrieval:

- Read F003-F010 Feature anchors, F011/F012 context, ADR-003, v0 design, golden evaluation vision, v1 design, and usage/triage guide.
- Retrieved decision: governed scenario assets remain the durable unit; direct Agent chat and live URLs are not the primary oracle.
- Retrieved boundary: Harness exposes reproducible evidence; owning RPA modules fix planner/snapshot/compiler/replay bugs.

Vision Gate:

- Mode: Entry Gate.
- Outcome: ready to plan; implementation may start only after this Feature and the linked plan exist.
- Original intent: make governed assets the default way to verify RPA core-chain changes before readiness claims.
- Alignment: the smallest coherent Phase 1 path is a deterministic profile wrapper/report shape over existing governed runner capabilities.
- Drift risks: expanding into full/live profile, CI blocking, automatic diagnosis, or region-specific Harness branches.
- Vision Anchor for Exit Gate: this Feature plus the v1 design document.

## Links

- Design: [RPA Harness v1 Asset-Driven User Input Replay](../rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md)
- Plan: [F013 Phase 1 implementation plan](../rpa/harness/f013-rpa-harness-v1-phase-1-plan.md)
- Evidence: [EV-013 RPA Harness v1 Asset-Driven User Input Replay Evidence](../evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md)
- Vision: [RPA Golden Evaluation Vision](../rpa/harness/golden-evaluation-vision.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Previous Feature: [F010 Assisted Asset Review And Promotion Pipeline](F010-assisted-asset-review-and-promotion-pipeline.md)
- Region Context: [F011 RPA Region-Scoped Snapshot](F011-rpa-region-scoped-snapshot.md)
- Live Profile Context: [F012 Live Agent Eval For RPA Harness](F012-live-agent-eval-for-rpa-harness.md)
- Usage Guide: [RPA Harness 使用与问题定位指南](../rpa/harness/usage-and-triage-guide.md)

## Acceptance Criteria

- [x] A deterministic profile entrypoint exists and is documented as the default pre-submit evidence path for RPA core-chain changes.
- [x] The deterministic profile reuses existing governed asset selection, asset validation, snapshot regression, compiler regression, Skill Replay, Stateful SOP, candidate-lite observation, and observability output instead of reimplementing runners.
- [x] Machine-readable output explicitly records `profile=deterministic`, selected/excluded asset ids, blocking vs warning-only status, first failing runner/category, and existing runner summaries.
- [x] Human-readable output or Markdown report gives Agent-friendly analysis inputs without becoming an automatic diagnosis platform.
- [x] Existing `run_governed_regression` behavior remains backward compatible or is clearly preserved as an alias to the deterministic path.
- [x] Focused tests cover the deterministic profile wrapper/report contract and compatibility with existing governed regression behavior.
- [x] A real bootstrap asset run is executed with `data/rpa_harness_assets_bootstrap`, and output paths/results are recorded in EV-013.
- [x] Harness knowledge validation is attempted; it fails because of pre-existing legacy document structure, and EV-013 records the attribution without broad frontmatter cleanup.
- [x] EV-013 records verification, residual risk, reviewer status, and closeout before F013 is marked completed.

## Patch History

None yet. F013 is ready for review rather than marked completed because independent review is still pending and strict knowledge validation remains blocked by pre-existing repo-wide metadata issues.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

See [EV-013 RPA Harness v1 Asset-Driven User Input Replay Evidence](../evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md).

## Next Step

Review the deterministic profile slice. If accepted, Phase 2 should first decide whether to harden Agent-readable Markdown closeout generation or clean up legacy Harness metadata so strict `knowledge_check.py` can become a reliable gate. Do not expand full/live profile before the deterministic evidence path is stable.
