---
id: EV-027
doc_kind: evidence
scope: project
feature_refs:
  - F026-rpa-agent-scienceclaw-host-rebuild
created: 2026-07-17
---

# EV-027：CoreTrace 到 SKILL 编译链路设计基线验证

## Supports Claim

本 Evidence 支撑以下有限声明：CoreTrace 到 SKILL 的编译设计已经完成用户分节评审并形成可恢复规格；规格覆盖非兼容边界、Compiler、RunContext、Page/Frame/Effect、Action 编译矩阵、准入与失败规则、SKILL 产物以及首个 E2E 验收标准，可以作为后续实现 Goal 的输入。

## Verification Scope

本次验证覆盖：

- 外部设计目录与 ScienceClaw worktree 内规格镜像的一致性；
- F026 中原有编译未决项、Acceptance Criteria、Current Status、Recovery Snapshot 和 Next Step 的更新；
- 规格是否明确拒绝旧 Trace、旧 Compiler、旧 Skill 和旧运行协议兼容；
- 规格是否包含已讨论的 Action Matrix、校验规则、失败规则、Skill 产物与验收边界；
- Markdown/Git 基础差异检查和 AgentMentor Feature 结构检查。

不覆盖任何新 `backend/rpa_agent` 代码、生成 Skill、浏览器回放、双 fixture E2E 或后端 Oracle。

## Checks

```text
Get-FileHash -Algorithm SHA256 \
  "E:\RPA-Agent\docs\design\RPA Agent CoreTrace 到 SKILL 编译链路设计基线.md" \
  "docs\superpowers\specs\2026-07-17-RPA-Agent-CoreTrace到SKILL编译链路设计基线.md"

rg -n "^#|^##|^###" \
  "E:\RPA-Agent\docs\design\RPA Agent CoreTrace 到 SKILL 编译链路设计基线.md"

rg -n "Open questions|编译链路|Current Status|Known risks|Next safe action|## Next Step" \
  docs/features/F026-rpa-agent-scienceclaw-host-rebuild.md

git diff --check

python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py \
  --root E:\RPA-Agent\.worktrees\ScienceClaw\rpa-agent-v1-coretrace \
  --docs-path docs --strict
```

## Results

- Pass：外部设计材料与仓库镜像的 SHA-256 均为 `4D5C0E9E2281488C9D8E3B2DCDE2054609B9C5D51D63D27A3CFC4325C048361F`。
- Pass：规格包含 15 个顶层章节，覆盖从第一性原理、ScienceClaw 复用边界到后续 Goal 验收标准的完整链路。
- Pass：F026 已将 Skill Input/RunContext、Page/Frame/Effect 和 CoreTrace 到 Skill 产物链路标记为已确认，不再作为未决项。
- Pass：`git diff --check` 无空白错误。
- Partial：AgentMentor 全仓 strict check 已执行，扫描 258 个 Markdown、61 个知识制品并发现 593 条历史格式错误；错误集中在旧 ADR、F001–F024 和 EV-001–EV-024。过滤输出未报告 F026 或 EV-027 自身错误。本次不扩展范围修复历史知识库格式债务。

## Artifacts

- [CoreTrace 到 SKILL 编译链路设计基线](../superpowers/specs/2026-07-17-RPA-Agent-CoreTrace到SKILL编译链路设计基线.md)
- [F026：RPA Agent 基于 ScienceClaw 宿主重构](../features/F026-rpa-agent-scienceclaw-host-rebuild.md)
- 外部设计材料：`E:\RPA-Agent\docs\design\RPA Agent CoreTrace 到 SKILL 编译链路设计基线.md`
- 外部设计索引：`E:\RPA-Agent\docs\design\README.md`

## Limitations

本 Evidence 只能证明设计规格已形成、被用户确认并可由后续 Agent 恢复，不能证明：

- CoreTrace Compiler 已经实现；
- ScienceClaw 新宿主协议已经改造；
- 任何 Action Renderer、RunContext、PageRegistry 或 EffectCoordinator 已经可运行；
- 生成 SKILL 可以回放；
- Replay A、Replay B 或后端 Oracle 已经通过；
- DataAsset、分页循环、阶段二执行器或通知能力已经设计或实现。

因此 F026 保持 `In Progress`，实现完成声明仍必须由后续纵向 E2E Evidence 支撑。

## Notes

用户明确要求当前会话不产出 Harness 工程设计、实施计划或团队任务拆分，而是把规格与验收标准作为后续新会话 Goal 的输入。`browser_segment.py` 不是能力必需项，但经讨论后在 V1 产物中保留，用于隔离稳定入口与阶段一生成代码；它不得成为运行时 CoreTrace 解释器。
