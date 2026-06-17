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

## Results

- Focused Chat runtime tests after sessions runtime-token coverage: `7 passed, 31 warnings`.
- Runtime manager AIO native selection tests: `9 passed, 74 deselected`.
- Related regression set: `37 passed, 31 warnings`.
- Sessions full regression: `26 passed, 31 warnings`.
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
- 本次只完成后端执行面首个闭环；Chat 前端预览/接管若仍混用旧 RPA/VNC proxy，应作为后续独立补丁处理。
