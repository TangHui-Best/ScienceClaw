---
id: EV-036
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F028-rpa-recording-intent-first-dual-mode-compilation.md
created: 2026-07-20
---

# EV-036：F028 upstream UI 交互恢复验证

## Supports Claim

在 `E:\RPA-Agent\ScienceClaw` 的 `codex/rpa-agent-intent-first-dual-mode` 分支，Recorder、Configure、Test 已恢复 upstream ScienceClaw 的主要信息架构和交互逻辑，同时保留 F028 的 Intent-first 顶层时间线、Playwright/Agent 双模式、输出/DataAsset 配置和隔离浏览器会话。

本证据只支持 UI 交互恢复与非 LLM 本地闭环；不替代 EV-035 中仍受外部额度阻塞的完整真实 LLM GitHub 场景。

## Verification Scope

### Donor Contract

- Recorder：顶部“录制 → 配置 → 测试保存”、左侧实时步骤、中部浏览器壳和地址栏、右侧对话式 AI 助手、顶部完成录制主操作。
- Timeline：默认显示业务摘要；点击展开执行状态、回放状态、编译方式和观察动作证据。
- Configure：左侧步骤复核，右侧技能信息、逐步编译/回退、参数提升、Secret、输出和 DataAsset 渐进配置；顶部与底部主操作一致。
- Test：左侧逐步结果、中部独立测试浏览器、右侧输入/Secret/DataAsset、回放结果与保存；通过后顶部主操作切换为保存。
- 非目标：不整体 cherry-pick donor，不恢复旧 Candidate/Settlement 控制 UI，不回退 F028 API 或旧 Runtime/Trace。

## Checks

```text
cd E:\RPA-Agent\ScienceClaw\RpaClaw\frontend
npm.cmd test
npm.cmd run build
npm.cmd run type-check
python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root E:\RPA-Agent\ScienceClaw --docs-path docs --strict
```

- Pass：`51` 个测试文件、`224` 个测试全部通过。
- Pass：Vite 生产构建成功。
- Baseline blocked：全仓 `vue-tsc` 仍被 ActivityPanel、ChatMessage、SessionItem、ChatPage、desktopWindow 等既有错误阻塞；本次修改的四个 RPA 文件未出现在错误清单中。
- Baseline blocked：严格知识检查扫描 `277` 个 Markdown、`75` 个知识工件，仍报告 `593` 个历史模板错误；定向过滤中 F028、EV-036、LL-003 已无诊断。

### Real Local UI Verification

本地非 Docker 启动 Vite `127.0.0.1:5173` 与 FastAPI `127.0.0.1:8000`，从真实 Recorder 页面执行：

1. 确认三栏、流程条、完成录制、地址栏、模型选择和对话输入均可见；
2. 点击“完成录制”，真实导航到同一 session 的 Configure；
3. 确认左侧步骤复核与右侧渐进配置；点击“新增输出”后输出字段立即出现；
4. 真实配置并编译空步骤测试产物，进入 Test；
5. 确认 Test 三栏和开始回放/保存状态；
6. 点击开始回放，后端创建独立测试浏览器，页面显示 `运行结果：succeeded`，顶部主操作变为“保存 SKILL”。

该验证没有调用 LLM，避免把余额环境条件混入 UI 恢复判定。生成的空步骤本地产物只用于交互与会话状态验证，不作为业务 Skill 验收样本。

## Results

UI 交互恢复：pass。完整真实 LLM Live UI E2E：仍按 EV-035 标记 partial / external Arrearage blocked。

## Artifacts

- 生产代码：`RecorderPage.vue`、`ConfigurePage.vue`、`TestPage.vue`、`RpaStepTimeline.vue`。
- 回归保护：`RpaStepTimeline.test.ts` 与 `TestPage.test.ts`，以及既有 Recorder/Configure/Test 测试套件。
- 视觉证据：本次本地浏览器会话中的 Recorder、Configure、Test 三页截图；截图未提交到仓库，页面结构与状态转换由上述自动化和本证据步骤复现。

## Limitations

- 本次真实页面闭环使用空步骤产物，只验证 UI、编译导航和隔离测试会话，不证明业务 Skill 的语义正确性。
- 没有调用真实 LLM；完整 GitHub Trending/Star 场景继续由 EV-035 管理，外部额度恢复后需要全新会话重跑。
- 全仓 `vue-tsc` 的既有错误仍未清理，本次范围内文件未新增类型错误。

## Notes

采用选择性 donor 移植，而不是整页或整提交回滚；这样恢复用户熟悉的交互，同时避免重新引入 F028 已否决的 Candidate/Settlement 运行控制和旧 Trace/Runtime。

## Recovery Snapshot

- 工作目录：`E:\RPA-Agent\ScienceClaw`
- 分支：`codex/rpa-agent-intent-first-dual-mode`
- donor：`upstream/master`，参考提交 `37f87da3` 与 pre-F028 `d7a01010`
- 主要修改：`RecorderPage.vue`、`ConfigurePage.vue`、`TestPage.vue`、`RpaStepTimeline.vue` 及时间线交互测试
- 回滚边界：只回滚 F028.3 UI 文件；不得回滚 F028 后端、API、Compiler 或 Runtime。
