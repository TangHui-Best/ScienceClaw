---
id: EV-025
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F025-browser-use-recording-operator-poc.md
created: 2026-07-05
updated: 2026-07-05
evidence_level: exhaustive
---

# EV-025: Browser-use Live UI E2E

## Supports Claim

本证据支持一个有限但关键的完成声明：ScienceClaw 录制页的“自然语言对话操作浏览器”入口可以在 local 模式下复用当前录制浏览器，调用 browser-use 完成真实浏览器操作，并把结果沉淀为 ScienceClaw accepted trace。

## Verification Scope

覆盖范围：

- 前端真实页面：`http://127.0.0.1:5177/rpa/recorder`
- 后端真实服务：`http://127.0.0.1:9798`
- RPA session start、CDP screencast、地址栏导航、自然语言 chat 入口
- local Playwright Chromium 通过 CDP URL 被 browser-use 复用
- browser-use 使用真实 OpenAI-compatible LLM 配置执行中文指令
- browser-use 操作完成后进入 ScienceClaw trace timeline

未覆盖范围：

- 完整业务 POC 矩阵，例如登录后操作、iframe、复杂表格、弹窗/抽屉、文件上传下载、多标签页、日期控件、富文本
- TraceSkillCompiler 生成 Skill 后的 replay 稳定性
- browser-use 每个内部微动作拆分为多个可回放 TraceStep 的完整粒度

## Checks

```powershell
.\.venv\Scripts\python.exe -m py_compile RpaClaw/backend/rpa/browser_use_recording_operator.py RpaClaw/backend/rpa/cdp_connector.py
```

```powershell
# Local CDP smoke: launch LocalCDPConnector browser, fetch ws://127.0.0.1:<port>/devtools/browser/<id>, then close.
```

```powershell
# Live UI E2E:
# 1. Start backend on 127.0.0.1:9798 with local mode and browser-use operator.
# 2. Open http://127.0.0.1:5177/rpa/recorder in real Chromium.
# 3. Wait for the recorder address bar and assistant input to become editable.
# 4. Navigate to https://github.com/trending through the recorder address bar.
# 5. Send the natural-language instruction: 打开和 codex 最相关的项目
# 6. Query /api/v1/rpa/session/{session_id} and inspect traces/diagnostics.
```

## Results

Pass.

Key backend evidence:

- RPA session id: `adc1b9e1-5953-4b4a-a724-af86bcf012d7`
- browser-use task instruction: `打开和 codex 最相关的项目`
- browser-use identified and clicked `openai/codex-plugin-cc`
- final browser URL: `https://github.com/openai/codex-plugin-cc`
- browser-use reported task success
- ScienceClaw session state:
  - `trace_count`: `2`
  - `diagnostic_count`: `0`
  - accepted trace 1: `source=manual`, `trace_type=navigation`, `after_url=https://github.com/trending`
  - accepted trace 2: `source=browser_use`, `trace_type=ai_operation`, `after_url=https://github.com/openai/codex-plugin-cc`
  - browser-use trace output included `action_count=3`

## Artifacts

- Backend live log: `.codex-live-backend-9798.err.log`
- Backend session endpoint checked during verification: `/api/v1/rpa/session/adc1b9e1-5953-4b4a-a724-af86bcf012d7`
- Code paths exercised:
  - `RpaClaw/backend/rpa/cdp_connector.py`
  - `RpaClaw/backend/rpa/browser_use_recording_operator.py`
  - `RpaClaw/backend/route/rpa.py`
  - `RpaClaw/backend/rpa/manager.py`

## Limitations

本证据不能证明完整业务矩阵已经通过，也不能证明生成的 Skill 已经稳定 replay。它证明的是最关键的 live UI 主链路已经打通：真实录制页接受用户自然语言指令，browser-use 复用当前录制浏览器完成操作，并生成 ScienceClaw accepted trace。

## Notes

本次 live UI E2E 先发现并修复了三个之前局部 E2E 没覆盖的问题：

- local 模式的 `LocalCDPConnector` 没有提供 browser-use 复用当前录制浏览器所需的 CDP URL。
- localhost CDP 探测需要禁用环境代理，否则 Windows 环境下可能得到代理返回的 `502 Bad Gateway`。
- browser-use 的 telemetry/cloud sync 事件可能在 `Agent.run()` 初始化 `_task_start_time` 前触发错误；ScienceClaw 集成层默认关闭该外部副作用，并在调用 `run()` 前预置 timing 属性，避免 finally 阶段用属性错误覆盖真实执行结果。
