---
doc_kind: feature
id: F002
title: RPA Harness v0
status: active
feature_ids: [F002]
created: 2026-05-18
updated: 2026-05-18
specs:
  - docs/rpa/harness/rpa-harness-v0-design.md
  - docs/rpa/harness/scenario-asset-schema.md
  - docs/rpa/harness/regression-strategy.md
plans:
  - docs/superpowers/plans/2026-05-17-rpa-harness-v0-implementation.md
decisions: []
evidence:
  - docs/evidence/EV-002-rpa-harness-v0.md
lessons:
  - docs/lessons/LL-001-harness-feature-evidence-closeout-miss.md
---

# F002 RPA Harness v0

## Vision Anchor

RPA Harness v0 要改变 RPA Agent 的研发方式：不再是“修一个页面 bug，不知道有没有影响其他页面”，而是“每次 DOM snapshot、trace recording、`TraceSkillCompiler` 等核心链路改动，都能用沉淀资产判断影响范围，并把新的页面形态沉淀为长期知识”。

这个 Feature 的产品 Harness 与本机 Codex Harness skills 不同。它服务的是 RPA Agent 自身的数据链路：

```text
SOP intent -> recording step -> page HTML evidence -> raw/compact snapshot
  -> accepted trace -> Skill compilation -> offline regression report
```

## User Problem

RPA 项目在不同页面和 DOM 形态上反复修 bug，但核心链路改动缺少可观测、可复现、可比较的资产集。尤其是 DOM 压缩、trace 编译、expected signal、manual/AI capture 等共享层变化时，很难回答：

- 改动影响了哪些已遇到的页面形态？
- 捕获资产是否完整到足以作为回归证据？
- snapshot 压缩是否丢失了任务关键信号？
- compiler 是否硬编码了录制现场值或破坏了数据流？
- 哪些设计来自真实页面资产，而不是临时经验规则？

## Desired Outcome

- `RPA_HARNESS_CAPTURE_ENABLED=false` 时，用户页面和录制链路保持零可感知影响。
- Harness capture 只能显式开启，并支持 Full SOP Capture 与 Selected Step Capture。
- 资产以统一 step checkpoint 格式沉淀：URL、HTML、step intent、trace evidence、expected signals、before/after state。
- 核心链路改动可以运行 snapshot regression、compiler regression、asset catalog、blast-radius、asset validation。
- 捕获资产默认 local-only/draft，进入仓库或 active 状态前必须人工确认 sensitivity 与完整性。

## Non-goals

- 不构建重型 contract-first 录制层。
- 不把 live URL 当作主要回归 oracle。
- 不为 GitHub、百度或任何单一页面形态写核心架构分支。
- 不把空输出、弱 selector、慢加载等稳定性问题变成录制主路径硬拦截。
- 不把 RPA Harness 变成通用 diagnostics export 产品。

## Feature Sequence

| Slice | Commit | Capability |
| --- | --- | --- |
| F0 | `81e3f67` | Harness v0 design, scenario schema, regression strategy, implementation plan |
| F1 | `9b396d7` | Zero-impact config gate and asset models |
| F2 | `7b3a2d9` | Capture session and Full SOP / Selected Step skeleton |
| F3 | `1836d97` | Step before/after HTML checkpoint capture |
| F4 | `4a40f45` | Expected signal draft generation |
| F5 | `e63b3fc` | Snapshot regression runner |
| F6 | `5dd5d25` | Compiler regression runner |
| F7 | `ca2bddb` | Trace-first AI recording checkpoint integration |
| F8 | `77dcef1` | RecorderPage opt-in capture controls |
| F9 | `58dc4e9` | Asset catalog and scenario coverage report |
| F10 | `a62362a` | Combined regression blast-radius report |
| F11 | `a967d0b` | Selected-step capture state sync |
| F12 | `f1ad336` | Scenario manifest and lifecycle persistence |
| F13 | `74f2ce7` | Full SOP manual trace checkpoint capture |
| F14 | `f03ba6f` | Extraction/dataflow expected-signal enrichment |

Post-F14 self-bootstrap fixes are tracked in `EV-002`, including UTF-8 CLI output, Full SOP entry navigation capture, selected-step UI state, pure navigation checkpoint capture, and asset integrity validation.

## Acceptance

- Feature slices are independently committed and pushed.
- Each slice has tests or runner output recorded in Evidence.
- Asset validation reports missing or incomplete checkpoint chains before snapshot/compiler results are interpreted.
- Snapshot/compiler regression can run over local captured HTML assets without depending on live URL state.
- Independent Vision review rejects site-specific architecture drift.
- Harness closeout records residual findings instead of calling the Feature done only because tests pass.

## Current State

Active. F0-F14 implementation is present in code and commits, but the Feature/Evidence/Lesson materials were created retroactively after a user-reported Harness process miss. This means the code capability exists, but the project memory trail before this recovery commit was incomplete.

The current recovery state is:

- Feature anchor: this document.
- Evidence: `docs/evidence/EV-002-rpa-harness-v0.md`.
- Process lesson: `docs/lessons/LL-001-harness-feature-evidence-closeout-miss.md`.
- Backlog state: `docs/BACKLOG.md`.

## Residual Risks

- Some local captured assets still report regression findings: one snapshot expected-signal miss and one compiler hardcoded observed value finding.
- `docs/superpowers/plans/2026-05-17-rpa-harness-v0-implementation.md` was partially updated during implementation and should be treated as a plan/history artifact, not the sole source of completion truth.
- A deterministic `knowledge_check.py` script is absent in this repo, so closeout currently relies on manual document consistency checks.

## Next Step

Before any further RPA Harness feature work, run the recovery checks recorded in `EV-002`, then decide whether the residual snapshot/compiler findings should become F002 follow-up slices or separate bug reports.
