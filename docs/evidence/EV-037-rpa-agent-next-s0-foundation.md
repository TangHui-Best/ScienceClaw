---
id: EV-037
doc_kind: evidence
scope: feature
feature_refs:
  - docs/features/F032-rpa-agent-next-architecture.md
created: 2026-08-02
---

# EV-037：RPA Agent Next S0 基础契约

## Scope

验证 F032 的 S0 最小基础骨架：vNext artifact identity 的 fail-closed ingress guard、provider-neutral RuntimeProvider port 与 deterministic fake provider、只读 QualityEvent，以及防止 RPA Core/Quality 跨越 Runtime Platform 和生产录制事实边界的静态架构守卫。

本 Evidence 不验证真实 AIO sandbox、Browser-use、CoreTrace 录制、编译、Skill 回放或真实 LLM E2E。

## Commands

```powershell
cd E:\RPA-Agent\ScienceClaw-rpa-agent-next\RpaClaw\backend
python -m pytest tests/rpa_agent_next -q
python -m pytest tests/rpa_agent/test_architecture_guard.py -q
python -m pytest tests/rpa_agent -q --basetemp E:\RPA-Agent\ScienceClaw-rpa-agent-next\RpaClaw\backend\.pytest-tmp-s0-20260802
```

## Results

Pass（限定范围）。

- `tests/rpa_agent_next`：11 passed，覆盖 vNext identity、legacy/unknown artifact 拒绝、session lease 隔离与单次释放、QualityEvent 只引用 immutable identity、架构越权检测，以及最小“acquire → legacy reject → quality event → release”链。
- `tests/rpa_agent/test_architecture_guard.py`：8 passed，确认现有 F028 `rpa_agent` 架构守卫仍通过。
- `tests/rpa_agent`：500 passed、2 skipped。第一次使用系统临时目录时出现 68 个 `WinError 5` setup error；改用 worktree 内的独立 `--basetemp` 后完整回归通过，故该失败归因于环境临时目录权限，而非 S0 代码。

## AgentMentor Validation

已运行：

```powershell
python C:\Users\HUAWEI\.codex\plugins\cache\personal\agentmentor\0.2.0+codex.20260604093000\skills\using-agentmentor\scripts\knowledge_check.py --root E:\RPA-Agent\ScienceClaw-rpa-agent-next --docs-path docs --strict
```

结果：仍报告 F028 基线中已存在的 20 个历史文档结构错误和 1 个历史警告；新增 F032、ADR-008、EV-037 没有引入新的结构错误或警告。

## Artifacts

- `RpaClaw/backend/rpa_agent/contracts/identity.py`
- `RpaClaw/backend/rpa_agent/platform/runtime_provider.py`
- `RpaClaw/backend/rpa_agent/quality/contracts.py`
- `RpaClaw/backend/rpa_agent/quality/architecture_guard.py`
- `RpaClaw/backend/tests/rpa_agent_next/`
- [F032 RPA Agent Next 统一交付架构](../features/F032-rpa-agent-next-architecture.md)
- [S0 vNext 基础契约与 Harness/E2E 计划](../superpowers/plans/2026-08-02-rpa-agent-next-s0-foundation.md)

## Notes

`FakeRuntimeProvider` 是确定性测试替身，不创建真实 sandbox。真实 AIO provider 的 acquire/release/health/file-policy adapter 是 S1 的工作；在该 adapter 有真实 session Evidence 前，不能宣称“每会话 sandbox 隔离”已交付。

完整回归使用的 `.pytest-tmp-s0-20260802` 是为避开系统临时目录权限问题而创建的测试临时目录，当前保留在 worktree 中且不属于产品产物。
