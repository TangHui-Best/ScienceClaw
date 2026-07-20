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

### 2026-07-20 续跑补充证据

- 在隔离的本地前端 `127.0.0.1:5174` 与后端 `127.0.0.1:12011` 上，真实 UI 会话 `rca_fa8ff141a6e85f188c74b9f1` 完成了：手工打开 Trending、两条原文 AI 指令即时入时间线、配置 `star_count`、生成三段双模式计划、编译以及全新测试宿主回放。
- 录制宿主为 `bhs_recording_b39a3a4168049b7dc09f5924`，测试宿主为 `bhs_test_5bbabce94b039658fa491698`；两者身份不同。重新录制后又创建了新的 recording host，时间线为 0 项，证明旧 Page/时间线未被沿用。
- 编译产物哈希为 `0d2cb18a3c4d5cf27a447d0abe1f3c17348a8e7f52c275c03dadce7373510b2e`。测试 UI 显示 `测试通过`、`运行结果：succeeded` 和结构化输出 `star_count = 5348`。
- 同次真实测试日志中的 GitHub DOM 明确给出 `repo-stars-counter-star`、`aria-label='5348 users starred this repository'` 与 `title='5,348'`，与 UI 输出一致。随后独立 GitHub API 读取为 `5350`，说明 Trending 仓库计数在核验窗口内继续增长；不把后读值反向改写为执行时 Oracle。
- 最终仓库为 `bojieli/ai-agent-book` 根页。独立页面核验显示 README 的第 2 章包含 `Agent Skills` 与 `agent-skills-ppt`，满足 repo name/description/topic/README heading 至少一处含 `skill` 的客观 Oracle。
- 续跑暴露并修复两项真实缺陷：OpenAI 兼容网关把结构化 JSON 放在 `reasoning_content` 且 `content` 为空；TestPage 未展示结构化输出。两者均已有回归测试。输出只在当前测试页直接呈现，不把整份 `run_result` 持久化到 sessionStorage，避免扩大敏感输出驻留面。
- 修复后串行验证：后端 `500 passed, 2 skipped`；前端 `51 files / 223 tests passed`；生产构建成功。一次并行全量运行曾使两个无关 `SkillDetailPage` 用例超时/重复调用，串行重跑全部通过，归因为并行资源竞争而非 F028 回归。
- 最新代码增加了更明确的 Browser-use 指导语，要求仓库根页加载后立即 `done`，但没有增加宿主侧 done/retry/成功改判门禁。曾尝试用 GitHub URL 后置条件强制改判，因违反 ADR-007 的 Browser-use 主体边界而在提交前撤回。
- 最新代码的再次全新 UI 复验被外部模型账户 `Arrearage` 阻断；页面中两个 `glm-4.7` 配置均返回同一欠费错误。因此本证据仍保持 **partial / Live UI 最新提交复验阻塞**，不能用上述成功会话替代解阻后的最终新会话验收。

续跑日志位于 `.tmp/live-e2e-continuation/`：`backend-reasoning-fix.stderr.log` 保存成功录制/测试轨迹，`backend-final.stderr.log` 保存两个模型配置的 `Arrearage` 阻断轨迹。`.tmp` 为本地临时证据目录，不提交 API Key 或模型明文凭据。

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
