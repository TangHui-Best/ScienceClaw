---
id: F022
doc_kind: feature
status: active
created: 2026-05-30
updated: 2026-05-30
---

# F022: RPA Harness 脱敏资产副本

## Goal

让 RPA Harness 可以从 raw captured asset 生成独立的 sanitized asset copy，并验证脱敏副本仍保留 SOP / Skill replay 的可执行价值。

核心边界：

- 不覆盖 raw asset；raw 仍是录制事实源。
- 脱敏副本使用独立 `asset_id`，默认 `<asset_id>-sanitized`。
- 脱敏副本写入 `sanitization_report.json` 和 `expected.json` 的 `state_signals.sanitization_contract`。
- 脱敏副本可以重新生成 `sensitivity_scan.json`、`review.md` 与执行审查用的 `execution_review.md`。
- 脱敏不会自动等于 `repo-safe` 或 `candidate/golden`；仍需人工确认 expected signals 和 sensitivity。

## Vision Anchor

- 原始请求：用户认可 F021 敏感扫描能力后，要求继续做敏感信息脱敏，并验证脱敏后资产是否还能被脚本化执行、模拟真实 SOP 录制价值。
- 用户痛点：只扫描不脱敏，资产仍无法安全共享或进入更高等级回归路径；直接改 raw asset 又会破坏录制事实。
- 期望结果：生成派生资产，将真实敏感值替换为语义占位符，例如 `<EMAIL_1>`、`<LOCAL_PATH_1>`、`<SESSION_ID_1>`、`<AMOUNT_1>`，同时保留字段语义、输出形态和 replay assertions。
- 非目标：不自动提升到 blocking candidate/golden；不把 public web noise 当成业务敏感值强制阻塞；不修复 TraceSkillCompiler 的既有硬编码问题。

## Current Status

Active。第一切片已实现并验证：脱敏副本生成、敏感扫描、review 生成、validation/snapshot 消费均可用；compiler 仍暴露 Step2/Step4 的既有硬编码问题，deterministic profile 因 governance 未进入 blocking baseline 而拒绝选中。

## Entry Gates

- Task class: high-risk。
- Risk triggers: 派生资产生成、敏感信息脱敏、raw evidence 保留、runner 可执行性和 promotion 误判风险。
- Delegation decision: not needed；第一切片边界清晰，使用确定性 sanitizer 与 focused runner 验证。
- Bug attribution: new F022 capability slice after F021。
- Required pre-work: 创建 F022/EV022；按 TDD 写 RED tests；实现 sanitized copy CLI；用真实资产跑 scan/review/validation/snapshot/compiler/profile。

## Links

- Evidence: [EV-022 RPA Harness Sanitized Asset Copy Evidence](../evidence/EV-022-rpa-harness-sanitized-asset-copy.md)
- Previous Feature: [F021 RPA Harness Asset Sensitivity Scan](F021-rpa-harness-asset-sensitivity-scan.md)
- Asset Review Flow: [RPA Harness 资产录制与审查最小流程](../rpa/harness/资产录制与审查最小流程.md)

### Evidence

- Historical links remain in the original record; this migration adds the current navigation category.

### Decisions / ADRs

- Historical links remain in the original record; this migration adds the current navigation category.

### Lessons

- Historical links remain in the original record; this migration adds the current navigation category.

### Specs / Plans

- Historical links remain in the original record; this migration adds the current navigation category.

### Related Features

- Historical links remain in the original record; this migration adds the current navigation category.

### External Context

- Historical links remain in the original record; this migration adds the current navigation category.

## Acceptance Criteria

- [x] 新增确定性 sanitizer，可以从 raw asset 生成 sanitized asset copy。
- [x] raw asset 不被覆盖；sanitized copy 有独立 `asset_id`。
- [x] sanitized copy 的 `scenario.json` 标记 `sensitivity=sanitized`，并记录来源 raw asset。
- [x] 敏感命中被替换为语义占位符，例如 `<EMAIL_1>`、`<LOCAL_PATH_1>`、`<SESSION_ID_1>`。
- [x] `expected.json` 写入 `state_signals.sanitization_contract`，表达 replay assertions 与 placeholders。
- [x] sanitized copy 扫描后不再出现 repo-safe blocking findings。
- [x] sanitized copy 可生成 `review.md`，并可被 Harness validation/snapshot/compiler/profile 消费。
- [x] scanner/sanitizer 覆盖 HTML 渲染或 JSON 转义后的 Windows 本地路径。
- [x] execution runner 的 JSON 结果可汇总为人类可读的 `execution_review.md`，并显式区分 Harness 离线入口与真实 UI/RPA 服务入口的模型配置注入边界。
- [x] EV-022 记录 RED/GREEN、真实资产运行结果和剩余风险。

## Patch History

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F022.1 | 2026-05-30 | pending | 脱敏资产仍可能保留 GitHub README 中被 HTML span 拆开的 Windows 路径 | scanner/sanitizer 只覆盖普通 `C:\...` 文本，未覆盖 `C:<span>\\</span>Users` 与 `C:\\Users` 转义形态 | 新增 scanner 与 sanitizer 回归测试，识别并整体替换 HTML-rendered / escaped local path | implemented |
| F022.2 | 2026-05-30 | pending | execution runner 会生成多个 JSON，人工审核不容易判断 SOP→Skill 链路失败原因；模型凭证失败也容易被误读成项目 `.env` 没配置 | 缺少类似 `review.md` 的执行审查汇总，且 runner 没有把真实 UI/RPA 服务入口的 `model_config` 注入边界写清楚 | 新增 `run_asset_execution_review` 与回归测试，输出资产目录内的 `execution_review.md`，汇总 stateful/skill/compiler/snapshot 报告并标注服务入口差异 | implemented |
| F022.3 | 2026-05-31 | pending | stateful/skill replay 使用 generated Skill 时无法复用项目模型凭证，导致 Harness 执行链路出现 `Missing credentials` | Harness 离线 runner 只执行 generated Skill，未把真实服务入口解析出的 `model_config` 注入 `_model_config` / `_runtime_context.runtime_ai.model_config` | 新增 Harness-only `model_config` 参数与 CLI `--model-config-file` 透传，报告只记录 `runtime_ai_model_config_source` 不记录密钥；真实资产重跑后缺凭证失败消失 | implemented |

## Patch Churn Review

F022 的 3 个 follow-up 没有继续扩张敏感规则或站点规则，而是逐步把问题上移到 Harness 不变量：

- F022.1 修的是 scanner/sanitizer 对同一类敏感值不同编码形态的覆盖缺口，保护点是确定性测试。
- F022.2 修的是执行结果缺少人类可读审查入口，保护点是 `execution_review.md` 和报告生成测试。
- F022.3 修的是 Harness 离线 runner 与真实服务入口之间的 runtime AI 配置注入边界，保护点是 `model_config` 显式注入测试和 `runtime_ai_model_config_source` 报告字段。

当前剩余失败已经不属于脱敏或模型配置注入：真实资产 rerun 后缺凭证问题消失，失败集中在 TraceSkillCompiler 硬编码录制现场值与 replay 输出形态不匹配。下一次补丁不应继续增加脱敏/扫描规则；若继续推进，应创建或归属到 compiler/generalization 修复边界。

## Evidence

See [EV-022 RPA Harness Sanitized Asset Copy Evidence](../evidence/EV-022-rpa-harness-sanitized-asset-copy.md).

## Next Step

是否进入 blocking candidate/golden 仍需人工确认 expected signals 和 sensitivity。当前 stateful/skill replay 已支持 Harness-only 模型配置注入；真实资产重跑后缺凭证问题消失，剩余主问题是 TraceSkillCompiler 对 Step2/Step4 的硬编码生成以及 replay 输出形态不匹配。

## Feature Intake

- Original problem: The original problem is preserved in `## Goal` and `## Vision Anchor`; this migration does not reinterpret it.
- User pain point: The historical user pain point is preserved in the original Feature narrative and linked Evidence.
- Capability promise: The delivered or intended capability remains the one described in `## Goal` and `## Acceptance Criteria`.
- Non-goals: This migration adds no business scope and does not change the historical Feature boundary.
- Acceptance source: Existing acceptance criteria, linked Evidence, and recorded validation remain the source of truth.
- Open questions: Any historical uncertainty remains unresolved unless the original record or a linked successor answers it.

## Capability Contract

The capability boundary is the historical `## Goal`, `## Vision Anchor`, acceptance criteria, and linked artifacts. This schema migration does not add, remove, or reinterpret RPA behavior.

## Decision Context

### Why

The original Feature and its linked decisions preserve the rationale; this migration only makes that context recoverable through the current template.

### Why Not

Do not infer new product decisions from a document-schema migration or replace historical validation with template text.

### If Modifying This Area, Check

Read this Feature's Goal, Evidence, and linked ADRs before changing its capability boundary or claiming a new verification result.

## Acceptance Map

| Claim | Acceptance | Evidence | Status |
| --- | --- | --- | --- |
| Historical Feature contract | Existing `## Acceptance Criteria` and historical Feature record | Historical evidence documented in `## Evidence` | migrated |

## State Timeline

| Date | State | Trigger | Evidence | Note |
| --- | --- | --- | --- | --- |
| 2026-07-25 | active | AgentMentor schema migration | Existing Feature/Evidence | Historical facts retained; current required structure added |

## Recovery Snapshot

- Read first: `## Goal`, `## Links`, `## Acceptance Criteria`, and `## Evidence`.
- Current capability state: Use the existing `## Current Status`; this migration does not change delivery status.
- Known risks: Historical verification is limited to what the original record explicitly states.
- Next safe action: Read the linked Evidence and ADRs before any follow-up change; update this Feature when the capability boundary or verified state changes.
- Unblock condition: Not blocked by this migration.
