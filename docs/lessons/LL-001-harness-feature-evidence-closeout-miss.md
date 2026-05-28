---
id: LL-001
doc_kind: lesson
status: active
scope: project
source_feature_ids: [F002]
feature_refs:
  - docs/features/F002-rpa-harness-v0.md
applies_to: [harness-closeout, multi-slice-feature, evidence-gate]
created: 2026-05-18
updated: 2026-05-22
---

# LL-001: Harness Feature Evidence Closeout Miss

## Pitfall

多 slice / high-risk 工作不能把 implementation plan、commit 序列或聊天记录当成 Feature/Evidence closeout。计划说明“怎么做”，commit 说明“改了什么”，但它们不能替代 Feature 的愿景/状态，也不能替代 Evidence 的验证、review、残留风险和门禁结果。

## Root Cause

F0-F14 开发过程中，执行者把 `docs/superpowers/plans/2026-05-17-rpa-harness-v0-implementation.md` 的 checklist 和每个 slice 的 commit/push 当成了足够的 Harness 约束，跳过了 F002 Feature、EV-002 Evidence、Lesson、Backlog 的同步更新。旧版执行依赖 agent 自觉，没有在项目内或系统级 validator 上形成每个 slice 的硬检查。

## Trigger

用户在回顾 RPA Harness v0 开发过程时指出：F01 到 F14 没有沉淀 Feature 等相关材料，没有遵从 Harness skill。随后使用系统级 `knowledge_check.py` 验证，确认 F001/F002/EV/ADR/LL 文档结构不符合最新 Harness 模板。

## Fix

本次恢复直接修正现有 Harness artifacts，而不是新增重复 Lesson：

- `docs/features/F002-rpa-harness-v0.md` 成为 RPA Harness v0 的 Feature anchor。
- `docs/evidence/EV-002-rpa-harness-v0.md` 记录 F0-F14、post-F14 fixes、系统级 validator 路径/输出和残留风险。
- 本 Lesson 保留过程事故根因和防复发机制。
- `docs/BACKLOG.md` 记录 F002 active 状态和下一步。
- 后续使用系统级 bundled validator：`C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py`。

## Protection

后续 multi-slice / high-risk 工作必须遵守：

1. 开始前创建或更新 active Feature page。
2. 每个 slice 开始前确认 Feature/Evidence 当前状态。
3. 每个 slice 完成后，在 Evidence 记录 commit、验证命令、结果、review 状态和 residual risk，再进入下一 slice。
4. 如果 closeout 缺失，只能报告 `implementation done, harness closeout pending`，不能继续声明 ready/completed。
5. 使用系统级 bundled scripts/templates；不要求项目先复制 Harness scripts/templates，除非未来接 CI、GitHub Actions 或离线策略。

## Recurrence

2026-05-22: F012 `live_agent_eval` initially shipped implementation, tests,
usage guide, and Backlog recovery context, but missed formal Feature/Evidence
capture until the user asked why the Feature document was absent. This was the
same failure class as LL-001: implementation evidence existed, but the
completion path treated a lightweight Backlog anchor as enough for a
non-trivial Harness capability.

Additional protection:

1. For any new Harness runner, validation mode, asset lifecycle change, or
   Agent/RPA behavior boundary, create or update the owning Feature/Evidence
   before the final commit/push or explicitly report `implementation done,
   harness closeout pending`.
2. In the final self-check, verify the changed-files list includes either an
   existing Feature/Evidence update or a documented reason why the task is too
   small to need one.
3. A Backlog item may record recovery state, but it does not replace
   Feature/Evidence for a new durable Harness capability.

## Source

- User report: “F01 到 F14 没有沉淀 Feature 等相关材料，没有遵从 harness 相关 skill。”
- Feature: [F002 RPA Harness v0](../features/F002-rpa-harness-v0.md)
- Evidence: [EV-002 RPA Harness v0 Evidence](../evidence/EV-002-rpa-harness-v0.md)
- Backlog: [Backlog](../BACKLOG.md)
- Recovery commit before template migration: `63107f8 docs: recover rpa harness feature evidence`

## Principle

Harness 的门禁必须留下可验证的项目记忆。计划、测试和 commit 都是证据输入，但 Feature/Evidence closeout 才是后续 agent 能恢复目标、验收状态和残留风险的入口。
