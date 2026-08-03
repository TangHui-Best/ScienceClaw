---
id: EV-039
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F032-rpa-agent-next-architecture.md
created: 2026-08-02
---

# EV-039: RPA Agent Next S2.5 会话编排与 API 隔离

## Scope

验证 S2.5 的替身环境边界：`/api/rpa-agent-next/...` 能以 vNext identity 创建独立会话，编排 runtime lease、宿主浏览器、录制 timeline 与监听门控；自然语言步骤复用同一 Page/CDP，关闭时按 gate、host、lease 的反向顺序回收。验证不包含真实 AIO sandbox、真实 Playwright listener 或真实 Browser-use 模型调用。

## Commands

```text
cd RpaClaw/backend
python -m pytest tests/rpa_agent_next -q
python -m pytest tests/rpa_agent -q --basetemp E:\RPA-Agent\ScienceClaw-rpa-agent-next\RpaClaw\backend\.pytest-tmp-s2-5-full-20260802
python -m pytest tests/rpa_agent_next/test_s2_5_session_orchestration.py -q
python -m compileall -q rpa_agent/application route/rpa_agent_next.py
cd ..
python -c "from backend.main import create_app; print(sorted(route.path for route in create_app().routes if 'rpa-agent' in route.path))"
```

## Results

Pass：Next 专项 37 passed；S2.5 API 专项 4 passed；既有 RPA 回归 500 passed、2 skipped；新入口在应用路由表中为 `/api/rpa-agent-next/...`，旧入口仍保持 `/api/v1/rpa-agent/...`，没有相互转发。

## AgentMentor Validation

Partial：已在创建 EV-039 后运行严格 `knowledge_check.py --root E:\RPA-Agent\ScienceClaw-rpa-agent-next --docs-path docs --strict`。它扫描到 81 个历史 Markdown，并报告 665 个既有模板/Feature Index 缺口，包括早于 EV-039 的 ADR、Feature、Evidence 与 Lesson；因此该命令当前不能作为本切片文档的通过信号。EV-039 未依赖任何旧资产或旧路由。

## Artifacts

- `RpaClaw/backend/rpa_agent/application/session_orchestrator.py`
- `RpaClaw/backend/route/rpa_agent_next.py`
- `RpaClaw/backend/tests/rpa_agent_next/test_s2_5_session_orchestration.py`
- `docs/superpowers/plans/2026-08-02-rpa-agent-next-s2.5-session-orchestration.md`

## Notes

此证据只允许进入 S3 的代码/契约实现：`CompileDecision` 与 `SkillBuildConfig` 现在拥有唯一的 Next timeline/session 输入。它不关闭 S1/S2 的 live runtime 门槛，也不能用于宣称 AIO 隔离、真实 Browser-use 或真实 Playwright 监听已在生产环境验证。
