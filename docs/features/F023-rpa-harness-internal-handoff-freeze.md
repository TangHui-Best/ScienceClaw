---
id: F023
doc_kind: feature
status: completed
created: 2026-05-31
updated: 2026-05-31
---

# F023: RPA Harness Internal Handoff Freeze

## Goal

完成 RPA Harness 从当前外网开发机切换到内网开发前的封箱加固：收束文档入口、清理过时活跃资料、提供资产池体检工具、补齐内网资产交接模板，并把 compiler / generalization 风险明确归属到 RPA core，而不是继续膨胀 Harness。

## Vision Anchor

- 原始请求或来源：用户明确说明后续将切换到内网开发，这台电脑上的 Harness 功能模块长期不会再有大迭代，要求依次完成内网接管/封箱手册、Asset Pool Doctor、内网资产录制最小模板、Compiler 风险显式归属。
- 用户痛点或工程问题：已有 Harness 文档和报告分散，部分历史材料仍写着过时 baseline 状态；当前资产池没有 blocking baseline，后续 Agent 容易误把 `candidate-lite`、generated full-live artifact 或历史报告当成可信回归基线。
- 期望结果：内网 Agent 可以从一个入口理解当前状态、运行最小体检、按模板交接真实资产，并知道 compiler hardcoded observed value 等问题应回到 `TraceSkillCompiler` / dataflow / RPA core 修复。
- 非目标或边界：不新增 Harness runner；不接 CI blocking；不自动 promotion；不修复 `TraceSkillCompiler` 泛化缺陷；不删除历史资料，只通过归档或入口收束降低误读风险。
- Exit Gate 对照来源：本 Feature、[EV-023](../evidence/EV-023-rpa-harness-internal-handoff-freeze.md)、[RPA Harness 内网接管与封箱指南](../rpa/harness/internal-handoff-and-freeze-guide.md)。

## Current Status

Completed. 本轮以一个 Feature 边界完成 4 个封箱切片：内网接管/封箱手册、Asset Pool Doctor、内网资产录制最小模板、Compiler 风险显式归属。验证结果沉淀在 EV-023。

## Entry Gates

Start Gate:

- Task class: high-risk.
- Risk triggers: Harness handoff semantics, document lifecycle, asset governance state, CLI behavior, future Agent recovery, and compiler ownership boundary.
- Delegation decision: single_agent. 4 个切片共享同一个封箱口径和 Evidence，拆分给多个实现 Agent 容易产生相互矛盾的状态判断；必要验证通过测试和 knowledge check 完成。
- Bug attribution: not triggered. 这是封箱增强与文档生命周期治理，不是已完成 Feature 的非微小 bugfix。
- Required pre-work: 创建 F023/EV023；执行知识检索；文档生命周期按 archive/superseded 处理；Asset Pool Doctor 按 TDD 先写失败测试。

Knowledge Retrieval:

- F018 说明 v1 closeout 的目标是清晰入口，不新增 runner、不接 CI blocking、不自动 promotion。
- F021/F022 说明 sensitivity scan / sanitized copy 已落地，但真实资产仍需人工 expected/sensitivity review。
- `docs/rpa/harness/usage-and-triage-guide.md` 说明 Harness 是回归与诊断层，不负责在 Harness 内修 planner/snapshot/compiler/selector/extraction 缺陷。
- 当前 `data/rpa_harness_assets_bootstrap` 运行 `run_catalog --format lifecycle` 显示没有 blocking baseline，只有 `candidate-lite` / `draft` 资产。

## Links

- Evidence: [EV-023 RPA Harness Internal Handoff Freeze Evidence](../evidence/EV-023-rpa-harness-internal-handoff-freeze.md)
- Handoff Guide: [RPA Harness 内网接管与封箱指南](../rpa/harness/internal-handoff-and-freeze-guide.md)
- v1 Entrypoint: [RPA Harness v1 Design](../rpa/harness/RPA-Harness-v1-设计.md)
- Usage and Triage: [RPA Harness 使用与问题定位指南](../rpa/harness/usage-and-triage-guide.md)
- Asset Review Flow: [RPA Harness 资产录制与审查最小流程](../rpa/harness/资产录制与审查最小流程.md)

## Acceptance Criteria

- [x] 新增一个内网接管/封箱单入口，说明当前状态、可信命令、资产治理路径和不可过度解释的边界。
- [x] 已完成或历史 phase plan 不再作为活跃入口；通过 archive 或 superseded note 降低检索误导。
- [x] 新增 Asset Pool Doctor CLI，默认快速读取资产池治理状态并给出下一步建议，不新增 runner、不自动 promotion。
- [x] Asset Pool Doctor 有 RED/GREEN 测试覆盖：无 blocking baseline、candidate-lite warning-only、有 blocking baseline 三类判断。
- [x] 新增内网资产交接模板和本地模型配置示例，说明哪些信息必须由人提供，哪些凭证不得提交。
- [x] 明确 compiler / generalization 风险归属为 RPA core follow-up，Harness 只暴露风险，不在 expected signals 或 replay fixture 中掩盖。
- [x] EV-023 记录验证命令、结果、残余风险和封箱后内网下一步。

## Patch History

No code patches after completion. This Feature is a freeze/handoff slice rather than a bugfix chain.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

See [EV-023 RPA Harness Internal Handoff Freeze Evidence](../evidence/EV-023-rpa-harness-internal-handoff-freeze.md).

## Next Step

封箱后下一步转入内网：录制 1-2 个真实 Full SOP asset，先生成 review/sensitivity 证据，再由人确认 expected signals 与 sensitivity 后提升到 blocking candidate。
