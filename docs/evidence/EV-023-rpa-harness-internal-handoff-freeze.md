---
id: EV-023
doc_kind: evidence
title: RPA Harness Internal Handoff Freeze Evidence
status: completed
scope: project
feature_ids: [F023]
feature_refs:
  - docs/features/F023-rpa-harness-internal-handoff-freeze.md
created: 2026-05-31
updated: 2026-05-31
evidence_level: exhaustive
---

# EV-023 RPA Harness Internal Handoff Freeze Evidence

## Scope

F023 的证据：完成 RPA Harness 切换内网开发前的封箱加固。范围包括文档入口收束、历史资料生命周期处理、Asset Pool Doctor CLI、内网资产交接模板，以及 compiler / generalization 风险归属。

## Entry Gate

```text
Start Gate: needs feature -> ready after F023/EV023 creation
Task class: high-risk
Risk triggers:
- Harness handoff semantics
- document lifecycle
- asset governance state
- CLI behavior
- future Agent recovery
- compiler ownership boundary
Delegation decision:
- single_agent; shared handoff口径比并行实现更重要
Bug attribution:
- not triggered
Required pre-work:
- create F023 and EV023
- use TDD for Asset Pool Doctor
```

## Commands

RED（Asset Pool Doctor 测试先行，预期失败）：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_pool_doctor.py
```

GREEN（实现 Asset Pool Doctor 后）：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_asset_pool_doctor.py
```

当前 bootstrap asset pool 快速体检：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m backend.rpa.harness.run_asset_pool_doctor --assets data\rpa_harness_assets_bootstrap --format summary --lang zh
```

文档生命周期引用检查：

```powershell
rg "docs/rpa/harness/f0(13|14|15|16|17|18)|rpa/harness/f0(13|14|15|16|17|18)" docs
```

最终验证：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest -q --basetemp E:\Work-Project\OtherWork\ScienceClaw\.pytest-tmp-current RpaClaw/backend/tests/test_rpa_harness_catalog.py RpaClaw/backend/tests/test_rpa_harness_asset_pool_doctor.py
python C:\Users\HUAWEI\.codex\skills\using-harness\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
git diff --check
```

## Results

- RED：测试先行时失败，失败点为 `ModuleNotFoundError: No module named 'backend.rpa.harness.asset_pool_doctor'`，符合预期。
- GREEN：`RpaClaw/backend/tests/test_rpa_harness_asset_pool_doctor.py` 通过，覆盖无 blocking baseline、candidate-lite warning-only、reviewed candidate ready、CLI JSON、CLI 中文 summary。
- 当前 bootstrap pool doctor 输出：`asset_count=3`、`blocking_baseline=0`、`warning-only=2`、`expected reviewed/unreviewed=0/3`、`sensitivity reviewed/unreviewed=0/3`、`recommended_next_action=review_or_promote_assets`。
- 文档生命周期检查：活跃文档不再引用旧 F013-F018 phase plan 路径；剩余旧路径只保留在 `docs/archive/2026-05/rpa-harness/` 的历史文档内部。
- F013-F018 phase/closeout plan 已归档到 `docs/archive/2026-05/rpa-harness/`，并补充 archive README。

## Harness Validation

Harness Readiness Dashboard:

```text
Task class: high-risk
Current stage: completion
Evidence Level: exhaustive
Delegation Gate: single_agent
Bugfix Attribution: not needed; this is handoff/freeze hardening, not a completed Feature bugfix.
Ready: yes, subject to residual risks below.
```

Knowledge Capture:

- Feature/Evidence closeout exists: F023 + EV-023.
- Change narrative exists in this evidence and commit body.
- Compiler/generalization risk has an owner boundary document and Backlog entry.
- Current asset pool readiness is intentionally reported as not ready, rather than inflated into a green baseline.

## Artifacts

- Feature: `docs/features/F023-rpa-harness-internal-handoff-freeze.md`
- Handoff guide: `docs/rpa/harness/internal-handoff-and-freeze-guide.md`
- Archive index: `docs/archive/2026-05/rpa-harness/README.md`
- Internal asset handoff template: `docs/rpa/harness/templates/internal-asset-handoff.md`
- Internal asset review report template: `docs/rpa/harness/templates/internal-asset-review-report.md`
- Local model config example: `docs/rpa/harness/templates/local_model_config.example.json`
- Compiler risk ownership: `docs/rpa/trace-skill-compiler-risk-ownership.md`
- Asset Pool Doctor: `RpaClaw/backend/rpa/harness/asset_pool_doctor.py`
- CLI: `RpaClaw/backend/rpa/harness/run_asset_pool_doctor.py`

## Residual Risk

- 当前 `data/rpa_harness_assets_bootstrap` 没有 blocking baseline；这是被 doctor 明确暴露的事实，不应在封箱时修饰成 ready。
- `candidate-lite` 只允许作为观察资产，不能作为 blocking candidate 或 golden baseline。
- F023 不修复 `TraceSkillCompiler` 泛化风险；后续若出现 `compiler-hardcoded-observed-value`、`output_key` 丢失、`_results` 引用丢失或 replay output shape 不一致，应归属 RPA core Feature。
- 内网真实资产可能包含不能出网的敏感截图、HTML、cookie、token 或业务数据；模板要求只提交元信息、review 结论和脱敏路径，不提交真实凭证。
- `git diff --check` 通过，但 Git 在 Windows 工作区提示若干既有 Markdown 文件下次触碰时 LF 会被替换为 CRLF；这不是 whitespace error。

## Notes

本轮不修复 `TraceSkillCompiler` 泛化问题；只把风险归属和验收路径写清楚，避免后续在 Harness 里加入站点特例或 expected-signal 例外。
