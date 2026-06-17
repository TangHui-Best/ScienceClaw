---
id: F026
doc_kind: feature
status: active
created: 2026-06-17
updated: 2026-06-17
---

# F026: AIO Native Chat Session Runtime

## Goal

把普通 `chat/{sessionId}` 会话提升为会话级 AIO runtime 执行域：同一个 chat session 的 DeepAgent、Skill、shell/file、外部工具执行、会话文件预览和下载都应绑定到同一个 `SessionRuntimeRecord`，而不是在本地执行、旧全局 sandbox 和 RPA runtime proxy 之间分裂。

## Vision Anchor

- 原始请求或来源：用户确认当前问题不是单个 Skill 或 API 未接好，而是主会话页尚未完整适配 AIO 沙箱；并要求基于 `codex/aio-native-chat-runtime` 分支使用 AgentMentor 完成功能开发。
- 用户痛点或工程问题：`aio_native` 已经在 RPA/录制浏览器链路上更接近可用，但普通 Chat 会话仍残留旧 sandbox 假设；在会话中执行 Skill 时，shell/file/artifact 可能没有进入 AIO sandbox。
- 期望结果：`RUNTIME_MODE=aio_native` 下，`session_id` 是 runtime ownership key；Chat 首次需要执行能力时通过 `SessionRuntimeManager.ensure_runtime(session_id, user_id)` 创建或复用 AIO sandbox，后续同一会话复用同一个执行面。
- 非目标或边界：不让每个 Skill 感知 AIO；不为 Chat、RPA、Skill 分别散落 `aio_native` 判断；不恢复 Runtime Adapter 作为第一阶段上线依赖；不修改 RPA trace/compiler/recorder 事实链路。
- 设计边界：`storage_backend=local` 只表示会话元数据和本地 Skill 源可以存本机，不再等同于执行面在本机；执行面由 `runtime_mode` 决定。

## Current Status

Active。首个后端闭环已经完成：普通 `deep_agent()` 在 `RUNTIME_MODE=aio_native` 时会确保会话 runtime 并使用 runtime-scoped sandbox backend；外部工具执行器和会话 sandbox 文件读取 fallback 已经改为优先使用 session runtime。真实内网 AIO create/status/refresh/delete 与真实 shell/file API 仍需在内网环境 smoke 验证。

## Links

- Decision: [ADR-006 AIO 原生 API 优先的会话级沙箱接入策略](../decisions/ADR-006-aio-native-api-first-runtime-strategy.md)
- Prior Feature: [F025 AIO Session Sandbox Runtime Adapter](F025-aio-session-sandbox-runtime-adapter.md)
- Handoff: [AIO Native Runtime Provider 内网交接](../rpa/aio-native-internal-handoff.md)
- Provider Notes: [AIO Native Runtime Provider](../rpa/aio-native-runtime-provider.md)
- RPA Boundary ADR: [ADR-004 RPA Core Owns Recording Facts, Harness Adapts Only](../decisions/ADR-004-rpa-core-owns-recording-facts-harness-adapts-only.md)
- Evidence: [EV-026 AIO Native Chat Session Runtime](../evidence/EV-026-aio-native-chat-session-runtime.md)

## Acceptance Criteria

- [x] `STORAGE_BACKEND=local` 且 `RUNTIME_MODE=aio_native` 时，普通 `deep_agent()` 会话会 ensure session runtime，并使用 runtime 的 `rest_base_url` 构建远程 sandbox backend。
- [x] 同一配置下，外部工具执行器使用 runtime-scoped sandbox base，而不是回退到本地执行器。
- [x] `FullSandboxBackend` 能把 `SessionRuntimeRecord.runtime_token` 注入 sandbox HTTP client，避免真实 AIO 执行面需要鉴权时丢失 token。
- [x] 本地 Skill 源在 local storage + remote runtime execution 场景中会被注入到 session sandbox 的 `.skills` 目录，Skill 本身无需感知 AIO。
- [x] `sessions.py` 的 sandbox 文件读取/下载 fallback 会按 `session_id -> SessionRuntimeRecord` 找 runtime base，并在 runtime token 存在时注入 `Authorization` header。
- [x] 默认本地模式未设置 AIO runtime 时仍保持本地执行行为。
- [x] 不触碰 RPA trace/compiler/recorder Core 主链路；若后续触碰 Core 文件，再运行 Core SOP->Skill focused regression。

## Patch History

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F026.1 | 2026-06-17 | pending | `RUNTIME_MODE=aio_native` + `STORAGE_BACKEND=local` 下，Chat/Skill shell 与 file 仍可能走本地或旧全局 sandbox；文件预览 fallback 即使切到 runtime base，也可能漏带 runtime token。 | DeepAgent 把 `storage_backend=local` 直接等同于本地执行面，没有让普通 chat session 成为 runtime ownership key；sessions 文件 API fallback 只选择 URL，没有继承 runtime 鉴权上下文。 | `test_deep_agent_uses_session_runtime_when_aio_native_overrides_local_storage`、`test_external_tool_executor_uses_sandbox_when_runtime_base_is_provided`、`test_sandbox_file_read_uses_session_runtime_base_when_available`、`test_full_sandbox_client_injects_runtime_token_header`。 | done |
| F026.2 | 2026-06-17 | pending | 本机 AIO 模拟中，Chat 创建 `hello.txt` 时工具调用进入 `/home/rpaclaw/workspace/...` 并返回 502；DeepAgent prompt 也仍可能冻结旧 workspace。 | AIO 原生 `/v1/sandbox` 的真实 home 为 `/home/gem`，而本地 Windows 默认配置会把旧 sandbox home 派生成 `\home\rpaclaw\workspace`；`deep_agent()` 在读取 runtime context 前就取走了 `sandbox.workspace`。 | `test_full_sandbox_rebases_workspace_to_runtime_home_dir`、`test_deep_agent_uses_session_runtime_when_aio_native_overrides_local_storage`、`test_deep_agent_eval_uses_session_runtime_when_aio_native`；本机 Node fetch probe 验证 `/home/gem/workspace/...` file API 可自动创建父目录。 | done |
| F026.3 | 2026-06-17 | pending | 最新页面验证仍显示工具路径为 `/home/rpaclaw/workspace/...`，并在 `/v1/file/write`、`/v1/file/read` 上返回 502。 | 请求开始时 `/v1/sandbox` 曾瞬时返回 502，`FullSandboxBackend` 因无法读取 context 而保留默认旧路径；`AioNativeRuntimeProvider` 也没有把已发现的 `home_dir` 缓存在 `SessionRuntimeRecord.metadata` 中。 | `test_full_sandbox_uses_runtime_home_dir_when_context_temporarily_unavailable`、`test_aio_native_runtime_provider_uses_fixed_native_aio_browser_info`、DeepAgent runtime metadata 传递断言；本机手动 `ensure_runtime()` 已把 `metadata.home_dir=/home/gem` 写入 session runtime。 | done |
| F026.4 | 2026-06-17 | pending | 页面再次验证时，backend 初始化日志已显示 workspace 为 `/home/gem/workspace/{session_id}`，但模型工具参数仍直接传入 `/home/rpaclaw/workspace/{session_id}`；同时 shell/file 请求仍可能对 `127.0.0.1:18090` 返回 502。 | 旧会话历史会诱导模型继续生成旧 workspace 绝对路径，backend 边界未把同一 session 的 legacy workspace 前缀归一到当前 AIO workspace；另外 `FullSandboxBackend` 的 `httpx.AsyncClient` 尚未像 runtime adapter/provider 一样设置 `trust_env=False`，本机环境下存在被代理配置污染 AIO localhost 控制流量的风险。 | `test_full_sandbox_rewrites_legacy_workspace_paths_for_file_tools`、`test_full_sandbox_rewrites_legacy_workspace_paths_inside_shell_commands`、`test_full_sandbox_client_injects_runtime_token_header`。 | done |
| F026.5 | 2026-06-17 | pending | shell 验证最终成功，但日志显示模型并发发出 `execute pwd` 与 `execute cat ...` 时，共享 shell session 输出出现 `pwdcat: command not found`。 | DeepAgent 可并行调度多个 `execute` tool call，而 `FullSandboxBackend` 对同一个 shell session 没有串行化保护；交互式 shell API 不能安全承载同一 session 的并发命令流。 | `test_full_sandbox_serializes_concurrent_shell_exec_calls`；AIO focused set `15 passed, 81 deselected, 1 warning`。 | done |
| F026.6 | 2026-06-17 | pending | 主会话执行录制 Skill 时读取到了 `/skills/.../SKILL.md`，但执行 `python3 /skills/.../skill.py` 失败，随后用 `curl` 模拟了浏览器结果。 | `/skills` 是 DeepAgent file/read 的虚拟 Skill 路由，不是 AIO shell 文件系统中的真实目录；本地 Skill 实际注入到 `{workspace}/.skills/{skill_name}`。此外老录制 Skill 在 AIO 中运行还需要 Python Playwright 依赖和可用 Chromium。 | `test_full_sandbox_rewrites_virtual_skill_paths_inside_shell_commands`；AIO focused set `16 passed, 81 deselected, 1 warning`；本机 raw AIO smoke 执行 `github-trending-best-project` 返回 `SKILL_SUCCESS`。 | done |
| F026.7 | 2026-06-17 | pending | 内网 AIO 平台要求 lifecycle API 带 `X-HW-ID` / `X-HW-APPKEY`，沙箱内部 API 还必须带动态 `x-livefunction-sandbox-id={sandboxId}`；仅靠现有 `AIO_BASE_URL` / Bearer token 配置无法访问内网网关。 | `aio_native` 首轮实现只覆盖本机固定 AIO 和 Bearer token 形态，没有把平台账号 header 与 create 返回的 `sandboxId` 组合成后续 shell/file/browser 请求 header；完整 URL 环境变量也未兼容。 | `test_aio_native_runtime_provider_can_use_intranet_lifecycle_api`、`test_full_sandbox_client_prefers_runtime_headers_for_native_aio`、`test_sandbox_file_read_uses_aio_native_gateway_headers`、`test_sandbox_tool_executor_sends_gateway_headers`；focused set `107 passed, 31 warnings`。 | done |

## Patch Churn Review

2026-06-17：F026 的 7 个补丁都收敛在同一个执行面边界：普通 Chat 会话必须把 `session_id -> SessionRuntimeRecord -> AIO home/workspace` 作为 shell/file/Skill 的唯一真源。F026.1 先把 `storage_backend=local` 与“本地执行面”解耦；F026.2 发现 AIO 原生沙箱真实 home 不是旧默认 `/home/rpaclaw`，把 workspace rebase 到 `/v1/sandbox.home_dir`；F026.3 进一步修复 transient context 502 时的回退问题，把 `home_dir` 缓存在 runtime metadata，并传入 `FullSandboxBackend`；F026.4 则把防线推进到工具执行边界：禁用环境代理污染，并把同一 session 的旧 workspace 绝对路径归一到当前 AIO workspace；F026.5 修复同一 shell session 的并发 execute 串扰，保证 DeepAgent 并行 tool call 不会把命令流交错写入同一个交互式 shell；F026.6 把虚拟 `/skills` 路由桥接到 AIO shell 可执行的 `.skills` 实际目录；F026.7 将内网 AIO 网关的账号 header 与动态 sandbox header 纳入 runtime request boundary。

这不是站点经验规则、Skill 内部适配或 RPA Core 事实链路变更。后续若继续出现 Chat/Skill 文件路径错误，不应继续在单个工具、单个 Skill 或 prompt 中补路径规则，而应优先检查 `SessionRuntimeRecord.metadata.home_dir` 是否来自真实 AIO context、`FullSandboxBackend.workspace` 是否仍由 runtime metadata/context 派生，以及前端预览/下载是否消费同一个 session runtime。

## Evidence

见 [EV-026 AIO Native Chat Session Runtime](../evidence/EV-026-aio-native-chat-session-runtime.md)。

## Local AIO Simulation Finding

- 2026-06-17 本机 `aio_native` 模拟验证发现，AIO 原生 `/v1/sandbox` 返回的真实 home 目录为 `/home/gem`，而旧配置默认 `SANDBOX_RPA_CLAW_HOME=/home/rpaclaw` 在 Windows 本地会被 `Path(...)` 派生成 `\home\rpaclaw\workspace`。因此 Chat runtime 不能把配置默认值当作 AIO 工作区真源。
- `FullSandboxBackend` 在 AIO native session runtime 下以 runtime context 的 `home_dir` 重建工作区：`{home_dir}/workspace/{session_id}`。DeepAgent、Skill、shell/file、eval agent 只消费这个 workspace contract，不感知 AIO 细节。
- 本机 AIO file API 已验证可在 `/home/gem/workspace/{session_id}/...` 下自动创建父目录；截图中的 502/失败路径根因是错误旧路径 `/home/rpaclaw/workspace/...`，不是必须新增 mkdir bootstrap。

## Next Step

进入人工 review；同步到内网后按 ADR-006 与 AIO native handoff 对真实 AIO shell/file、session runtime lifecycle、preview/download 进行 smoke。若前端 Chat 预览仍混用旧 RPA/VNC proxy，再以独立补丁把 Chat 页预览路由统一到 session runtime proxy。
