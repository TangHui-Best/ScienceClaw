# RPA Harness 简介：从录制资产到可回归基线

RPA Harness 是 RpaClaw 的录制资产治理与回归验证层。它不替代 RPA Agent，也不在 Harness 内部修 planner、snapshot、compiler、selector 或 extraction 的问题。它负责把一次真实录制沉淀为可审查、可升级、可执行、可分析的资产。

核心边界：

```text
Scripts execute.
Agents explain.
Humans govern.
```

也就是说：脚本负责执行检查和生成报告；Agent 负责解释事实、定位风险和建议下一步；人负责确认业务预期、敏感性和资产升级。

## 执行前准备

所有命令默认在仓库根目录执行：

```powershell
$env:PYTHONPATH='RpaClaw'
$assetRoot = 'data\rpa_harness_assets_internal'
$assetId = '<asset_id>'
```

这里 `$env:PYTHONPATH` 是 Python 模块解析环境变量；`$assetRoot` 和 `$assetId` 是
PowerShell 变量，只是为了让下面的命令少写路径。它们不等价于
`RPA_HARNESS_CAPTURE_ENABLED` / `RPA_HARNESS_ASSETS_DIR`：

- `RPA_HARNESS_CAPTURE_ENABLED` 和 `RPA_HARNESS_ASSETS_DIR` 控制产品录制时是否写出
  Harness 资产、写到哪里。
- `$assetRoot` 和 `$assetId` 控制录制后 CLI 脚本读取哪个资产池、哪个资产。

如果使用本地 bootstrap 资产池，可把 `$assetRoot` 改为：

```powershell
$assetRoot = 'data\rpa_harness_assets_bootstrap'
```

常用参数：

| 参数 | 含义 |
| --- | --- |
| `--assets` | Harness 资产根目录。 |
| `--asset-id` | 指定单个资产；部分脚本可重复传入。 |
| `--output` | 写出 JSON 报告，适合 Agent 分析或留证。 |
| `--format summary` | 输出人类可读摘要。 |
| `--lang zh` | 使用中文摘要。 |
| `--model-config-file` | full-live 或 runtime AI replay 需要模型配置时使用；不要提交真实密钥。 |

## 资产旅程

一个 Harness 资产通常从 Full SOP 录制开始，最终可能成为 `candidate` 或 `golden` 回归基线。

```text
录制
  -> 扫描 / 检测
  -> 人工矫正预期（可选）
  -> 人工审批
  -> 资产升级
  -> 资产执行
  -> 结果分析
  -> 异常修复（可选）
  -> rerun
```

### 1. 录制：先保存事实

录制由产品流程完成。录制后，一个资产通常出现在：

```text
<assetRoot>/<assetId>/
  scenario.json
  review.md
  execution_review.md
  steps/
    001/
      checkpoint.json
      trace_events.json
      expected.json
      before.html
      after.html
```

录制只回答“当时发生了什么”，不回答“业务结果是否正确”。`runtime_status=success` 只说明运行时认为步骤执行完了，不代表资产可以进入回归基线。

Full SOP 的 `steps/001`, `steps/002` ... 是语义 checkpoint 顺序，不是浏览器原始事件流水号。录制器会按最终 accepted trace / `session.steps` 时间线刷新 checkpoint：

- 导航、点击跳转、表单填值等会成为可审查步骤。
- 纯输入框 focus click 通常会折叠进随后的 `fill`，避免把“点进输入框”当作业务步骤。
- 通过 `Ctrl+V` / `Cmd+V` / paste 写入输入框时，物理快捷键不应成为业务
  `press` 步骤；录制事实应归一为目标输入框的 `fill`，并在 signals 中保留
  `source_method=paste` 之类的输入方式证据。
- 如果浏览器事件异步到达，Harness 以排序后的 trace 时间线为准补齐 checkpoint，而不是按事件到达顺序落盘。
- 表单输入值会在写入资产时参数化，例如 `{{input:login_username}}` / `{{input:login_password}}`；`trace_events.json`、`expected.json`、`checkpoint.json.step_intent` 和 HTML 页面证据都应共享同一套替换。
- 输入参数名只来自 `fill` 的稳定证据（已有 `input_contract`、`data-testid`、`label`、`placeholder`、`role name`、弱 locator 序号等），用于提升 review/replay 可读性；它不参与 recorder 事件捕获、accepted trace 排序、下载归因或 compiler 动作分支。

因此，内网验证 Full SOP 时，应把资产步骤与生成 Skill 的语义步骤对齐，而不是要求每一次 DOM click / focus 都单独出现。若 Skill 有某个语义步骤但资产缺对应 checkpoint，优先按 capture/export 问题处理；若资产有 checkpoint 但 expected 或 generated Skill 不符合业务预期，再进入 review / compiler / replay 归因。

### 2. 扫描 / 检测：先看资产是否健康

先看整个资产池是否具备回归价值：

```powershell
python -m backend.rpa.harness.run_asset_pool_doctor `
  --assets $assetRoot `
  --format summary `
  --lang zh
```

需要机器可读报告时：

```powershell
python -m backend.rpa.harness.run_asset_pool_doctor `
  --assets $assetRoot `
  --output tmp-harness-asset-pool-doctor.json
```

重点看：

```text
summary.status
summary.readiness
summary.blocking_baseline_count
blocking_baseline_asset_ids
warning_only_asset_ids
excluded_assets[*].reasons
trust_limits
```

再做资产结构校验：

```powershell
python -m backend.rpa.harness.run_asset_validation `
  --assets $assetRoot `
  --output tmp-harness-asset-validation.json
```

这一步检查资产文件是否完整、JSON 是否可读、checkpoint / trace / expected / HTML 是否齐备。

### 3. 敏感信息扫描

对新资产做 sensitivity scan：

```powershell
python -m backend.rpa.harness.run_asset_sensitivity_scan `
  --assets $assetRoot `
  --asset-id $assetId
```

如果不传 `--output`，脚本会把单资产报告写入：

```text
<assetRoot>/<assetId>/sensitivity_scan.json
```

需要汇总 JSON 时：

```powershell
python -m backend.rpa.harness.run_asset_sensitivity_scan `
  --assets $assetRoot `
  --asset-id $assetId `
  --output tmp-harness-sensitivity-scan.json
```

扫描结果只是风险提示，不能替代人工确认。进入 `candidate` 或 `golden` 前，仍需人确认 sensitivity。

### 4. 生成人工审查入口

生成 Review Packet：

```powershell
python -m backend.rpa.harness.run_asset_review `
  --assets $assetRoot `
  --asset-id $assetId
```

它会生成或更新：

```text
<assetRoot>/<assetId>/review.md
```

人主要读 `review.md`，确认 SOP 意图、每步输出、expected signals、敏感性和 promotion 建议。Agent 可以协助解释，但不能替人批准资产升级。

### 5. 人工矫正预期（可选）

如果录制事实有价值，但自动 expected signals 不对，不要篡改 `trace_events.json`。正确做法是：

- 保留真实录制事实。
- 在 `review.md` 或 triage report 里写清人工判断。
- 修正或补充 `expected.json` 中的机器可执行预期。
- 重新运行 `run_asset_review` 和 `run_asset_validation`。

核心原则：

```text
recorded facts are evidence
reviewed expectations are acceptance criteria
promotion is a human governance act
```

### 6. 人工审批与资产升级

只做诊断观察，不阻塞回归：

```powershell
python -m backend.rpa.harness.run_asset_promote `
  --assets $assetRoot `
  --asset-id $assetId `
  --level candidate-lite
```

进入 blocking `candidate`，必须确认 expected signals 和 sensitivity 已人工审查：

```powershell
python -m backend.rpa.harness.run_asset_promote `
  --assets $assetRoot `
  --asset-id $assetId `
  --level candidate `
  --confirm-expected `
  --confirm-sensitivity
```

升级 `golden` 需要额外人工批准：

```powershell
python -m backend.rpa.harness.run_asset_promote `
  --assets $assetRoot `
  --asset-id $assetId `
  --level golden `
  --confirm-expected `
  --confirm-sensitivity `
  --human-approved-golden
```

生命周期含义：

| 状态 | 含义 | 是否阻塞回归 |
| --- | --- | --- |
| `draft` / `captured` | 新录制事实，尚未治理。 | 否 |
| `candidate-lite` | 可观察、可诊断，但不阻塞。 | 否 |
| `candidate` | 人工确认后进入回归基线。 | 是 |
| `golden` | 长期稳定、高价值基线。 | 是 |

不要为了让回归“看起来通过”跳级。资产升级的意义是提高信任，不是制造通过率。

### 7. 资产执行

默认先跑 deterministic profile：

```powershell
python -m backend.rpa.harness.run_harness_profile `
  --assets $assetRoot `
  --profile deterministic `
  --output tmp-harness-profile-deterministic.json
```

需要给人读：

```powershell
python -m backend.rpa.harness.run_harness_profile `
  --assets $assetRoot `
  --profile deterministic `
  --format summary `
  --lang zh `
  --output tmp-harness-profile-deterministic.md `
  --machine-report tmp-harness-profile-deterministic.json
```

跑综合回归：

```powershell
python -m backend.rpa.harness.run_governed_regression `
  --assets $assetRoot `
  --format summary `
  --lang zh
```

需要 JSON 留证：

```powershell
python -m backend.rpa.harness.run_governed_regression `
  --assets $assetRoot `
  --output tmp-harness-governed-regression.json
```

如果涉及 runtime AI replay 或 full-live 路径，可传入本地模型配置：

```powershell
python -m backend.rpa.harness.run_harness_profile `
  --assets $assetRoot `
  --profile full-live `
  --model-config-file local_model_config.json `
  --output tmp-harness-profile-full-live.json
```

### 8. 结果分析

对单个资产生成执行审查包：

```powershell
python -m backend.rpa.harness.run_asset_execution_review `
  --assets $assetRoot `
  --asset-id $assetId
```

它会生成或更新：

```text
<assetRoot>/<assetId>/execution_review.md
```

分析失败时，先判断归属：

| 现象 | 优先归属 |
| --- | --- |
| 缺文件、JSON 损坏 | asset governance |
| raw snapshot 缺目标事实 | snapshot capture |
| raw 有但 compact 丢失 | snapshot compression |
| trace 正确但 Skill 硬编码现场值 | TraceSkillCompiler |
| deterministic 通过但 full-live 失败 | RecordingRuntimeAgent / Planner / LLM path |
| 没有 blocking baseline | asset pool governance |

Harness 暴露问题，不应在自己内部悄悄修业务链路问题。若失败属于 RPA core，应回到对应模块修复，再用同一资产 rerun。

### 9. 异常修复后 rerun

如果修的是资产治理问题，通常 rerun：

```powershell
python -m backend.rpa.harness.run_asset_validation --assets $assetRoot
python -m backend.rpa.harness.run_asset_review --assets $assetRoot --asset-id $assetId
python -m backend.rpa.harness.run_asset_pool_doctor --assets $assetRoot --format summary --lang zh
```

如果修的是 RPA core 问题，通常 rerun：

```powershell
python -m backend.rpa.harness.run_harness_profile --assets $assetRoot --profile deterministic --output tmp-harness-profile-deterministic.json
python -m backend.rpa.harness.run_governed_regression --assets $assetRoot --output tmp-harness-governed-regression.json
python -m backend.rpa.harness.run_asset_execution_review --assets $assetRoot --asset-id $assetId
```

可信闭环不是“代码改了”，而是：

```text
同一个资产
  -> 同一组 runner
  -> 失败消失，或残留风险被明确记录
```

## 快速判断

- 只想知道当前资产池能不能用于回归：跑 `run_asset_pool_doctor`。
- 想审一个新录制资产：跑 `run_asset_sensitivity_scan` 和 `run_asset_review`。
- 想验证 RPA core 改动有没有退化：跑 `run_harness_profile --profile deterministic` 或 `run_governed_regression`。
- 看到 `blocking_baseline_asset_ids=[]`：不要声称当前 RPA Agent 在 blocking baseline 上健康；这只说明当前资产池还没有足够可信的阻塞基线。

## 继续阅读

- [RPA Harness v1 设计](RPA-Harness-v1-设计.md)
- [资产录制与审查最小流程](资产录制与审查最小流程.md)
- [使用与问题定位指南](usage-and-triage-guide.md)
- [内网接管与封箱指南](internal-handoff-and-freeze-guide.md)
