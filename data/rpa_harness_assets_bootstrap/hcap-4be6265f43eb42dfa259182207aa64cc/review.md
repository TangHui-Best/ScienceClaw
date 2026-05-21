# 资产审查包（Asset Review Packet）

资产 ID: `hcap-4be6265f43eb42dfa259182207aa64cc`
捕获范围: `full_sop`
资产状态: `active`
敏感级别: `repo-safe`
捕获时间: `2026-05-18T19:09:29.662524`

## 场景身份（Scenario Identity）

- 推断场景: Navigate GitHub Trending, open a repository, and extract fork count.
- 置信度: 高
- 来源站点: github.com
- 步骤数: 3
- 最终输出: fork_count = Fork 1.3k
- 身份来源: scenario.sop_intent
- 原始 SOP 意图: Navigate GitHub Trending, open a repository, and extract fork count.

## 人类可读 SOP（Human SOP）

1. 导航到 github.com page - 动作: navigate
2. 点击 link("tinyhumansai / openhuman") 并跳转页面 - 动作: navigate_click (目标: link: tinyhumansai / openhuman)
3. 获取fork数 - 动作: ai_operation (输出: fork_count: "Fork 1.3k")

## 证据摘要（Evidence Summary）

| 步骤 | 意图 | 前置页面 | 动作 | 后置页面 | 输出 |
| --- | --- | --- | --- | --- | --- |
| 1 | 导航到 github.com page | about:blank | navigate | Trending repositories on GitHub today · GitHub | - |
| 2 | 点击 link("tinyhumansai / openhuman") 并跳转页面 | Trending repositories on GitHub today · GitHub | navigate_click: link: tinyhumansai / openhuman | GitHub - tinyhumansai/openhuman: Your Personal AI super intelligence. Private, Simple and extremely powerful. · GitHub | - |
| 3 | 获取fork数 | GitHub - tinyhumansai/openhuman: Your Personal AI super intelligence. Private, Simple and extremely powerful. · GitHub | ai_operation | GitHub - tinyhumansai/openhuman: Your Personal AI super intelligence. Private, Simple and extremely powerful. · GitHub | fork_count: "Fork 1.3k" |

## 自动检查（Auto Checks）

- 资产校验: 通过
- Snapshot 回归: 通过 (3/3)
- Compiler 回归: 通过 (3/3)
- 检查点: 3 个；运行状态: success
- Trace events: 3 个；accepted: 3
- 预期输出字段: fork_count
- 治理状态: candidate；expected reviewed=True；sensitivity reviewed=True

## 人工确认问题（Review Questions）

- 推断出的场景描述是否符合实际录制意图？
- SOP 步骤是否准确描述真实用户流程，并且不依赖 live 页面状态？
- 目标证据和页面标题是否足以识别预期 UI 元素？
- 观测到的输出值在语义上是否正确，并且适合作为审查证据保留？

## 建议升级（Suggested Promotion）

- candidate-lite: 保持当前状态，除非审查者要求重新进入观察层。
- blocking candidate: 需要显式确认 expected signals 和 sensitivity。
- golden: 仅适用于已审查的 blocking 回归资产。
