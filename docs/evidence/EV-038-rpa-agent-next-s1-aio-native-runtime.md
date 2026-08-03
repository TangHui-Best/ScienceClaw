---
id: EV-038
doc_kind: evidence
scope: feature
feature_refs:
  - docs/features/F032-rpa-agent-next-architecture.md
created: 2026-08-02
---

# EV-038：RPA Agent Next S1 AIO Native Runtime Platform

## Supports Claim

F032 的 S1 已在代码级完成 AIO native sandbox 生命周期适配：RPA Core 只能通过 `RuntimeProviderPort` 获取 opaque lease；AIO API、认证 header、sandbox ID 与 session registry 只存在于 `backend/runtime/` 平台实现层。Mock transport 验证了创建、同 owner 复用、owner 冲突拒绝、未 ready 不签发 lease、释放与脱敏错误行为。

## Verification Scope

仅覆盖注入式 HTTP mock 下的 client/provider 契约、静态依赖边界，以及现有 `rpa_agent` 回归。未连接真实 AIO endpoint、template 或 Browser-use/CDP；in-memory registry 也不构成多实例生产实现。

## Checks

- `AioNativeLifecycleClient` 仅调用四个约定的 AIO lifecycle endpoint，并只提交 `templateId` 和 `timeout` 创建载荷。
- `AioNativeRuntimeProvider` 仅在 sandbox 状态为 ready 时发放 lease；同一 session 的不同 user 被 fail-closed 拒绝。
- release 仅在 lease 与 registry record 完全一致时删除远端 sandbox，并在远端成功或明确 missing 时移除本地 record。
- 静态 guard 检查 vNext Provider 不导入录制、编译、质量 mutator 或旧 `backend.rpa`。

## Commands

```powershell
cd E:\RPA-Agent\ScienceClaw-rpa-agent-next\RpaClaw\backend
python -m pytest tests/rpa_agent_next -q --basetemp E:\RPA-Agent\ScienceClaw-rpa-agent-next\RpaClaw\backend\.pytest-tmp-s1-20260802
python -m pytest tests/rpa_agent/test_architecture_guard.py -q --basetemp E:\RPA-Agent\ScienceClaw-rpa-agent-next\RpaClaw\backend\.pytest-tmp-s1-guard-20260802
python -m pytest tests/rpa_agent -q --basetemp E:\RPA-Agent\ScienceClaw-rpa-agent-next\RpaClaw\backend\.pytest-tmp-s1-full-20260802
```

## Results

- `tests/rpa_agent_next`：16 passed。
- `tests/rpa_agent/test_architecture_guard.py`：8 passed。
- `tests/rpa_agent`：500 passed、2 skipped；保留既有 1367 条警告（主要为 Python 3.14 的第三方弃用警告），无新增失败。

## Artifacts

- `RpaClaw/backend/runtime/aio_native_lifecycle.py`
- `RpaClaw/backend/runtime/rpa_agent_next_aio_provider.py`
- `RpaClaw/backend/rpa_agent/platform/runtime_provider.py`
- `RpaClaw/backend/rpa_agent/quality/architecture_guard.py`
- `RpaClaw/backend/tests/rpa_agent_next/test_aio_native_runtime_provider.py`
- [F032 RPA Agent Next 统一交付架构](../features/F032-rpa-agent-next-architecture.md)
- [S1 AIO Native Runtime Platform 计划](../superpowers/plans/2026-08-02-rpa-agent-next-s1-aio-native-runtime-platform.md)

## Limitations

- 未提供真实 AIO URL、template ID 与授权配置，因此没有真实 sandbox create/status/delete 或 session 隔离证据。
- 未验证 BrowserHostSession、Page/CDP、受控文件 API 或 Browser-use 在真实 sandbox 上的工作情况。
- `InMemoryRuntimeLeaseRegistry` 仅用于测试；生产接入必须使用带 session 原子约束的共享持久化 registry，才可宣称多实例隔离。
- 创建后仍处于 provisioning 的 sandbox 不会签发给 RPA；该 record 会保留，待后续 acquire 再查状态。S1 尚未实现超时回收 worker。

## Notes

完整回归使用 worktree 内的 `--basetemp`，以避开本机系统临时目录此前出现的 `WinError 5` 权限限制。该临时目录不是产品产物，当前因环境策略无法在本轮自动删除。
