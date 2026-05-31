---
id: F017
doc_kind: feature
status: ready_for_review
created: 2026-05-28
updated: 2026-05-28
---

# F017: RPA Harness v1 Full/Live Profile Integration

## Goal

落地 RPA Harness v1 Phase 5：把 F012 的 `live_agent_eval` 能力收束进
Harness v1 的统一 profile/report/asset-governance 闭环，形成
`full-live` profile。

Phase 5 不是新增一个孤立 live runner，而是让受管资产中的用户输入事实可以在受控
HTML fixture 或 captured page state 上触发真实
`RecordingRuntimeAgent.run()` / Planner / LLM 路径，生成新的 accepted trace，
再进入 compiler、Skill replay、stateful checks，并输出 v1 风格 JSON-first report
和 Markdown summary。

核心边界仍然是：

```text
Scripts execute.
Agents explain.
Humans govern.
```

## Vision Anchor

- Original request: 在 `codex/rpa-harness-region-integration` 分支继续推进
  RPA Harness v1 Phase 5，先按 Harness 完成 Start Gate、Knowledge Retrieval、
  Vision Gate、Delegation Gate，并创建 F017/EV-017/Plan 后再实现。
- User pain point: Phase 1-4 已有 deterministic profile、报告解释闭环、资产生命周期
  治理和 deterministic user-input replay，但还没有一个统一的 v1 profile 可以在受控环境
  中真实触发 `RecordingRuntimeAgent` / Planner / LLM。
- Desired outcome: 开发者或 Agent 可以运行
  `run_harness_profile --profile full-live`，基于受管资产的 natural-language step
  生成 controlled fixture，真实调用 RecordingRuntimeAgent，生成 candidate-lite/profile
  artifact，再执行 post-capture checks，并得到机器 JSON 与人类 summary。
- First slice: 只支持 natural-language step 的 full-live replay。click/type/select/submit
  保持 F016 deterministic user-input replay 能力，不在本切片真实驱动所有手动 UI 事件。
- Non-goals:
  - 不做 CI 强阻断。
  - 不把 live 网站当 oracle。
  - 不让外层 Agent 直接点击产品 UI。
  - 不做自动 Bug 诊断系统。
  - 不做自动 candidate/golden promotion。
  - 不把 F012、F016、profile runner 揉成一个巨型模块。
  - 不为了 region selection 建特例架构。
  - 不改变 deterministic profile 的默认语义。

Exit Gate source: this Feature, [EV-017](../evidence/EV-017-rpa-harness-v1-full-live-profile-integration.md),
[Phase 5 plan](../archive/2026-05/rpa-harness/f017-rpa-harness-v1-phase-5-plan.md),
[RPA Harness v1 design](../rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md),
[F016](F016-rpa-harness-v1-asset-driven-user-input-replay.md),
[EV-016](../evidence/EV-016-rpa-harness-v1-asset-driven-user-input-replay.md),
[F012](F012-live-agent-eval-for-rpa-harness.md),
[EV-012](../evidence/EV-012-live-agent-eval-for-rpa-harness.md),
[Live Agent Eval guide](../rpa/harness/live-agent-eval.md),
[ADR-003](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md),
and [usage guide](../rpa/harness/usage-and-triage-guide.md).

## Current Status

Ready for review. Phase 5 first slice is implemented as a `full-live` profile
adapter over F012 and F016. It selects natural-language input events from governed
assets, builds controlled fixtures from captured `before.html`, invokes
`RecordingRuntimeAgent.run()` through the existing live-agent execution bottom,
writes generated candidate-lite/profile artifacts outside the source asset root,
and returns a v1 JSON-first report plus Markdown summary.

Review follow-up F017.1 tightened the boundary between report facts and runtime
facts: F016 region context is normalized into the Runtime contract before invoking
`RecordingRuntimeAgent`, fixture-build failures are reported as JSON-first failures,
and summary rendering can load an existing machine report without rerunning
`full-live`.

Review follow-up F017.2 tightened controlled fixture file containment: captured
`before_page.html_path` must be relative to the source asset directory and must
still resolve inside that source asset before any HTML is read.

The deterministic profile remains the default and existing deterministic behavior
is unchanged.

## Entry Gates

Start Gate:

- Task class: high-risk.
- Risk triggers: live Planner/LLM execution path, Harness profile/report contract,
  generated asset governance, candidate-lite boundary, controlled fixture safety,
  possible drift toward direct Agent UI operation or live URL oracle, and report
  interpretation overclaiming.
- Delegation decision: authorized for a read-only sidecar explorer because the
  user explicitly allowed subagents for complex tasks. Main implementation remains
  local unless a disjoint write scope appears.
- Bug attribution: not triggered; this is a new Phase 5 Feature slice, not a
  patch to completed behavior.
- Required pre-work: retrieve F012/F016/ADR/design/usage context, run Vision Gate,
  create this Feature, EV-017, and Phase 5 plan before code.

Knowledge Retrieval:

- Read `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read `docs/rpa/harness/RPA-Harness-v1-设计.md`.
- Read `docs/features/F016-rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read `docs/evidence/EV-016-rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read `docs/features/F012-live-agent-eval-for-rpa-harness.md`.
- Read `docs/evidence/EV-012-live-agent-eval-for-rpa-harness.md`.
- Read `docs/rpa/harness/live-agent-eval.md`.
- Read `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`.
- Read `docs/rpa/harness/usage-and-triage-guide.md`.
- Read relevant code and tests for `profile_runner`, `user_input_replay`,
  `live_agent_eval`, `run_harness_profile`, `run_live_agent_eval`, and
  `RecordingRuntimeAgent`.

Retrieval conclusion:

- F012 already proves the live-agent execution substrate:
  controlled HTML fixture -> Playwright -> `RecordingRuntimeAgent.run()` ->
  candidate-lite asset -> post-capture checks.
- F016 already provides asset-driven user input event extraction and report
  boundary facts, but its boundary injection is deterministic record-only.
- ADR-003 remains binding: governed assets are the correctness unit; live URLs
  and direct Agent chat must not become the oracle.
- The smallest Phase 5 path is a new `full_live_profile.py` module that builds
  F012-compatible controlled scenarios from F016 natural-language events and
  asset checkpoints, then wraps results in a v1 profile report.

Vision Gate:

- Mode: Entry Gate.
- Outcome: ready to implement after this Feature and plan exist.
- Original intent: give Harness v1 a unified high-fidelity profile that triggers
  the real recording-time intelligent path under controlled inputs.
- Alignment: reusing F012 as the execution bottom and F016 as the input boundary
  avoids a new live runner and keeps profile_runner small.
- Drift risks: overbuilding manual UI event replay, treating live pages as oracle,
  promoting generated assets automatically, hiding Planner bugs inside Harness
  rules, or creating region-specific branches.
- Reviewer policy: independent review recommended before readiness because this
  changes the Harness execution/report contract and touches live Planner/LLM semantics.

## Links

- Evidence: [EV-017 RPA Harness v1 Full/Live Profile Integration Evidence](../evidence/EV-017-rpa-harness-v1-full-live-profile-integration.md)
- Plan: [F017 Phase 5 implementation plan](../archive/2026-05/rpa-harness/f017-rpa-harness-v1-phase-5-plan.md)
- Previous Feature: [F016 RPA Harness v1 Asset-Driven User Input Replay](F016-rpa-harness-v1-asset-driven-user-input-replay.md)
- Live substrate: [F012 Live Agent Eval For RPA Harness](F012-live-agent-eval-for-rpa-harness.md)
- Design: [RPA Harness v1 Asset-Driven User Input Replay](../rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)

## Acceptance Criteria

- [x] `run_harness_profile(..., profile="full-live")` runs and returns a v1 profile report.
- [x] CLI `python -m backend.rpa.harness.run_harness_profile --profile full-live ...`
  can write JSON.
- [x] Deterministic profile remains default and existing deterministic tests continue to pass.
- [x] Full-live report has `profile.name=full-live`,
  `profile.uses_live_planner=true`, `profile.uses_live_url_oracle=false`, and
  `profile.uses_outer_agent_ui_control=false`.
- [x] First slice selects only eligible `natural_language_instruction` input events.
- [x] No eligible full-live input returns failed or insufficient evidence, never passed.
- [x] Generated assets are written only to explicit `--generated-assets` or a temporary
  profile output directory, not the source governed asset root.
- [x] Generated assets are `candidate-lite` or profile artifacts and cannot auto-promote.
- [x] Tests inject a fake planner and assert planner invocation count is non-zero.
- [x] CLI default does not inject a fake planner.
- [x] Controlled fixture metadata records source asset ids, checkpoint paths, HTML source,
  instruction source, and region context pass-through.
- [x] Region context, if present, is passed as generic context to
  `RecordingRuntimeAgent.run()` without a region-specific runner branch.
- [x] F016 `region_context` shape is normalized so Runtime/Planner receives usable
  selected-region evidence instead of an empty compact context.
- [x] Controlled fixture build failures, such as missing `before.html`, return
  JSON-first failure reports instead of uncaught exceptions.
- [x] Controlled fixture `before_page.html_path` rejects absolute paths and `..`
  traversal that resolves outside the source asset directory before reading HTML.
- [x] Summary generation can render from an existing machine report without
  rerunning `full-live`.
- [x] Post-capture validation, snapshot, compiler, skill replay, and stateful SOP summaries
  are included in the report.
- [x] Candidate-lite remains warning-only and does not become a blocking baseline.
- [x] Report includes trust limits, failures/failure categories, governance boundary, and
  `agents_may_promote_automatically=false`.
- [x] Markdown summary is generated for human/Agent review.
- [x] EV-017 records commands, results, report paths, residual risk, reviewer status, and
  whether a v1 closeout/stabilization slice is needed.

## Patch History

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F017.1 | 2026-05-28 | pending | Review found region context was only carried in report shape, fixture build errors escaped JSON reports, and summary CLI reran full-live instead of reading the existing machine report. | F017 first slice connected F016/F012 facts but did not normalize every boundary into the downstream contract. | Added RED/GREEN tests for Runtime-consumed region context, JSON-first fixture build failures, and existing machine report summary rendering. | ready_for_review |
| F017.2 | 2026-05-28 | pending | Review found `before_page.html_path` could traverse outside the governed source asset directory and load external local HTML into the controlled fixture. | `_read_event_html()` joined paths and used `relative_to(assets_root)` without resolving or checking containment before reading. | Added RED/GREEN tests for `..` traversal and absolute path rejection; `_read_event_html()` now resolves source root, source asset dir, and candidate HTML path before read. | ready_for_review |

## Evidence

See [EV-017 RPA Harness v1 Full/Live Profile Integration Evidence](../evidence/EV-017-rpa-harness-v1-full-live-profile-integration.md).

## Next Step

Run human review on F017. A small v1 stabilization/closeout slice is recommended
only if review asks for more real internal full-live scenarios or broader manual
event support.
