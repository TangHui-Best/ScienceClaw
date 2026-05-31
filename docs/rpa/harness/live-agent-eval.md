# Live Agent Eval：验证自然语言 SOP 转义能力

> 生命周期说明：本文是 live-agent evaluation runner 的 active guide。它被
> F012/F017 Evidence 引用，但自身不是 Harness Feature/Evidence/ADR/Lesson。
> 交付与 closeout 状态以 F012/EV-012 或 F017/EV-017 为准。

## 背景

离线 Harness 负责验证“已沉淀 trace 资产 -> Skill 编译 -> Skill 回放”的确定性链路。它不触发 `RecordingRuntimeAgent`，也不让 Planner/LLM 基于当前页面重新决策。

这对回归很有价值，但不能回答一个更核心的问题：RPA Agent 在真实自然语言步骤下，是否能把 SOP 步骤转义成可沉淀、可编译、可回放的 Skill 资产。

`live_agent_eval` 用来补上这一层验证：

- 启动真实 Playwright 页面。
- 使用受控 HTML fixture，避免依赖 live 外网页面或内网页面状态。
- 调用 `RecordingRuntimeAgent.run()` 执行自然语言步骤。
- 将成功的 AI trace 捕获为 Harness `candidate-lite` 资产。
- 立即复用现有 Harness 检查：资产校验、snapshot regression、compiler regression、skill replay、stateful SOP capture-to-skill。

## 适用场景

适合用于内网验证前后的能力检查：

- 验证自然语言步骤是否真实触发 Planner/LLM。
- 验证 Agent 输出的临时代码是否能沉淀为 trace。
- 验证 trace 是否能进入后置 Skill 编译和回放链路。
- 给 iframe、区域选择、动态列表、表单填写等场景建立最小可复现 fixture。

不适合替代离线 governed regression。离线 Harness 仍然是稳定回归主路径；Live Agent Eval 是更靠近真实录制体验的补充入口。

## 运行方式

```powershell
$env:PYTHONPATH = "RpaClaw"
python -m backend.rpa.harness.run_live_agent_eval `
  --scenarios data\rpa_harness_live_scenarios_internal `
  --assets data\rpa_harness_assets_internal `
  --output tmp-harness-live-agent-internal.json
```

如果需要显式传入模型配置：

```powershell
python -m backend.rpa.harness.run_live_agent_eval `
  --scenarios data\rpa_harness_live_scenarios_internal `
  --assets data\rpa_harness_assets_internal `
  --model-config-file data\local_model_config.json `
  --output tmp-harness-live-agent-internal.json
```

CLI 默认不注入 fake planner，因此会使用 `RecordingRuntimeAgent` 的真实 Planner/LLM 配置。单元测试为了确定性，会注入 fake planner，但这不是内网运行方式。

## Scenario 格式

最小示例：

```json
{
  "schema_version": "rpa-harness-live-agent-scenario-v0",
  "scenario_id": "invoice-total",
  "instruction": "Extract the invoice total",
  "url": "https://fixture.local/invoice",
  "html": "<html><body><dt>Invoice Total</dt><dd id=\"invoice-total\">$42.00</dd></body></html>",
  "expected": {
    "output_key": "invoice_total",
    "must_contain_text": ["$42.00"]
  },
  "page_patterns": ["detail-page", "data-extraction"]
}
```

字段说明：

- `instruction`：传给 `RecordingRuntimeAgent.run()` 的自然语言步骤。
- `url`：fixture 页面地址；runner 会拦截该 URL 并返回本地 HTML。
- `html` / `html_path`：二选一，定义受控页面内容。
- `expected.output_key`：期望输出字段名，用于报告和资产检查。
- `expected.must_contain_text`：输出中必须包含的文本信号。
- `page_patterns`：写入生成资产的页面模式标签，便于后续筛选。

## 资产状态

Live Agent Eval 生成的资产会被标记为：

- `asset_status = active`
- `promotion_status = candidate-lite`
- `sensitivity = local-only`
- `environment.runner = live_agent_eval`
- `environment.controlled_fixture = true`

这表示资产已经能被 Harness runner 消费，但还没有经过人工期望信号、敏感信息和泛化边界复核。需要复核后，才应该提升到 `candidate` 或 `golden`。

## 边界

- 会真实启动 Playwright，并调用 `RecordingRuntimeAgent.run()`。
- 内网 CLI 默认会走真实 Planner/LLM；测试中才会注入 fake planner。
- 不访问 live 外网或内网页面；页面由 scenario HTML 控制。
- 不重新规划整套 SOP，只验证单个自然语言步骤能否转成可沉淀 trace。
- 不把成功结果直接视为黄金样本；只产出 `candidate-lite`。

## 与 iframe 修复的关系

iframe 问题后续可以新增一个专门 scenario：fixture 页面外层包含 iframe，目标元素放在 iframe 内部。这样可以验证：

- snapshot 是否保留 frame context。
- Planner/LLM 是否能生成正确的 frame 定位代码。
- 捕获 trace 是否能被 `TraceSkillCompiler` 编译成可回放 Skill。
- replay 时是否仍然能在受控 iframe fixture 中找到目标元素。

在内网模型链路尚未验证前，不建议把旧 `codex/rpa-frame-context-facts` 的改动直接搬入当前分支。更稳妥的路径是先用 Live Agent Eval 建立可复现场景，再在新的 v2 分支里围绕失败事实修复 iframe frame context。
