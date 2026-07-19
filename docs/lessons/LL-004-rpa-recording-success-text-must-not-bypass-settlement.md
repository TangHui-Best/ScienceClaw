---
id: LL-004
doc_kind: lesson
status: active
scope: project
feature_refs:
  - docs/features/F027-rpa-agent-recording-finalization-contract.md
applies_to:
  - RpaClaw/backend/rpa_agent/browser_use
  - RpaClaw/backend/rpa_agent/host
  - RpaClaw/backend/route/rpa_agent.py
  - RpaClaw/frontend/src/pages/rpa
created: 2026-07-19
updated: 2026-07-19
---

# LL-004：RPA 录制成功文本不能绕过动作结算与输出绑定

## Case

真实 Live UI 中，browser-use 已完成导航和点击，聊天区也返回成功，但 Candidate 仍为 pending，配置保存返回 422。数据任务“获取 star 数”还能只在 `done` 文本返回数值，UI 一度把非 SOP 动作计入步骤，导致“看起来完成”与“可编译产物”分离。

## Resolution

生产路由按本轮 Candidate ID 精确调用 Settlement Engine；导航、点击和变量输出使用宿主可验证证据；`extract_variable` 映射为显式 extract CoreTrace；当前轮没有 Candidate 时拒绝 `done`；前端改用 `replayable_action_count`。针对 readiness timeout、重定向查询参数和 browser-use 方括号索引增加了边界级规范化与回归测试。

## Pitfall

不要把 LLM 的最终文本、工具无异常返回或 UI 成功提示当成录制成功。也不要在停止录制时批量接受 pending，或用站点关键词补丁伪造输出语义。

## Root Cause

系统缺少“每轮实际动作必须关闭自己的证据、结算和输出契约”这一生产不变量：Adapter 负责注册但 route 未负责结算；完成协议只依赖模型服从，没有工具边界阻止无动作 `done`；UI 又混用了执行动作数和可回放步骤数。

## Protection

- `BrowserSession.settle_agent_round` 只结算本轮 Agent Candidate。
- `RecordingBrowserUseTools.act` 在当前轮无 Candidate 时拒绝 `done`。
- `classify_candidate_action` 只接受确定性后置条件或显式变量输出。
- `test_agent_instruction_settles_round_candidates_before_configuration` 覆盖生产 route 到配置。
- Host/Adapter 测试覆盖导航超时、重定向、点击后 DOM、显式 extract、方括号索引和无动作 `done`。
- Recorder/API 测试覆盖 `replayable_action_count` 与真实模型长耗时。
- 高风险完成声明必须附本地真实 LLM Live UI Evidence；外部额度失败必须保留为限制，不能改写成通过。

## Source

来自 [F027](../features/F027-rpa-agent-recording-finalization-contract.md) 与 [EV-033](../evidence/EV-033-rpa-recording-finalization-live-ui.md) 的真实 GitHub 录制、配置 422 及后续复跑轨迹。

## Principle

在 Agent 系统中，“模型说成功”只是会话状态；只有动作级证据完成结算并进入单一事实时间线，才是可录制、可编译、可回放的工程能力。
