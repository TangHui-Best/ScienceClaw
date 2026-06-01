# RPA Harness v1 Design

> 生命周期说明：本文是当前 v1 设计总入口和兼容索引，不是 implementation plan，
> 也不能单独作为完成证据。判断当前接管/封箱状态时先读
> `internal-handoff-and-freeze-guide.md`；判断交付状态时读关联 Feature/Evidence。

## Vision

RPA Harness v1 把 Phase 0-5 已经完成的能力收束成一个可执行、可解释、
可治理、可恢复上下文的闭环：

```text
Scripts execute.
Agents explain.
Humans govern.
```

它的目标不是继续增加 runner，也不是把 Harness 变成第二个 RPA Agent。v1 的目标是
让 RPA core-chain 变更可以通过受管资产反复验证，让 Agent 在事实报告之后解释，
让人决定资产治理和后续取舍。

详细设计源仍然是：

[RPA Harness v1: Asset-Driven User Input Replay](rpa-harness-v1-asset-driven-user-input-replay.md)

本文件是 v1 的设计总入口。若任务是从当前外网开发机切换到内网开发、判断封箱状态、
选择资产池体检命令或确认当前 bootstrap 资产治理状态，应先读
[RPA Harness 内网接管与封箱指南](internal-handoff-and-freeze-guide.md)。
未来 Agent 或人类如果只读一份 v1 设计文档，应先读这里。
录制后审查、人工正确性判断、Skill 泛化预期和资产升级的最短操作说明见：
[RPA Harness 资产录制与审查最小流程](资产录制与审查最小流程.md)。

## User Journey

v1 的完整用户旅程是：

```text
capture
  -> review
  -> promote
  -> deterministic
  -> user-input replay
  -> full-live
  -> Agent analysis
  -> human decision
```

含义如下：

1. `capture`: 录制或导入 Harness asset，保存 checkpoint、HTML、trace、
   runtime result、expected signals 等事实。
   Full SOP checkpoint 是语义时间线：输入框 focus click 可折叠进随后的 `fill`，
   表单输入值应参数化为 `{{input:<key>}}` 或 runtime secret ref。
2. `review`: 生成 Review Packet，让人和 Agent 阅读事实摘要，而不是直接翻原始
   HTML / trace / checkpoint。
3. `promote`: 通过 CLI 和人工确认把资产从 `draft` 推进到
   `candidate-lite` / `candidate` / `golden`。
4. `deterministic`: 默认稳定回归路径，验证受管资产上的核心链路。
5. `user-input replay`: 从资产中提取用户输入事件链，并用脚本记录输入边界。
6. `full-live`: 在 controlled fixture 上触发 recording-time intelligent path。
   使用真实模型凭证运行时，它验证 `RecordingRuntimeAgent / Planner / LLM` 路径；
   使用 injected deterministic planner 运行时，它只验证 fixture、Runtime 调用、
   trace/artifact 和 post-capture 检查的集成闭环。
7. `Agent analysis`: Agent 读取 JSON-first 报告和 summary，解释事实、边界和风险。
8. `human decision`: 人决定是否修 RPA core、补资产、promote 资产、进入 v1.1，
   或接受当前 residual risk。

## Asset Lifecycle

v1 使用固定生命周期：

| Lifecycle | 用途 | 是否 blocking |
| --- | --- | --- |
| `draft` / `captured` | 新捕获事实资产，默认本地，先生成 Review Packet。 | 否 |
| `candidate-lite` | 人工初筛后的 warning-only observation。 | 否 |
| `candidate` | 人工确认 expected signals 和 sensitivity 后的 blocking regression asset。 | 是 |
| `golden` | 从 candidate 人工批准提升的长期 contract asset。 | 是 |

规则：

- `candidate-lite` 只能作为 warning-only observation，不能污染 blocking baseline。
- `candidate` 必须显式确认 expected signals 和 sensitivity。
- `golden` 必须从合格 candidate 人工批准提升。
- Agent 可以解释 eligibility report 和 review packet，但不能自动决定
  `candidate` 或 `golden` promotion。

## Main Commands

### Deterministic Profile

默认稳定回归路径：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile `
  --assets data\rpa_harness_assets_bootstrap `
  --profile deterministic `
  --output docs\rpa\harness\reports\YYYY-MM-DD-deterministic-profile.json
```

需要给人读时生成 summary：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile `
  --assets data\rpa_harness_assets_bootstrap `
  --profile deterministic `
  --format summary `
  --lang zh `
  --output docs\rpa\harness\reports\YYYY-MM-DD-deterministic-profile.md `
  --machine-report docs\rpa\harness\reports\YYYY-MM-DD-deterministic-profile.json
```

### User-Input Replay

脚本化重放资产中的用户输入边界：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_user_input_replay `
  --assets data\rpa_harness_assets_bootstrap `
  --output docs\rpa\harness\reports\YYYY-MM-DD-user-input-replay.json
```

需要给人读时生成 summary：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_user_input_replay `
  --assets data\rpa_harness_assets_bootstrap `
  --format summary `
  --lang zh `
  --output docs\rpa\harness\reports\YYYY-MM-DD-user-input-replay.md `
  --machine-report docs\rpa\harness\reports\YYYY-MM-DD-user-input-replay.json
```

### Full-Live Profile

在 controlled fixture 上触发 recording-time intelligent path：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile `
  --assets data\rpa_harness_assets_bootstrap `
  --profile full-live `
  --generated-assets docs\rpa\harness\reports\f018-generated-assets `
  --output docs\rpa\harness\reports\YYYY-MM-DD-full-live-profile.json
```

需要给人读时生成 summary：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_harness_profile `
  --assets data\rpa_harness_assets_bootstrap `
  --profile full-live `
  --generated-assets docs\rpa\harness\reports\f018-generated-assets `
  --format summary `
  --lang zh `
  --output docs\rpa\harness\reports\YYYY-MM-DD-full-live-profile.md `
  --machine-report docs\rpa\harness\reports\YYYY-MM-DD-full-live-profile.json
```

## Which Profile To Run

| Situation | Run | Why |
| --- | --- | --- |
| 普通 RPA core-chain 变更、PR/readiness closeout、默认回归 | deterministic profile | 最稳定、最可比较，不调用真实 Planner/LLM。 |
| 需要确认资产是否能表达用户输入边界、输入事件链、boundary injection 记录 | user-input replay | 证明 captured facts 可以脚本化进入输入边界。 |
| 修改 Planner/LLM、RecordingRuntimeAgent、自然语言录制路径，或需要高保真受控验证 | full-live profile | 在 controlled fixture 上触发 intelligent path；只有真实模型凭证运行才证明真实 Planner/LLM 行为。 |
| 新录制或内网资产准备进入治理流程 | Review Packet + lifecycle / eligibility report | 先审查事实、敏感性和 expected signals，再考虑 promotion。 |
| 想证明全局 RPA Agent 健康 | 不应只靠 v1 bootstrap profiles | v1 报告只证明 covered asset pool 范围内的事实。 |

默认选择是 deterministic profile。full-live 是补充高保真 profile，不是默认
blocking pre-submit path。

## What Results Prove

deterministic profile 可以证明：

- 当前受管 `candidate/golden` 资产覆盖的 offline core-chain 未暴露 blocking
  regression。
- snapshot、compiler、Skill Replay、Stateful SOP 等已有 runner facts 可被同一份
  JSON 报告读取。
- `interpretation.verdict=no meaningful change` 只表示当前 covered asset pool
  的单次运行未见有意义变化，不表示全局健康，也不表示 improvement。

user-input replay 可以证明：

- 资产中已经捕获的 navigation、click、fill、natural-language instruction 等输入事实
  能被提取为 replay event；实际覆盖以当前 runner JSON 的 selected/replayed events
  为准。
- `boundary_injections` 记录了脚本 adapter 对输入边界的执行。
- 第一切片的 adapter 是 record-only；它不证明 live UI side effect，也不证明
  full-live Planner 行为。

full-live profile 可以证明：

- controlled fixture + natural-language event 可以进入
  `RecordingRuntimeAgent` 执行路径。
- 当 run 使用真实模型凭证和默认 Planner 时，报告可以作为真实 Planner/LLM
  行为证据。
- 当 run 使用 injected deterministic planner 时，报告只能证明 full-live profile
  的 fixture、Runtime 调用、trace/artifact 生成和 post-capture 检查集成闭环。
- 生成的 accepted trace / generated artifact 可以进入 post-capture checks。
- 这是一条高保真受控验证路径，不是 live URL 正确性来源。

任何 profile 都不能证明：

- 全局 RPA Agent 完全健康。
- live 网站当前状态就是正确性判据。
- Agent 可以自动 promotion。
- generated profile artifacts 可以默认进入 governed asset pool。
- injected deterministic planner 的通过结果可以证明真实模型质量或内网 Planner
  行为。
- 失败根因已经自动确定；Agent 只能基于报告事实提出推断。

## Report Interpretation

Agent 必须优先读机器 JSON，再读 Markdown summary。

deterministic profile 优先字段：

```text
profile
summary.status
summary.first_failure_category
summary.selected_asset_ids
summary.excluded_asset_ids
asset_pool
interpretation
deterministic.observability.runner_signals
```

user-input replay 优先字段：

```text
summary
asset_pool
selection
replayed_input_events
boundary_injections
failures
governance_boundary
```

full-live profile 优先字段：

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

解释时先说明：

- 执行了哪个 profile；
- 选中了哪些资产，排除了哪些资产；
- 是否有 blocking failure；
- 第一个 failure category 是什么；
- 结论只覆盖哪些资产池和 profile 边界；
- 下一步应由资产治理、RPA core 修复、补充场景，还是人工 review 处理。

## Generated Artifact Identity

`docs/rpa/harness/reports/f017-generated-assets/...` 是 F017 full-live profile 的
Evidence/profile artifact。

F018 或后续 full-live 运行生成的：

```text
docs/rpa/harness/reports/f018-generated-assets/...
```

也同样只是 Evidence/profile artifact。

这些目录不是 governed asset pool。未来 Agent 不应把它们当成默认可 promote 的
资产根，也不应从 report folder 直接把 artifact 视为 `candidate` 或 `golden`。

细节上，某些 generated `scenario.json` 在一次 full-live 通过后可能记录
`promotion_status=candidate-lite`，因为它们是 profile 运行产物。这个状态不改变
folder-level 规则：report folder 仍是 Evidence/profile artifact，不是默认 baseline
asset root。

如果某个 generated artifact 确实要进入长期资产池，必须先经过：

```text
generated profile artifact
  -> Assisted Review / Review Packet
  -> sensitivity review
  -> expected-signal review
  -> human confirmation
  -> CLI-backed promotion
```

在此之前，它只能作为某次 full-live profile 的证据材料。

## Governance Boundaries

v1 默认不接 CI blocking。

原因：

- 当前 bootstrap assets 覆盖仍窄；
- deterministic profile 是 process-required 的 readiness evidence path，但还不是
  技术强制门禁；
- full-live profile 有 Planner/LLM、browser timing、fixture fidelity 等噪声；
- CI blocking 需要更稳定的资产池、敏感性策略和失败归因体验。

v1 不自动 promotion。

原因：

- `candidate` / `golden` 是治理状态，不是 runner 成功状态；
- expected signals 和 sensitivity 必须由人确认；
- golden 是长期 contract asset，需要人工批准。

v1 不把 live URL 当正确性来源。

原因：

- live 页面会受权限、排序、A/B、时序、数据变动影响；
- ADR-003 已经决定 correctness unit 是 governed scenario assets；
- full-live 只能使用 controlled fixture 或 captured state 做受控验证。

v1 不让外层 Agent 操控 UI。

原因：

- 默认执行路径必须可复现、可比较；
- 外层 Agent 点击产品 UI 会叠加 UI 状态、模型方差和 timing 噪声；
- Agent 的位置在事实产生之后：解释报告，不是替代脚本执行。

## v1 Closeout Boundary

F018 closeout 成功的判断不是新增功能，而是未来任何 Agent 或人类都能从这个入口
理解：

- Harness v1 是什么；
- 怎么 capture、review、promote、执行；
- deterministic / user-input replay / full-live 各自证明什么；
- 哪些报告能作为证据；
- 哪些资产只是 Evidence artifact，不能误当成 governed asset；
- 下一步增强应进入 v1.1，而不是继续膨胀 v1。

内部 controlled full-live scenario 不应默认阻塞 v1 closeout。当前 bootstrap /
controlled full-live 验收足以证明 v1 核心闭环、报告边界和 profile wiring 已经存在。
若要验证真实内部模型或内网页面，应作为 v1.1/backlog 增加 1-2 个 internal
controlled scenario，除非人明确把内部场景纳入 v1 完成标准。

## Source Map

- F013 deterministic profile:
  [Feature](../../features/F013-rpa-harness-v1-asset-driven-user-input-replay.md),
  [Evidence](../../evidence/EV-013-rpa-harness-v1-asset-driven-user-input-replay.md)
- F014 evidence/report trust loop:
  [Feature](../../features/F014-rpa-harness-v1-evidence-report-trust-loop.md),
  [Evidence](../../evidence/EV-014-rpa-harness-v1-evidence-report-trust-loop.md)
- F015 lifecycle operationalization:
  [Feature](../../features/F015-rpa-harness-v1-asset-lifecycle-operationalization.md),
  [Evidence](../../evidence/EV-015-rpa-harness-v1-asset-lifecycle-operationalization.md)
- F016 user-input replay:
  [Feature](../../features/F016-rpa-harness-v1-asset-driven-user-input-replay.md),
  [Evidence](../../evidence/EV-016-rpa-harness-v1-asset-driven-user-input-replay.md)
- F017 full-live profile:
  [Feature](../../features/F017-rpa-harness-v1-full-live-profile-integration.md),
  [Evidence](../../evidence/EV-017-rpa-harness-v1-full-live-profile-integration.md)
- F018 closeout/stabilization:
  [Feature](../../features/F018-rpa-harness-v1-closeout-stabilization.md),
  [Evidence](../../evidence/EV-018-rpa-harness-v1-closeout-stabilization.md)
- Golden evaluation decision:
  [ADR-003](../../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)
- Usage and triage:
  [RPA Harness 使用与问题定位指南](usage-and-triage-guide.md)
