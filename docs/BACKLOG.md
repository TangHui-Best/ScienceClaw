# Backlog

> 说明：这是项目运行态的分支/待办记录，不是 Harness artifact，因此不再保留 `doc_kind` frontmatter。

_Updated: 2026-05-27_

## Active Branch Map

当前 RPA 相关工作保持三条活跃分支，避免区域选择、iframe 修复和 Harness 验证再次混线。

| Branch | Purpose | Base / State | Notes |
| --- | --- | --- | --- |
| `codex/rpa-region-selection-optimization-v2` | 区域选择功能优化 | 基于 `upstream/master` 新建，当前所在分支 | 用于继续优化区域选择体验、准确性、交互和 snapshot 选择效果。不要混入 iframe 专项修复。 |
| `codex/rpa-iframe-frame-context-fix-v2` | iframe / frame context bug 修复 | 基于已合入区域选择功能后的 `upstream/master` | 用于专门处理 iframe 场景失败。旧 `codex/rpa-frame-context-facts` 只作为历史参考。 |
| `codex/rpa-harness-region-integration` | Harness + 区域选择协同验证 | 已推送，包含 live-agent eval、F012/EV-012 和 LL-001 复盘 | 用作内网 Harness 验证和实现参考，不作为区域选择优化主开发分支。 |

## Historical Reference Branches

以下分支原则上不再继续开发，只在需要查历史实现或恢复上下文时参考：

- `codex/rpa-region-context-refine-main`
- `codex/rpa-region-scoped-snapshot-master-pr`
- `codex/rpa-frame-context-facts`
- `codex/rpa-trace-first-harness`

## Next Actions

- 区域选择优化：继续在 `codex/rpa-region-selection-optimization-v2` 上推进。下一步把 `/section-texts` 手动 fixture 接入 runner-backed eval case，或保存一次手动 region selection 录制/编译 artifact，证明可依赖 section/container anchor 走确定性编译，缺 anchor 的自由文本走 runtime AI 且不嵌入录制现场文本。
- iframe 修复：先建立可复现 iframe scenario，再进入 `codex/rpa-iframe-frame-context-fix-v2`。
- Harness 验证：内网运行 live-agent eval 时参考 `codex/rpa-harness-region-integration` 上的 F012/EV-012 和 `docs/rpa/harness/live-agent-eval.md`。

## Deferred RPA Recording Follow-ups

- F001 / manual recording: hover-triggered dropdown buttons that also open on click can still record an invalid `click body` when the user clicks near the edge of the trigger and the browser event target falls through to the page background. Short-term workaround: click the trigger center during manual recording. Long-term fix: once pointer movement reveals an actionable floating menu context, record the hover menu trigger event so replay can reopen the menu before clicking the menu item, even when a later click target is weak (`body`, background, or overlay container). Solve this from raw event evidence, not from site-specific menu text or page rules.
