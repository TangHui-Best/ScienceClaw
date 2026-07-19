---
id: EV-030
doc_kind: evidence
scope: project
feature_refs:
  - F026-rpa-agent-scienceclaw-host-rebuild
created: 2026-07-19
---

# EV-030：新版 RPA Agent 本地 CDP 宿主修复

## Supports Claim

证明 Windows 上 `STORAGE_BACKEND=local` 且 `RUNTIME_MODE` 缺省时，新版 RPA Agent 会话使用宿主机本地 Chromium/CDP 创建，默认 `POST /api/v1/rpa-agent/sessions` 返回 201，不再把本地会话交给指向 `http://sandbox:8080` 的 SessionRuntimeManager。

## Verification Scope

覆盖中立 Local CDP 宿主、旧 Connector 兼容导出、直接 CDP runtime lease、local/非 local provider 分流、503 脱敏诊断、默认路由、真实 Chromium 启动与 CDP 获取、`connect_over_cdp`、Preview Registry 注册和清理，以及录制页相关前端测试与生产构建。

不覆盖外部 LLM 语义质量、容器/Kubernetes runtime 的真实部署、DataAsset/分页/阶段二能力，也不把仓库既有 CoreTrace schema 哈希不一致解释为本补丁回归。

## Checks

```text
$env:PYTHONPATH='RpaClaw'; python -m pytest RpaClaw/backend/tests/runtime/test_local_cdp.py RpaClaw/backend/tests/runtime/test_cdp_connector.py RpaClaw/backend/tests/rpa_agent/test_browser_use_host.py RpaClaw/backend/tests/rpa_agent/test_route.py -q
Result: 73 passed

$env:PYTHONPATH='RpaClaw'; $env:RPA_AGENT_LOCAL_LIVE='1'; python -m pytest RpaClaw/backend/tests/rpa_agent/test_local_host_live.py -q -s
Result: 1 passed；真实本地 Chromium/CDP、默认路由 201、Preview Registry 与清理均通过

Set-Location RpaClaw/backend; $env:PYTHONPATH='..'; python -m pytest tests/rpa_agent tests/contracts -q
Result: 476 passed, 2 skipped, 1 failed；唯一失败为既有 schemas/core-trace-timeline-v0.1.schema.json 与 snapshot-sha256.json 锁定值不一致

Set-Location RpaClaw/frontend; npm.cmd test -- --run src/pages/rpa/RecorderPage.test.ts src/components/SandboxPreview.test.ts
Result: 2 test files / 6 tests passed

Set-Location RpaClaw/frontend; npm.cmd run build
Result: Pass；5318 modules transformed（保留仓库既有 duplicate key、CSS 与 chunk-size warnings）
```

## Results

Pass（本补丁范围）。根因是默认 provider 缺少 `storage_backend × runtime mode` 组合分流，而不是 Sandbox 偶发不可用；Windows local 配置只是触发条件。修复把本地 Chromium/CDP 所有权放入 `backend.runtime` 中立宿主层，并在 local 模式向共享 lease 注入直接 CDP resolver；非 local 行为保持不变。

Incident Learning 判定复发风险为中等：同类“默认模式落入错误基础设施”可由其他入口重复。保护已前移到可执行边界：local provider 回归断言 SessionRuntimeManager 不被调用，真实 opt-in 浏览器烟测验证生产链路。无需依赖维护者记忆，因此不另建 Lesson；F026.1 Patch History 和本 Evidence 足以承载本次故障知识。

## Artifacts

- 中立宿主提交：`b5ee3149 refactor: extract neutral local cdp host`
- 直接 CDP lease 提交：`389c4697 feat: support direct cdp runtime leases`
- 默认 provider 修复提交：`e6dc0710 fix: start rpa agent on local browser host`
- 真实浏览器烟测提交：`745cc262 test: cover local rpa agent browser host live`
- 设计：`docs/superpowers/specs/2026-07-19-rpa-agent-local-cdp-host-fix-design.md`
- 实施计划：`docs/superpowers/plans/2026-07-19-rpa-agent-local-cdp-host-fix.md`

## Limitations

大回归中的 CoreTrace schema 哈希失败来自本补丁未修改的既有文件：该 schema 与锁定清单最后同属提交 `5add3748`，当前工作树对二者均无改动。本 Evidence 因此只允许声明本地 RPA Agent 宿主修复通过，不允许声明整个仓库全绿。

真实烟测通过 ASGI 默认路由并仅替换所有权查询，没有启动外部 HTTP 服务；浏览器启动、CDP、Playwright 连接、页面注册和资源清理均为生产实现。

## Notes

- 环境：Windows，Python 3.12，ScienceClaw worktree `E:\RPA-Agent\ScienceClaw`。
- 回滚：回退 `e6dc0710`、`389c4697` 与 `b5ee3149` 可恢复旧 provider/lease/Connector 委托；本补丁不包含数据迁移。回滚后 Windows local 模式会重新暴露原 503，故仅在需要恢复旧行为时使用。
- 503 日志只记录 `storage_backend` 与异常类型，不写异常消息、CDP URL 或密钥。
