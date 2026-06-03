---
id: F021
doc_kind: feature
status: active
created: 2026-05-30
updated: 2026-05-30
---

# F021: RPA Harness Asset Sensitivity Scan

## Goal

为 RPA Harness 资产增加确定性的敏感信息扫描能力，并把扫描结论写入资产 `review.md`。该能力同时定义脱敏后资产如何保留 SOP 与 Skill replay 价值：资产可以隐藏真实敏感值，但必须保留字段角色、数据形态、运行时 secret 引用或 controlled fixture 入口，让回归脚本仍能触发执行并验证语义。

## Vision Anchor

- 原始请求：用户确认敏感扫描是 Harness 必须完善的能力，要求提供扫描工具、把结论写入 `review.md`，并考虑账号密码、交易金额等敏感网页在脱敏后如何保持资产价值和可执行性。
- 用户痛点：当前 Harness 只有 `sensitivity_reviewed` 治理字段和人工确认开关，没有确定性扫描报告；Agent 临时扫描不可重复、不可审计，也不能证明脱敏资产仍可 replay。
- 期望结果：`run_asset_sensitivity_scan` 能输出结构化风险报告，`run_asset_review` 能展示扫描结论；脱敏资产通过占位符、语义类型和运行时 secret/fixture contract 保留可执行 replay 价值。
- 非目标或边界：第一切片不做全自动资产重写，不把扫描器变成杀毒软件，不用站点特定规则决定 promotion，不自动把资产升为 `candidate` 或 `golden`。
- Exit Gate 对照来源：本 Feature、[EV-021 RPA Harness Asset Sensitivity Scan Evidence](../evidence/EV-021-rpa-harness-asset-sensitivity-scan.md)、[F010 Assisted Asset Review And Promotion Pipeline](F010-assisted-asset-review-and-promotion-pipeline.md)、[F015 RPA Harness v1 Asset Lifecycle Operationalization](F015-rpa-harness-v1-asset-lifecycle-operationalization.md)、[RPA Harness 资产录制与审查最小流程](../rpa/harness/资产录制与审查最小流程.md)。

## Current Status

Active。2026-05-30 第一切片已实现并本地验证。Harness 现在提供确定性敏感扫描 CLI，默认把单资产扫描报告写入资产目录的 `sensitivity_scan.json`；`review.md` 会展示扫描结论，`expected.json` 可通过 `state_signals.sanitization_contract` 表达脱敏后 replay 价值。

## Entry Gates

Start Gate:

- Task class: high-risk.
- Risk triggers: Harness 资产治理、敏感信息、repo-safe 边界、脱敏后 replay 可信度、review packet 结论可审计性。
- Delegation decision: not needed；第一切片边界清楚，主代理可按 TDD 实现。
- Bug attribution: new F021 capability slice. 这是 F010/F015 资产审查治理后的能力缺口，不是某个已完成 Feature 的窄 bugfix。
- Required pre-work: 创建 F021/EV021/Plan；检索 F010/F015/F020、资产最小审查流程；按 TDD 写 RED tests 后实现。

Knowledge Retrieval:

- F010 已建立 assisted review / promotion pipeline，但没有敏感扫描器。
- F015 已把 lifecycle、candidate-lite、candidate/golden promotion guardrails 落地，`candidate` 仍要求 expected/sensitivity 人工确认。
- `资产录制与审查最小流程.md` 明确 `sensitivity` 不是自动保证无敏感数据，`sensitivity_reviewed` 是人工确认。
- F020 最近扩展了真实资产 review packet 事实展示，说明 review packet 是此类治理事实的合适入口。

## Links

- Evidence: [EV-021 RPA Harness Asset Sensitivity Scan Evidence](../evidence/EV-021-rpa-harness-asset-sensitivity-scan.md)
- Plan: [F021 implementation plan](../rpa/harness/f021-asset-sensitivity-scan-plan.md)
- Asset Review Flow: [RPA Harness 资产录制与审查最小流程](../rpa/harness/资产录制与审查最小流程.md)
- Review Pipeline: [F010 Assisted Asset Review And Promotion Pipeline](F010-assisted-asset-review-and-promotion-pipeline.md)
- Lifecycle: [F015 RPA Harness v1 Asset Lifecycle Operationalization](F015-rpa-harness-v1-asset-lifecycle-operationalization.md)

## Acceptance Criteria

- [x] 新增确定性敏感扫描模块，可扫描单个或多个 Harness asset。
- [x] 新增 CLI `run_asset_sensitivity_scan`，输出 JSON 报告并支持 `--asset-id` 与 `--output`。
- [x] 扫描报告能分类 secret/token、auth/session、credential/password、financial、PII、local-path、sanitized-placeholder、public-web-noise。
- [x] 扫描报告能给出 repo-safe 阻断、local-only 建议、人工确认建议和脱敏建议。
- [x] `run_asset_review` 生成的 `review.md` 包含 Sensitivity Scan 区块。
- [x] 脱敏资产可以通过占位符、语义类型、runtime secret 引用或 controlled fixture contract 表达 replay 价值。
- [x] Focused tests 覆盖扫描、review 注入、脱敏 replay contract。
- [x] EV-021 记录 RED/GREEN 命令、验证结果和剩余风险。

## Patch History

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F021.1 | 2026-05-30 | pending | 用户指出扫描报告输出到仓库临时路径，不在对应资产目录，削弱资产可追溯性。 | CLI 第一版只支持显式 `--output` 或 stdout，没有默认 sidecar 输出策略。 | Added focused RED/GREEN test for default `<asset_dir>/sensitivity_scan.json` output; CLI now writes per-asset sidecars when `--output` is omitted. | implemented |
| F021.2 | 2026-05-30 | pending | 重新扫描同一资产时，已有 `sensitivity_scan.json` 被纳入扫描输入，导致 public-web-noise 数量膨胀。 | Scanner 的文本文件枚举包含资产目录下所有 `.json`，没有排除自身生成的 sidecar/report 文件。 | Added RED/GREEN test proving generated sidecar reports are ignored; scanner now skips `sensitivity_scan.json` and `review_generation_report.json`. | implemented |
| F021.3 | 2026-05-30 | pending | `review.md` 在预览器中显示无法渲染。 | Review packet 把长输出和区域局部文本塞入单行 Markdown / 表格单元格，部分渲染器对超宽行不稳定。 | Added render-safe RED/GREEN test; review rendering now truncates long display text and caps generated lines while preserving raw facts in trace/HTML/scan sidecars. | implemented |
| F021.4 | 2026-05-30 | pending | Suggested Promotion 没有显式引用 Sensitivity Scan，审查者需要手动拼接扫描风险和升级建议。 | Review packet 的升级建议只看 lifecycle/governance 字段，没有消费扫描报告的 `repo_safe_blocked` 与 `sanitized_replay_contract`。 | Added RED/GREEN test; Suggested Promotion now states scan blockers and keeps candidate-lite as observation while discouraging blocking candidate/repo-safe/golden until sensitivity blockers are addressed. | implemented |

## Patch Churn Review

F021 出现 3 个 follow-up，不是扫描模式方向错误，而是第一切片把“生成报告”先落地后，真实资产使用暴露了报告生命周期边界：

- F021.1 说明报告应作为资产 sidecar，而不是临时仓库输出。
- F021.2 说明 sidecar 进入资产目录后，扫描输入边界必须排除自身生成物。
- F021.3 说明 review packet 是人类审查入口，必须是 render-safe 摘要，而不是 raw evidence dump。
- F021.4 说明审查入口必须把扫描事实转化为升级建议，而不是让人手动拼接区块。

当前收敛后的边界是：`sensitivity_scan.json` 承载机器可读详细扫描事实；`review.md` 只承载可渲染的人类摘要；raw HTML/trace/expected 继续作为原始证据。后续如果继续扩展，应优先做 sanitized asset 副本/脱敏建议生成，而不是继续扩大 `review.md` 内容量。

## Evidence

See [EV-021 RPA Harness Asset Sensitivity Scan Evidence](../evidence/EV-021-rpa-harness-asset-sensitivity-scan.md).

## Next Step

进入人工 review。下一步可以继续做第二切片：基于扫描报告生成脱敏建议补丁或 sanitized asset 副本，但仍应避免自动覆盖 raw evidence。
