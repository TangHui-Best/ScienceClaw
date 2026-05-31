# RPA Harness 内网接管与封箱指南

> 生命周期说明：本文是当前 RPA Harness 内网接管与封箱入口。判断当前资产池状态时，
> 应先读本文，而不是历史 phase plan 或旧运行报告。本文是 guide，不是 Harness
> Feature/Evidence/ADR/Lesson；正式交付与 closeout 状态以
> `docs/features/F023-rpa-harness-internal-handoff-freeze.md` 和
> `docs/evidence/EV-023-rpa-harness-internal-handoff-freeze.md` 为准。

## 目的

这份文档是从当前外网开发机切换到内网开发前的 RPA Harness 单入口。它回答四个问题：

1. 当前 Harness 功能模块已经具备什么能力。
2. 内网接手后第一步应该跑什么、看什么。
3. 哪些资产状态可以作为 blocking baseline，哪些只能观察。
4. 哪些失败应回到 RPA core 修复，而不是继续扩张 Harness。

核心边界保持不变：

```text
Scripts execute.
Agents explain.
Humans govern.
```

Harness 是回归、诊断、证据和治理层。它不负责在自身内部修复 planner、snapshot、compiler、selector 或 extraction 的缺陷。

## 当前封箱状态

截至 2026-05-31，本机代码侧已经具备：

- 资产校验：`run_asset_validation`
- 资产目录与生命周期报告：`run_catalog --format lifecycle`
- Asset Pool Doctor：`run_asset_pool_doctor`
- Review Packet：`run_asset_review`
- 敏感信息扫描：`run_asset_sensitivity_scan`
- 脱敏资产副本：`run_asset_sanitize`
- 执行审查报告：`run_asset_execution_review`
- deterministic profile：`run_harness_profile --profile deterministic`
- user-input replay：`run_user_input_replay`
- full-live profile：`run_harness_profile --profile full-live`
- governed regression：`run_governed_regression`

但当前 `data/rpa_harness_assets_bootstrap` 的本机状态不能再被口头描述为“已有 blocking baseline”。在本机检查中，当前资产池是：

```text
asset_count=3
candidate-lite=2
draft=1
blocking_baseline_asset_ids=[]
expected_signals_reviewed=0
sensitivity_reviewed=0
```

历史报告中曾经存在两个 `candidate` asset 并跑通过 governed regression，但当前目录状态已经不同。后续 Agent 必须以当前 asset root 的实际 doctor/catalog 输出为准，不要引用历史报告替代当前资产池事实。

## 内网接手第一步

在内网机器上先设置环境：

```powershell
$env:PYTHONPATH='RpaClaw'
```

然后对内网资产根目录运行快速体检：

```powershell
python -m backend.rpa.harness.run_asset_pool_doctor --assets data\rpa_harness_assets_internal --format summary --lang zh
```

如果需要机器可读报告：

```powershell
python -m backend.rpa.harness.run_asset_pool_doctor --assets data\rpa_harness_assets_internal --output tmp-harness-asset-pool-doctor.json
```

优先看这些字段：

```text
summary.status
summary.readiness
summary.blocking_baseline_count
summary.warning_only_count
summary.recommended_next_action
blocking_baseline_asset_ids
warning_only_asset_ids
excluded_assets[*].reasons
trust_limits
```

判断口径：

- `ready`：至少有 active、reviewed 的 `candidate` / `golden`，且启用了 `offline_core_chain`。
- `warning`：有 `candidate-lite`，但没有 blocking baseline；可以观察，不可阻塞回归。
- `not_ready`：只有 draft/captured/rejected/inactive，或缺 expected/sensitivity review。

## 内网资产最小流程

新资产默认不可信，不应直接进入 blocking baseline。

推荐流程：

1. 新资产放在内网本地 asset root，例如 `data\rpa_harness_assets_internal\<asset_id>`。
2. 生成 Review Packet：

   ```powershell
   python -m backend.rpa.harness.run_asset_review --assets data\rpa_harness_assets_internal --asset-id <asset_id>
   ```

3. 做敏感信息扫描：

   ```powershell
   python -m backend.rpa.harness.run_asset_sensitivity_scan --assets data\rpa_harness_assets_internal --asset-id <asset_id>
   ```

4. 如果有诊断价值但还未人工确认，先升为非阻塞观察：

   ```powershell
   python -m backend.rpa.harness.run_asset_promote --assets data\rpa_harness_assets_internal --asset-id <asset_id> --level candidate-lite
   ```

5. 人工确认 expected signals 和 sensitivity 后，才允许进入 blocking `candidate`：

   ```powershell
   python -m backend.rpa.harness.run_asset_promote --assets data\rpa_harness_assets_internal --asset-id <asset_id> --level candidate --confirm-expected --confirm-sensitivity
   ```

6. 再跑 Asset Pool Doctor 和 deterministic profile：

   ```powershell
   python -m backend.rpa.harness.run_asset_pool_doctor --assets data\rpa_harness_assets_internal --format summary --lang zh
   python -m backend.rpa.harness.run_harness_profile --assets data\rpa_harness_assets_internal --profile deterministic --output tmp-harness-profile-deterministic.json
   ```

## 资产交接必须包含的信息

把一个内网资产交给后续 Agent 前，至少提供：

- asset root 和 asset id
- Human SOP
- Review Packet 路径
- 当前 lifecycle：`draft` / `captured` / `candidate-lite` / `candidate` / `golden`
- expected signals 是否已由人确认
- sensitivity 是否已由人确认
- 是否允许 candidate-lite
- 是否允许 blocking candidate
- 已知执行偏差或 Skill 泛化偏差
- rerun 命令
- local model config 文件位置，不要包含真实密钥内容

模板见：

- `docs/rpa/harness/templates/internal-asset-handoff.md`
- `docs/rpa/harness/templates/internal-asset-review-report.md`
- `docs/rpa/harness/templates/local_model_config.example.json`

## 失败归因顺序

不要从下游先修。先找最早失败层：

1. Asset validation
2. Snapshot regression
3. Compiler regression
4. Skill Replay E2E
5. Stateful SOP

归因规则：

- 资产缺文件、JSON 损坏、缺 trace events：先处理资产或 capture/export。
- raw snapshot 缺目标事实：检查 production DOM snapshot。
- raw 有事实但 compact 丢：检查 snapshot compression。
- `compiler-hardcoded-observed-value`：修 `TraceSkillCompiler` 或 dataflow inference，不要在 Harness 里加例外。
- Skill replay execution error：看 generated Skill、runtime AI model config、controlled fixture。
- Stateful SOP failed：先看 accepted trace reconstruction，再看 replay。

## Compiler 风险归属

当前 F022 后的主要残余风险已经不是 Harness 缺少 runner，而是 RPA core 的 compiler/generalization 边界：

- generated Skill 可能硬编码录制现场值；
- manual click trace 可能保留 `Issues 10` 这类现场文本；
- runtime semantic replay 输出 shape 可能与 expected 不匹配；
- dataflow 或 snapshot evidence 不足时，compiler 不能伪造确定性 DOM 提取。

这类问题的 owner 是：

```text
TraceSkillCompiler / trace dataflow / RPA core
```

不是：

```text
Harness expected signal exception / site-specific replay fixture / promotion shortcut
```

后续修复必须使用同一批资产 rerun，并把验证记录沉淀到对应 RPA core Feature/Evidence 中。

## 文档入口与归档规则

当前推荐入口：

1. 本文件：内网接管和封箱状态。
2. `RPA-Harness-v1-设计.md`：v1 总设计、profile 语义和治理边界。
3. `usage-and-triage-guide.md`：失败定位和 runner 解释。
4. `资产录制与审查最小流程.md`：新资产 review/promotion 最小流程。

已完成的 F013-F018 phase/closeout plan 已归档到：

```text
docs/archive/2026-05/rpa-harness/
```

它们仍可用于历史审计，但不再作为当前运行和内网接管入口。

## 不要做什么

- 不要把 `runtime_status=success` 当成资产通过。
- 不要把 `candidate-lite` 当成 blocking baseline。
- 不要把 full-live generated artifact 当成 governed asset pool。
- 不要让 Agent 自动 promotion。
- 不要用 live URL 作为 correctness oracle。
- 不要为了让 Harness 变绿而添加站点特定规则。
- 不要在 expected signals 中掩盖 compiler hardcoded observed value。

## 封箱后内网下一步

最小有价值路径：

1. 录制 1-2 个真实内网 Full SOP asset。
2. 生成 Review Packet 和 sensitivity scan。
3. 先升 `candidate-lite` 观察。
4. 人工确认 expected/sensitivity。
5. 升 `candidate`。
6. 跑 Asset Pool Doctor 和 deterministic profile。
7. 如果失败，按最早失败层回到 owning RPA core 修复。
