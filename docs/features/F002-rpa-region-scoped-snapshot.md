---
doc_kind: feature
id: F002
title: RPA Region-Scoped Snapshot
status: active
feature_ids: [F002]
created: 2026-05-19
updated: 2026-05-19
specs:
  - docs/superpowers/specs/2026-05-19-rpa-region-scoped-snapshot-design.md
plans:
  - docs/superpowers/plans/2026-05-19-rpa-region-scoped-snapshot.md
decisions: []
evidence: []
---

# F002 RPA Region-Scoped Snapshot

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

Active design anchor. Implementation has not started.

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

No implementation patches yet.

## Evidence

No implementation evidence yet. This Feature currently links only the design anchor.

## Next Step

Review and approve the design, then create an implementation plan before touching code.
