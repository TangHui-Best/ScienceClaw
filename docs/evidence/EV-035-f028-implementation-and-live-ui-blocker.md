---
id: EV-035
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F028-rpa-recording-intent-first-dual-mode-compilation.md
created: 2026-07-20
---

# EV-035：F028 实现验证与真实模型额度阻塞

## Supports Claim

F028 的 RecordingTimeline、AIInstructionStep、双模式编译、运行时 Agent、全局变量、独立录制/测试 BrowserHostSession 及 Recorder/Configure/Test UI 已实现并通过自动化回归。真实本地 UI 已多次完成“打开 Trending → 选择项目 → 获取精确 Star → 编译 → 新测试主机回放”的后台链路；最新一次完整后台回放在 `PKUFlyingPig/cs-self-learning` 根页返回结构化 `star_count=74143`，HTTP 200。

本证据**不支持 Live UI 最终通过声明**。修复 UI 30 秒超时及 `tested` 状态重跑后，最终全新重录被外部模型账户余额阻塞：余额 `$0.025578`，关闭视觉后的最小请求仍需 `$0.037968` 以上，真实网关连续返回 403。恢复条件是补充该模型账户额度，然后从新会话完整重跑，禁止复用本文中的旧录制或旧测试结果。

## Verification Scope

- 手工导航立即形成正式 CoreTrace；两条原文指令立即形成 AIInstructionStep。
- 无显式 URL 的语义选择仅有初始 navigate 证据时保持 Runtime Agent，不错误降级为 Playwright。
- 录制与运行共用限定提示：仅检查当前 Trending，禁止全站搜索；Star 步骤停留当前仓库并读取精确计数。
- Anthropic 兼容网关丢失 tool_use 时，进行一次同 Schema 文本 JSON 请求并继续严格 Pydantic 校验。
- 生产 `--app-dir RpaClaw` 拓扑可加载生成产物，不产生重复运行时类身份。
- 测试请求使用 10 分钟客户端超时；`compiled`/`tested` 均可重跑，每次创建新的测试浏览器身份。
- 文本 DOM 模式关闭视觉截图，以降低真实模型成本；语义和结构化输出仍由真实 LLM 完成。

## Checks

```text
cd RpaClaw/backend
$env:PYTHONPATH='.'; python -m pytest tests/rpa_agent -q --basetemp=..\..\.tmp\pytest-final-full-sequential

cd RpaClaw/frontend
npm.cmd test
npm.cmd test -- src/api/rpaAgent.test.ts src/components/rpa/RpaStepTimeline.test.ts src/pages/rpa/ConfigurePage.test.ts src/pages/rpa/RecorderPage.test.ts src/pages/rpa/TestPage.test.ts src/utils/rpaAgentCreationProjection.test.ts src/utils/rpaAgentSkillConfiguration.test.ts src/utils/rpaFlowGuide.test.ts
npm.cmd run build
```

## Results

- Pass：后端 `499 passed, 2 skipped`。
- Pass：前端全量 `51 files / 223 tests passed`，F028 定向 `8 files / 26 tests passed`。
- Pass：前端生产构建成功。
- Partial：真实后端回放成功；最终全新 Live UI 重录因外部模型账户 403 被阻塞。

## Artifacts

- 成功后台回放日志：`.tmp/live-e2e/backend-live-accepted.stderr.log`，包含项目根页 `PKUFlyingPig/cs-self-learning`、精确 aria-label `74143 users starred this repository`、结构化 `{"star_count": 74143}` 及 HTTP 200。
- 最终阻塞日志：`.tmp/live-e2e/backend-live-low-cost.stderr.log`，显示关闭视觉后仍因余额不足连续 403。
- 自动化最终结果：后端 `tests/rpa_agent` 全量 `499 passed, 2 skipped`；前端全量 `51 files / 223 tests passed`；F028 变更集定向 `8 files / 26 tests passed`；`npm run build` 成功。构建保留仓库既有的重复样式键、CSS 语法和大 chunk 警告，不影响本次构建退出码。

## Limitations

本证据不能证明附件要求的最终 Live UI E2E 已通过，也不能用历史 session、后台 HTTP 200 或自动化测试替代该声明。外部额度恢复后必须新建录制身份完整重跑，并独立核验仓库根页与 Star。

## Notes

根因不是单一页面缺陷，而是测试拓扑、证据充分性、录制/运行提示、客户端超时和状态机重跑契约未被同一 Harness 覆盖。对应保护已落为自动化测试；不依赖人工“下次小心”。外部额度属于环境阻塞，不通过 mock、旧结果或内部接口绕过。

`knowledge_check.py --strict` 扫描 276 个 Markdown、74 个知识工件后仍报告 593 个仓库既有旧模板错误；过滤结果中 F028 与 EV-035 已无诊断。`git diff --check` 通过。全仓历史文档迁移不属于 F028 范围。

## Recovery Snapshot

- 分支：`codex/rpa-agent-intent-first-dual-mode`
- 工作树：`E:\RPA-Agent\.worktrees\rpa-agent-intent-first-dual-mode`
- 隔离服务：后端 `127.0.0.1:12011`，前端 `127.0.0.1:5174`；用户原有 `12001` 未触碰。
- 恢复动作：为模型 `claude-sonnet-4-6-anthropic-live` 补充至少能覆盖四次真实 Agent 调用的额度；重启隔离后端；创建全新录制身份；严格重走附件 1–15；用 GitHub API/页面 aria-label 独立核对根仓库和 Star；保存截图与新 session/browser/page/generation。
- 禁止：复用 `rca_dacd44578d36edc57ec569b4` 或本文任何历史成功结果作为最终验收。
