---
id: F019
doc_kind: feature
status: ready_for_review
created: 2026-05-29
updated: 2026-05-29
---

# F019: RPA Harness Controlled Download Side Effects

## Goal

补齐 RPA Harness 对“自然语言点击列表第一行文件名称并触发下载”这一类场景的可验收闭环。

当前 Harness 已能在 controlled fixture 中验证自然语言目标选择，也能在编译后的 Skill
中使用 Playwright `expect_download()` 保存文件；缺口在于静态 `before.html` 默认没有真实
下载响应，导致“点中了目标”和“浏览器下载事件被捕获”之间缺少受控证据。

F019 的目标是把下载建模为 Harness controlled side effect：由资产 expected signals
声明受控下载响应，由 replay route 提供真实 attachment response，由 Skill replay 验证
下载结果，而不是把 Harness 扩展成通用业务后端模拟器。

## Current Status

ready_for_review

2026-05-29: 已完成 F019 第一切片实现。Harness 现在可以在受控 fixture 中声明下载副作用、返回真实 attachment response、让生成后的 Skill 触发 Playwright `download` 事件并保存文件，同时在 replay/full-live/stateful post-capture 报告中记录 controlled download 证据。

完整相关测试集中仍有 2 个测试受既有脏工作区影响失败：`data/rpa_harness_assets_bootstrap/**` 的 tracked bootstrap assets 在本次任务开始前已处于删除状态，导致 real governed candidate asset 计数为 0。该问题不属于 F019 行为改动，未在本切片中恢复或回滚。

## Next Step

进入人工 review。Review 重点：

- 确认 `controlled_download` expected signal 的边界是否足够小，是否仍保持 Harness controlled side effect，而不是泛化 mock backend。
- 确认报告中的 controlled download evidence 不会被误读为 live-site download oracle。
- 在恢复或确认 bootstrap assets 后，可重新运行包含 real governed candidate asset 的完整相关测试集。

## Vision Anchor

- Original request: 为 Harness 当前无法完整模拟或捕获自然语言
  “点击列表第一行的文件名称”触发下载事件的问题，落地一个完整修复。
- User pain point: 静态页面可以验证 Agent 是否点对列表项，但不能天然触发浏览器
  `download` event；如果不显式建模，报告容易把 `runtime_status=success` 或静态点击
  误读成下载链路通过。
- Desired outcome: 受管资产可以在 controlled fixture 中声明下载副作用，Skill replay
  能触发真实 Playwright download event、保存文件、输出下载结果，并在报告中明确这是
  controlled fixture 下载，不是 live URL oracle。

## Non-goals

- 不新增新的 Harness profile。
- 不做通用 mock server 或站点特定业务后端。
- 不把 live URL 当正确性 oracle。
- 不自动 promotion。
- 不把所有异步导出、轮询、鉴权下载都纳入第一切片。
- 不改变 deterministic profile、user-input replay 或 full-live 的治理边界。

## Entry Gates

Start Gate:

- Task class: high-risk.
- Risk triggers: Harness asset expected-signal shape, controlled replay route,
  browser side effect, generated Skill replay semantics, report interpretation, and
  risk of drifting into a mock business backend.
- Delegation decision: not needed. The first slice is tightly coupled across one
  replay path; subagent coordination would add overhead without a clean independent
  write boundary.
- Bug attribution: existing behavior gap spans F016 user-input replay and F017
  full-live controlled fixture, but this is a new capability slice rather than a
  patch to a completed accepted feature.
- Required pre-work: retrieve F016/F017/F018, v1 design, ADR-003, existing replay
  and compiler download support; create F019/EV-019 before code.

Knowledge Retrieval:

- Read F016, F017, and F018 Feature pages.
- Read EV-018 closeout evidence.
- Read existing `TraceSkillCompiler`, `PlaywrightGenerator`, `skill_replay`, and
  `live_agent_eval` download / controlled-route behavior.

Retrieval conclusion:

- Compiler and legacy generator already know how to compile `signals.download`
  into `expect_download()` and save files.
- `skill_replay` controlled route currently serves captured HTML documents and
  returns 204 for non-document resources, so static fixture download cannot pass.
- `user_input_replay` records boundary injection only and should not be redefined
  as live side-effect execution.
- The smallest coherent fix is controlled download side-effect support in expected
  signals plus Skill replay controlled routing.

Vision Gate:

- Mode: Entry Gate.
- Outcome: ready to implement.
- Original intent: make download-triggering natural-language/list-click scenarios
  verifiable without depending on live websites.
- Alignment: controlled side-effect modeling keeps Scripts execute / Agents explain
  / Humans govern intact.
- Drift risks: creating a generic backend simulator, overclaiming controlled download
  as live-site correctness, or hiding Planner/selector bugs inside Harness rules.

## Links

- Evidence: [EV-019 RPA Harness Controlled Download Side Effects Evidence](../evidence/EV-019-rpa-harness-controlled-download-side-effects.md)
- Design: [RPA Harness v1 Asset-Driven User Input Replay](../rpa/harness/rpa-harness-v1-asset-driven-user-input-replay.md)
- Previous Feature: [F017 RPA Harness v1 Full/Live Profile Integration](F017-rpa-harness-v1-full-live-profile-integration.md)
- Closeout Feature: [F018 RPA Harness v1 Closeout / Stabilization](F018-rpa-harness-v1-closeout-stabilization.md)
- Decision: [ADR-003 RPA Golden Evaluation Uses Scenario Assets, Not Direct Agent Chat](../decisions/ADR-003-rpa-golden-evaluation-uses-assets-not-live-agent-chat.md)

## Acceptance Criteria

- [x] Expected signals can declare a controlled download response for a step.
- [x] Skill replay installs a controlled download route that returns a real attachment
  response instead of 204 for declared download URLs.
- [x] Generated Skill replay can trigger Playwright `download` event from controlled
  fixture HTML and save the file.
- [x] Replay validation can assert downloaded filename and saved file presence.
- [x] Report item includes controlled download evidence and failure category when
  download expectations are not met.
- [x] Existing non-download Skill replay tests continue to pass in the focused suite
  excluding two pre-existing bootstrap-asset-dependent failures.
- [x] F019 Evidence records focused tests, residual risks, and closeout status.

## Patch History

None yet.

| Patch | Date | Commit | Symptom | Root Cause | Protection | Status |
| --- | --- | --- | --- | --- | --- | --- |

## Evidence

See [EV-019 RPA Harness Controlled Download Side Effects Evidence](../evidence/EV-019-rpa-harness-controlled-download-side-effects.md).
