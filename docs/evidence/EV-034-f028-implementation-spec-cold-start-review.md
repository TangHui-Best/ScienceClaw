---
id: EV-034
doc_kind: evidence
scope: project
feature_refs:
  - docs/features/F028-rpa-recording-intent-first-dual-mode-compilation.md
created: 2026-07-20
---

# EV-034：F028 实施规格冷启动可实施性审阅

## Supports Claim

支撑以下有限声明：F028 已有一份面向零历史背景工程师/Coding Agent 的自包含实施规格；规格中的技术架构、数据架构、Browser-use 边界、API/并发、Compiler/Runtime、会话所有权、迁移路径和验收 Harness 已消除本次冷启动审阅发现的实施阻塞歧义。

不支撑“F028 产品能力已实现”或“Live E2E 已通过”。

## Verification Scope

覆盖：

- 将实施规格与 ADR-007、F028、当前 `backend/rpa_agent`、RPA API 和前端 Recorder 路径交叉核对；
- 由不继承历史讨论结论的独立审阅 Agent，以 ClaudeCode 首次接手视角检查可实施性；
- 对首次审阅的五个 P0 逐项修订并复核；
- 检查 Markdown 本地链接、代码围栏和 Git whitespace。

不覆盖产品代码实现、Schema migration、自动化测试、真实 Browser-use/LLM 或 Live UI。

## Checks

```text
独立冷启动审阅：规格 + ADR-007 + F028 + 必要当前代码路径
P0 定点复核：timeline ordering / manual entry / atomic admission / per-step policy / browser host ownership
PowerShell Markdown local-link existence check
Markdown fence count check
git diff --check
PowerShell targeted required-heading check: F028 / ADR-007 / EV-034
python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root <worktree> --docs-path docs --strict
python C:\Users\HUAWEI\.codex\skills\using-agentmentor\scripts\knowledge_check.py --root <worktree> --docs-path docs --feature-index docs/features/F028-rpa-recording-intent-first-dual-mode-compilation.md
```

## Results

- `Pass`：首次冷启动审阅识别出 5 个 P0：时间线序号冲突、手工权威入口不明确、202/409 admission 竞态、逐步输出/资源策略不闭环、测试浏览器会话所有权缺失。
- `Pass`：修订后定点复核确认 5 个 P0 全部关闭，没有残余规格级实施阻塞。
- `Pass`：本地 Markdown 链接均可解析，代码围栏数量为偶数，`git diff --check` 无 whitespace error。
- `Pass`：针对 F028、ADR-007、EV-034 的必需章节检查通过，四份本次核心文档的相对链接检查通过；strict 输出中没有指向这三份当前知识文档的错误。
- `Partial`：全库 `knowledge_check.py --strict` 扫描 275 个 Markdown/73 个知识 artifact，因既有 F001–F024、ADR-001–004、EV-001–024 未迁移到新版模板而返回 593 个错误；该债务不在 F028 文档任务范围内。
- `Partial`：`--feature-index F028...` 仍执行全库检查，并因仓库不存在 `docs/features/INDEX.md` 增至 594 个错误；不能声称 Feature Index 通过。没有为了本任务批量改写无关历史文档。

## Artifacts

- [F028 权威实施规格](../superpowers/specs/2026-07-20-rpa-agent-intent-first-dual-mode-implementation-design.md)
- [ADR-007](../decisions/ADR-007-rpa-recording-intent-first-dual-mode-compilation.md)
- [F028](../features/F028-rpa-recording-intent-first-dual-mode-compilation.md)
- 两份旧规格顶部的 2026-07-20 生命周期说明。

## Limitations

该 Evidence 只证明设计材料达到冷启动可实施程度，不证明代码符合设计。F028 仍为 `active / implementation pending`；真实本地 LLM/browser-use、GitHub Trending/Star、Download、UI 回归和新会话重放仍需在实施阶段分别产出 Evidence。

## Notes

冷启动审阅后的核心收敛包括：顶层顺序只由 `RecordingTimeline.items` 决定；手工动作只认 `/manual-inputs`；AI admission 在短锁内预占 operation lease；AgentSegment 使用 per-step configuration；BrowserHostSession 与 BrowserUseAttachment 分离；V1 SessionStore 明确为进程内 2 小时 TTL。
