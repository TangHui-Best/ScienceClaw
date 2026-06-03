# 资产审查包（Asset Review Packet）

资产 ID: `hcap-686aaeabed7d4949a45f2d7f20327e91`
捕获范围: `full_sop`
资产状态: `draft`
敏感级别: `local-only`
捕获时间: `2026-05-29T00:28:57.827630`

## 场景身份（Scenario Identity）

- 推断场景: 获取前10项PR的标题，目标 link: Pull requests，页面 Pull requests · anthropics/skills · GitHub，(about_content, pr_titles)，观测值 True
- 置信度: 高
- 来源站点: github.com
- 步骤数: 5
- 最终输出: pr_titles = 
- 身份来源: 来自捕获证据推断
- 原始 SOP 意图: (空)

## 人类可读 SOP（Human SOP）

1. 导航到 github.com page - 动作: navigate
2. 点击和SKILL最相关的项目 - 动作: ai_operation (输出: observed_output: {"action_performed": true, "action_type": "click", "clicked_item": "anthropics / skills"})
3. 获取项目About的内容 - 动作: ai_operation (输出: about_content: "Public repository for Agent Skills")
4. 点击 link("Pull requests") 并跳转页面 - 动作: navigate_click (目标: link: Pull requests)
5. 获取前10项PR的标题 - 动作: ai_operation (输出: pr_titles: [])

## 证据摘要（Evidence Summary）

| 步骤 | 意图 | 前置页面 | 动作 | 后置页面 | 输出 |
| --- | --- | --- | --- | --- | --- |
| 1 | 导航到 github.com page | about:blank | navigate | Trending repositories on GitHub today · GitHub | - |
| 2 | 点击和SKILL最相关的项目 | Trending repositories on GitHub today · GitHub | ai_operation | GitHub - anthropics/skills: Public repository for Agent Skills · GitHub | observed_output: {"action_performed": true, "action_type": "click", "clicked_item": "anthropics / skills"} |
| 3 | 获取项目About的内容 | GitHub - anthropics/skills: Public repository for Agent Skills · GitHub | ai_operation | GitHub - anthropics/skills: Public repository for Agent Skills · GitHub | about_content: "Public repository for Agent Skills" |
| 4 | 点击 link("Pull requests") 并跳转页面 | GitHub - anthropics/skills: Public repository for Agent Skills · GitHub | navigate_click: link: Pull requests | Pull requests · anthropics/skills · GitHub | - |
| 5 | 获取前10项PR的标题 | Pull requests · anthropics/skills · GitHub | ai_operation | Pull requests · anthropics/skills · GitHub | pr_titles: [] |

## 自动检查（Auto Checks）

- 资产校验: 警告 (1 个非阻塞问题)
- Snapshot 回归: 通过 (5/5)
- Compiler 回归: 警告 (4/5)
- 检查点: 5 个；运行状态: success
- Trace events: 5 个；accepted: 5
- 预期输出字段: about_content, pr_titles
- 治理状态: captured；expected reviewed=False；sensitivity reviewed=False

## 生命周期状态（Lifecycle State）

- Asset status: `draft`
- Promotion: `captured`
- Expected signals reviewed: `false`
- Sensitivity reviewed: `false`
- Runner coverage: `offline_core_chain`
- Core-chain coverage: `none`
- Golden eligibility: `not-eligible`
- Human approval required: `true`
- Eligibility blockers: `promotion-status-captured`, `asset-status-draft`, `expected-signals-not-reviewed`, `sensitivity-not-reviewed`, `missing-core-chain-coverage`

## 人工确认问题（Review Questions）

- 推断出的场景描述是否符合实际录制意图？
- SOP 步骤是否准确描述真实用户流程，并且不依赖 live 页面状态？
- 目标证据和页面标题是否足以识别预期 UI 元素？
- 观测到的输出值在语义上是否正确，并且适合作为审查证据保留？
- 在分享或升级出 local-only 范围前，是否已经确认没有敏感信息？

## 建议升级（Suggested Promotion）

- candidate-lite: 建议，在人工语义确认后进入非阻塞观察。
- blocking candidate: 需要显式确认 expected signals 和 sensitivity。
- golden: 不建议，新录制资产不能自动成为 blocking golden。

## 人工审查修正（Manual Review Correction）

Step 5 的录制事实与人工预期不一致：

- Intent: 获取前 10 项 PR 的标题。
- Recorded output: `pr_titles: []`，保留为录制时真实发生的事实。
- Expected result: `pr_titles` 必须是长度为 10 的数组，并包含 `before.html` 中前 10 个 PR 标题。
- Observed evidence: `steps/005/before.html` 中标题链接实际使用 `/anthropics/skills/pull/<number>`，而录制时 AI 代码使用了 `a[href*="/pulls/"]`，因此抽取为空。
- Asset decision: 保持 `draft` / `captured`，不要提升为 `candidate` 或 `golden`，直到修复抽取逻辑或重新录制第 5 步并通过回放验证。
- Expected-signal update: `steps/005/expected.json` 已覆盖自动草稿中的 `allow_empty_output=true`，现在要求 `observed_output_shape.length=10` 并校验 10 个标题文本。
