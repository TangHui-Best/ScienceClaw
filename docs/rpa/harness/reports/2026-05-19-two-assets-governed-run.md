# 两个已升级资产 Harness 核心链路分析报告

> 生命周期说明：本文是 2026-05-19 当时资产池状态的 historical report，不能作为当前
> asset-pool readiness 证据。判断当前状态前，必须对当前 asset root 重新运行
> `run_asset_pool_doctor` 或 `run_catalog --format lifecycle`。

## 执行结论

本次执行通过。两个已升级为 blocking `candidate` 的 RPA Harness 资产都被
governed regression 选中，没有资产被排除；asset validation、snapshot、
compiler、skill replay、stateful SOP 均无失败。

工程判断：当前 RPA Agent 核心链路在“GitHub Trending 卡片列表 -> 仓库详情页
-> 详情页字段提取 -> TraceSkillCompiler -> Skill replay -> Stateful SOP
capture-to-skill”这条资产覆盖路径上是健康的。此次执行可以作为后续优化
snapshot、planner、compiler、skill replay、stateful SOP 时的 blocking
回归基线。

但这次执行不证明 RPA Agent 已经泛化到所有网站、所有页面结构或所有输出形态。
当前资产覆盖仍集中在 GitHub、同一仓库详情页、两个相近字段提取场景。

## 执行对象

| Asset | Promotion | Status | 输出 |
| --- | --- | --- | --- |
| `hcap-4be6265f43eb42dfa259182207aa64cc` | `candidate` | `active` | `fork_count = Fork 1.3k` |
| `hcap-de463b7bb608482e9b5bcdd5b78a224e` | `candidate` | `active` | `star_count = 18.3k stars` |

## 执行命令

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_validation `
  --assets data\rpa_harness_assets_bootstrap `
  --output tmp-harness-asset-validation-run-two-assets.json

python -m backend.rpa.harness.run_governed_regression `
  --assets data\rpa_harness_assets_bootstrap `
  --output tmp-harness-governed-run-two-assets.json
```

## Asset Validation

```text
capture_count = 2
issue_count = 0
blocking_issue_count = 0
```

## Governed Regression

```text
status = passed
selected_capture_count = 2
excluded_capture_count = 0
selected_asset_ids = [
  hcap-4be6265f43eb42dfa259182207aa64cc,
  hcap-de463b7bb608482e9b5bcdd5b78a224e
]
excluded_asset_ids = []
snapshot_failed = 0
compiler_failed = 0
skill_replay_failed = 0
stateful_sop_failed = 0
```

## Runner 输出摘要

| Runner | Asset | Status | Output |
| --- | --- | --- | --- |
| Stateful SOP | `hcap-4be6265f43eb42dfa259182207aa64cc` | `passed` | `fork_count = Fork 1.3k` |
| Stateful SOP | `hcap-de463b7bb608482e9b5bcdd5b78a224e` | `passed` | `star_count = 18.3k stars` |
| Skill Replay | `hcap-4be6265f43eb42dfa259182207aa64cc` | `passed` | `fork_count = Fork 1.3k` |
| Skill Replay | `hcap-de463b7bb608482e9b5bcdd5b78a224e` | `passed` | `star_count = 18.3k stars` |

## 机器报告

- `tmp-harness-asset-validation-run-two-assets.json`
- `tmp-harness-governed-run-two-assets.json`

## 结论与后续

这两个资产已经不是只完成了 Review Packet 或 promotion 标记，而是实际进入
blocking governed baseline 并跑通。后续新增录制资产时，应继续走：

1. 生成中文优先 `review.md`。
2. 人工确认 SOP、expected、sensitivity。
3. 先 `candidate-lite`，明确强确认后升 blocking `candidate`。
4. 跑 governed regression 并生成对应执行报告。

## 核心链路健康判断

| 链路 | 本次证据 | 工程判断 |
| --- | --- | --- |
| 资产治理选择 | `selected_capture_count=2`，`excluded_capture_count=0` | 两个资产已经真正进入 blocking baseline，不是只完成了 promotion 标记。 |
| Asset validation | `issue_count=0`，`blocking_issue_count=0` | 资产结构、checkpoint 引用、expected 文件和 governance 元数据当前可作为回归输入。 |
| HTML -> raw snapshot | 6 个 step 全部执行；raw snapshot 无失败 | 生产 DOM snapshot 能从沉淀 HTML 生成可用 raw snapshot。 |
| raw -> compact snapshot | 6 个 step 全部执行；目标点击 step 的 compact signal 为 `present` | 对卡片列表中 `tinyhumansai / openhuman` 的选择信号，compact snapshot 没有丢失关键候选。 |
| planner/action selection | 两个资产的点击步骤均通过 snapshot/runner 检查 | 对“从 Trending 中选择目标仓库链接”的核心选择链路当前健康。 |
| trace -> skill | 6 个 step compiler 全部通过；无 hardcoded executable value；无 missing output key | TraceSkillCompiler 当前没有把现场值硬编码进可执行逻辑，也保留了输出字段。 |
| skill replay | 6 个 step 全部通过；`fork_count` 和 `star_count` 均复现 | 单步/分步 skill replay 能基于 captured HTML controlled replay 复现结果。 |
| stateful SOP capture-to-skill | 2 个 Full SOP asset 全部通过；每个资产 3 条 accepted trace | F009 的“完整 SOP -> session-style accepted traces -> full SOP Skill -> controlled replay”闭环在这两个资产上成立。 |

## 本次执行证明了什么

1. **沉淀资产已经能模拟真实 SOP 主路径。**
   两个资产都不是单步 fixture，而是包含 3 步 Full SOP：进入 Trending、点击目标仓库、
   提取详情页字段。stateful SOP runner 对两个资产都成功重建 accepted traces 并完成
   Skill replay。

2. **卡片列表选择信号没有在 snapshot 压缩中丢失。**
   两个资产的第 2 步都是从 GitHub Trending 卡片列表点击
   `tinyhumansai / openhuman`。报告显示 source/raw/compact signal 都为
   `present`，说明当前 compact snapshot 对这个语义选择场景保留了关键证据。

3. **TraceSkillCompiler 对输出字段的保护有效。**
   compiler runner 没有报告 hardcoded executable value、missing output key 或
   missing dataflow refs。`fork_count` 和 `star_count` 都在 skill replay 中被保留。

4. **当前优化若影响这些链路，可以用这两个资产做 blocking 回归。**
   如果后续修改 snapshot compression、planner selection、trace compiler、
   skill replay 或 stateful SOP 编译，只要这两个资产退化，就说明改动破坏了已沉淀
   的真实 SOP 能力。

## 暴露的风险与优化信号

| 风险 / 信号 | 现象 | 建议 |
| --- | --- | --- |
| 覆盖域仍窄 | 两个资产都来自 `github.com`，且都围绕 GitHub Trending -> 同一仓库详情页。 | 不要据此判断跨站点、登录态、表单、分页、弹窗、动态列表等能力已经健康。后续应继续沉淀不同站点和不同页面形态资产。 |
| 输出 shape 有轻微不一致 | `fork_count` stateful output 是字符串；`star_count` stateful output 是嵌套对象：`{"star_count": {"star_count": "18.3k stars"}}`。 | 当前不阻塞回归，但这是一个 RPA Agent/Skill 输出归一化优化信号。后续可新增 Feature 让 stateful SOP replay 输出统一为 `output_key -> scalar/object` 的稳定形态。 |
| 字段提取只覆盖详情页简单读数 | 当前字段是 fork/stars 这类详情页可见计数。 | 不能外推到表格抽取、多字段结构化抽取、空值合法性、跨步骤参数引用等复杂提取场景。 |
| step 1 导航 snapshot 信息弱 | step 1 是 `about:blank -> GitHub Trending`，raw/compact snapshot 很小，signal 多为 `not_checked`。 | 这不是失败，但说明入口导航 step 主要证明流程边界，不证明页面理解能力。核心语义证据集中在点击和字段提取 step。 |
| sensitivity 分类未自动改写 | 新资产 `sensitivity_reviewed=true`，但 `sensitivity` 标签仍是 `local-only`。 | 这是治理语义边界：确认 sensitivity 不等于自动改分类。若要把分类改为 `repo-safe`，应单独做显式 promotion/classification 流程。 |

## 是否说明当前 RPA Agent 需要优化

当前没有 blocking 失败，因此没有证据表明必须立刻修复 snapshot、planner、
TraceSkillCompiler、skill replay 或 stateful SOP 主链路。

更准确的判断是：

- **不需要因为这两个资产触发紧急修复。**
- **可以把输出 shape 归一化列为后续优化候选。**
- **应该继续扩展资产覆盖，而不是仅凭两个 GitHub 资产判断泛化能力。**

## 后续优化如何用这两个资产验收

后续每次改 RPA Agent 核心链路时，应至少跑：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_governed_regression `
  --assets data\rpa_harness_assets_bootstrap `
  --output tmp-harness-governed-after-change.json
```

验收标准：

- `selected_capture_count` 仍为 `2`。
- `excluded_capture_count` 仍为 `0`。
- `snapshot_failed = 0`。
- `compiler_failed = 0`。
- `skill_replay_failed = 0`。
- `stateful_sop_failed = 0`。
- `fork_count` 和 `star_count` 输出仍能复现。

如果某次优化目标正是输出 shape 归一化，还应额外断言：

- `star_count` stateful output 不再出现不必要的嵌套对象。
