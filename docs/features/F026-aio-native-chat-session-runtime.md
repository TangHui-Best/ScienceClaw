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

## Evidence

见 [EV-026 AIO Native Chat Session Runtime](../evidence/EV-026-aio-native-chat-session-runtime.md)。

## Next Step

进入人工 review；同步到内网后按 ADR-006 与 AIO native handoff 对真实 AIO shell/file、session runtime lifecycle、preview/download 进行 smoke。若前端 Chat 预览仍混用旧 RPA/VNC proxy，再以独立补丁把 Chat 页预览路由统一到 session runtime proxy。
