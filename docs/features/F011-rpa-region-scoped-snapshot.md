---
doc_kind: feature
id: F011
title: RPA Region-Scoped Snapshot
status: active
feature_ids: [F011]
created: 2026-05-19
updated: 2026-05-19
specs:
  - docs/superpowers/specs/2026-05-19-rpa-region-scoped-snapshot-design.md
plans:
  - docs/superpowers/plans/2026-05-19-rpa-region-scoped-snapshot.md
decisions: []
evidence:
  - docs/evidence/EV-011-rpa-region-scoped-snapshot.md
---

# F011 RPA Region-Scoped Snapshot

## Goal

让页面区域选择进入 RPA 录制的 snapshot 采集与压缩链路。用户框选区域后，下一条自然语言指令使用 `region_scoped_snapshot`，使选区内 DOM evidence 优先成为任务候选，选区外 DOM 只保留最小页面身份与恢复上下文。

## Vision Anchor

当页面元素过多导致自然语言录制指令执行不准确时，用户可以框选一个页面区域，让下一条指令使用 region-scoped snapshot：选区内 DOM evidence 优先采集和压缩，选区外 DOM 不参与任务候选竞争，只保留页面身份、父级定位、frame/dialog/heading 等最小恢复上下文。

## User Problem

当前 RPA 录制执行失败的主要原因之一不是 planner 完全不理解指令，而是目标 DOM 在 raw snapshot 采集上限、compact snapshot 过滤、region tiering 或上下文预算分配中被挤掉。旧的选区方案如果只把 `region_context` 作为 planner 旁路提示，无法从根上解决 DOM 压缩和候选竞争问题。

## Desired Outcome

- 选区默认只作用于下一条自然语言指令。
- 选区进入 snapshot 采集与压缩链路，而不是成为并行执行策略。
- planner 接收统一的 `region_scoped_snapshot`，选区内 evidence 是任务候选，选区外只作为上下文。
- accepted trace 保留 scope evidence，但 replay 不依赖坐标。
- 失败诊断可以区分采集失败、压缩失败、planner 误判和执行/locator 问题。

## Current Status

Active implementation slice. RegionScope conversion, region-prioritized raw snapshot capture, scoped compression, RecordingRuntimeAgent planner wiring, and trace scope evidence are implemented. Final readiness remains conditional on environment-complete verification because this worktree is missing `langchain_openai` and frontend `node_modules`.

## Links

- Spec: `docs/superpowers/specs/2026-05-19-rpa-region-scoped-snapshot-design.md`
- Related architecture: `docs/decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md`
- Related compiler boundary: `docs/decisions/ADR-002-trace-evidence-driven-compiler-strategy.md`

## Non-goals

- 不做持续作用域。
- 不以截图/VLM 或坐标点击作为主路径。
- 不新增站点规则、经验 selector 库或 contract-first 录制层。
- 不把 `region_context.py` 扩张成第二套 snapshot/compression/compiler 系统。

## Acceptance Criteria

- `docs/superpowers/specs/2026-05-19-rpa-region-scoped-snapshot-design.md` 被实现计划引用。
- 实现前创建或更新实施计划，并明确 capture、compression、runtime、frontend、trace/evidence 的切片。
- 实现后 Evidence 记录 targeted backend tests、frontend tests/type-check、以及至少一个 region-scoped debug artifact 示例。

## Patch History

- 2026-05-19: Implemented RegionScope conversion, scoped raw snapshot capture, `region_scoped_snapshot` compression, RecordingRuntimeAgent wiring, trace scope evidence, and focused backend regression coverage. Full readiness remains blocked by local verification dependencies documented in EV-011.

## Evidence

- `docs/evidence/EV-011-rpa-region-scoped-snapshot.md`

## Next Step

Resolve local verification environment gaps (`langchain_openai`, frontend dependencies) or rerun the blocked route/default-planner/frontend checks in a provisioned environment before marking F011 ready.
