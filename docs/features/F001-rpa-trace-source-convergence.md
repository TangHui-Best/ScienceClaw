---
id: F001
doc_kind: feature
status: active
created: 2026-05-13
updated: 2026-05-27
---

# F001: RPA Trace Source Convergence

## Goal

把 RPA 录制、配置、生成、测试、保存和 MCP/export 的 accepted timeline 收敛到 `session.traces` / `RPAAcceptedTrace`，让 trace 成为唯一业务事实源，避免 step 系旧对象继续污染新路径契约、编译输入和诊断修复链路。

## Vision Anchor

- 原始目标：trace-first 方向已经确定，accepted timeline 不能继续同时依赖 `steps`、`recorded_actions`、`recording_diagnostics`、`legacy_steps` 和 step-index API。
- 用户/工程痛点：多事实源会让 timeline、编译器、repair、MCP/export 和 Harness 读取到不同对象，结果难以验收、追溯和恢复。
- 期望结果：新 session 只以 trace 和 trace diagnostic 驱动公共接口、删除/修复动作、编译、测试、保存和导出。
- 非目标：不引入 contract-first 录制层，不为单站点补规则，不通过重新启用 step fallback 掩盖 trace 证据缺口。
- Exit Gate 对照来源：`docs/superpowers/plans/2026-04-28-rpa-trace-first-full-migration.md`、`docs/superpowers/plans/2026-05-16-rpa-trace-source-final-convergence.md`、`docs/decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md`、`docs/decisions/ADR-002-trace-evidence-driven-compiler-strategy.md`。

## Current Status

Active。公共 session 投影、trace/diagnostic 删除修复、生成/测试/保存输入、MCP/export 主要路径已经切到 trace-first，但 F001 之后又出现了一串 follow-up hardening，集中在“trace 是唯一载体，但证据质量仍会让 repair/compiler 走错分支”这一层。当前分支的 7M/7N 系列补丁已经推送并有本地验证证据，但本次迁移没有重新观察最新远端 CI/PR 结果，因此状态不能写 Done。

## Links

- Evidence: [EV-001 RPA Trace Source Convergence Evidence](../evidence/EV-001-rpa-trace-source-convergence.md)
- ADR: [ADR-001 RPA Trace Is The Single Accepted Timeline](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md)
- ADR: [ADR-002 Trace Evidence Drives Compiler Strategy](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md)
- Legacy spec: `docs/superpowers/specs/2026-04-28-rpa-trace-first-full-migration-design.md`
- Legacy plan: `docs/superpowers/plans/2026-04-28-rpa-trace-first-full-migration.md`
- Legacy plan: `docs/superpowers/plans/2026-05-16-rpa-trace-source-final-convergence.md`
- Legacy spec: `docs/superpowers/specs/2026-05-12-rpa-sso-redirect-chain-compile-design.md`

## Acceptance Criteria

- [x] accepted timeline 的公共新路径只消费 `session.traces` / `trace_diagnostics` / `runtime_results`。
- [x] 删除、locator promotion、失败重试等公共修复动作使用 `trace_id` 或 `diagnostic_id`，不再依赖 step-index fallback。
- [x] compiler 不再从 output-only evidence、随机 testid 或过弱 frame evidence 发明确定性 replay 逻辑。
- [ ] 围绕 recording -> configure -> generate/test/save -> MCP/export 的最新全链路 smoke 需要结合 7M/7N follow-up 再做一次收口确认。
- [ ] 当前分支最近一次 GitHub Actions / PR 结果尚未在本次 closeout 中重新观察并写回证据。

## Patch History

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F001.1 | 2026-05-25 | `6b473f0` | 随机样式 `data-testid` 被当成稳定 replay locator，trace-first 仍会生成脆弱脚本。 | trace 已收敛为唯一载体，但 locator 证据质量没有被同样收敛到共享稳定性判定。 | `EV-001` 中的 locator stability / compiler focused tests。 | landed |
| F001.2 | 2026-05-25 | `cf53c19`, `18d529d`, `33b494e` | 仅仅拒绝随机 locator 后，Configure 会退化成 delete-only，用户丢失可回放 SOP 事实。 | repair 路径会拦坏证据，但没有补回稳定语义候选，也没有折叠非 SOP 的焦点点击。 | `EV-001` 中 recorder runtime candidate augmentation、diagnostic rejection、fill-folding 回归测试。 | landed |
| F001.3 | 2026-05-25 | `2c8ec5f`, `77d7f59`, `909b11f` | iframe 场景会生成 `about:blank` 新页或等待录制期动态 iframe selector。 | compiler 把 frame-context 证据误当成新 tab 物化证据，又把动态精确 iframe `src` 误当成稳定 selector。 | `EV-001` 中 frame-context compiler focused tests 与 full compiler suite。 | landed |
| F001.4 | 2026-05-26 | `c1628c9` | 新 tab opener 的 accepted trace 丢失 `signals.popup`，trace-only 编译无法生成 `expect_popup()`。 | popup 元数据异步补到旧 step 后，没有同步刷新 accepted trace。 | `EV-001` 中 popup signal sync manager tests 与相关 compiler regression。 | landed |
| F001.5 | 2026-05-26 | `8373def` | Configure 能展示 `page.locator(...).filter(has_text=...)` 修复候选，但后端无法真正采用。 | recording normalizer、repair path 和 compiler 没有共享 `filter_has_text` 这一 locator 规范形态。 | `EV-001` 中 normalizer / manager / compiler focused tests。 | landed |

## Patch Churn Review

F001 已经进入明显的 patch chain。复盘后可以看到，这些 follow-up 不是“trace-first 不成立”，而是“trace-only 载体上的证据分类和传播仍有空洞”。本轮迁移保留这一判断，不把问题倒退成 step-based fallback，也不为单站点补经验规则。当前保护策略是继续把事实差异显式化到 trace、repair 和 compiler 的共享证据边界，并用 focused regression tests 锁住，不再接受“先拦住再说”的校验型补丁。

## Evidence

- 主证据文档：[EV-001 RPA Trace Source Convergence Evidence](../evidence/EV-001-rpa-trace-source-convergence.md)
- 当前 patch chain 关联提交：`6b473f0`, `cf53c19`, `18d529d`, `33b494e`, `2c8ec5f`, `77d7f59`, `909b11f`, `c1628c9`, `8373def`
- 当前状态说明：本地 focused verification 已有记录；远端 CI evidence pending，因此 Feature 维持 active。

## Next Step

先检查 `origin/codex/rpa-region-selection-optimization-v2` 最近一次 GitHub Actions / review 结果，并把结果写回 `EV-001`。如果没有新增 blocker，就把 F001 剩余的全链路 smoke 和 MCP/export 收口验证补齐；如果有新增失败，要继续归因到现有 patch chain，而不是重新引入 step、legacy metadata 或站点特化 fallback。
