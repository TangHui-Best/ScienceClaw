---
id: EV-041
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F032-rpa-agent-next-architecture.md
created: 2026-08-02
---

# EV-041：RPA Agent Next S4 质量闭环

## Supports Claim

S4 已提供可重复的 vNext 质量闭环内核：受治理 Harness 资产、独立回放报告、指标聚合、稳定失败归因及需要人工接受的 Bad Case。它只消费新生 Skill 的身份和版本事实，不读取、转换或修改旧资产与生产 `CoreTrace`。

## Verification Scope

覆盖 `HarnessAsset` 的新生身份与人工审核门槛；基于 S3 独立回放的成功、执行失败和 OutcomeAssertion 失败报告；原始输入不进入质量报告；指标汇总及失败报告到 Bad Case 的人工审核链路。

## Checks

```text
cd RpaClaw/backend
python -m pytest tests/rpa_agent_next/test_s4_quality_closure.py -q --basetemp .pytest-tmp-s4-20260802
python -m pytest tests/rpa_agent_next -q --basetemp .pytest-tmp-s4-next-full-20260802
python -m pytest tests/rpa_agent -q --basetemp .pytest-tmp-s4-rpa-full-20260802
python -m compileall -q rpa_agent/quality rpa_agent/skill_build
cd ..
python -c "from backend.main import create_app; paths={route.path for route in create_app().routes}; assert '/api/rpa-agent-next/sessions' in paths; assert '/api/v1/rpa-agent/sessions' in paths; print('next-and-legacy-route-families-isolated')"
```

## Results

通过：S4 专项 4 passed；全量 Next 专项 46 passed；既有 RPA 回归 500 passed、2 skipped。专项覆盖确认：

- `proposed` HarnessAsset 不能触发 replay；`accepted` 状态必须带人工 reviewer。
- 报告仅保存输入指纹，序列化内容不含原始测试输入。
- Playwright 步骤失败映射为 `replay_execution_failed`，资源仍由 S3 的独立 lease/host 清理。
- 显式 OutcomeAssertion 失败映射为 `outcome_assertion_failed`，不再与步骤执行失败混淆。
- 失败报告只能先成为 `proposed` BadCase，必须经人工接受后才是回归样本；指标按失败类别聚合。

## Artifacts

- `RpaClaw/backend/rpa_agent/contracts/identity.py`
- `RpaClaw/backend/rpa_agent/quality/harness_assets.py`
- `RpaClaw/backend/rpa_agent/quality/harness.py`
- `RpaClaw/backend/rpa_agent/quality/metrics.py`
- `RpaClaw/backend/rpa_agent/quality/bad_cases.py`
- `RpaClaw/backend/rpa_agent/skill_build/replay.py`
- `RpaClaw/backend/tests/rpa_agent_next/test_s4_quality_closure.py`

## AgentMentor Validation

已运行严格校验：`python C:\Users\HUAWEI\.codex\skills\agentmentor\scripts\knowledge_check.py --root E:\RPA-Agent\ScienceClaw-rpa-agent-next --docs-path docs --strict`。扫描 83 份 Markdown、检查 82 个知识工件并报告 652 项错误；错误来自仓库既有的 Feature/ADR/Evidence 模板与缺失 Feature Index 债务。本次已将 F032 与 ADR-008 对齐当前元数据和章节约束；但仓库级校验在剩余历史债务清偿前仍为 Partial，不能作为 S4 代码验证失败的信号。

## Limitations

本 Evidence 只证明 deterministic fake/contract 层的质量闭环，不证明真实 AIO sandbox、真实 Browser-use、真实 Playwright 或产品 UI 的端到端可用性。它也不构成五条历史能力线任一来源分支的删除证据；删除前仍需相应 live E2E/回放 Evidence。
