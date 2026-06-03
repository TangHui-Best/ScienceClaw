---
id: F010
doc_kind: feature
status: completed
created: 2026-05-19
updated: 2026-05-19
---

# F010: Assisted Asset Review And Promotion Pipeline

## Goal

实现 Assisted Asset Review And Promotion Pipeline，让新录制的 RPA Harness
asset 自动生成可读 Review Packet，并能通过一条命令升级为非阻塞
`candidate-lite` 回归资产。人工只做语义确认，不再阅读原始 capture 文件，也不手改
governance JSON。

## Vision Anchor

- Original request: F002-F009 已完成并 push 后，继续 ScienceClaw RPA
  Harness 工作，开启 F010，并在开始前创建 Feature/Evidence。
- User pain point: 新录制 capture 目录太难读，用户和其它 Agent 很难判断
  “这个资产到底对应什么场景、是否值得升级为回归资产”。
- Desired outcome: 每个新录制 asset 可自动解释成人能理解的 SOP、证据摘要、
  健康检查和升级建议；一条命令可将通过审查的 asset 标记为非阻塞
  `candidate-lite`，纳入 Harness runner 观察但不污染 blocking baseline。
- Non-goals:
  - 不扩充资产数量，不伪造 candidate。
  - 不修 planner/compiler/extraction bug。
  - 不依赖 live GitHub 或 live URL 作为 oracle。
  - 不恢复 direct Agent chat。
  - 不实现嵌套 Agent 点击 RPA 产品 UI。
  - 不把 expected/sensitivity 的强确认完全自动化。
  - 不让刚录的 draft 直接变成 blocking candidate/golden。
- Exit Gate source: this Feature, [EV-010](../evidence/EV-010-assisted-asset-review-and-promotion-pipeline.md),
  [RPA Harness 使用与问题定位指南](../rpa/harness/usage-and-triage-guide.md),
  [Scenario Asset Schema](../rpa/harness/scenario-asset-schema.md), [F009](F009-stateful-sop-capture-to-skill-regression-runner.md),
  and [EV-009](../evidence/EV-009-stateful-sop-capture-to-skill-regression-runner.md).

## Current Status

Completed locally. Review Packet generation, `candidate-lite` promotion, and
warning-only governed observation are implemented and verified. After human
review confirmed expected signals and sensitivity, the target asset
`hcap-de463b7bb608482e9b5bcdd5b78a224e` now has Chinese-first `review.md` and
is promoted to active blocking `candidate`.

## Links

- Evidence: [EV-010 Assisted Asset Review And Promotion Pipeline Evidence](../evidence/EV-010-assisted-asset-review-and-promotion-pipeline.md)
- Plan: [F010 implementation plan](../rpa/harness/f010-assisted-asset-review-and-promotion-plan.md)
- Usage Guide: [RPA Harness 使用与问题定位指南](../rpa/harness/usage-and-triage-guide.md)
- Schema: [Scenario Asset Schema](../rpa/harness/scenario-asset-schema.md)
- Previous Feature: [F009 Stateful SOP Capture-to-Skill Regression Runner](F009-stateful-sop-capture-to-skill-regression-runner.md)
- Previous Evidence: [EV-009 Stateful SOP Capture-to-Skill Regression Runner Evidence](../evidence/EV-009-stateful-sop-capture-to-skill-regression-runner.md)
- Backlog: [Backlog](../BACKLOG.md)

## Acceptance Criteria

- [x] A review packet builder exists and writes `review.md` under each selected
  asset directory without requiring live URL access.
- [x] Review Packet first screen answers scenario identity, human SOP, page
  transitions, final extracted output, auto checks, review questions, and
  suggested promotion.
- [x] Scenario identity can be inferred when `scenario.sop_intent` is empty,
  using step intent, before/after URL/title, action evidence, locator/target
  evidence, `output_key`, observed output, and runner check results.
- [x] Review packet generation reuses or summarizes existing asset validation,
  snapshot regression, compiler regression, accepted traces, output keys, and
  observed outputs.
- [x] `candidate-lite` is represented as a non-blocking asset promotion level:
  it may enter Harness runner observation, including F009 Stateful SOP, but
  failures are warnings and do not affect the blocking governed baseline.
- [x] A promotion CLI can update one asset to `candidate-lite` without requiring
  manual `scenario.json` edits.
- [x] Blocking `candidate`/`golden` behavior remains unchanged and still
  requires explicit expected-signal and sensitivity confirmation.
- [x] Focused tests demonstrate review packet inference, promotion update, and
  non-blocking governed baseline behavior before implementation code lands.
- [x] EV-010 records RED/GREEN verification, real-asset command output, reviewer
  status, residual risk, and closeout before F010 is marked completed.

## Patch History

F010.1 recorded below.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F010.1 | 2026-05-19 | pending | `review.md` was still English-first for a Chinese-native reviewer. | Review Packet copy was implemented as English labels/questions even though the review workflow is meant to remove human reading friction. | Added Chinese-first Review Packet assertions, localized headings/labels/check questions/promotion guidance, and regenerated current bootstrap asset reviews. | completed |
| F010.2 | 2026-05-19 | pending | Human-confirmed `candidate` promotion still left the new asset outside blocking governed baseline. | Promotion CLI changed `governance.promotion_status` but did not activate the asset or ensure runner coverage for blocking candidate/golden promotion. | Added promotion tests requiring candidate/golden promotion to set `asset_status=active` and runner/core-chain coverage; reran real promotion and governed regression selecting both assets. | completed |

## Evidence

See [EV-010 Assisted Asset Review And Promotion Pipeline Evidence](../evidence/EV-010-assisted-asset-review-and-promotion-pipeline.md).

## Next Step

Use the same Review Packet flow for future newly captured assets. New assets
should start at `candidate-lite`, then move to blocking `candidate` only after
human expected-signal and sensitivity confirmation.
