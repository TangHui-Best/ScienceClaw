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
4. 选择 UI 仍偏向拖拽框选；小按钮、链接、输入框等精确目标需要更低成本的点选 acquisition，但该体验增强不能演变成新的后端主链路或 Elements 面板。

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
- [x] 选择 UI 支持 hover 高亮当前元素、单击选中元素、拖拽仍选择区域；元素点选只作为 region acquisition 的精确方式，不新增平级 `kind=element` / `element_context` 后端路径。

## UI Acquisition Enhancement

本轮下一步只提升 RPA 录制页的选择交互体验：在现有拖拽选择页面区域的基础上，增加“像浏览器元素选择器一样 hover 高亮、单击选中当前元素”的精确选择方式。

这不是新的后端主链路，也不是完整 Elements 面板。元素点选只是区域选择的一种更精确的 acquisition 方式：前端用被点元素的可视 bounding box 生成现有 region analyze 请求，后端继续返回 `region_id`，chat 请求继续只携带 `region_id`。现有 `region_scoped_snapshot -> accepted trace -> compiler` 语义不因本 UI 改动而扩张。

### UX Scope

选择按钮仍是录制页 composer 里的单一入口，文案可以维持“选择页面区域”。点击后进入一次性选择模式：

1. 鼠标移动到浏览器画面上时，高亮当前可见 DOM 元素的投影区域。
2. 单击未发生拖拽时，选中当前 hover 元素。
3. 按住并拖拽超过阈值时，走现有区域框选。
4. `Esc` 取消选择。
5. 选中后在输入框上方展示 attachment preview。

Preview 不需要暴露 DOM 树，只展示用户可理解的选择上下文：

- 元素点选：`元素 · button · 导出`，缺少 tag/name 时退化为 `已选择页面元素`。
- 区域框选：沿用 `区域 420x180，包含 12 个元素`。

Chat 发送后仍显示普通用户指令和一个紧凑 attachment chip。Timeline 不新增 “element trace” 类型。

### Interaction Model

前端内部可以区分 selection acquisition：

```ts
type SelectionAcquisition = 'drag_region' | 'picked_element';
```

但该字段只用于 UI 呈现、调试和未来兼容，不改变后端主语义。发送给 `/region/analyze` 的核心 payload 仍是：

```ts
{
  tab_id: string;
  rect: { x: number; y: number; width: number; height: number };
  viewport: { width: number; height: number };
}
```

元素点选时，`rect` 来自 hover 元素映射到浏览器 viewport 的 bounding box。后端如果暂时不理解 acquisition metadata，也不影响功能。

### Frontend Design

选择模式中，前端需要知道鼠标下的元素边界。实现应优先复用当前 CDP / Playwright 可用能力，并保持局部：

- 鼠标移动节流，避免频繁请求。
- 根据 viewport point 获取当前元素的可视 bounding box、tag、role/name/text 摘要。
- 前端只绘制一个 overlay，不改变浏览器页面本身。
- 如果 hover 查询失败，退化为只支持拖拽区域选择。

查询结果示例：

```ts
interface HoveredElementPreview {
  rect: { x: number; y: number; width: number; height: number };
  tag?: string;
  role?: string;
  name?: string;
  text?: string;
}
```

Gesture rules:

- `mousedown` 记录起点和当前 hover element。
- `mousemove` 超过拖拽阈值后切换为框选区域。
- `mouseup` 时如果没有进入拖拽，则使用最后一个 hover element 的 rect 作为选择区域。
- 小于现有 `MIN_REGION_SIZE` 的选择继续取消。
- 选择期间不转发鼠标、滚轮、键盘输入到远端浏览器；`Esc` 例外，用于取消。

Visual rules:

- Hover 高亮使用和区域框选同一紫色系，但透明度更低。
- 拖拽框选时显示矩形框，优先于 hover 高亮。
- 不显示 DOM 属性面板、层级列表、selector 文本或调试字段。
- 所有按钮和 chip 文案走现有 i18n。

### Backend Boundary

本阶段后端保持最小变更：

- 不修改 `TraceSkillCompiler` 分支优先级。
- 不引入新的 `element_context` 或平级 `kind=element`。
- 不迁移上游 selected-region planner validation。
- 不把空值提取全局视为失败。
- 不让坐标或 observed text 进入 replay 主逻辑。

只有在前端无法仅用现有 `/region/analyze` 表达点选元素时，才允许补一个可选 metadata 字段，例如：

```json
{
  "acquisition": "picked_element",
  "target_preview": {
    "tag": "button",
    "role": "button",
    "text": "导出"
  }
}
```

该 metadata 只能用于 UI preview、debug artifact 或后续 evidence audit，不能改变 planner/compiler 策略。

### UI Acceptance Criteria

- 用户点击选择按钮后，鼠标 hover 浏览器画面时能看到元素级高亮。
- 用户单击一个元素后，composer 出现元素 attachment preview。
- 用户拖拽时仍能选择区域，且行为与现有区域选择兼容。
- 发送 chat 请求时仍只依赖 `region_id`，不把完整 evidence 从前端传给 planner。
- 非选择模式下，canvas 鼠标/键盘转发行为不变。
- 后端 replay/compiler 行为不因本 UI 改动改变。
- 失败或无法识别 hover 元素时，用户仍可使用拖拽区域选择。

### Test Plan

Frontend focused tests:

- 点击选择按钮进入 selection mode。
- hover 元素时显示元素 overlay。
- 单击 hover 元素后调用 region analyze，并生成元素 preview。
- 拖拽超过阈值时调用原区域选择流程。
- `Esc` 取消后 overlay 和 pending selection 清空。
- 发送消息时仍只带 `region_id`。

Backend regression tests:

- 现有 region analyze、chat region_id、selected-region compiler tests 继续通过。
- 若新增 optional metadata，验证缺省 metadata 时旧请求仍可用。

Rollback:

- 该改动应可通过前端 feature flag 或隐藏元素 hover 查询降级为现有拖拽区域选择。后端不做主链路迁移，因此回滚不应影响已存在的 `region_scoped_snapshot`、accepted trace 或 compiler 行为。

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

- 2026-05-27 UI acquisition hardening：录制页选择模式已支持 hover 元素高亮、单击元素转为现有 region analyze、拖拽仍走原区域选择；新增 `/region/element-bounds` 只做点到 bbox 预览，不存储 `RPARegionContext`，不新增 `kind=element` / `element_context` 主链路。独立 review 后补齐取消期间 pending 请求失效、快速移动后点击重新按点击点解析、元素点选 preview 优先显示元素摘要三项保护。验证：`npm.cmd run test -- src/utils/rpaRegionSelection.test.ts src/pages/rpa/RecorderPage.test.ts`、`.\\.venv\\Scripts\\python.exe -m pytest RpaClaw/backend/tests/test_rpa_region_context.py -q`、`knowledge_check.py --strict` 均通过；`npm.cmd run type-check` 仍被既有全仓 TS 错误阻塞，未发现本次文件新增错误。残余风险：iframe 内部元素点选当前可能退化为 iframe 外层 bbox；若要做内层精确点选，应单独扩展 frame point 映射，不并入本轮 UI hardening。

## Next Step

继续把 `/section-texts` fixture 转成可复现的 eval 或录制/编译 artifact，并把当前分支最近一次 GitHub Actions / review 结果写回 `EV-011`。在这些证据收齐之前，不新拆 Feature，避免把同一条区域选择 hardening 链切成多份平行记忆。
