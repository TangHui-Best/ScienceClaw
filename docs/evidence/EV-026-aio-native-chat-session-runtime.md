---
id: EV-026
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F026-aio-native-chat-session-runtime.md
status: current
created: 2026-06-17
updated: 2026-06-17
evidence_level: standard
---

# EV-026: AIO Native Chat Session Runtime

## Scope

本证据记录 `codex/aio-native-chat-runtime` 分支对普通 Chat 会话执行面的首个闭环改造验证。

覆盖范围：

- `STORAGE_BACKEND=local` 且 `RUNTIME_MODE=aio_native` 时，Chat `deep_agent()` 不再回落本地 shell backend，而是通过 `SessionRuntimeManager.ensure_runtime()` 取得会话 runtime。
- DeepAgent 外部工具执行器在 runtime base 已知时使用 runtime-scoped sandbox executor。
- `FullSandboxBackend` 能把 `SessionRuntimeRecord.runtime_token` 注入 sandbox HTTP client。
- local storage + remote runtime execution 场景下，本地 Skill 源会被注入到 session sandbox 的 `.skills` 目录。
- `sessions.py` 的 sandbox 文件读取 fallback 能按 `session_id` 使用 session runtime base，并在 runtime token 存在时注入 `Authorization` header。
- 既有 local mode、CDP connector、sessions 相关测试保持通过。

不覆盖范围：

- 本机不验证真实内网 AIO create/status/refresh/delete lifecycle。
- 本机不验证真实内网 AIO shell/file API 和浏览器/CDP 网络稳定性。
- 本次未触碰 RPA trace/compiler/recorder Core 文件，因此未运行 Core SOP->Skill focused regression。

## Commands

Focused Chat runtime tests:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/deepagent/test_agent_runtime_selection.py RpaClaw/backend/tests/test_full_sandbox_runtime_context.py RpaClaw/backend/tests/test_sessions.py::TestSessionRuntimeSandboxFiles::test_sandbox_file_read_uses_session_runtime_base_when_available -q --basetemp=tmp-pytest-aio-chat-runtime-focused
```

Runtime manager AIO native selection tests:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/runtime/test_runtime_manager.py -k "aio_native or provider_factory_returns" -q --basetemp=tmp-pytest-aio-chat-runtime-manager
```

Related regression set:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/deepagent/test_tool_execution.py RpaClaw/backend/tests/runtime/test_cdp_connector.py RpaClaw/backend/tests/test_sessions.py -q --basetemp=tmp-pytest-aio-chat-runtime
```

Sessions full regression after test-class placement fix:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/test_sessions.py -q --basetemp=tmp-pytest-aio-chat-runtime-sessions
```

AgentMentor strict validation:

```powershell
python C:/Users/HUAWEI/.codex/plugins/cache/personal/agentmentor/0.2.0+codex.20260604093000/skills/using-agentmentor/scripts/knowledge_check.py --root E:/Work-Project/OtherWork/ScienceClaw --docs-path docs --strict
```

Diff whitespace check:

```powershell
git diff --check -- RpaClaw/backend/deepagent/agent.py RpaClaw/backend/deepagent/full_sandbox_backend.py RpaClaw/backend/route/sessions.py RpaClaw/backend/tests/deepagent/test_agent_runtime_selection.py RpaClaw/backend/tests/test_full_sandbox_runtime_context.py RpaClaw/backend/tests/test_sessions.py docs/features/F026-aio-native-chat-session-runtime.md docs/evidence/EV-026-aio-native-chat-session-runtime.md
```

Workspace rebasing focused tests after local AIO simulation failure:

```powershell
python -m pytest RpaClaw/backend/tests/test_full_sandbox_runtime_context.py RpaClaw/backend/tests/deepagent/test_agent_runtime_selection.py -q --basetemp=tmp-pytest-aio-workspace-2
```

AIO home-dir metadata resilience tests:

```powershell
python -m pytest RpaClaw/backend/tests/deepagent/test_agent_runtime_selection.py RpaClaw/backend/tests/test_full_sandbox_runtime_context.py RpaClaw/backend/tests/runtime/test_runtime_manager.py -k "aio_native or runtime_home_dir or full_sandbox" -q --basetemp=tmp-pytest-aio-home-final
```

DeepAgent sandbox transport/path-boundary regression tests after latest local validation:

```powershell
python -m pytest RpaClaw/backend/tests/test_full_sandbox_runtime_context.py -q --basetemp=tmp-pytest-aio-path-green
python -m pytest RpaClaw/backend/tests/deepagent/test_agent_runtime_selection.py RpaClaw/backend/tests/test_full_sandbox_runtime_context.py RpaClaw/backend/tests/runtime/test_runtime_manager.py -k "aio_native or runtime_home_dir or full_sandbox or legacy_workspace" -q --basetemp=tmp-pytest-aio-path-final
```

Shell execution serialization regression after `pwdcat` validation signal:

```powershell
python -m pytest RpaClaw/backend/tests/test_full_sandbox_runtime_context.py::test_full_sandbox_serializes_concurrent_shell_exec_calls -q --basetemp=tmp-pytest-aio-shell-green
python -m pytest RpaClaw/backend/tests/deepagent/test_agent_runtime_selection.py RpaClaw/backend/tests/test_full_sandbox_runtime_context.py RpaClaw/backend/tests/runtime/test_runtime_manager.py -k "aio_native or runtime_home_dir or full_sandbox or legacy_workspace or serializes_concurrent_shell_exec" -q --basetemp=tmp-pytest-aio-shell-final
```

Virtual Skill path bridge and browser Skill smoke:

```powershell
python -m pytest RpaClaw/backend/tests/test_full_sandbox_runtime_context.py::test_full_sandbox_rewrites_virtual_skill_paths_inside_shell_commands -q --basetemp=tmp-pytest-aio-skill-path-green
python -m pytest RpaClaw/backend/tests/deepagent/test_agent_runtime_selection.py RpaClaw/backend/tests/test_full_sandbox_runtime_context.py RpaClaw/backend/tests/runtime/test_runtime_manager.py -k "aio_native or runtime_home_dir or full_sandbox or legacy_workspace or serializes_concurrent_shell_exec or virtual_skill" -q --basetemp=tmp-pytest-aio-skill-path-final
```

Intranet AIO gateway header regression:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/runtime/test_runtime_manager.py RpaClaw/backend/tests/test_full_sandbox_runtime_context.py RpaClaw/backend/tests/test_sessions.py::TestSessionRuntimeSandboxFiles RpaClaw/backend/tests/deepagent/test_agent_runtime_selection.py RpaClaw/backend/tests/deepagent/test_tool_execution.py -q --basetemp=tmp-pytest-aio-native-intranet-headers-2
```

Local AIO API probe:

```javascript
await fetch("http://127.0.0.1:18090/v1/sandbox")
await fetch("http://127.0.0.1:18090/v1/file/write", {
  method: "POST",
  headers: {"content-type": "application/json"},
  body: JSON.stringify({
    file: "/home/gem/workspace/codex-probe2/hello.txt",
    content: "hello aio"
  })
})
```

## Results

- Focused Chat runtime tests after sessions runtime-token coverage: `7 passed, 31 warnings`.
- Runtime manager AIO native selection tests: `9 passed, 74 deselected`.
- Related regression set: `37 passed, 31 warnings`.
- Sessions full regression: `26 passed, 31 warnings`.
- Workspace rebasing focused tests after local AIO simulation failure: `9 passed, 1 warning`.
- AIO home-dir metadata resilience tests after latest screenshot: `12 passed, 81 deselected, 1 warning`.
- DeepAgent sandbox transport/path-boundary regression tests:
  - `test_full_sandbox_runtime_context.py`: `8 passed, 1 warning`.
  - AIO focused set with legacy workspace coverage: `14 passed, 81 deselected, 1 warning`.
- Shell execution serialization regression:
  - RED before fix: `test_full_sandbox_serializes_concurrent_shell_exec_calls` failed with `assert 2 == 1`, proving concurrent `/v1/shell/exec` calls overlapped on one shell session.
  - Single regression after fix: `1 passed, 1 warning`.
  - AIO focused set with shell serialization coverage: `15 passed, 81 deselected, 1 warning`.
- Virtual Skill path bridge:
  - RED before fix: `test_full_sandbox_rewrites_virtual_skill_paths_inside_shell_commands` showed `python3 /skills/.../skill.py` stayed on virtual `/skills` and would not exist in AIO shell.
  - Single regression after fix: `1 passed, 1 warning`.
  - AIO focused set with virtual Skill path coverage: `16 passed, 81 deselected, 1 warning`.
- Intranet AIO gateway header regression:
  - `107 passed, 31 warnings`.
  - Covered full URL lifecycle envs, `X-HW-ID` / `X-HW-APPKEY` lifecycle headers, create `timeout`, dynamic `x-livefunction-sandbox-id` headers for `FullSandboxBackend`, sessions sandbox file fallback, and external tool sandbox executor.
- Local AIO API probe after container restart:
  - `/v1/sandbox` returned `home_dir=/home/gem`.
  - `/v1/file/write` to `/home/gem/workspace/codex-probe2/hello.txt` returned `200` and wrote the file.
  - `/v1/shell/sessions/create` with `exec_dir=/home/gem/workspace/codex-probe2` returned `200`.
- AgentMentor strict validation after doc schema repair: `Scanned 273 markdown file(s). Checked 60 knowledge artifact(s). Errors: 0. Warnings: 0.`
- Diff whitespace check: passed with only existing Windows LF/CRLF normalization warnings.
- Initial AgentMentor strict validation failed because F026/EV026 missing required schema sections; docs were corrected before closeout.
- Warnings are existing FastAPI/Pydantic/Python 3.14 deprecation warnings from the local test environment, not behavior failures.

## AgentMentor Validation

```powershell
python C:/Users/HUAWEI/.codex/plugins/cache/personal/agentmentor/0.2.0+codex.20260604093000/skills/using-agentmentor/scripts/knowledge_check.py --root E:/Work-Project/OtherWork/ScienceClaw --docs-path docs --strict
```

Result: `Scanned 273 markdown file(s). Checked 60 knowledge artifact(s). Errors: 0. Warnings: 0.`

## Artifacts

- Feature: [F026 AIO Native Chat Session Runtime](../features/F026-aio-native-chat-session-runtime.md)
- Decision: [ADR-006 AIO Native API First Runtime Strategy](../decisions/ADR-006-aio-native-api-first-runtime-strategy.md)
- Code: `RpaClaw/backend/deepagent/agent.py`
- Code: `RpaClaw/backend/deepagent/full_sandbox_backend.py`
- Code: `RpaClaw/backend/route/sessions.py`
- Tests: `RpaClaw/backend/tests/deepagent/test_agent_runtime_selection.py`
- Tests: `RpaClaw/backend/tests/test_full_sandbox_runtime_context.py`
- Tests: `RpaClaw/backend/tests/test_sessions.py`

## Notes

- 第一次尝试扩展回归时，pytest 默认 temp 目录出现 Windows `PermissionError`；改用新的 `--basetemp=tmp-pytest-aio-chat-runtime*` 后通过。
- 为运行 DeepAgent 相关测试，本地 Python 环境安装了 `deepagents==0.4.4`。
- 用户截图中的 502 不是 Chat 工具完全未接入 AIO，而是 Chat 运行面已经开始调用 AIO file/shell，但 workspace 仍为旧 `/home/rpaclaw/workspace/{session_id}`；修复后 workspace 由 AIO runtime context 的 `home_dir` 派生为 `/home/gem/workspace/{session_id}`。
- 最新页面验证再次出现旧路径时，backend 日志显示请求开始阶段 `/v1/sandbox` 曾瞬时返回 502；补丁将 AIO `home_dir` 缓存到 `SessionRuntimeRecord.metadata`，并让 `FullSandboxBackend` 在 context 暂不可用时仍使用 metadata 中的 `/home/gem`，避免回退到旧 `/home/rpaclaw`。
- 进一步读取最新 session 事件后确认，`execute`/`ls` 工具参数由模型直接传入旧 `/home/rpaclaw/workspace/{session_id}`，不是 UI 渲染错；`FullSandboxBackend` 现在会把同一 session 的 legacy workspace 绝对路径改写到当前 `/home/gem/workspace/{session_id}`，包括 shell command 文本中的路径。
- `FullSandboxBackend` 的 HTTP client 现在显式 `trust_env=False`，与 runtime adapter/provider 的本机 AIO 控制流量策略保持一致，降低 Windows/本机代理环境把 `127.0.0.1:18090` 请求误导向代理并返回 502 的风险。
- 2026-06-17 本机手动执行 `ensure_runtime('bJoUhvYVg2pKMUcG6zMLLW', ...)` 后，`data/session_runtimes/bJoUhvYVg2pKMUcG6zMLLW.json` 已持久化 `metadata.home_dir=/home/gem`。
- 2026-06-17 shell 验证截图中最终结果成功，但日志显示两个并发 `execute` tool call 对同一 shell session 产生 `pwdcat: command not found`；这不是 AIO path 或 502 问题，而是共享 shell session 并发命令流串扰。`FullSandboxBackend.aexecute()` 现在对同一 backend 实例串行化 shell execute，避免交互式 shell 输入交错。
- 2026-06-17 录制 Skill 验证发现，`/skills` 在 DeepAgent file 工具中是虚拟路由，但 AIO shell 里不存在；`FullSandboxBackend` 现在会在 shell command 文本中把 `/skills/{name}` 改写为 `{workspace}/.skills/{name}`。
- 2026-06-17 本机 AIO raw smoke 使用 `github-trending-best-project` 测试 Skill：
  - 手工修正该单个 Skill 的 `SKILL.md` frontmatter 为 `name: github-trending-best-project`。
  - AIO 中 `python3 -m pip install playwright` 成功；`playwright install chromium` 超时，改用 AIO 已有 `/usr/bin/chromium-browser`。
  - 该 Skill 的 `skill.py` 改为使用系统 Chromium，并增加 `TRACE_*` heartbeat，避免 AIO shell `no_change_timeout`。
  - raw `/v1/shell/exec` 返回 `status=completed`、`exit_code=0`、`SKILL_SUCCESS`，`SKILL_DATA.repository=freeCodeCamp/freeCodeCamp`。
- 2026-06-17 内网 AIO 网关配置适配：
  - 支持 `AIO_NATIVE_CREATE_URL`、`AIO_NATIVE_STATUS_URL_TEMPLATE`、`AIO_NATIVE_DELETE_URL_TEMPLATE`、`AIO_NATIVE_REFRESH_URL_TEMPLATE` 完整 URL 形式，同时保留 `AIO_NATIVE_API_BASE_URL` + path/template 形式。
  - 生命周期 API 通过 `AIO_NATIVE_HW_ID` 与 `AIO_NATIVE_APPKEY` 发送 `X-HW-ID` / `X-HW-APPKEY`；`AIO_NATIVE_API_TOKEN` 的 Bearer 兼容仍保留。
  - 沙箱内部 API 通过 create/status record 上的 `sandbox_id` 动态发送 `x-livefunction-sandbox-id`，密钥不写入 `SessionRuntimeRecord` 持久化文件。
- 本次只完成后端执行面首个闭环；Chat 前端预览/接管若仍混用旧 RPA/VNC proxy，应作为后续独立补丁处理。
