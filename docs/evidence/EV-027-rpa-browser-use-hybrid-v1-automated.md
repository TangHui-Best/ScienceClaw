---
id: EV-027
doc_kind: evidence
scope: feature
feature_refs:
  - docs/features/F029-rpa-browser-use-hybrid-v1.md
created: 2026-07-20
---

# EV-027：Browser-use 人工/自然语言混合录制 V1 自动化验证

## Scope

验证 F029 V1 的自动化可证明范围：Browser-use History 不参与 Playwright 代码生成、用户原始指令和前序普通运行结果进入运行时、人工/AI/人工顺序不变、自然语言执行期间人工输入与 Trace 入库暂停、并发暂停所有权隔离、精确 CDP target 继续传递、Browser-use 保持原生 planner 参数边界，以及执行结束后释放 Browser-use 附件资源但不关闭宿主浏览器。

本 Evidence 不包含真实 Recorder UI、真实网页和真实 LLM 的 Live UI E2E。用户已明确由其自行完成最终 Live UI 验收，因此 F029 仍保持 `active`，不能据此声明产品验收完成。

## Commands

```text
cd E:\Work-Project\OtherWork\ScienceClaw\RpaClaw
python -m pytest backend/tests/test_browser_use_recording_operator.py backend/tests/test_rpa_trace_skill_compiler.py backend/tests/test_rpa_runtime_context_browser_use.py backend/tests/test_rpa_manager.py backend/tests/test_rpa_route_trace.py backend/tests/test_rpa_region_context.py -q

python -m pytest backend/tests/test_rpa_harness_ai_capture_integration.py -q --basetemp=.pytest-f029-run

cd E:\Work-Project\OtherWork\ScienceClaw\RpaClaw\frontend
npm.cmd test -- --run
npm.cmd run build
npm.cmd run type-check
```

## Results

- Pass：后端 V1/Core 聚焦回归 `313 passed`，包含 SSE 流取消后暂停 token 释放测试。
- Pass：AI/Harness 交错与 checkpoint 回归 `7 passed`。默认系统临时目录无权限，显式使用工作区 `--basetemp` 后通过；这是环境问题，不是测试断言失败。
- Pass：前端全量 Vitest `45 passed` test files、`238 passed` tests。
- Pass：Vite production build 成功。
- Partial：仓库全局 `vue-tsc` 仍失败，错误分布在 `ActivityPanel.vue`、`ChatMessage.vue`、`SessionItem.vue` 等既有文件；过滤结果没有 `RecorderPage.vue` 或 `RecorderPage.test.ts` 新错误。本 Feature 未扩大范围修复全仓历史类型债务。
- Not Run：真实 Local Recorder UI / Playwright / Browser-use / LLM E2E，由用户后续执行。

## AgentMentor Validation

已运行：

```text
python C:\Users\HUAWEI\.codex\plugins\cache\personal\agentmentor\0.2.0+codex.20260604093000\skills\using-agentmentor\scripts\knowledge_check.py --root E:\Work-Project\OtherWork\ScienceClaw --docs-path docs --strict
```

首次严格校验扫描 61 个知识文档并发现 6 个结构错误，其中本轮新增的 `ADR-008` 标题和 Feature Index 放置问题已修正。再次严格校验扫描 61 个知识文档，剩余 4 个错误全部来自旧 `ADR-005`、`EV-025`、`EV-026` 和 `F025 ... feature_evidence`；本轮 F029、ADR-008、EV-027 未再报错。用户已要求旧文档暂不更新，因此总体 `knowledge_check.py --strict` 结果记录为 Partial，而不是伪报 Pass。

## Artifacts

- Feature：[F029](../features/F029-rpa-browser-use-hybrid-v1.md)
- Decision：[ADR-008](../decisions/ADR-008-rpa-browser-use-staged-hybrid-recording.md)
- Implementation spec：[Browser-use Hybrid V1](../superpowers/specs/2026-07-20-rpa-browser-use-hybrid-v1-implementation-design.md)
- 变更代码：`RpaClaw/backend/rpa/browser_use_recording_operator.py`、`RpaClaw/backend/rpa/trace_skill_compiler.py`、`RpaClaw/backend/rpa/manager.py`、`RpaClaw/backend/route/rpa.py`、`RpaClaw/frontend/src/pages/rpa/RecorderPage.vue`
- 自动化契约：对应 backend tests 与 `RpaClaw/frontend/src/pages/rpa/RecorderPage.test.ts`

## Notes

- Browser-use History 仍保存在 `signals.browser_use` 中用于诊断，但 Compiler 的 V1 主路径无条件使用 `user_instruction`。
- `keep_alive=True` 配合 `BrowserSession.stop()` 只释放 Browser-use 自身 CDP/session/event 资源；是否在真实产品环境中持续保留宿主 Page，仍需 Live UI E2E 观察。
- Browser-use 执行期间前端禁止地址栏和 screencast 鼠标、键盘、粘贴输入；后端 execution token 防止并发自然语言请求提前恢复另一个请求的监听状态。
- `.pytest-f029-run` 是本次权限规避产生的本地测试临时产物，不属于提交内容。
