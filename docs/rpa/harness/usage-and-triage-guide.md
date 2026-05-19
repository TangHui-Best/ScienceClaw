# RPA Harness 使用与问题定位指南

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

当前默认 repo-safe baseline 只有一个 candidate asset：

```text
data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc
```

所以 Harness 已经可运行，但置信度仍受 `single-candidate-asset-baseline`
限制。真正提升价值的下一步是录制更多内网真实资产并审核 promoted。

## 环境准备

在仓库根目录执行命令：

```powershell
$env:PYTHONPATH='RpaClaw'
```

Harness 不需要启动 FastAPI backend 或 frontend dev server。它需要本地
Python 环境、项目依赖，以及 Playwright/browser 依赖，因为 snapshot 和
replay runner 会用到浏览器能力。

内网迁移时，直接拉取包含 F009 的分支或 commit：

```text
branch: codex/rpa-trace-first-harness
current pushed HEAD: 909c72c20b2c3f8e6c58b7ed5f8b30ff401ff054
```

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

2. 跑 asset validation。

3. 做 sensitivity review。内网页面 HTML、截图、凭证、session token、个人信息
   不应复制到外部仓库。

4. 做 expected signals review。expected signals 应表达业务意图，不应冻结偶然的
   absolute selector 或临时页面文案。

5. 审核通过后再编辑 `scenario.json` promoted：

   ```json
   {
     "asset_status": "active",
     "sensitivity": "local-only",
     "governance": {
       "promotion_status": "candidate",
       "runner_modes": [
         "offline_core_chain",
         "skill_replay_e2e",
         "stateful_sop_capture_to_skill"
       ],
       "core_chain_coverage": [
         "html_to_raw_snapshot",
         "raw_to_compact_snapshot",
         "planner_action_selection",
         "trace_to_skill",
         "skill_replay",
         "stateful_capture_to_skill"
       ],
       "expected_signals_reviewed": true,
       "sensitivity_reviewed": true,
       "review_notes": "Internal reviewed candidate asset."
     }
   }
   ```

6. 对内网资产根目录跑 governed regression：

   ```powershell
   $env:PYTHONPATH='RpaClaw'
   python -m backend.rpa.harness.run_governed_regression --assets data\rpa_harness_assets_internal --format summary --lang zh
   ```

`golden` 只给应当成为 blocking regression fixture 的资产。还在评估的资产先用
`candidate`。

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
