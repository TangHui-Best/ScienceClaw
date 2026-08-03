---
id: EV-040
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F032-rpa-agent-next-architecture.md
created: 2026-08-02
---

# EV-040: RPA Agent Next S3 构建与独立回放

## Scope

验证 S3 替身环境能力：只以 vNext `RecordingTimeline` 和新 `SkillBuildConfig` 构建 `CompiledSkill`；手工 `CoreTrace` 经纯函数 `CompileDecision` 决定 Playwright step，`AIInstructionStep` 固定为 Browser-use step；独立回放使用 purpose=`replay` 的新 lease/new host，并在成功与失败后释放资源。

## Commands

```text
cd RpaClaw/backend
python -m pytest tests/rpa_agent_next/test_s3_skill_build_and_replay.py -q
python -m pytest tests/rpa_agent_next -q
python -m pytest tests/rpa_agent -q --basetemp E:\RPA-Agent\ScienceClaw-rpa-agent-next\RpaClaw\backend\.pytest-tmp-s3-full-rerun-20260802
python -m compileall -q rpa_agent/skill_build rpa_agent/application
cd ..
python -c "from backend.main import create_app; paths = {route.path for route in create_app().routes}; assert '/api/rpa-agent-next/sessions' in paths; assert '/api/v1/rpa-agent/sessions' in paths; print('next-and-legacy-route-families-isolated')"
```

## Results

Pass：S3 专项 5 passed；Next 专项 42 passed；既有 RPA 回归 500 passed、2 skipped；应用路由中 Next 与旧 RPA Agent 保持两个独立前缀。

专项覆盖确认：AI 的 recording execution/history 不影响 source hash；包含 `agent` action 的伪手工事实只能得到 `review_required`，不会自动降级成 Browser-use；显式 OutcomeAssertion 才会传给回放 evaluator；step 失败仍回收新的 host 和 replay lease。

## AgentMentor Validation

Partial：已在创建 EV-040 后运行严格 `knowledge_check.py --root E:\RPA-Agent\ScienceClaw-rpa-agent-next --docs-path docs --strict`。它扫描 82 个 Markdown，并报告 670 项既有模板/Feature Index 问题；结果只能记录为仓库级历史文档债务，不可替代本切片的代码验证。

## Artifacts

- `RpaClaw/backend/rpa_agent/skill_build/contracts.py`
- `RpaClaw/backend/rpa_agent/skill_build/decisions.py`
- `RpaClaw/backend/rpa_agent/skill_build/builder.py`
- `RpaClaw/backend/rpa_agent/skill_build/replay.py`
- `RpaClaw/backend/rpa_agent/application/skill_build_service.py`
- `RpaClaw/backend/tests/rpa_agent_next/test_s3_skill_build_and_replay.py`

## Notes

S3 的 Playwright 执行以窄 `PlaywrightReplayPort` 接口表示，并由 deterministic fake 验证编排与资源隔离。真实 Playwright adapter、真实 AIO sandbox、真实 Browser-use 调用和产品 E2E 属于未关闭的 live runtime 证据，不能由本 Evidence 代替。
