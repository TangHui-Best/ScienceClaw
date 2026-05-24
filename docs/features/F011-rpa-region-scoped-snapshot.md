---
doc_kind: feature
id: F011
title: RPA Region-Scoped Snapshot
status: ready_for_review
feature_ids: [F011]
created: 2026-05-19
updated: 2026-05-24
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

Ready for review after PR #55 follow-up. RegionScope conversion, region-prioritized raw snapshot capture, scoped compression, RecordingRuntimeAgent planner wiring, and trace scope evidence are implemented. The review blockers are resolved: compiled replay no longer injects recorded `region_context`, geometry fallback is frame-safe, `region_scoped_snapshot` enforces budget trimming above the minimum identity payload, and empty extract values are valid by default unless explicitly required/non-empty. Backend F011 verification passes in the shared Python 3.12 environment.

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
- 2026-05-20: PR #55 blocking review follow-up opened. Accepted review findings: compiled replay must not inject recorded `region_context`; geometry fallback must respect `frame_path`; `region_scoped_snapshot` must enforce `char_budget` while keeping identity and selected evidence; extract-snapshot empty values must be diagnostics by default, failing only for explicit required/non-empty contracts.
- 2026-05-20: PR #55 follow-up fixed and re-verified. Compiler/replay now treats selected-region local text as snapshot field evidence when fields exist and as plain runtime semantic replay without recorded region context otherwise; scoped geometry fallback rejects same-coordinate regions in other iframes; scoped compression trims low-priority context under budget; extract_snapshot no longer treats empty outputs as failure unless a field is required or non-empty output is explicit.
- 2026-05-22: Manual validation follow-up fixed for selected GitHub repository About text. Raw and compact `region_scoped_snapshot` already contained the selected free text, but the planner produced successful `run_python` code that located by the exact observed text, so the compiler embedded recording-time content into replay. Compiler replay now treats region-backed free-text extraction without structured snapshot fields as runtime semantic replay, while preserving structured table/list/single-value region compilation and action evidence paths. Runtime planner guidance now names `region_scoped_snapshot` and forbids exact observed selected text as replay selector logic.
- 2026-05-22: Added a narrower deterministic compile path for heading-scoped selected text. `region_scoped_snapshot` now preserves ancestor heading evidence for selected text regions; `RecordingRuntimeAgent` records a `region_text_extract` signal only when the compact snapshot has both context heading evidence and selected text evidence; `TraceSkillCompiler` compiles that signal to a same-sibling text-block extraction (`following_sibling_block`) instead of replaying runtime AI. This remains a generic section-text contract, not a GitHub About template, and still falls back to runtime AI when the accepted trace lacks the heading-scoped evidence.
- 2026-05-23: Fixed the section-text contract after manual validation generated a deterministic script anchored on `Topics` and returned an empty About result. The root cause was that selected in-region headings were emitted as generic text while nearby/downstream headings were emitted as `context_headings`, and the accepted trace promoted `context_headings[0]` into replay anchor evidence. Scoped compression now separates `inside_headings`, `selected_body_texts`, `before_context_headings`, `after_context_headings`, and an explicit `section_anchor`. Accepted traces only create `region_text_extract` from `section_anchor` with `inside_heading` or `preceding_heading` relation, and the compiler only scripts `bounded_section_text`; after-context headings fall back to runtime AI.
- 2026-05-24: Added backend evidence hardening for region-scoped free-text extraction. The current `runtime_ai_missing_anchor` fallback direction is accepted because replay must not hard-code recording-time selected text when no reusable section/container anchor exists. Do not narrow `_looks_like_extract_instruction()` markers such as `获取` / `读取` / `get` / `read` yet; the stronger preconditions already limit this path to region-scoped, non-action, non-table/list/single-value traces without snapshot fields and with extract intent. Backend compiler tests now prove the compile classification boundary; runner-backed eval or manual recording/compile artifacts remain pending.

## Patch Churn Review

2026-05-19: F011 已出现多次手动验证后补丁，按 Harness 归零审视要求重新检查失败轨迹。前两类失败分别暴露了诊断证据不足、选区内 standalone text 未进入 compact candidate；这些修复都移动到诊断/压缩边界，而不是新增站点规则。最新失败的诊断显示 raw snapshot 与 compact `region_scoped_snapshot` 都已经包含目标 star 文本，因此不应继续修改 snapshot compression、prompt 或 selector。当前修复上移到 planner JSON contract 边界：对缺少 runner wrapper 但引用 `page`/`await`/`results` 的 top-level runtime code 做窄包装，使其进入真实执行/repair；非 runtime Python-like 片段仍保持 contract failure。独立 Vision Gate / Patch Churn reviewer 结论为 pass，建议已落实为窄判定测试。无需 ADR；复发保护由 RED/GREEN regression tests 与 EV-011 证据承担。

2026-05-22: The GitHub About follow-up was split into two layers after comparing raw/compact evidence. First, region-backed free-text extraction without structured evidence must not embed selected observed text in replay, so it stays runtime semantic. Second, if compact snapshot already carries a reusable ancestor heading and selected text evidence, the accepted trace can record a narrow `heading_scoped_text` contract and the compiler can emit deterministic section-text extraction. Independent review flagged global `following::*` as too broad; the final compile strategy is explicitly `following_sibling_block`, which avoids crossing unrelated document regions while keeping the MVP independent from GitHub-specific selectors. Stronger container-bounded section extraction remains a possible follow-up when capture can provide stable container locators.

2026-05-23: The next manual validation exposed that `following_sibling_block` was still too optimistic because the accepted trace had no proof that the chosen heading was the selected text's section anchor. The fix moved the invariant upstream: deterministic compile is now gated by an explicit `section_anchor` relation, not by arbitrary `context_headings`. This reduces patch churn by making downstream compiler behavior depend on a durable evidence contract. GitHub-specific selectors remain rejected; if the capture/compression layer cannot prove a valid section anchor, replay uses runtime AI instead of compiling a fragile empty-result script.

## Evidence

- [EV-011 RPA Region-Scoped Snapshot Evidence](../evidence/EV-011-rpa-region-scoped-snapshot.md)

## Next Step

Turn the `/section-texts` manual fixture into reproducible eval/recording evidence: either add golden eval cases or save manual region-selection recording/compile artifacts that show heading + body compiles deterministically, after-context-only heading preserves runtime AI or avoids heading-scoped signal generation, and complex nested container text remains `runtime_ai_missing_anchor` until capture/compression can prove a durable container anchor. The long-term direction is to reduce `runtime_ai_missing_anchor` by moving more free-text cases into deterministic section/container extraction only after anchor evidence exists. Keep the strict-mode locator repair issue as a separate follow-up because it belongs to runtime repair/locator disambiguation, not region-scoped snapshot capture or compression.
