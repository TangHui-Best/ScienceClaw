# 新版 RPA Agent 本地 CDP 宿主修复设计

> 文档状态：已确认设计，待实现。
>
> 归属：F026.1，修复 F026 在 `STORAGE_BACKEND=local` 下遗漏真实产品启动验收的问题。

## 1. 问题与目标

新版录制页创建浏览器会话后，`POST /api/v1/rpa-agent/sessions` 无条件通过 `SessionRuntimeManager` 获取 CDP。当前本地配置未设置 `RUNTIME_MODE`，因此运行时默认选择 `shared`，把浏览器地址解析为仅容器网络可达的 `http://sandbox:8080`。Windows 宿主无法解析 `sandbox`，异常最终被折叠为 `rpa_agent.browser_host_unavailable` 503。

本修复的目标是：

- `STORAGE_BACKEND=local` 且未设置 `RUNTIME_MODE` 时，新版录制会话直接使用本地 Chromium/CDP；
- 人工输入、Screencast 和 Browser-use 始终连接同一个 BrowserContext；
- Shared、Docker、K8s 的现有 Runtime Lease 行为保持不变；
- 新版领域核心不反向依赖旧 `backend.rpa` 领域模型、Trace 或 Compiler；
- 宿主接入失败时保留可诊断的后端根因，同时继续向客户端返回脱敏错误码。

## 2. 非目标

- 不通过启动本地 Sandbox 服务或修改 `SANDBOX_BASE_URL` 绕过问题；
- 不改变 CoreTrace、Settlement、Compiler、Skill 产物或前端录制交互协议；
- 不迁移旧 RPA 会话和资产；
- 不在本补丁中处理模型密钥明文持久化问题，该安全问题应独立治理。

## 3. 方案

### 3.1 中立的本地 CDP 宿主层

在 `backend/runtime` 下建立中立的本地 CDP 生命周期模块。该模块只负责：

- 在 Windows 兼容的独立 Proactor Event Loop 中启动和持有本地 Chromium；
- 暴露稳定、可等待的 CDP WebSocket URL；
- 对并发获取做串行化，避免重复启动浏览器；
- 提供幂等关闭能力，并明确区分“关闭 CDP 客户端连接”和“关闭宿主浏览器”。

旧 `backend/rpa/cdp_connector.py` 保持原有公开入口，但把本地浏览器启动和 CDP URL 获取委托给该中立模块。这样新旧调用方共享同一份宿主生命周期，不产生第二套本地浏览器实现。

### 3.2 新版宿主按运行模式分流

`backend/rpa_agent/host/scienceclaw_browser.py` 的 Lease 获取分为两条路径：

```text
STORAGE_BACKEND=local
  -> 中立 Local CDP Host
  -> 获取 CDP URL
  -> Playwright connect_over_cdp
  -> 选择或创建 Context/Page
  -> BrowserPreviewRegistry.register(session_ref, page, cdp_url)
  -> BrowserSessionPort

非 local
  -> SessionRuntimeManager.ensure_runtime
  -> runtime /v1/browser/info
  -> Playwright connect_over_cdp
  -> BrowserPreviewRegistry.register(...)
  -> BrowserSessionPort
```

两条路径在获得 CDP URL 后复用同一个“连接、选择 Page、注册 Preview、引用计数、释放”的实现，避免本地与容器模式在 Page 选择规则上继续分叉。

### 3.3 所有权与清理

- 浏览器会话所有权校验仍在获取宿主资源之前执行；
- RPA Agent Lease 关闭时，注销自己注册的 Preview Page 并断开自己的 Playwright CDP 客户端；
- 本地 Chromium 的最终生命周期由中立宿主层管理，单个 RPA Agent 会话停止不得误杀其他会话正在使用的浏览器；
- 同一 `browser_session_ref` 的并发 Lease 使用引用计数，最后一个 Lease 释放后清理注册和客户端连接。

### 3.4 错误处理与可观测性

- API 对外继续返回 `503` 与 `rpa_agent.browser_host_unavailable`，不暴露内部 URL、堆栈或凭据；
- 后端在捕获宿主异常时记录异常类型、运行模式、会话引用和失败阶段；
- 不再用无日志的宽泛捕获吞掉本地 CDP 启动、CDP 信息获取、连接和 Preview 注册的真实根因。

## 4. 测试设计

实施遵循 TDD，先增加并运行失败用例，再写生产代码。

### 4.1 必须先失败的回归用例

1. `STORAGE_BACKEND=local` 时，默认 Provider 不调用 `SessionRuntimeManager.ensure_runtime`，而使用注入的 Local CDP URL。
2. 本地 Provider 能注册带精确 CDP provenance 的 Page，并成功返回 `BrowserSessionPort`。
3. `POST /api/v1/rpa-agent/sessions` 在本地模式返回 201，而不是 503。
4. 两个并发本地 Lease 只启动一次宿主浏览器，释放顺序不会提前关闭共享资源。

### 4.2 保持通过的回归

- 现有 Shared Runtime Lease、CDP URL rewrite 和 provenance mismatch 测试；
- 新版 RPA Agent route/host/architecture tests；
- 旧 Local CDP connector 的现有测试；
- RecorderPage 目标测试与前端生产构建。

### 4.3 真实冒烟验收

在 Windows 本地配置下启动真实 Chromium，创建 browser-mode ScienceClaw 会话，再创建新版 RPA Agent 会话，确认：

- HTTP 状态为 201；
- Preview Registry 中存在活动 Page；
- 返回的 `main_scope` 可用于人工输入；
- Browser-use CDP URL 与 Preview Registry provenance 完全一致；
- 停止会话后资源清理无异常。

## 5. 验收标准

- 原始失败配置 `STORAGE_BACKEND=local`、`RUNTIME_MODE` 缺省时不访问 `http://sandbox:8080`；
- 点击“录制技能”可以建立新版 RPA Agent 会话；
- Screencast、人工输入和 Browser-use 共享同一个本地浏览器上下文；
- 非本地 Runtime 行为与既有测试结果不变；
- 新生产目录继续通过旧 RPA 领域依赖护栏；
- F026 增加 `F026.1` Patch History，并以新的 Evidence 记录红绿测试、回归和真实冒烟结果。

## 6. 回滚路径

若本地宿主迁移导致旧 RPA 本地执行回归，可恢复旧 `cdp_connector.py` 的本地实现，同时保留新版 Provider 的模式分流和回归测试；不得回退到 `sandbox:8080` 配置绕过。所有新模块均为进程内宿主适配，不涉及数据迁移或持久化 Schema，代码回滚即可恢复。
