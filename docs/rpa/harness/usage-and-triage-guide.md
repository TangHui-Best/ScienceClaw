# RPA Harness 使用与问题定位指南

> 生命周期说明：本文是当前 RPA Harness runner 使用与问题定位指南。它说明如何执行
> 和解读 Harness 命令，但不替代当前 Feature/Evidence，也不替代对真实 asset root
> 的体检。如果历史示例与当前输出冲突，以 `run_asset_pool_doctor`、
> `run_catalog --format lifecycle` 和所属 Feature/Evidence 为准。

## 当前入口

内网接管和封箱状态先读：

```text
docs/rpa/harness/internal-handoff-and-freeze-guide.md
```

本文继续作为 runner 使用与问题定位指南。若本文的历史示例与当前资产池状态冲突，以 `run_asset_pool_doctor` / `run_catalog --format lifecycle` 的当前输出为准。

## 目的

这份文档说明当前 RPA Harness 如何执行、如何阅读输出、以及其它 Agent
应该如何根据 Harness 报告定位问题。

Harness 是回归与诊断层。它负责保存受管场景资产、重跑标准离线检查、
报告 RPA 核心链路在哪里出现偏差。它不负责把 planner、snapshot、
compiler、selector 或 extraction 的缺陷悄悄修在 Harness 里面。

## 当前能力

`run_governed_regression` 会在已审核的场景资产上组合执行以下检查：

| 能力 | 检查内容 | 通常暴露的问题 |
| --- | --- | --- |
| Asset validation | `scenario.json`、checkpoint、HTML、trace events、expected signals、Full SOP 步骤连续性。 | 资产缺文件、JSON 损坏、录制证据不完整、资产还不适合 promoted。 |
| Snapshot regression | captured HTML -> production raw snapshot -> compact snapshot。 | 页面事实没有进入 raw snapshot，或 raw 中存在但 compact 时丢失。 |
| Compiler regression | trace evidence -> `TraceSkillCompiler`。 | 编译脚本硬编码现场值、丢 `output_key`、丢 `_results` 数据流引用。 |
| Skill Replay E2E | trace 编译成 Skill，并在 controlled captured HTML 上执行。 | 生成 Skill 跑不起来、输出结构不对、缺少期望文本或结果。 |
| Stateful SOP Capture-to-Skill | 用受管 Full SOP asset 模拟录制输入边界，重建 session-style accepted traces，编译完整 SOP Skill，并可控 replay。 | recording-to-Skill 内部链路漂移、accepted trace 缺失、完整 SOP 编译或 replay 失败。 |
| Observability / blast radius | 汇总状态、failure categories、受影响资产、受影响页面形态、confidence risks。 | 判断失败是单点、资产级、runner 级，还是覆盖度不足。 |

Full SOP 步骤连续性按语义 checkpoint 判断，不按浏览器原始事件数判断。输入框 focus click
会折叠到后续 `fill`；账号、密码、搜索词等输入值应在资产里表现为
`{{input:<key>}}` 或 runtime secret 引用。若 generated Skill 的语义步骤完整，而资产
缺对应 checkpoint，优先看 capture/export；若资产 checkpoint 完整但 replay 或 generated
Skill 不符合预期，再看 expected、compiler 或 Skill replay。

历史 bootstrap baseline 曾经有两个 blocking `candidate` assets：

```text
data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc
data/rpa_harness_assets_bootstrap/hcap-de463b7bb608482e9b5bcdd5b78a224e
```

它们覆盖的真实 SOP 形态是：

```text
GitHub Trending -> 点击 tinyhumansai / openhuman -> 提取 fork_count
GitHub Trending -> 点击 tinyhumansai / openhuman -> 提取 star_count
```

这些历史报告证明过“沉淀 Full SOP 资产 -> accepted traces ->
TraceSkillCompiler -> generated Skill -> controlled replay”的基本闭环。
但不要把历史报告当成当前 asset root 的治理状态。当前工作区里的
`data/rpa_harness_assets_bootstrap` 可能只包含 `draft` / `candidate-lite`
资产，甚至没有 blocking baseline。每次接手或迁移前都应先运行：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_pool_doctor --assets data\rpa_harness_assets_bootstrap --format summary --lang zh
```

如果 `blocking_baseline_asset_ids=[]`，只能说明当前资产池证据不足，不能声称
RPA Agent 在 blocking baseline 上健康。真正提升价值的下一步是录制更多内网真实资产、
生成 Review Packet、完成 expected/sensitivity review，并通过 CLI promoted。

## 环境准备

在仓库根目录执行命令：

```powershell
$env:PYTHONPATH='RpaClaw'
```

Harness 不需要启动 FastAPI backend 或 frontend dev server。它需要本地
Python 环境、项目依赖，以及 Playwright/browser 依赖，因为 snapshot 和
replay runner 会用到浏览器能力。

内网迁移时，直接拉取当前 Harness 分支或 commit：

```text
branch: codex/rpa-harness-region-integration
minimum commit: dde739a1 or newer
```

如果内网使用的是其它交接分支，以交接人提供的 branch/commit 为准；不要只凭历史
phase 文档判断当前 Harness 能力。

## 标准执行命令

### 快速中文汇总

拉取分支后，或者修改 RPA 核心代码后，优先跑这个 smoke：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_bootstrap --format summary --lang zh
```

健康输出的形态应接近：

```text
受管离线回归：passed
Skill replay：checked=3，failed=0
Stateful SOP：checked=1，failed=0
```

具体措辞可能随 summary 文案变化，但关键是整体 `passed`，并且 failed
计数为 `0`。

### JSON 报告

Agent 需要定位问题时，不要只读 summary，要生成 JSON：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_bootstrap --output tmp-harness-governed.json
```

优先查看这些字段：

```text
summary.status
summary.failure_category
observability.runner_signals
observability.blast_radius
asset_validation
snapshot
compiler
skill_replay
stateful_sop
```

### 工程判断报告

Harness 的目的不是只输出 `passed/failed`，而是让用户和 Agent 判断：

- 哪些 RPA Agent 核心链路被资产证明是健康的；
- 哪些链路暴露了风险或覆盖不足；
- 当前失败应该由资产、snapshot、planner、compiler、skill replay 还是
  stateful SOP owning module 处理；
- 某次优化是否真的被沉淀资产验证通过。

因此执行资产后，Agent 应同时保留机器 JSON，并生成一份人类可读 Markdown
分析报告。推荐位置：

```text
docs/rpa/harness/reports/YYYY-MM-DD-<scope>-governed-run.md
```

报告至少包含：

```text
执行对象
执行命令
Asset validation 摘要
Governed regression 摘要
Runner 输出摘要
核心链路健康判断
本次执行证明了什么
暴露的风险与优化信号
是否说明当前 RPA Agent 需要优化
后续优化如何用同一批资产验收
机器报告路径
```

已有示例：

```text
docs/rpa/harness/reports/2026-05-19-two-assets-governed-run.md
```

### 单独 runner

当 governed report 已经指向某一层时，可以单独跑对应 runner 降低噪声：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_validation --assets data\rpa_harness_assets_bootstrap
```

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_snapshot_regression --assets data\rpa_harness_assets_bootstrap
```

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_compiler_regression --assets data\rpa_harness_assets_bootstrap
```

### 单资产 SOP→Skill core-chain 导出

如果问题是“录制资产重新生成的 Skill 到底长什么样”或“Full SOP
capture 后 generated Skill 是否符合预期”，不要从 capture 目录里找历史最终
`SKILL.md`。Harness capture 保存的是录制事实，不保存最终导出包。

使用 asset-local core-chain 导出：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_core_chain --assets <asset_root> --asset-id <asset_id>
```

该命令会在对应资产目录生成：

```text
<asset_root>/<asset_id>/core-chain-report.md
<asset_root>/<asset_id>/core-chain-full-report.json
<asset_root>/<asset_id>/generated_skills/full_sop/skill.py
<asset_root>/<asset_id>/generated_skills/full_sop/compile_metadata.json
<asset_root>/<asset_id>/generated_skills/steps/<NNN>/skill.py
<asset_root>/<asset_id>/generated_skills/steps/<NNN>/compile_metadata.json
```

这些文件是执行证据，不是新的录制事实。若它们暴露 compiler、dataflow、download、
navigation 或 runtime AI replay 问题，应回到 owning RPA core component 修复，并用
同一资产 rerun。

### 新录制资产 Review Packet

新录制的 `draft/captured` 资产不应要求用户或其它 Agent 直接阅读原始
HTML、trace、checkpoint 和 expected JSON。先生成 Review Packet：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_review --assets data\rpa_harness_assets_bootstrap --asset-id <asset_id>
```

输出会写入：

```text
data/rpa_harness_assets_bootstrap/<asset_id>/review.md
```

Review Packet 应先回答场景身份、Human SOP、每一步页面变化、最终输出字段和值、
自动检查结果、人工 review 问题，以及建议的升级层级。它只读取 captured facts，
不访问 live URL，不恢复 direct Agent chat。

如果人工确认该资产值得进入非阻塞观察层，可以升级为 `candidate-lite`：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_promote --assets data\rpa_harness_assets_bootstrap --asset-id <asset_id> --level candidate-lite
```

`candidate-lite` 会进入 governed regression 的 warning-only observation。
它可以运行 validation、snapshot、compiler、Skill Replay 和 Stateful SOP 观察，但不会进入
blocking candidate/golden baseline，也不会自动确认 `expected_signals_reviewed` 或
`sensitivity_reviewed`。

只有在 expected signals 和 sensitivity 都被显式确认后，才可以考虑 blocking
`candidate` 或 `golden`：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_promote --assets data\rpa_harness_assets_bootstrap --asset-id <asset_id> --level candidate --confirm-expected --confirm-sensitivity
```

## 如何阅读 governed report

先看 `summary.failure_category`。

| Failure category | 第一判断 | 第一检查位置 |
| --- | --- | --- |
| `no-governed-offline-assets` | 没有 active 且 reviewed 的 candidate/golden asset 可跑。 | `scenario.json` 的 governance 字段和 asset lifecycle。 |
| `governed-asset-validation-blocked` | 资产证据链不可信。 | `asset_validation.summary`、issue category、缺失路径。 |
| `snapshot-regression-failed` | captured HTML 无法生成满足期望的 raw/compact snapshot。 | `snapshot.assets[*].failure_category`、raw/compact signal status。 |
| `compiler-regression-failed` | trace-to-Skill 输出违反 compiler expected signals。 | `compiler.assets[*].failure_category`、生成脚本片段。 |
| `skill-replay-e2e-failed` | 生成 Skill 在 controlled HTML 上 replay 失败。 | `skill_replay.assets[*].failure_category`、actual output、missing text。 |
| `stateful-sop-capture-to-skill-failed` | Full SOP asset 无法重建 recording-to-Skill 链路。 | `stateful_sop.assets[*].steps`、accepted trace count、compile/replay。 |
| `blast-radius-failed` | blocking asset 或页面形态受影响。 | `observability.blast_radius`。 |

然后看 `observability.runner_signals`。它能快速告诉 Agent 哪个 runner
真的失败了，避免从完整 JSON 里盲扫。

## 定位问题的顺序

按下面顺序定位，避免在下游修补上游事实缺失。

1. **Asset validation failed**

   先按资产问题处理，除非有明确证据说明是当前 capture/export 代码生成了坏资产。
   修复或重新录制资产。不要基于无效资产修改 planner/compiler。

2. **Snapshot failed**

   先比较 raw 和 compact signal status。

   - raw 缺目标文本或结构：检查 production DOM snapshot extraction。
   - raw 有、compact 丢：检查 snapshot compaction。遵守项目军规：
     先比较 raw snapshot 和 compact snapshot，再考虑 planner。

3. **Compiler failed**

   看 compiler failure category。

   - `compiler-hardcoded-observed-value`：修 `TraceSkillCompiler`
     泛化或 dataflow inference，不要在 Harness 里加例外。
   - `compiler-output-key-lost`：保持 runtime result output key。
   - `compiler-dataflow-lost`：保持 `_results` 引用，不能写死 observed value。

4. **Skill replay failed**

   判断是 generated Skill 本身错误，还是 controlled replay 断言过严。

   - execution error：看 generated Skill 和 replay stack trace。
   - output missing signal：看 `expected.json` 和 replay `actual_output`。
   - controlled HTML 问题：看 asset 的 before/after HTML 路径。

5. **Stateful SOP failed**

   这是 F009 最重要的信号。它说明 Full SOP asset 没能驱动接近真实录制的
   recording/session-state -> Skill 链路。

   检查顺序：

   - `accepted_trace_count`：应匹配可接受 SOP 步骤数量。
     这里的数量是语义 accepted trace 数，不包含被折叠的输入框 focus click。
   - `steps[*].failure_category`：看是否是 missing trace events、
     invalid checkpoint、missing accepted trace 或 capture-to-trace error。
   - `compile.failure_category`：看完整 SOP trace 编译是否失败。
   - `replay.failure_category`：看完整 SOP Skill 的 controlled replay 是否失败。

   不要把 stored trace files 直接编译作为主路径来绕过失败。这个 runner
   的目标就是暴露 session-style recording-to-Skill 路径是否漂移。

## 常见 failure category

| Category | 含义 | 可能 owner |
| --- | --- | --- |
| `missing-scenario` | asset 目录缺 `scenario.json`。 | 资产整理或 capture export。 |
| `invalid-scenario` | scenario JSON 无法解析或校验。 | 资产整理。 |
| `missing-checkpoint` | scenario 引用的 checkpoint 不存在。 | 资产整理或 capture export。 |
| `invalid-checkpoint` | checkpoint JSON 损坏。 | 资产整理或 capture export。 |
| `missing-trace-events` | 步骤缺 trace evidence。 | 资产质量或 recording trace capture。 |
| `invalid-trace-events` | trace events JSON 损坏。 | 资产整理或 recording export。 |
| `missing-accepted-trace` | 没有 accepted trace event 可驱动 runner。 | recording trace acceptance 或资产质量。 |
| `step-index-gap` / Full SOP checkpoint 不连续 | `scenario.json.step_checkpoints` 不能覆盖连续语义步骤。 | capture/export 或资产整理；不要先改 planner/compiler。 |
| `raw-snapshot-missing-signal` | production raw snapshot 不含期望事实。 | Snapshot extraction。 |
| `compact-snapshot-lost-signal` | raw 有事实但 compact 丢了。 | Snapshot compaction。 |
| `compiler-hardcoded-observed-value` | Skill 脚本冻结录制现场值。 | `TraceSkillCompiler` 或 dataflow inference。 |
| `compiler-output-key-lost` | 编译后 Skill 丢 output key。 | `TraceSkillCompiler`。 |
| `compiler-dataflow-lost` | 编译后 Skill 丢跨步骤结果引用。 | `TraceSkillCompiler` 或 trace normalization。 |
| `replay-execution-error` | generated Skill replay 时抛错。 | generated Skill、compiler 或 replay fixture。 |
| `controlled-replay-output-missing-signal` | replay 完成但缺期望信号。 | compiler、runtime extraction、expected signal 或 fixture。 |
| `skill-compile-error` | Stateful full SOP Skill 编译失败。 | `TraceSkillCompiler` 或 accepted trace shape。 |
| `capture-to-trace-error` | Stateful runner 无法从资产输入重建 accepted trace。 | Recording trace conversion 或 asset shape。 |

## 内网资产 promoted 流程

新录制资产默认应留在内网本地，先不要视为可信回归基线。

推荐流程：

1. 把资产放到内网资产根目录，例如：

   ```text
   data/rpa_harness_assets_internal/<asset_id>
   ```

2. 生成 Review Packet，不要直接让人读原始 HTML / trace / checkpoint：

   ```powershell
   $env:PYTHONPATH='RpaClaw'
   python -m backend.rpa.harness.run_asset_review --assets data\rpa_harness_assets_internal --asset-id <asset_id>
   ```

3. 先升级到非阻塞 `candidate-lite` 观察层：

   ```powershell
   $env:PYTHONPATH='RpaClaw'
   python -m backend.rpa.harness.run_asset_promote --assets data\rpa_harness_assets_internal --asset-id <asset_id> --level candidate-lite
   ```

4. 跑 governed regression，确认它只作为 warning-only observation，不污染
   blocking baseline。

5. 做 sensitivity review。内网页面 HTML、截图、凭证、session token、个人信息
   不应复制到外部仓库。

6. 做 expected signals review。expected signals 应表达业务意图，不应冻结偶然的
   absolute selector 或临时页面文案。
   对表单输入步骤，还要确认 `trace_events.json`、`checkpoint.json.step_intent`、
   HTML 和 `expected.json` 都使用同一套 input placeholder / secret ref，不保留现场值。

7. 明确确认 expected 和 sensitivity 后，用 CLI 升级为 blocking `candidate`。
   不要手改 governance JSON：

   ```powershell
   $env:PYTHONPATH='RpaClaw'
   python -m backend.rpa.harness.run_asset_promote --assets data\rpa_harness_assets_internal --asset-id <asset_id> --level candidate --confirm-expected --confirm-sensitivity
   ```

8. 对内网资产根目录跑 governed regression：

   ```powershell
   $env:PYTHONPATH='RpaClaw'
   python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_internal --format summary --lang zh
   ```

9. 生成工程判断报告，说明本次资产执行证明了哪些核心链路健康、暴露了哪些风险、
   是否需要优化 RPA Agent。

`golden` 只给长期稳定、应当成为强 blocking regression fixture 的资产。刚通过
人工确认的资产先用 `candidate`。

## 可直接交给内网 Agent 的执行提示词

下面这段提示词可以直接发给内网 Agent。把 `<asset_root>` 替换成内网资产根目录，
必要时把 `<report_slug>` 换成更具体的名字。

```text
你是 ScienceClaw / RpaClaw 的 RPA Harness 执行 Agent。请严格按 Harness 工程目标执行：

目标：
基于已沉淀的 RPA Harness 资产执行核心链路，判断当前 RPA Agent 的 snapshot、planner/action selection、TraceSkillCompiler、Skill Replay、Stateful SOP capture-to-skill 链路是否健康；生成机器 JSON 和人类可读 Markdown 工程判断报告。

工作目录：
E:\Work-Project\OtherWork\ScienceClaw

资产根目录：
<asset_root>

必须遵守：
- 不访问 live URL 作为 oracle。
- 不恢复 direct Agent chat。
- 不用嵌套 Agent 去点击 RPA 产品 UI。
- 不为了通过回归而添加站点特定 Harness 规则。
- 先看 asset validation，再看 snapshot，再看 compiler，再看 skill replay，再看 stateful SOP。
- 如果失败，定位最早失败层和 owning module，不要在 Harness 里掩盖 RPA core bug。
- 报告以中文为主，必要技术名词保留英文。

请执行：
1. 设置环境：
   $env:PYTHONPATH='RpaClaw'

2. 跑资产校验：
   python -m backend.rpa.harness.run_asset_validation --assets <asset_root> --output tmp-harness-asset-validation-<report_slug>.json

3. 跑 governed regression：
   python -m backend.rpa.harness.run_governed_regression --assets <asset_root> --output tmp-harness-governed-<report_slug>.json

4. 读取两个 JSON 报告，提取：
   - validation summary
   - governed summary
   - selected_asset_ids / excluded_asset_ids
   - snapshot_failed / compiler_failed / skill_replay_failed / stateful_sop_failed
   - observability.runner_signals
   - observability.blast_radius
   - stateful_sop.assets[*].accepted_trace_count
   - stateful_sop.assets[*].replay.actual_output
   - skill_replay.assets 中带 output_key 的输出项

   如需审查具体 generated Skill，再执行：

   ```powershell
   python -m backend.rpa.harness.run_asset_core_chain --assets <asset_root> --asset-id <asset_id>
   ```

5. 生成 Markdown 工程判断报告：
   docs/rpa/harness/reports/YYYY-MM-DD-<report_slug>-governed-run.md

报告必须包含这些章节：
- 执行结论
- 执行对象
- 执行命令
- Asset Validation
- Governed Regression
- Runner 输出摘要
- 核心链路健康判断
- 本次执行证明了什么
- 暴露的风险与优化信号
- 是否说明当前 RPA Agent 需要优化
- 后续优化如何用这批资产验收
- 机器报告路径

报告判断规则：
- 如果 selected_capture_count 为 0，说明没有真正进入 blocking baseline。
- 如果 excluded_capture_count > 0，必须列出每个 excluded asset 的原因。
- 如果 snapshot_failed > 0，先比较 raw_signal_status 和 compact_signal_status。
- 如果 compiler_failed > 0，优先检查 hardcoded observed value、missing output key、missing dataflow refs。
- 如果 skill_replay_failed > 0，说明 generated Skill 或 controlled replay 断言有问题。
- 如果 stateful_sop_failed > 0，说明完整 SOP recording-to-Skill 内部链路漂移。
- 如果全部通过，也必须写覆盖边界和残余风险，不能泛化成“RPA Agent 全局健康”。

最后输出：
- 两个 JSON 报告路径
- Markdown 报告路径
- 总体结论：passed / warning / failed
- 是否建议进入 RPA Agent 优化任务
```

## 给其它 Agent 的分析协议

当 Agent 被要求分析 Harness failure 时，按这个协议执行：

1. 运行或读取 governed JSON report。不要只依赖 summary 文本。
2. 说明 failing runner 和 `failure_category`。
3. 找到最早失败层：asset validation -> snapshot -> compiler -> skill replay -> stateful SOP。
4. 命名可能 owner module，但区分事实和推断。
5. 打开失败 item 指向的 asset、step checkpoint、`expected.json`、trace file。
6. 涉及 snapshot 时，先比较 raw signal 和 compact signal，再碰 planner prompt。
7. 涉及 compiler 时，先看 generated Skill 和 trace dataflow，再改 Harness 断言。
8. 涉及 stateful SOP 时，先看 accepted trace reconstruction，再跳到 replay。
9. 不要为了让场景通过而添加站点特定 Harness 规则。
10. 在 owning RPA component 中修复后，用同一批 asset rerun。

Agent 输出应包含：

```text
Failing command:
Report path:
summary.status:
summary.failure_category:
Failing runner:
Failing asset:
Failing step:
Earliest failing layer:
Observed fact:
Likely owner:
Proposed next fix:
Verification command after fix:
Residual risk:
```

## Harness 不应该做什么

不要用 Harness：

- 增加站点特定 selector 规则来绕过 planner 理解；
- 在 expected-signal 例外里隐藏 compiler 泛化 bug；
- 用 live URL 作为回归正确性 oracle；
- 恢复 direct Agent chat 作为 golden runner；
- 默认用嵌套 Agent 去点击 RPA 产品 UI；
- 在成熟 baseline 中把缺少 opt-in asset 当作成功；
- 未做 sensitivity 和 expected-signal review 就把资产标记为 `candidate` 或 `golden`。

正确闭环是：

```text
record real asset -> review/promote asset -> run Harness -> expose failure
  -> fix owning RPA core component -> rerun same asset -> capture Evidence
```

### Asset Pool Doctor

接手一个资产池时，先跑轻量体检。它不新增 runner，不自动 promotion，只读取资产治理状态并给出下一步建议：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_pool_doctor --assets <asset_root> --format summary --lang zh
```

机器 JSON：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_pool_doctor --assets <asset_root> --output tmp-harness-asset-pool-doctor.json
```

优先看：

```text
summary.readiness
summary.blocking_baseline_count
summary.warning_only_count
summary.recommended_next_action
blocking_baseline_asset_ids
warning_only_asset_ids
excluded_assets[*].reasons
```

## F013 deterministic profile

RPA Harness v1 Phase 1 的默认 pre-submit evidence path 是
`deterministic` profile。它是脚本/CLI 执行入口，复用已有 governed assets、
asset validation、snapshot、compiler、Skill Replay、Stateful SOP 和
candidate-lite observation，不调用真实 Planner/LLM，不访问 live URL，不让外层
Agent 点击 RPA 产品 UI。

推荐在 RPA core-chain 变更后先运行机器 JSON：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile deterministic --output tmp-harness-profile-deterministic.json
```

需要人工 closeout 或 PR/Evidence 摘要时，再生成可读 summary：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile deterministic --format summary --lang zh --output docs\rpa\harness\reports\YYYY-MM-DD-deterministic-profile.md --machine-report tmp-harness-profile-deterministic.json
```

Agent 解读时应优先读取 JSON，不要只看 summary。重点字段：

```text
profile
summary.status
summary.first_failure_category
summary.selected_asset_ids
summary.excluded_asset_ids
summary.warning_only_observation_count
deterministic.observability
deterministic.validation
deterministic.snapshot
deterministic.compiler
deterministic.skill_replay
deterministic.stateful_sop
deterministic.candidate_lite_observation
```

`interpretation` 是 Phase 2 的有界解释入口。它只基于当前 runner facts，不调用 LLM，不替代人的治理判断，也不做自动 root-cause 诊断。Agent 应按下面顺序读取：

```text
interpretation.verdict
interpretation.comparison_basis
interpretation.bounded
interpretation.basis
interpretation.evidence_limits
interpretation.recommended_agent_flow
summary
deterministic.observability.runner_signals
```

`interpretation.verdict` 的语义固定为：

| Verdict | 含义 | 边界 |
| --- | --- | --- |
| `regression` | 当前 deterministic profile 有 blocking runner failure。 | 只说明已有受管资产暴露了回归信号，不自动判断根因。 |
| `improvement` | 预留给未来显式 baseline comparison。 | 单次通过不能推断 improvement。 |
| `no meaningful change` | 当前单次 deterministic profile 通过，且有受管资产覆盖。 | 没有 baseline comparison 时只能说明覆盖范围内未见有意义变化。 |
| `insufficient evidence` | 没有选中受管资产、runner facts 不完整，或覆盖不足以支撑判断。 | 需要补资产、补 evidence 或 rerun，而不是把空跑视为通过。 |

Phase 1 不接 CI blocking，不扩张 full/live profile，不做自动诊断平台。失败分析由
Agent 基于报告事实解释，真正修复应回到 owning RPA core component。

## F015 asset lifecycle operationalization

Phase 3 的目标是让资产生命周期成为日常可操作流程，而不是新增 runner。核心边界仍然是：

```text
Scripts execute.
Agents explain.
Humans govern.
```

资产生命周期语义固定为：

| Lifecycle | 用途 | 是否 blocking |
| --- | --- | --- |
| `draft` / `captured` | 新捕获事实资产，默认本地，先生成 Review Packet。 | 否 |
| `candidate-lite` | 人工初筛后的 warning-only observation。 | 否 |
| `candidate` | 人工确认 expected signals 和 sensitivity 后的 blocking regression asset。 | 是 |
| `golden` | 从 candidate 人工批准提升的长期 contract asset。 | 是 |

### 生命周期摘要

查看资产池状态、review 状态、runner coverage 和可信边界：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_catalog --assets data\rpa_harness_assets_bootstrap --format lifecycle --output docs\rpa\harness\reports\YYYY-MM-DD-lifecycle-summary.json
```

Agent 优先读取：

```text
summary.lifecycle_distribution
review_state
blocking_baseline_asset_ids
warning_only_asset_ids
golden_asset_ids
coverage_boundary
trust_limits
lifecycle_warnings
```

`candidate-lite` 只允许进入 `warning_only_asset_ids`，不允许进入 `blocking_baseline_asset_ids`。

### Golden eligibility report

查看哪些 candidate 满足 golden 资格，但不要把 eligibility 当成 promotion：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_catalog --assets data\rpa_harness_assets_bootstrap --format golden-eligibility --output docs\rpa\harness\reports\YYYY-MM-DD-golden-eligibility.json
```

资格规则：

- 当前必须是 `promotion_status=candidate`。
- 必须是 `asset_status=active`。
- `expected_signals_reviewed=true`。
- `sensitivity_reviewed=true`。
- 必须启用 `offline_core_chain`。
- `core_chain_coverage` 不能为空。
- 即使 `eligible=true`，仍然必须有人工 golden contract approval。

### Promotion guardrails

`candidate-lite` 不设置 expected/sensitivity review，也不污染 blocking baseline：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_promote --assets <asset_root> --asset-id <asset_id> --level candidate-lite
```

`candidate` 必须显式确认 expected signals 和 sensitivity：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_promote --assets <asset_root> --asset-id <asset_id> --level candidate --confirm-expected --confirm-sensitivity
```

`golden` 只能从合格 candidate 提升，并且需要人工批准：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_promote --assets <asset_root> --asset-id <asset_id> --level golden --confirm-expected --confirm-sensitivity --human-approved-golden
```

只有在人明确承担治理责任时才可使用 override，并且仍然必须传入 `--human-approved-golden`：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_promote --assets <asset_root> --asset-id <asset_id> --level golden --confirm-expected --confirm-sensitivity --human-approved-golden --override-golden-eligibility
```

Agent 可以解释 eligibility report 和提出建议，但不得自动决定 `candidate` 或 `golden` promotion。

### Deterministic profile asset pool boundary

F015 后 deterministic profile JSON 会包含 `asset_pool`：

```text
asset_pool.summary.lifecycle_distribution
asset_pool.blocking_baseline_asset_ids
asset_pool.warning_only_asset_ids
asset_pool.coverage_boundary
asset_pool.trust_limits
```

这些字段用于说明当前 profile 证明了哪些资产池边界。即使 `interpretation.verdict=no meaningful change`，也只表示当前 covered asset pool 未暴露有意义变化，不代表全局 RPA Agent 健康。

### 内网真实资产最小流程

1. 新资产放在内网本地 asset root，保持 `draft/captured`。
2. 生成 Review Packet，不直接要求人读 raw HTML / trace / checkpoint。
3. 若场景有观察价值，先升为 `candidate-lite`。
4. 跑 deterministic profile 或 governed regression，确认它只产生 warning-only observation。
5. 做 sensitivity review，确认敏感 HTML、截图、token、个人信息不会进入不该进入的位置。
6. 做 expected signals review，确认 expected 表达业务意图，不冻结偶然文案或绝对 selector。
7. 人工确认后升为 `candidate`。
8. 只有长期稳定、代表核心能力、低维护的 candidate 才进入 golden eligibility review。
9. human approval 后才允许 `golden` promotion。

## 内网交接最小清单

把 Harness 交给其它 Agent 使用前，至少提供：

- branch 或 commit：`codex/rpa-trace-first-harness` /
  `909c72c20b2c3f8e6c58b7ed5f8b30ff401ff054`；
- asset root，例如 `data\rpa_harness_assets_internal`；
- 实际执行的命令；
- JSON report path；
- 资产状态是 `draft`、`candidate` 还是 `golden`；
- sensitivity 和 expected signals 是否已 review；
- 当前任务是诊断、修 RPA core、重新录制资产，还是 promoted 资产。

如果这些输入缺失，Agent 应先追问，不要靠猜测定位。

## F016 asset-driven user input replay

Phase 4 第一切片让 Harness 从已捕获资产中提取“用户输入事件链”，并用脚本把
这些事件送入确定性的输入边界 adapter，记录 `boundary_injections`。它不是
full/live profile，不访问 live URL 作为 oracle，不让外层 Agent 点击产品 UI，
也不做自动 promotion。

核心边界仍然是：

```text
Scripts execute.
Agents explain.
Humans govern.
```

运行机器 JSON：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_user_input_replay --assets data\rpa_harness_assets_bootstrap --output docs\rpa\harness\reports\YYYY-MM-DD-user-input-replay.json
```

生成中文 summary：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_user_input_replay --assets data\rpa_harness_assets_bootstrap --format summary --lang zh --output docs\rpa\harness\reports\YYYY-MM-DD-user-input-replay.md --machine-report docs\rpa\harness\reports\YYYY-MM-DD-user-input-replay.json
```

Agent 优先读取 JSON 字段：

```text
schema_version
kind
profile
summary
asset_pool
selection
warning_only_observation
replayed_input_events
boundary_injections
failures
trace_session_result_ids
trust_limits
governance_boundary
```

生命周期规则：

- `candidate` / `golden` 是 blocking replay baseline。
- `candidate-lite` 是 warning-only observation；失败不应污染 blocking baseline。
- `draft` / `captured` / inactive / rejected assets 默认 excluded，并记录原因。

事件字段重点看：

```text
event_kind
injected_boundary
source_metadata.checkpoint_path
source_metadata.trace_events_path
payload.user_instruction
payload.locator_candidates
payload.region_context
result_refs.trace_id
result_refs.session_id
result_refs.result_id
diagnostics
runtime_result
injection
```

`injected_boundary` 不是只读标签；F016 会为每个 replay event 执行
`scripted_user_input_replay_adapter`，并在 `boundary_injections[*]` 记录 adapter、
boundary、status、trace/session/result id 和 input signal。第一切片的 adapter
是 record-only：它证明脚本边界被执行和记录，不证明 live UI side effect。

早期 bootstrap assets 曾经主要覆盖：

```text
navigation
click
natural_language_instruction
```

当前录制路径已经支持把表单 `fill` 写入 Harness checkpoint，并把输入值参数化为
`{{input:<key>}}`。但某个资产池是否真的具备 fill/type/select/submit/region
coverage，仍然取决于当前 runner JSON 里 selected/replayed events 和对应
trace/checkpoint 事实。不要因为测试 fixture 或某次 draft asset 支持这些事件，就声称
blocking baseline 已经覆盖真实表单输入或区域选择。

失败分析顺序：

1. 先看 `summary.blocking_failure_count` 和 `failures[*].failure_category`。
2. 再看失败事件的 `source_metadata`，打开对应 checkpoint 和 trace events。
3. 看 `payload`、`diagnostics` 和 `runtime_result` 判断输入事实是否缺失或损坏。
4. 如果失败来自 captured fact 缺失，先处理资产或 capture/export；不要在 Harness
   里加站点规则掩盖问题。
5. 如果失败暴露 RPA core 行为漂移，由 Agent 解释事实并回到 owning module 修复。

报告中的 `governance_boundary.agents_may_promote_automatically=false` 是硬边界。
Agent 可以解释 replay 报告和建议下一步，但不能自动把资产升为 `candidate` 或
`golden`。

## F017 full-live profile

`full-live` profile 是 v1 的高保真受控验证路径。它基于受管资产中的
`natural_language_instruction` 事件，在 controlled fixture 或 captured page state
上触发 recording-time intelligent path，再生成 profile artifact 并进入
post-capture checks。只有使用真实模型凭证和默认 Planner 运行时，它才证明真实
`Planner / LLM` 行为；如果使用 injected deterministic planner，它只证明
full-live wiring、fixture、Runtime 调用、trace/artifact 生成和 post-capture checks。

运行机器 JSON：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile full-live --generated-assets docs\rpa\harness\reports\f018-generated-assets --output docs\rpa\harness\reports\YYYY-MM-DD-full-live-profile.json
```

生成中文 summary：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_bootstrap --profile full-live --generated-assets docs\rpa\harness\reports\f018-generated-assets --format summary --lang zh --output docs\rpa\harness\reports\YYYY-MM-DD-full-live-profile.md --machine-report docs\rpa\harness\reports\YYYY-MM-DD-full-live-profile.json
```

Agent 优先读取 JSON 字段：

```text
profile
summary
source_asset_ids
selected_input_events
controlled_fixtures
planner_invocation_count
generated_asset_ids
post_capture
failures
trust_limits
governance_boundary
```

边界：

- 第一切片只覆盖 natural-language input event。
- 真实 Planner/LLM 质量必须来自无 injected planner 的 real Planner run；fake planner
  通过不能作为模型质量证据。
- click/type/select/submit 仍由 F016 deterministic user-input replay 表达。
- 不访问 live URL 作为 oracle。
- 不让外层 Agent 点击 RPA 产品 UI。
- 不自动 promotion。
- generated artifacts 只是 profile evidence，不是 governed asset pool。

## F018 v1 closeout / stabilization

v1 总入口是：

```text
docs/rpa/harness/RPA-Harness-v1-设计.md
```

未来 Agent 或人类应先从这个入口理解 v1 的用户旅程、profile 选择、报告解释边界、
generated artifact 身份和治理边界。

F018 的判断口径是：v1 closeout 成功不是因为新增功能，而是因为任何人都能从入口
知道怎么 capture、review、promote、执行、解释和治理。

必须特别注意：

- `docs/rpa/harness/reports/f017-generated-assets/...` 是 F017 full-live profile 的
  Evidence/profile artifact，不是 governed asset pool。
- F018 或后续 full-live 运行写入
  `docs/rpa/harness/reports/f018-generated-assets/...` 时同理。
- 如果 generated artifact 要进入长期资产池，必须经过 Assisted Review /
  Promotion、sensitivity review、expected-signal review 和人工确认。
- deterministic profile 仍是默认稳定回归路径。
- full-live profile 是 controlled high-fidelity validation，不是默认 blocking CI。
- 内部 controlled full-live scenario 可以进入 v1.1/backlog；除非人明确要求，不应阻塞
  v1 closeout。
