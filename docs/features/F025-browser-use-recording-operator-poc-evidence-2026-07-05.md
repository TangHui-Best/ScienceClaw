---
id: F025-evidence-2026-07-05
doc_kind: feature_evidence
feature_id: F025
created: 2026-07-05
---

# F025 browser-use 录制 Operator 第一阶段证据

## 实现结果

第一阶段基础集成已完成：

- 新增 `BrowserUseRecordingOperator`，通过 `RPA_RECORDING_OPERATOR=browser_use` 切换录制期自然语言浏览器操作实现，默认仍为 `native`，避免破坏现有路径。
- browser-use 通过 CDP URL 复用当前录制浏览器；如果拿不到 CDP URL，不会另开浏览器伪装成功，而是返回失败诊断。
- browser-use action history、action result、extracted content 会沉淀到 accepted trace 的 `signals.browser_use`；trace 使用 `source=browser_use`、`ai_execution.language=browser_use`。
- TraceSkillCompiler 对 browser-use trace 生成 `_execute_browser_use_instruction` runtime replay；普通 runtime AI trace 仍走原有 `RecordingRuntimeAgent` 路径。
- browser-use history 明确失败时，adapter 不再生成成功 trace，避免“操作失败但 trace 成功”的假阳性。

## 验证证据

- Core regression: `PYTHONPATH=RpaClaw pytest RpaClaw/backend/tests/test_browser_use_recording_operator.py RpaClaw/backend/tests/test_rpa_runtime_context_browser_use.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_recording_runtime_agent.py RpaClaw/backend/tests/test_rpa_route_trace.py -q` -> 243 passed, 29 warnings.
- Harness/SOP regression: 使用工作区 `.tmp/pytest` 作为 `TMP/TEMP` 后，`test_rpa_harness_skill_replay.py`、`test_rpa_harness_stateful_sop.py`、`test_rpa_harness_governed_regression.py` -> 29 passed, 2 failed。失败原因是当前 checkout 缺少固定 bootstrap asset `data/rpa_harness_assets_bootstrap/hcap-4be6265f43eb42dfa259182207aa64cc`。
- Real browser-use E2E: 本地 HTTP 页面 + headless Chromium CDP + `BrowserUseRecordingOperator` + 真实 OpenAI-compatible LLM。用户指令为“输入 invoice 并点击 Search”，最终页面状态为 `Searched invoice`，trace source 为 `browser_use`，trace language 为 `browser_use`，action_count 为 `4`。

## 模型配置校正

- 用户提供的 `Qwen3.6-Max-Preview` 在该 endpoint 上返回 `model_not_found`。
- `/models` 返回可用模型 `qwen3.7-max-preview`，因此本地 ignored `.env` 已改为 `qwen3.7-max-preview` 以完成真实 E2E。
- API key 只写入 ignored `.env` 文件，不进入仓库。

## 剩余验收

- 仍需在真实业务系统页面上跑完整 POC 矩阵：登录后页面、iframe、表格搜索/筛选/行内按钮、弹窗/抽屉/下拉树、上传下载、分页提取、多标签页、日期控件、富文本/复杂组件。
- 仍需对真实业务录制生成的 Skill 做 replay 验证，确认 browser-use runtime replay 能满足业务稳定回放，而不仅是录制期完成操作。
