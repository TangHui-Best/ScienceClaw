# TraceSkillCompiler 风险归属说明

## 目的

这份说明把 F022/F023 暴露出的 compiler / generalization 风险明确归属到 RPA core，而不是 RPA Harness。

Harness 的职责是保存受管资产、重跑事实链路、暴露失败层和生成可审查报告。它不应该通过站点特例、expected-signal 例外或 replay fixture 放宽来掩盖 generated Skill 的泛化问题。

## 当前风险

已观察到的风险类型：

- `compiler-hardcoded-observed-value`：generated Skill 把录制现场值写入可执行逻辑。
- 现场文本依赖：例如手动点击 trace 保留 `Issues 10` 这类当次页面文本，导致 replay 页面变化后失败。
- 输出 shape 不稳定：runtime semantic replay 可能返回字符串、对象或列表，与 expected/replay 断言不一致。
- dataflow 证据不足：后续步骤依赖前序输出时，如果 `_results` / `output_key` 没有被保留，compiler 可能退化为硬编码。
- snapshot evidence 不足：没有可靠结构化字段或区域证据时，compiler 不应发明确定性 DOM 提取。

## Owner

这些问题的 owner 是：

```text
TraceSkillCompiler
trace_recorder / dataflow inference
trace evidence classification
snapshot / region evidence supplied to compiler
```

不是：

```text
Harness expected signals
asset promotion
asset review packet
controlled replay fixture
site-specific harness rule
```

## 修复原则

后续修复应遵守：

1. 先用同一批资产复现失败，记录最早失败层。
2. 如果失败类别是 `compiler-hardcoded-observed-value`、`compiler-output-key-lost` 或 `compiler-dataflow-lost`，优先修 `TraceSkillCompiler` / dataflow，而不是修改 expected signals。
3. 录制现场 URL、项目名、链接文本、列表项、临时排序只能作为 evidence，不能成为最终 Skill 的泛化逻辑。
4. 缺少强证据时，compiler 应诚实回退 runtime AI 或保留语义 replay，而不是伪造确定性 selector。
5. 修复后用同一 asset root rerun：

   ```powershell
   $env:PYTHONPATH='RpaClaw'
   python -m backend.rpa.harness.run_asset_pool_doctor --assets <asset_root> --format summary --lang zh
   python -m backend.rpa.harness.run_harness_profile --assets <asset_root> --profile deterministic --output tmp-harness-profile-deterministic.json
   ```

## 验收信号

一个 compiler/generalization 修复不应只让某个单步 replay 通过，还应证明：

- 不再报告对应 `compiler-hardcoded-observed-value`。
- generated Skill 保留必要的 `output_key`。
- 需要跨步骤数据时保留 `_results` 引用。
- expected output shape 与 replay actual output 有稳定契约。
- 没有新增站点特定 Harness 规则。

## 与 Harness 的关系

Harness 可以做：

- 捕获失败事实；
- 报告 failing runner 和 failure category；
- 指出 likely owner；
- 在修复后用同一批资产 rerun；
- 阻止未 review 资产进入 blocking baseline。

Harness 不应该做：

- 为某个站点加特殊 selector；
- 放宽 expected signals 来掩盖硬编码；
- 自动 promotion；
- 把 `candidate-lite` 当 blocking baseline；
- 把 live URL 当 correctness oracle。

## 后续归属

如果内网真实资产继续暴露 compiler 风险，应创建或归属到 RPA core Feature，例如：

```text
TraceSkillCompiler generalization hardening
```

该 Feature 的 Evidence 应引用触发失败的 asset、doctor/profile 报告、generated Skill 片段和修复后的 rerun 结果。
