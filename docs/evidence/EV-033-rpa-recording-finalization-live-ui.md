---
id: EV-033
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F027-rpa-agent-recording-finalization-contract.md
created: 2026-07-19
---

# EV-033：F027 录制结算与 Live UI 验证

## Supports Claim

证明 F027 的生产 Candidate 结算、可回放计数、显式输出工具契约以及录制后配置保存已按既有架构实现；同时约束不能据此声称完整真实 LLM GitHub E2E 已通过。

## Verification Scope

覆盖 Browser-use Adapter/Host、Agent instruction Route、Creation Projection、Recorder/API/Configure 前端、生产构建，以及本地 5757/12001 非 Docker Live UI。未完成最终“Trending -> 相关项目 -> Star 输出 -> 成功回放”的连续通过证明。

## Checks

```text
$env:TEMP='E:\RPA-Agent\ScienceClaw\.tmp\pytest-f027-final'
$env:TMP=$env:TEMP
$env:PYTHONPATH='RpaClaw/backend'
.\.venv\Scripts\python.exe -m pytest RpaClaw/backend/tests/rpa_agent/test_route.py RpaClaw/backend/tests/rpa_agent/test_browser_use_adapter.py RpaClaw/backend/tests/rpa_agent/test_browser_use_host.py RpaClaw/backend/tests/rpa_agent/test_manual_input_producer.py -q

cd RpaClaw/frontend
npm.cmd test -- --run src/api/rpaAgent.test.ts src/pages/rpa/RecorderPage.test.ts src/pages/rpa/ConfigurePage.test.ts src/components/rpa/TimelinePanel.test.ts
npm.cmd run build

git diff --check

.\.venv\Scripts\python.exe C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root . --docs-path docs --strict
.\.venv\Scripts\python.exe C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root . --feature-index docs/features/F027-rpa-agent-recording-finalization-contract.md

Local Live UI: http://127.0.0.1:5757/rpa/recorder
Backend: http://127.0.0.1:12001
Model: qwen3.7-max-preview
```

## Results

Partial。

- 后端聚焦回归：`138 passed`。
- 前端聚焦回归：`14 passed`；API 测试确认 instruction 超时使用 600 秒，Recorder 测试确认 `actual_action_count=2` 时只显示 `replayable_action_count=1`。
- 前端构建：Pass，`5313 modules transformed`；仅有既存 bundle/CSS/重复 key 警告。
- `git diff --check`：Pass；只有 CRLF 转换警告，无 whitespace error。
- Knowledge Check：F027、EV-033、LL-004 没有文件级错误；仓库级 strict 仍因既存知识文档格式债务失败（593 errors），Feature Index 检查还因 `docs/features/INDEX.md` 不存在而失败。
- Live UI 会话 `rca_ea3cf408456792b18e8b4b7d`：GitHub 搜索被二级限流后模型改走 DuckDuckGo；两个动态导航与点击最终全部“已确认”，证明动态 URL 结构化后置条件与本轮结算有效。该轮耗时超过旧 180 秒 UI 超时，促成超时上调。
- Live UI 会话 `rca_a4d1be5266a8801d8e4bf5b4`：`POST /stop=200`、`PUT /configuration=200`、`POST /compile=200`，原配置 422 不再复现；测试入口成功进入，`POST /test-run=200`，但运行结果为 `failed/action.failed`。
- 真实模型曾生成 `extract_variable`，包含页面索引字符串 `"[2752]"` 与观察值 `669`；由此增加边界规范化。最终复跑时模型先尝试直接 `done`，被新不变量拒绝，随后模型服务返回 403 `insufficient_quota`，无法完成新的显式 extract 结算证明。

## Artifacts

- Feature：[F027](../features/F027-rpa-agent-recording-finalization-contract.md)
- Lesson：[LL-004](../lessons/LL-004-rpa-recording-success-text-must-not-bypass-settlement.md)
- Live 日志：`.tmp/f027-live/backend12001g.*`、`.tmp/f027-live/backend12001i.*`
- 编译产物 hash：`484a8ca0a098edf72e1b323769ee1a7bc747d4f8d547dd8c4c4b8fd42f924ebc`

## Limitations

- 外部模型免费额度已耗尽，不能将最后一次失败归因于本地代码，也不能据此声称完整真实 LLM E2E 已通过。
- GitHub 未登录搜索触发二级限流，模型选择从仓库改为 `github.com/skills` 组织页，业务选择结果存在外部波动。
- 配置保存和编译通过，但测试回放结果仍为 `action.failed`，完整验收未闭环。
- 本工作区包含用户此前未提交改动，本 Evidence 只证明所列检查，不证明整个脏工作区的所有变更。
- 仓库知识基线尚未全量迁移到当前 schema，不能把本次新增文档的局部校验通过表述为全仓 Knowledge Check 通过。

## Notes

根因与触发分离：根因是“生产执行成功”没有被一个强制的结算/输出不变量约束；触发分别是 browser-use readiness timeout、动态 URL 重定向、LLM 跳过扩展工具、方括号索引格式、GitHub 限流和模型额度耗尽。修复保留 fail-closed：只有可验证 URL/dispatch/变量输出证据才能结算，聊天文本不能成为事实源。
