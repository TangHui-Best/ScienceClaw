# 执行审查报告（Execution Review）

资产 ID: `hcap-fd43c31be477429e9418199e2e557af5-sanitized`
资产状态: `draft`
Promotion: `candidate-lite`
Sensitivity: `sanitized`
Expected reviewed: `False`
Sensitivity reviewed: `False`

## 结论摘要

- SOP→Skill 链路: 已触发但未通过
- 重建 trace 数: `5`
- generated Skill size: `15572`
- Runtime result keys: `about_content, issue_titles`

## 执行入口边界

本报告验证的是 Harness 离线执行入口：已有 asset -> 重建 trace session -> TraceSkillCompiler -> generated Skill -> controlled replay。
它会复用 `RecordingRuntimeAgent` 和 `TraceSkillCompiler` 等核心组件，但不等同于真实 UI/RPA 服务入口。
真实 UI/RPA 服务入口通常会先解析用户选择的模型配置或数据库中的默认模型配置，再把 `model_config` 透传给 runtime AI。
当前 generated Skill 的 runtime AI 只读取 `_runtime_context.runtime_ai.model_config` 或 `_model_config`；如果 runner 没注入这些配置，即使项目 `.env` 里有其它命名的凭证，也会在 replay 时表现为模型凭证缺失。

## Runner Summary

| Runner | Status | Runtime AI Config | Total | Passed | Failed | Failure Categories |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot` | `passed` | - | 5 | 5 | - | - |
| `compiler` | `failed` | - | 5 | 3 | 2 | - |
| `skill_replay` | `failed` | harness_explicit_model_config | 5 | 2 | 3 | replay-output-shape-mismatch=3 |
| `stateful_sop` | `failed` | harness_explicit_model_config | 1 | - | 1 | controlled-replay-execution-error=1 |

## Failure Analysis

| Runner | Step | 问题 | 证据 |
| --- | --- | --- | --- |
| `stateful_sop` | SOP | controlled-replay-execution-error | TimeoutError: Locator.click: Timeout 10000ms exceeded. Call log: - waiting for get_by_role("link", name="Issues 10") |
| `skill_replay` | 2 | 输出形态与 expected 不一致 | replay-output-shape-mismatch |
| `skill_replay` | 3 | 输出形态与 expected 不一致 | replay-output-shape-mismatch |
| `skill_replay` | 5 | 输出形态与 expected 不一致 | replay-output-shape-mismatch |
| `compiler` | 2 | 生成 Skill 硬编码录制现场值 | click |
| `compiler` | 4 | 生成 Skill 硬编码录制现场值 | Issues 10 |

## Report Files

- `stateful_sop_execution_report.json`: present
- `skill_replay_execution_report.json`: present
- `compiler_execution_report.json`: present
- `snapshot_execution_report.json`: present

## Suggested Next Actions

- 当前执行报告未再出现模型凭证缺失；后续应继续处理 replay 输出形态和 compiler 泛化问题。
- 若目标是让该资产进入 blocking baseline，应先人工确认 expected signals 和 sensitivity。
- 若 compiler 报 `compiler-hardcoded-observed-value`，应修 TraceSkillCompiler 泛化逻辑，而不是修改录制事实。
- 若 replay 报输出形态不匹配，应对齐 generated Skill 输出结构和 `expected.json` 的 `observed_output_shape`。
