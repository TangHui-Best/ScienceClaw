---
id: LL-003
doc_kind: lesson
status: active
scope: project
feature_refs:
  - docs/features/F026-rpa-agent-scienceclaw-host-rebuild.md
applies_to:
  - RpaClaw/frontend/src/pages/rpa
  - RpaClaw/frontend/src/components/rpa
  - RpaClaw/backend/rpa_agent/host
created: 2026-07-19
updated: 2026-07-20
---

# LL-003：RPA 宿主 UI 被最小联调页替换时必须用产品契约与 Live E2E 保护

## Case

F026 新版领域核心和纵向 E2E 已通过大量离线契约与后端回放，但 Recorder 和 Configure 在实现时被缩减为最小 API 联调页。用户本地验收后发现录制工作台、停止后的配置页均与原 ScienceClaw 明显不同；后续真实 UI 验收又暴露了 Agent 结果未回显、通用 30 秒超时误报失败、停止期间轮询覆盖步骤快照，以及官方本地启动方式下生成包找不到/重复加载 `rpa_agent.runtime` 的问题。F026.4 的再次验收进一步发现：退出或重新录制虽然产生新的业务会话，却复用了旧 Playwright BrowserContext/Page，导致 URL、Cookie、Storage 和页面历史可能跨录制串扰。

## Resolution

恢复原流程导航、左侧步骤时间线、中部浏览器工作区、右侧 AI 录制助手和录制后双栏配置，仅把数据源替换为新版 `/rpa-agent` API 与 ViewModel。真实 Agent 结果返回对话区，Agent 调用使用独立超时；停止响应携带服务端最终步骤投影；生成包加载时临时把公共 `rpa_agent.runtime` 名称绑定到当前宿主已加载的同一模块。最后用本地真实 Qwen + browser-use 完成 GitHub Trending 录制、编译、回放和保存。会话生命周期修复则把 BrowserContext/Page 所有权明确归入单个录制会话：每次开始强制 `new_context()`，停止立即释放宿主端口，退出调用废弃会话 API；底层 Chromium/CDP 可以共享，但任何页面状态都不得共享。

## Pitfall

不要把“新 API 已连通”“三栏 DOM 存在”或后端 E2E 通过等同于宿主产品交互保持兼容。技术纵向切片可以正确，但仍可能通过替换页面、丢失反馈或破坏停止后的状态传递，使用户认为整个产品被重写。

## Root Cause

Harness 主要保护了新领域模型、结算、Compiler 和回放事实，没有把 ScienceClaw UI 的信息架构、关键交互路径、真实模型时延、官方本地启动拓扑和录制会话资源所有权写成可执行产品契约。最小联调页因此满足技术验收，却违背用户要求的宿主交互连续性；宿主租约也因此把“共享 Chromium 进程”错误放大成“共享已有 Context/Page”。

## Protection

- `RecorderPage.test.ts` 必须断言流程导航、左/中/右工作区、模型选择、对话结果和停止期间投影竞态。
- `ConfigurePage.test.ts` 必须断言原双栏配置工作流，并继续使用新版精确 binding location。
- `RpaStepTimeline.test.ts` 必须断言默认业务摘要、点击展开、执行/回放/编译三类独立状态和观察证据；“观察数组存在”但不可展开不算交互恢复。
- Test 页面必须同时保护左侧逐步结果、中部独立浏览器、右侧输入/回放/保存，以及顶部主操作从回放到保存的状态转换。
- `test_stop_draft_is_derived_from_exact_timeline_binding_locations` 必须断言停止响应包含最终 `creation_steps`。
- `test_default_host_services.py` 必须在生成包加载边界保护官方 `backend.main` 启动方式和运行时类型身份。
- 宿主租约必须提供并由录制入口启用 `isolated_context`，跨会话测试必须断言 BrowserContext/Page 身份不同且旧 Cookie/Storage 不可见；不得以新 session id 代替资源隔离证明。
- 停止录制必须在最终投影形成后立即释放浏览器端口；Recorder 离开页面必须调用废弃会话 API。监听器清理失败时仍必须尝试关闭宿主端口，不能把 Context 留给 TTL 兜底。
- 本地 opt-in Chromium 烟测必须连续创建至少两个录制会话，并同时覆盖 stop -> 新会话与 discard -> 新会话的资源释放边界。
- 用户可见录制变更在完成前必须执行至少一个本地非 Docker、真实 LLM + browser-use 的 Live UI 闭环，并记录 Evidence；离线替身只证明契约，不证明产品路径。

## Source

来自 [F026.3/F026.4](../features/F026-rpa-agent-scienceclaw-host-rebuild.md) 的用户回归反馈、[EV-031](../evidence/EV-031-rpa-agent-scienceclaw-ui-live-e2e.md) 的 UI/真实模型闭环、[EV-032](../evidence/EV-032-rpa-recording-session-browser-isolation.md) 的会话隔离修复，以及 [EV-036](../evidence/EV-036-f028-upstream-ui-interaction-recovery.md) 对同类回归再次发生后的 donor 交互契约补强。

## Principle

复用宿主不是复用后端基础设施就结束；只要用户被承诺交互连续性，宿主 UI 与录制会话生命周期就是必须由结构测试、资源身份断言和真实闭环共同保护的产品契约。共享宿主进程不等于共享会话状态，BrowserContext/Page 必须由单个录制会话独占并显式释放。
