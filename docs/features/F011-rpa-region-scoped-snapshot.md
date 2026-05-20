---
doc_kind: feature
id: F011
title: RPA Region-Scoped Snapshot
status: ready_for_review
feature_ids: [F011]
created: 2026-05-19
updated: 2026-05-20
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

Ready for review / readiness pass. RegionScope conversion, region-prioritized raw snapshot capture, scoped compression, RecordingRuntimeAgent planner wiring, and trace scope evidence are implemented. Backend F011 verification passes in the provisioned Python 3.12 environment, F011 frontend region-selection tests pass after installing worktree dependencies, production frontend build passes, and the user has manually validated the local service flow. Remaining failures are pre-existing project-level frontend type debt / npm audit debt, not F011 scoped snapshot blockers.

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
- 2026-05-19: Added generic planner failure debug dumps for initial/repair planner contract failures so invalid JSON/code responses persist with compact snapshot summary, raw-vs-compact presence comparison, and LLM call summary. Independent review requested repair-path coverage; direct initial and repair tests now cover the artifact path. This is diagnostic-only and does not change planner, prompt, selector, UI, or replay behavior.
- 2026-05-19: Fixed region-scoped action-group compression after manual validation showed selected standalone text (`1,027 stars today`) was present in raw snapshot but missing from compact expanded evidence, while an outside same-card action (`star 37,451`) remained available as a candidate. Scoped action groups now preserve selected text evidence and filter outside actions from expanded candidates.
- 2026-05-19: Fixed planner contract handling after manual validation showed raw and compact region-scoped snapshots both contained the selected repository star text (`3,184 stars today`), but the planner returned a valid JSON plan whose `code` field was top-level Playwright Python lacking `async def run(page, results)`. The runtime now narrowly wraps top-level `run_python` code only when it references recording runtime context (`page`, `await`, or `results`), leaving non-runtime or invalid code as planner contract failures.

## Patch Churn Review

2026-05-19: F011 已出现多次手动验证后补丁，按 Harness 归零审视要求重新检查失败轨迹。前两类失败分别暴露了诊断证据不足、选区内 standalone text 未进入 compact candidate；这些修复都移动到诊断/压缩边界，而不是新增站点规则。最新失败的诊断显示 raw snapshot 与 compact `region_scoped_snapshot` 都已经包含目标 star 文本，因此不应继续修改 snapshot compression、prompt 或 selector。当前修复上移到 planner JSON contract 边界：对缺少 runner wrapper 但引用 `page`/`await`/`results` 的 top-level runtime code 做窄包装，使其进入真实执行/repair；非 runtime Python-like 片段仍保持 contract failure。独立 Vision Gate / Patch Churn reviewer 结论为 pass，建议已落实为窄判定测试。无需 ADR；复发保护由 RED/GREEN regression tests 与 EV-011 证据承担。

## Evidence

- [EV-011 RPA Region-Scoped Snapshot Evidence](../evidence/EV-011-rpa-region-scoped-snapshot.md)

## Next Step

Open review against upstream `master`. Keep the strict-mode locator repair issue as a separate follow-up because it belongs to runtime repair/locator disambiguation, not region-scoped snapshot capture or compression.
