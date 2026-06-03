# 资产审查包（Asset Review Packet）

资产 ID: `hcap-fd43c31be477429e9418199e2e557af5-sanitized`
捕获范围: `full_sop`
资产状态: `draft`
敏感级别: `sanitized`
捕获时间: `2026-05-30T10:43:39.044049`

## 场景身份（Scenario Identity）

- 推断场景: 获取前10项Issues的标题信息，目标 link: Issues 10，页面 Issues · harry0703/MoneyPrinterTurbo · GitHub，(about_content, issue_titles)，观测值 True
- 置信度: 高
- 来源站点: github.com
- 步骤数: 5
- 最终输出: issue_titles = ['[Bug]: PermissionError: [WinError 10013] 以一种访问权限不允许的方式做了一个访问套接字的尝试。', '[Feature]: 文案生成缺少自定义功能', '[Bug]:app.services.video:get_bgm_file:251 - reject unsafe bgm file: ./resource...
- 身份来源: 来自捕获证据推断
- 原始 SOP 意图: (空)

## 人类可读 SOP（Human SOP）

1. 导航到 github.com page - 动作: navigate
2. 点击和金融最相关的项目 - 动作: ai_operation (输出: observed_output: {"action_performed": true, "action_type": "click", "target": "harry0703 / MoneyPrinterTurbo"})
3. 获取About的内容 - 动作: ai_operation (输出: about_content: {"about_content": "利用AI大模型，一键生成高清短视频 Generate short videos with one click using AI LLM."})
4. 点击 link("Issues 10") - 动作: navigate_click (目标: link: Issues 10)
5. 获取前10项Issues的标题信息 - 动作: ai_operation (输出: issue_titles: {"issue_titles": ["[Bug]: PermissionError: [WinError 10013] 以一种访问权限不允许的方式做了一个访问套接字的尝试。", "[Feature]: 文案生成缺少自定义功能", "[Bug]:app.services.video:get_bgm_file:251...)

## 证据摘要（Evidence Summary）

| 步骤 | 意图 | 前置页面 | 动作 | 后置页面 | 输出 |
| --- | --- | --- | --- | --- | --- |
| 1 | 导航到 github.com page | about:blank | navigate | Trending repositories on GitHub today · GitHub | - |
| 2 | 点击和金融最相关的项目 | Trending repositories on GitHub today · GitHub | ai_operation | GitHub - harry0703/MoneyPrinterTurbo: 利用AI大模型，一键生成高清短视频 Generate short videos with one click using AI LLM. · GitHub | observed_output: {"action_performed": true, "action_type": "click", "target": "harry0703 / MoneyPrinterTurbo"} |
| 3 | 获取About的内容 | GitHub - harry0703/MoneyPrinterTurbo: 利用AI大模型，一键生成高清短视频 Generate short videos with one click using AI LLM. · GitHub | ai_operation | GitHub - harry0703/MoneyPrinterTurbo: 利用AI大模型，一键生成高清短视频 Generate short videos with one click using AI LLM. · GitHub | about_content: {"about_content": "利用AI大模型，一键生成高清短视频 Generate short videos with one clic...
| 4 | 点击 link("Issues 10") | GitHub - harry0703/MoneyPrinterTurbo: 利用AI大模型，一键生成高清短视频 Generate short videos with one click using AI LLM. · GitHub | navigate_click: link: Issues 10 | GitHub - harry0703/MoneyPrinterTurbo: 利用AI大模型，一键生成高清短视频 Generate short videos with one click using AI LLM. · GitHub | - |
| 5 | 获取前10项Issues的标题信息 | Issues · harry0703/MoneyPrinterTurbo · GitHub | ai_operation | Issues · harry0703/MoneyPrinterTurbo · GitHub | issue_titles: {"issue_titles": ["[Bug]: PermissionError: [WinError 10013] 以一种访问权限不允许的方式做了一个访问套接字的尝试。", "[Feature]: 文案生成缺少自定义功能", "[Bug]:app.services.video:get_bgm_file:251... |

## 区域选择证据（Region Selection Evidence）

| Step | Region ID | Acquisition | Kind | Local evidence |
| --- | --- | --- | --- | --- |
| 2 | region-5f64a033f28a4e9ba53c2eb06013a3ed | - | action_region | Skip to content {"props":{"docsUrl":"docs.github.com page {"resolvedServerCol..., Skip to content {"props":{"docsUrl":"docs.github.com page {"resolvedServerCol..., Explore Topic... |
| 3 | region-71cf664aa3bd4b9dbc6c0f63f658759b | - | text_region | About 利用AI大模型，一键生成高清短视频 Generate short videos with one click using AI LLM. To..., About 利用AI大模型，一键生成高清短视频 Generate short videos with one click using AI LLM. To..., 利用AI大模型，一键生成高... |
| 5 | region-13e6b9ff8b9344d49e2d224ec3554be2 | - | list_region | Skip to content {"props":{"docsUrl":"docs.github.com page {"resolvedServerCol..., Skip to content {"props":{"docsUrl":"docs.github.com page {"resolvedServerCol..., harry0703 / M... |

## 自动检查（Auto Checks）

- 资产校验: 警告 (1 个非阻塞问题)
- Snapshot 回归: 通过 (5/5)
- Compiler 回归: 警告 (3/5)
- 检查点: 5 个；运行状态: success
- Trace events: 5 个；accepted: 5
- 预期输出字段: about_content, issue_titles
- 治理状态: candidate-lite；expected reviewed=False；sensitivity reviewed=False

## Sensitivity Scan

- Risk level: `low`
- Recommended sensitivity: `sanitized`
- Repo-safe blocked: `false`
- Finding count: `187`
- Categories: `public-web-noise`=89, `sanitized-placeholder`=98
- Sanitized replay contract: `preserved`
- Runtime secret refs: `none`
- Controlled fixtures: `none`

| Category | Severity | File | Line | Reason |
| --- | --- | --- | --- | --- |
| sanitized-placeholder | info | sanitization_report.json | 9 | sanitized placeholder |
| sanitized-placeholder | info | sanitization_report.json | 15 | sanitized placeholder |
| sanitized-placeholder | info | sanitization_report.json | 21 | sanitized placeholder |
| sanitized-placeholder | info | sanitization_report.json | 27 | sanitized placeholder |
| sanitized-placeholder | info | sanitization_report.json | 33 | sanitized placeholder |

## 生命周期状态（Lifecycle State）

- Asset status: `draft`
- Promotion: `candidate-lite`
- Expected signals reviewed: `false`
- Sensitivity reviewed: `false`
- Runner coverage: `offline_core_chain`, `skill_replay_e2e`, `stateful_sop_capture_to_skill`
- Core-chain coverage: `html_to_raw_snapshot`, `raw_to_compact_snapshot`, `planner_action_selection`, `trace_to_skill`, `skill_replay`, `stateful_capture_to_skill`
- Golden eligibility: `not-eligible`
- Human approval required: `true`
- Eligibility blockers: `promotion-status-candidate-lite`, `asset-status-draft`, `expected-signals-not-reviewed`, `sensitivity-not-reviewed`

## 人工确认问题（Review Questions）

- 推断出的场景描述是否符合实际录制意图？
- SOP 步骤是否准确描述真实用户流程，并且不依赖 live 页面状态？
- 目标证据和页面标题是否足以识别预期 UI 元素？
- 观测到的输出值在语义上是否正确，并且适合作为审查证据保留？

## 建议升级（Suggested Promotion）

- candidate-lite: 保持当前状态，除非审查者要求重新进入观察层。
- blocking candidate: 需要显式确认 expected signals 和 sensitivity。
- golden: 仅适用于已审查的 blocking 回归资产。
