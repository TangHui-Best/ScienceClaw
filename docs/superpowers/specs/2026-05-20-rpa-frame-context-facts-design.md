# RPA iframe 与 tab 上下文事实修复策略

## 背景

本策略基于 `origin/codex/rpa-region-scoped-snapshot-master-pr` 新建独立分支 `codex/rpa-frame-context-facts`。目标是在不污染当前检视修复分支的前提下，处理一次内网回放失败暴露出的 RPA 录制事实模型问题。

用户在内网录制的场景中，录制阶段无报错，但回放阶段在 `iframe:nth-of-type(2)` 内等待 `#c_layout` 超时。后续最小复现 accepted trace 显示：

- 点击 `text("操作")` 后，后续输入框位于页面内 iframe。
- 输入框 trace 同时包含 `frame_path: ["iframe:nth-of-type(2)"]` 和 `signals.reported_frame_path`，其中 iframe `src` 指向 `https://kweweb-b4.huawei.com/pr/...shoppingcar/index.html?...`。
- 同一段 trace 又出现新的 `signals.tab.tab_id`，但没有 `popup`、`switch_tab`、`context.on("page")` 等真实 browser page 证据。

因此根因不是等待时间不足，也不是某个站点 selector 特例，而是 iframe 上下文事实被误表达为 browser tab 事实，编译器随后把裸 `tab_id` 变化解释成需要 materialize 新 `Page`。

## Vision Anchor

RPA Trace-first Recording 的主路径应忠实记录用户真实浏览器操作事实，并在编译阶段只根据事实回放上下文。录制事实必须区分：

1. browser page/tab：真实 Playwright `Page` 拓扑。
2. frame scope：页面内 iframe 定位链。
3. action locator：控件级 selector 候选。

本修复的验收目标是：iframe 内动作应在同一 `current_page` 上通过 `frame_locator` 回放；真实 popup、多 tab、显式 switch tab 仍保持现有 page 切换能力。

## 非目标

- 不为 `kweweb-b4`、`iframe:nth-of-type(2)` 或特定 PR 页面写站点模板。
- 不通过加长 timeout、空值硬失败、弱 selector 预拦截等方式掩盖根因。
- 不重写整体 RPA 编译器，不改变 Trace-first + Post-hoc Skill Compilation 的主架构。
- 不把 iframe `src` 差异当成顶层 page 导航或新 tab 证据。

## 方案总览

采用“两端收敛”的保守修复：

1. 录制侧修正上下文事实来源，避免 iframe 事件制造新的 browser `tab_id`。
2. 编译侧增加防御性边界，拒绝把“裸 tab_id 变化”直接升级为新 page。
3. 测试侧覆盖 iframe、popup、显式 switch_tab、同页导航四类上下文，防止误伤已有能力。

### 1. 录制侧：tab_id 只表示真实 Page

候选修改位置：

- `RpaClaw/backend/rpa/manager.py`
- 重点函数：`_handle_event()`、`_step_data_from_event()`、`register_context_page()`、`_upgrade_recent_click_to_open_tab()`

原则：

- `tab_id` 只来自已注册的 Playwright `Page`。
- 事件发生在 iframe 时，`frame_path` 和 `signals.reported_frame_path` 表示 frame scope；事件仍继承所属顶层 page 的 tab_id。
- 如果事件携带的新 `tab_id` 不在当前 session 的 `_tabs[session_id]` 中，且事件有 `frame_path` 或 `reported_frame_path`，应归一化为当前 `active_tab_id` 或所属 page 的已知 tab_id。
- 真实新 page 仍由 `context.on("page") -> register_context_page()` 建立，并通过 popup/open-tab 信号关联前序点击。

不要在这里依赖 URL 判断新 tab，因为 iframe `src`、SPA hash 和顶层导航都可能表现为 URL 变化。

### 2. trace 层：保留 iframe 证据，避免污染 page 语义

候选修改位置：

- `RpaClaw/backend/rpa/trace_recorder.py`
- `RpaClaw/backend/rpa/trace_models.py` 如需补充结构化 frame signal，可先用现有 `signals` 承载，避免模型大改。

原则：

- `manual_step_to_trace()` 继续保留 `frame_path`。
- `signals.reported_frame_path` 应保留，必要时可规整到 `signals.frame.reported_frame_path` / `signals.frame.url`。
- `after_page.url` 不应被 iframe `src` 当作顶层 page URL 的唯一事实来源。若现有采集层暂时只能提供 iframe URL，应在 trace 中保留为 frame evidence，而不是用于推断 browser tab 拓扑。

这一层的任务是让 trace 表达“目标控件在某个 iframe 内”，不是让它替代 page manager 判断真实 tab。

### 3. 编译侧：只有强证据才切换 Page

候选修改位置：

- `RpaClaw/backend/rpa/trace_skill_compiler.py`
- 重点函数：`_render_trace_tab_alignment()`、`_record_trace_tab_side_effects()`、`_render_switch_tab_trace()`、`_render_side_effect_interaction()`、`_frame_scope_lines()`

原则：

- 真实 page 切换的强证据包括：
  - `signals.popup.target_tab_id`
  - action 为 `switch_tab`
  - action 为 `close_tab` 且存在 fallback tab
  - 已知真实 page 注册证据
- 裸 `signals.tab.tab_id` 变化不应自动 materialize 新 page，尤其当 trace 有 `frame_path` 或 `reported_frame_path` 时。
- 对 iframe trace，编译器应保持 `current_page`，并通过 `_frame_scope_lines(trace.frame_path)` 生成 `frame_locator(...)`。
- 现有真实 popup 和显式 switch tab 测试必须继续通过。

如果需要处理历史 trace，可考虑在编译器里增加“疑似 iframe tab drift”的兼容路径：当新 tab_id 没有 popup/switch/close 证据且 trace 存在 frame_path，则只输出注释并保持当前 page。

### 4. iframe selector 稳定性

现阶段不要把稳定性修复扩大成独立抽象。可以在编译器生成 frame scope 时优先使用已有 `frame_path`；如果未来要增强，方向应是：

- 使用 `signals.reported_frame_path` 中的 iframe `src` 作为更稳定候选。
- 保留 `iframe:nth-of-type(N)` 作为 fallback。
- 通过 condition-based wait 等待目标 frame 或目标控件出现，而不是固定 sleep。

这部分建议作为第二阶段，除非第一阶段测试证明 `iframe:nth-of-type(2)` 本身就是主要不稳定点。

## 测试策略

优先写 focused regression tests，再实现修复。

建议测试：

1. `test_iframe_trace_with_new_tab_id_does_not_materialize_page`
   - 构造 click 后的 fill trace：fill trace 有新 `tab_id`、`frame_path`、`reported_frame_path`，但无 popup/switch。
   - 断言生成脚本不会在该 trace 前调用 `_ensure_recorded_tab(...)`。
   - 断言 fill 使用 `current_page.frame_locator(...)`。

2. `test_real_popup_still_compiles_to_expect_popup`
   - 复用现有 popup 覆盖，确保 `expect_popup()`、`tabs[target] = new_page` 不回退。

3. `test_manual_switch_tab_still_requires_recorded_url_or_known_tab`
   - 复用显式 switch_tab 行为，确保缺 recorded URL 时仍清晰失败。

4. `test_navigate_click_same_tab_still_treated_as_navigation`
   - 确认同一 tab 顶层导航不被 iframe 逻辑误吞。

5. 录制侧 manager/recorder 测试
   - 构造 iframe 事件携带未知 tab_id + frame_path，断言入库 step/trace 继承 active tab 或不触发 tab 切换。
   - 构造真实 `register_context_page()` 场景，断言 popup/open-tab 仍建立新 tab。

建议命令：

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q -k "iframe or popup or switch_tab or navigation"
python -m pytest RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_trace_recorder.py -q -k "frame or tab or popup"
```

如修改影响 trace 编译主路径，再跑：

```powershell
$env:PYTHONPATH="RpaClaw"
python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_e2e.py -q
```

## 分支与验证策略

当前修复分支：

- Worktree: `E:\Work-Project\OtherWork\ScienceClaw\.worktrees\rpa-frame-context-facts`
- Branch: `codex/rpa-frame-context-facts`
- Base: `origin/codex/rpa-region-scoped-snapshot-master-pr`

如果 base 分支继续修检视意见，先同步：

```powershell
cd E:\Work-Project\OtherWork\ScienceClaw\.worktrees\rpa-frame-context-facts
git fetch origin
git rebase origin/codex/rpa-region-scoped-snapshot-master-pr
```

推送供内网验证：

```powershell
git push -u origin codex/rpa-frame-context-facts
```

如已推送后 rebase：

```powershell
git push --force-with-lease
```

## 风险与防护

- 风险：过度收紧 tab 切换导致真实 popup 或 switch_tab 回放失败。
  - 防护：只拒绝“无 popup/switch/close 证据的裸 tab_id 变化”，保留强证据路径。

- 风险：历史 trace 里确实存在只有 tab_id 变化、缺 popup 证据的真实多 tab。
  - 防护：编译器可仅在 trace 存在 `frame_path` 或 `reported_frame_path` 时启用 iframe drift 兼容；其它裸 tab_id 可先保留现状或输出更明确诊断。

- 风险：iframe `frame_path` 的 `nth-of-type` 不稳定。
  - 防护：本轮先修上下文事实，不扩大到 frame selector 重构；如内网验证仍失败，再以 `reported_frame_path` 的 iframe `src` 作为第二阶段增强。

- 风险：把 `after_page.url` 语义改动过大，影响导航记录。
  - 防护：优先在事件归一化和编译 tab alignment 层处理，不急于大改 page state 模型。

## 推荐实施顺序

1. 添加编译器 regression，复现“iframe trace 带新 tab_id 不应 materialize page”。
2. 修改 `TraceSkillCompiler._render_trace_tab_alignment()`，让 iframe trace 的裸 tab_id drift 保持当前 page。
3. 添加录制侧 regression，复现 iframe event 不应切 active tab。
4. 修改 `RPASessionManager` 事件归一化，保证未来 trace 不再产生错误 tab 事实。
5. 运行 focused tests。
6. 推送分支给内网验证。
7. 内网验证若仍卡在 iframe 定位，再进入第二阶段 frame selector 稳定性增强。

