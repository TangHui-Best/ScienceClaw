---
id: F018
doc_kind: feature
status: ready_for_review
created: 2026-05-28
updated: 2026-05-28
---

# F018: RPA Harness v1 Closeout / Stabilization

## Goal

完成 RPA Harness v1 的 closeout / stabilization：把 Phase 0-5 已经完成的
能力收束成一个未来 Agent 和人类都能正确使用、验收、恢复上下文的入口。

F018 不是 Phase 6，不新增 runner，不扩 full-live 到所有手动 UI 事件，不接 CI
强阻断，也不改变 deterministic、user-input replay 或 full-live 的核心执行语义。

## Vision Anchor

- Original request: 在 `codex/rpa-harness-region-integration` 上完成一个很小的
  RPA Harness v1 closeout / stabilization slice。
- User pain point: F013-F017 已经分别完成 deterministic profile、Evidence /
  Report trust loop、asset lifecycle、user-input replay、full-live profile，但
  `docs/rpa/harness/RPA-Harness-v1-设计.md` 仍只是 compatibility index，未来
  Agent 可能从错误入口误解 v1、过度解释报告、误把 generated full-live artifacts
  当成 governed assets，或把 v1 closeout 继续膨胀成 Phase 6。
- Desired outcome: v1 有一个清晰总入口，说明用户旅程、三类 profile、何时运行
  哪个 profile、报告可解释边界、治理边界、generated artifacts 的 evidence 身份、
  验收命令结果，以及内部 controlled full-live scenario 是否属于 v1.1/backlog。
- Core boundary:

```text
Scripts execute.
Agents explain.
Humans govern.
```

## Non-goals

- 不新增 runner。
- 不扩 full-live 到所有手动 UI 事件。
- 不接 CI blocking。
- 不自动 promotion。
- 不把 generated artifacts 移入 governed asset pool。
- 不清理或删除旧文档；如需文档生命周期处理，只做轻量标注和入口收束。
- 不改 deterministic / profile / user-input / full-live 的核心执行语义。
- 不为 region selection 做特例架构。

## Current Status

Ready for review. The v1 entrypoint has been upgraded, generated artifact identity is
documented, the full v1 acceptance checklist has been run, and EV-018 records the
closeout judgment and residual risks.

## Entry Gates

Start Gate:

- Task class: high-risk.
- Risk triggers: Harness closeout semantics, v1 source-of-truth entrypoint,
  generated artifact governance boundary, full-live interpretation limits,
  future Agent handoff, and possible scope drift into Phase 6.
- Delegation decision: authorized for read-only sidecar audit because the user
  explicitly allowed subagents for complex tasks; implementation and verification
  integration remain local.
- Bug attribution: not triggered; this is a closeout/stabilization slice, not a
  bugfix against a completed Feature.
- Required pre-work: retrieve F013-F017/EV-013-EV-017, v1 design, user-input replay
  design, ADR-003, usage guide; run Vision Gate; run Doc Lifecycle judgment; create
  this Feature, EV-018, and F018 plan before editing docs or running validation.

Knowledge Retrieval:

- Read `docs/rpa/harness/RPA-Harness-v1-设计.md`.
- Read `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md`.
- Read F013 through F017 Feature pages and EV-013 through EV-017 Evidence records.
- Read `docs/decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md`.
- Read `docs/rpa/harness/usage-and-triage-guide.md`.

Retrieval conclusion:

- F013-F017 are all `ready_for_review`.
- The v1 implementation direction is already coherent: deterministic profile is the
  stable default, lifecycle/promotion guardrails govern assets, user-input replay
  scripts the input boundary, and full-live runs the real recording-time intelligent
  path only in controlled fixture/profile mode.
- ADR-003 remains binding: governed assets are the correctness unit; live URLs and
  direct Agent chat are not the oracle.
- F017 generated assets under `docs/rpa/harness/reports/f017-generated-assets` are
  full-live Evidence/profile artifacts, not the governed source asset pool.

Vision Gate:

- Mode: Entry Gate.
- Outcome: ready to implement after F018/EV-018/Plan anchors exist.
- Original intent: close out v1 core loop so future users can run, interpret, and
  govern it without expanding scope.
- Alignment: the smallest coherent path is documentation convergence plus full v1
  acceptance rerun and Evidence closeout.
- Drift risks: Phase 6 expansion, CI blocking, automatic promotion, live URL oracle,
  outer Agent UI control, automatic diagnosis, or moving generated artifacts into
  governed assets.
- Reviewer policy: independent review recommended; read-only sidecar audit is
  authorized and final human review remains recommended.

Doc Lifecycle:

- `docs/rpa/harness/RPA-Harness-v1-设计.md` should be upgraded from compatibility
  index to v1 total entrypoint.
- `docs/rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md` remains a
  detailed design source and should be linked from the new entrypoint, not archived.
- Existing Phase plans and Evidence records remain active historical anchors.
- No deletion or broad archival is needed for F018.

## Links

- Evidence: [EV-018 RPA Harness v1 Closeout / Stabilization Evidence](../evidence/EV-018-rpa-harness-v1-closeout-stabilization.md)
- Plan: [F018 closeout / stabilization plan](../archive/2026-05/rpa-harness/f018-rpa-harness-v1-closeout-stabilization-plan.md)
- Design entrypoint: [RPA Harness v1 Design](../rpa/harness/RPA-Harness-v1-设计.md)
- Detailed design: [RPA Harness v1 Asset-Driven User Input Replay](../rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Previous Feature: [F017 RPA Harness v1 Full/Live Profile Integration](F017-rpa-harness-v1-full-live-profile-integration.md)

## Acceptance Criteria

- [x] F018 / EV-018 exist and state this is v1 closeout/stabilization, not Phase 6.
- [x] `docs/rpa/harness/RPA-Harness-v1-设计.md` is a clear v1 total entrypoint.
- [x] The generated artifact evidence identity is documented.
- [x] Full v1 acceptance checklist is run and recorded.
- [x] EV-018 explicitly decides whether internal controlled full-live scenarios block
  v1 closeout or belong to v1.1/backlog.
- [x] `knowledge_check.py --strict` passes.
- [x] F013-F017 focused tests are not broken.
- [x] Final F018 status is `ready_for_review`.

## Patch History

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F018.1 | 2026-05-28 | pending | Review found Source Map links resolved to `docs/rpa/*` instead of canonical `docs/*`, and sidecar audit was cited without enough durable audit detail. | The v1 entrypoint was written from `docs/rpa/harness/` but used one-level relative links; EV-018 summarized sidecar output but did not make its scope and findings recoverable enough. | Fixed Source Map links to `../../features`, `../../evidence`, and `../../decisions`; added a durable sidecar audit record and clarified that sidecar review is auxiliary while local reports/tests/knowledge check remain the primary closeout evidence. | completed |

## Evidence

See [EV-018 RPA Harness v1 Closeout / Stabilization Evidence](../evidence/EV-018-rpa-harness-v1-closeout-stabilization.md).

## Next Step

Review F018. Harness v1 core loop is now closeout-ready; further capability expansion
should move to v1.1/backlog or PR review, not more v1 scope.
