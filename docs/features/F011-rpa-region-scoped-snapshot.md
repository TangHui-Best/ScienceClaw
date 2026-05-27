---
id: F011
doc_kind: feature
status: active
created: 2026-05-19
updated: 2026-05-27
---

# F011: RPA Region-Scoped Snapshot

## Goal

让页面区域选择真正进入 RPA 录制的 snapshot 采集、压缩、accepted trace 和编译链路。用户框选区域后，后续自然语言指令应优先消费 `region_scoped_snapshot` 的选区证据，而不是退回整页候选竞争、录制期现场文本硬编码，或站点特例规则。

## Vision Anchor

- 原始目标：解决“目标信息明明在页面上，但在 raw/compact snapshot 与编译链路中被挤掉或误分类”的问题。
- 用户/工程痛点：如果 `region_context` 只是 planner 的旁路提示，而不是主链路证据，那么压缩、accepted trace 和 compiler 仍会在后续环节重新走偏。
- 期望结果：capture、compression、runtime planner、accepted trace 和 compiler 都理解 `region_scoped_snapshot`，并且能稳定区分结构化字段、单值文本、锚点区域内容、action/download side effect。
- 非目标：不引入站点模板，不让 compiler 靠 selector 经验猜语义，不把录制期 observed value 当 replay 逻辑。
- Exit Gate 对照来源：`docs/evidence/EV-011-rpa-region-scoped-snapshot.md`、`docs/decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md`、`docs/decisions/ADR-002-trace-evidence-driven-compiler-strategy.md`。

## Current Status

Active。PR #55 已把核心 `region_scoped_snapshot` 能力合入主线，但该 Feature 后续持续暴露出一条 hardening 链：

1. 选区自由文本提取会把 observed text 或不稳定 anchor 编进 replay。
2. `heading_scoped_text`、`selected_region_text_extract`、`extract_snapshot` 等路径没有共享统一的 replay-safe 边界。
3. “读取框选文本本身”和“以框选标题为锚点读取该区域内容”两类提取语义仍会互相抢占，导致修标题影响批量/区域提取，修区域提取又把标题路径拖回 `get_by_text(observed_text)`。

当前结论是：这不是新 Feature，而是 F011 的后续 hardening。应继续在 F011 下收敛证据与边界，而不是把同一条区域选择能力链切成多份平行记忆。

## Links

- Evidence: [EV-011 RPA Region-Scoped Snapshot Evidence](../evidence/EV-011-rpa-region-scoped-snapshot.md)
- Related ADR: [ADR-001 RPA Trace Is The Single Accepted Timeline](../decisions/ADR-001-rpa-trace-is-single-accepted-timeline.md)
- Related ADR: [ADR-002 Trace Evidence Drives Compiler Strategy](../decisions/ADR-002-trace-evidence-driven-compiler-strategy.md)
- Legacy spec: `docs/superpowers/specs/2026-05-19-rpa-region-scoped-snapshot-design.md`
- Legacy plan: `docs/superpowers/plans/2026-05-19-rpa-region-scoped-snapshot.md`
- Legacy design: `docs/superpowers/specs/2026-05-26-rpa-selected-region-text-extract-design.md`
- Legacy design scratch: `docs/superpowers/specs/2026-05-27-rpa-selected-region-extract-splitting-design.md`

## Acceptance Criteria

- [x] 选区进入 raw snapshot、compact compression 和 accepted trace 主链路，而不是仅作为 planner 提示。
- [x] 结构化字段、表格、列表、单值区域、action/download side effect 已有各自明确证据路径。
- [x] replay 不再依赖坐标点选，而是依赖 accepted trace 中保留下来的结构证据。
- [x] PR #55 review blockers 已通过 compiler/compression/runtime 边界修复并记录在 `EV-011`。
- [x] selected-region extract 需要显式分层为两类稳定语义：`single_value_extract` 与 `anchored_region_extract`。
- [x] `selected_region_text_extract`、`heading_scoped_text`、`extract_snapshot` 相关路径需要共享“observed value 不得进入 replay 逻辑”的统一 guard。
- [ ] `/section-texts` 手动 fixture 还需要转成可复现 eval 或录制/编译 artifact，作为 selected-region extract splitting 的正式收口证据。
- [ ] 当前分支最近一次 GitHub Actions / review 结果尚未写回 `EV-011`。

## Patch History

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F011.1 | 2026-05-20 | `6cb4b29` | planner contract 失败时证据不足，难以判断是 snapshot miss 还是 planner 输出异常。 | debug artifact 只保留快照，不保留无效 planner 输出和调用摘要。 | `EV-011` 中 planner failure artifact focused tests。 | landed |
| F011.2 | 2026-05-20 | `4a1adf2` | 选区内 standalone text 在 compact evidence 中丢失，而同卡片外部 action 仍参与候选竞争。 | scoped compression 对 action-group 文本和 outside action 的边界过宽。 | `EV-011` 中 scoped compression focused regressions。 | landed |
| F011.3 | 2026-05-20 | `5ea9aa7` | planner 返回顶层 Playwright Python 时，runtime 把可执行代码误判成 contract failure。 | planner contract 过早要求固定 wrapper，而不是先识别 runtime-context code。 | `EV-011` 中 planner wrapper RED/GREEN tests。 | landed |
| F011.4 | 2026-05-20 | `699b088` | PR #55 review blockers 暴露 recorded `region_context` 泄漏到 replay、geometry fallback 跨 iframe、budget trimming 过宽、空提取被误判失败。 | capture/compression/compiler/runtime 的证据边界过松，没有把“局部上下文”与“主路径 replay 逻辑”拆开。 | `EV-011` 中 PR #55 impacted backend subset 与 review follow-up tests。 | merged |
| F011.5 | 2026-05-24 至 2026-05-27 | `a27bb41`, `4a2fe58`, `7c1e273`, `04b8fac`, `8e1d1ad`, `f3a6c59` | selected-region 自由文本提取会把 observed text 或不稳定 section anchor 编进 replay，或缺少可复现分类证据。 | text-region extraction 缺少稳定单值边界、显式 anchor 合同和对应 evidence 沉淀。 | `EV-011` 中 bounded section / classification / stable single-value focused tests 与 fixture evidence。 | active |
| F011.6 | 2026-05-25 | `0a2abc3` | 带 `table_region` 的 action/download trace 被错误编译成确定性表格提取。 | compiler 让区域结构证据抢占了 action/download side-effect 证据。 | `EV-011` 中 export-table action/download compiler regressions。 | active |
| F011.7 | 2026-05-27 | pending commit | 修标题单值提取会伤区域/批量内容提取，修区域内容提取又会把标题路径拖回 `get_by_text(observed_text)`。 | “读取框选值本身”与“以框选标题为锚点读取该区域内容”共享 producer / compiler 分支，且 `heading_scoped_text`、`selected_region_text_extract`、`extract_snapshot` 没有统一 replay-safe gate。 | `EV-011` 中 selected-region extract splitting harness、shared anti-hardcode guard、single-value vs anchored-region regression matrix；本地 RED/GREEN 覆盖 `heading_scoped_text` observed value、dynamic id、structural header 三类绕行。 | locally verified |

## Patch Churn Review

F011 的 patch churn 说明真正脆弱的不是“有没有 region selection”，而是“选区证据在 capture -> compression -> accepted trace -> compiler 之间有没有被正确分类”。当前更进一步的结论是：**还必须把 selected-region extract 明确拆成两种语义能力**：

- `single_value_extract`：读取框选文本本身
- `anchored_region_extract`：以框选标题为锚点读取该区域内容

如果这两类能力继续共享脆弱分支，就会反复出现双向回归。后续 hardening 应围绕“语义分层 + 共享 anti-hardcode guard”推进，而不是继续给单条分支补站点经验规则。

## Evidence

- 主证据文档：[EV-011 RPA Region-Scoped Snapshot Evidence](../evidence/EV-011-rpa-region-scoped-snapshot.md)
- 当前 patch chain 关联提交：`6cb4b29`, `4a1adf2`, `5ea9aa7`, `699b088`, `a27bb41`, `4a2fe58`, `7c1e273`, `04b8fac`, `8e1d1ad`, `f3a6c59`, `0a2abc3`
- 当前状态说明：主线能力已交付，selected-region extract splitting 本地后端验证已通过；远端 CI / review evidence pending。

## Next Step

继续把 `/section-texts` fixture 转成可复现的 eval 或录制/编译 artifact，并把当前分支最近一次 GitHub Actions / review 结果写回 `EV-011`。在这些证据收齐之前，不新拆 Feature，避免把同一条区域选择 hardening 链切成多份平行记忆。
