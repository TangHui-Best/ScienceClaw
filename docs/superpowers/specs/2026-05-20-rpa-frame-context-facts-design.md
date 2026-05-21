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

## 第二阶段：Frame Scope Resolver 方案

内网验证显示，第一阶段已避免 iframe `tab_id` drift 被编译为新 `Page`，但回放仍可能卡在
`current_page.frame_locator("iframe:nth-of-type(2)")`。这说明问题已从 Page/tab 事实边界收敛到
frame selector 稳定性：录制 trace 同时保留了弱 `frame_path` 与更强的 `signals.reported_frame_path`，
但编译器目前只使用 `trace.frame_path`。

第二阶段目标不是为特定站点替换 selector，而是在编译阶段引入通用的 frame scope 解析：

1. 保持 Page/tab 与 iframe 分层：iframe 仍是当前 `Page` 内的 frame scope，不因 iframe URL 变化切换 Page。
2. 将 frame 定位从单一路径升级为候选链，候选来源包括：
   - `signals.frame.reported_frame_path`
   - `signals.reported_frame_path`
   - `trace.frame_path`
3. 从 `iframe[src="..."]` 生成泛化候选时，应优先保留稳定结构而不是硬编码现场业务值：
   - name/title/testid/id 等稳定属性优先。
   - `src` 可派生 path 级候选，例如匹配 `shoppingcar/index.html`。
   - exact `src` 仅作为 fallback。
   - `iframe:nth-of-type(N)` 保留为最后 fallback。
4. frame 候选必须通过目标 locator probe 才能被选中。仅找到 iframe 不代表选中了正确业务 frame。
5. 不通过加长 timeout、空值硬失败、站点模板或 URL 推断 Page 拓扑来掩盖问题。

建议的生成形态是为 iframe trace 输出一个轻量 helper：

```python
frame_scope = await _resolve_frame_scope(
    current_page,
    [
        ["iframe[src*='shoppingcar/index.html']"],
        ["iframe[src='...recorded exact src...']"],
        ["iframe:nth-of-type(2)"],
    ],
    lambda scope: scope.get_by_role(...),
)
```

helper 语义：

- 按候选顺序尝试 frame path。
- 对每个候选 frame scope，使用当前 trace 的目标 locator probe 验证目标控件是否存在/可见。
- 命中后返回该 frame scope。
- 全部失败时，再让原目标操作抛出带候选列表的清晰错误，便于下一轮诊断。

最小测试矩阵：

1. `reported_frame_path` 有 `src`、`frame_path` 是 `nth-of-type` 时，脚本优先尝试 reported frame 候选。
2. reported frame 候选存在但目标 locator 不在其中时，fallback 到 `trace.frame_path`。
3. `src` 带 query/hash 时，生成 path 级泛化候选，同时保留 exact fallback。
4. popup trace 同时带 frame evidence 时，仍走 `expect_popup()`，不被 frame resolver 改写 Page 语义。
5. 旧 trace 只有 `iframe:nth-of-type(2)` 时，保持兼容。
6. 无 iframe trace 时，不引入 frame resolver 行为。

## 第三阶段：Frame × Target Locator Resolver 方案

2026-05-20 第二轮内网验证显示，提交 `7649d1c fix: resolve iframe frame scope candidates` 后，
脚本已经保持 `current_page`，并且会输出 `_resolve_frame_scope(...)`，但回放仍在第一个 iframe
textbox 操作失败。失败日志中的候选为：

```python
[
    ["iframe[src*='pr']"],
    ["iframe[src=\"https\\:\\/\\/kweweb-b4\\.huawei\\.com\\/pr\\/\\#\\!purpr\\/shoppingcar\\/index\\.html\\?..."]"],
    ["iframe:nth-of-type(2)"],
]
```

失败错误为：

```text
Unable to resolve iframe scope containing target locator;
last error: Locator.wait_for timeout on
locator("iframe:nth-of-type(2)").content_frame.get_by_role(
    "textbox",
    name="请对本次申购做出简要说明",
    exact=True,
)
```

### 根因归零

这次失败说明第一阶段与第二阶段各自只解决了部分症状：

1. Page/tab 分层已生效：脚本没有再 `_ensure_recorded_tab(...)` materialize 新 `Page`，iframe 动作仍在 `current_page` 上执行。
2. frame 候选链已部分生效：脚本开始尝试 `reported_frame_path` 与 `trace.frame_path`。
3. 但 frame selector 泛化仍有 bug：`https://.../pr/#!purpr/shoppingcar/index.html?...` 被当前 `_src_path_candidate()` 解析成 `iframe[src*='pr']`，而不是 `iframe[src*='shoppingcar/index.html']`。原因是只读取 `urlsplit(src).path`，没有解析 hash route 中的业务 path。
4. 更关键的是 resolver 只验证单一 target locator。当前 probe 使用编译器改写后的 `role exact=True`：
   ```python
   scope.get_by_role("textbox", name="请对本次申购做出简要说明", exact=True)
   ```
   但 trace 的 `playwright_locator` 原始事实是非 exact：
   ```python
   page.get_by_role("textbox", name="请对本次申购做出简要说明")
   ```
   如果真实 accessible name 包含必填标记、隐藏文本、换行或前后缀，录制时非 exact 可以唯一命中，但回放 probe 会失败。
5. trace 同时有 `placeholder` locator candidate，当前 resolver 没有把它纳入 probe，也不会在 role probe 失败时用 placeholder 执行最终 action。

因此第三阶段不能继续把问题描述为“frame selector 还不够稳”。更准确的抽象是：

```text
iframe replay scope = frame candidate × target locator candidate 的解析矩阵
```

frame 是否正确，必须由目标控件验证；但目标 locator 本身也可能需要候选解析。只验证一个被编译器收紧后的 locator，会把“locator 过严”误判为“frame 不对”。

### 第三阶段目标

在不影响无 iframe、popup、switch_tab、close_tab、普通导航和普通 click/fill 的前提下，将 iframe replay 从
“解析 frame scope”升级为“解析 frame scope 与 target locator 组合”。

### 实现原则

1. 只在 iframe trace 启用：
   - `trace.frame_path`
   - `signals.reported_frame_path`
   - `signals.frame.reported_frame_path`

2. 非 iframe trace 不引入 resolver：
   - 无 iframe 的普通 action 仍直接使用 `current_page.<locator>()`。
   - popup / download side effect 仍使用 `expect_popup()` / `expect_download()`，只是在 iframe 内 action 时允许 resolver 提供 scope 与 locator。
   - `switch_tab` / `close_tab` 强证据 Page 语义不变。

3. frame candidates 生成必须修正 hash route：
   - 先 CSS-deescape `iframe[src="..."]`。
   - 同时解析 URL `path` 与 `fragment/hash`。
   - 对 `https://.../pr/#!purpr/shoppingcar/index.html?...` 生成：
     - `iframe[src*='shoppingcar/index.html']`
     - 可选：`iframe[src*='purpr/shoppingcar/index.html']`
     - exact `iframe[src="..."]` fallback
     - `iframe:nth-of-type(2)` 最后 fallback
   - 禁止生成过宽候选如 `iframe[src*='pr']`，除非没有更具体片段且片段长度/结构足够有区分度。

4. target locator candidates 必须进入 resolver：
   - 按 trace 中 `locator_candidates` 顺序尝试，selected candidate 优先。
   - 每个 candidate 转换为 probe locator expression。
   - 如果 role candidate 失败，但 placeholder candidate 成功，则 resolver 返回 placeholder 对应的 locator expression。
   - 最终 action 必须使用 resolver 命中的 locator，不要再回到原 selected locator。

5. probe 必须忠实录制事实：
   - 不要在 probe 阶段无条件调用 `_apply_exact_defaults()`。
   - 如果 candidate 的 `playwright_locator` 没有 `exact=True`，probe 应保留非 exact 语义。
   - 可以保留最终 action 的既有 default exact 逻辑，但 iframe resolver 命中 locator 后，最终 action 应使用命中 locator 的语义。

6. 失败诊断输出二维矩阵：
   - 每个 frame candidate。
   - 每个 target locator candidate。
   - 每组 probe 的失败原因。
   - 这样下一轮可以区分 frame 未加载、frame selector 不对、target locator 不对或目标控件本身未出现。

### 建议生成形态

```python
frame_scope, target_locator = await _resolve_frame_target(
    current_page,
    frame_candidate_paths=[
        ["iframe[src*='shoppingcar/index.html']"],
        ["iframe[src='...exact recorded src...']"],
        ["iframe:nth-of-type(2)"],
    ],
    locator_candidates=[
        lambda scope: scope.get_by_role("textbox", name="请对本次申购做出简要说明"),
        lambda scope: scope.get_by_placeholder("请对本次申购做出简要说明"),
    ],
)
await target_locator.click()
```

或在保持字符串生成简单的前提下：

```python
frame_scope, _target = await _resolve_frame_target(
    current_page,
    ...,
)
await _target.fill(kwargs.get("textbox", "采购一批电脑"))
```

### 必补 TDD 测试矩阵

1. `reported_frame_path` 为 hash route `.../pr/#!purpr/shoppingcar/index.html?...` 时，生成 `iframe[src*='shoppingcar/index.html']`，且不生成 `iframe[src*='pr']`。
2. iframe role locator 的 `playwright_locator` 不含 `exact=True` 时，probe 不应被 `_apply_exact_defaults()` 改成 exact。
3. selected role probe 失败但 placeholder candidate 成功时，resolver 使用 placeholder locator 执行最终 click/fill。
4. reported frame candidate 失败时，fallback 到 `trace.frame_path`，并继续尝试所有 target locator candidates。
5. popup trace 同时带 frame evidence 时，仍走 `expect_popup()`，只是 action expression 可以来自 resolved `_target`。
6. 无 iframe trace 不出现 `_resolve_frame_target`。
7. 旧 trace 只有 `iframe:nth-of-type(2)` 且只有一个 locator candidate 时保持兼容。

### 禁止路线

- 不要加长 timeout 来掩盖 resolver 语义错误。
- 不要写 `kweweb-b4`、`purpr`、`shoppingcar` 站点模板。
- 不要把 iframe `src` 当作顶层 `Page` URL 或新 tab 证据。
- 不要全局取消 role/text 的 exact default；如需调整，应限制在 iframe resolver probe/命中 locator 语义内。
- 不要新增“空值硬失败”或 selector 预拦截，这与当前失败无关。

### 当前交接状态

- Worktree: `E:\Work-Project\OtherWork\ScienceClaw\.worktrees\rpa-frame-context-facts`
- Branch: `codex/rpa-frame-context-facts`
- 已推送提交：
  - `011cba2 fix: keep iframe traces on current page`
  - `46e6fa1 chore: remove default credential from agent rules`
  - `7649d1c fix: resolve iframe frame scope candidates`
- 当前未提交文档改动：
  - 本文件新增第二阶段与第三阶段说明，用于下一会话恢复上下文。
- 下一步不应直接实现补丁；应先执行 Harness Start Gate / Retrieval / Vision Gate / Delegation Gate，然后按 TDD 从上述测试矩阵第 1 条和第 3 条开始。

### 第三阶段实现进展（2026-05-20）

本轮已按 Harness gate、systematic debugging 与 TDD 推进第三阶段，不再停留在交接状态。

实现结果：

1. 编译器对 manual iframe action 生成 `_resolve_frame_target(...)`，按 `frame_candidate_paths × locator_candidates` 解析。
2. resolver 命中后返回 `(frame_scope, target_locator)`，最终 click/fill/press 等动作使用命中的 `target_locator`，不再回退到 selected primary locator。
3. iframe resolver probe 使用 trace 原始 locator candidate 语义，不在 probe 阶段套 `_apply_exact_defaults()`；非 iframe action 仍保留既有 exact default 行为。
4. `iframe[src="..."]` 的泛化候选已解析 hash route：
   - `.../pr/#!purpr/shoppingcar/index.html?...` 生成 `iframe[src*='shoppingcar/index.html']` 与 `iframe[src*='purpr/shoppingcar/index.html']`。
   - exact src 仍作为 fallback。
   - `iframe:nth-of-type(N)` 仍最后 fallback。
   - 不再从单段父路径退化出 `iframe[src*='pr']`。
5. popup/download 语义未改：iframe 内 click 若带 popup/download signal，仍由 `expect_popup()` / `expect_download()` 包裹，只是触发动作的表达式来自 resolved target locator。

新增/更新测试覆盖：

1. hash route reported frame path 生成 `shoppingcar/index.html`，不生成过宽 `pr`。
2. role locator 原始 `playwright_locator` 不含 `exact=True` 时，iframe probe 不加 `exact=True`。
3. selected role probe 失败但 placeholder candidate 成功时，最终 fill 使用 placeholder locator。
4. reported frame candidate 失败时 fallback 到 `trace.frame_path`，并继续 probe target locator candidates。
5. popup trace 带 frame evidence 时仍保留 `expect_popup()`。
6. 无 iframe trace 不出现 `_resolve_frame_target()`。
7. 旧 trace 只有 `iframe:nth-of-type(2)` 且一个 locator candidate 时保持兼容。

已跑验证：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q
python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q -k "iframe or popup or switch_tab or navigation"
python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_e2e.py -q
python -m pytest RpaClaw/backend/tests/test_rpa_manager.py RpaClaw/backend/tests/test_rpa_trace_recorder.py -q -k "frame or tab or popup"
```

后续仍需要内网回放验证确认真实页面 accessible name / placeholder 与 frame candidate 命中情况。

## 第四阶段：跨 Trace iframe 后置条件等待方案（2026-05-21）

### 背景

2026-05-21 内网重新生成脚本并执行 `7cf60dc chore: log iframe resolver diagnostics` 后，`FRAME_DIAG` 给出了新的关键事实：

```json
{
  "top_url": "https://kweweb-uata.huawei.com/iplatform/saasone/#/miniapps/.../requirementManagement?reqId=3548124130716926322",
  "top_title": "TEST -- iPlatform",
  "iframe_elements": [
    {
      "index": 0,
      "src": "",
      "visible": false,
      "box": {"x": 0, "y": 0, "width": 0, "height": 0}
    }
  ],
  "frames": [
    {"index": 0, "url": "https://kweweb-uata.huawei.com/iplatform/saasone/#/.../requirementManagement?reqId=3548124130716926322"},
    {"index": 1, "url": "about:blank"}
  ]
}
```

这说明第三阶段的 `frame_candidate_paths × locator_candidates` resolver 并没有选错 iframe。失败时页面里根本没有出现录制时的 `kweweb-b4.../pr/#!purpr/shoppingcar/index.html?...` iframe，只有一个不可见空 iframe 与 `about:blank` frame。

因此当前根因不再是 iframe selector、frame tab drift 或 locator exact 语义，而是跨 trace 业务状态依赖缺失：

```python
await current_page.get_by_text('操作', exact=True).click()
await current_page.wait_for_timeout(500)
```

这段只证明 Playwright click 已完成，不证明业务状态已经进入“后续申购 iframe 已加载且目标 textbox 可定位”。下一条 iframe trace 依赖这个状态，但编译器没有把相邻 trace 之间的后置条件表达出来。

### Vision Anchor

Trace-first Recording 的回放脚本应忠实表达用户操作序列中可验证的能力增量：当前一步如果为下一步打开了新的 frame scope 或目标控件，编译阶段应把这个相邻依赖编译成保守的后置条件等待，而不是依赖固定 sleep。

目标不是让编译器理解某个站点的“操作”按钮语义，而是用下一条 trace 已经记录的事实作为当前步骤的 postcondition：

- 当前步骤：执行用户点击或按键。
- 下一步骤：已记录在某个 iframe 中操作某个目标控件。
- 编译结果：当前步骤完成后等待“下一步骤的 frame candidates 与 target locator candidates 可解析”，再进入下一步骤。

### 非目标

- 不继续补 `kweweb-b4`、`shoppingcar`、`purpr` 等站点模板。
- 不全局加长 click 后 sleep。
- 不自动点击别的“操作”按钮或猜测业务列表中的正确行。
- 不把 iframe `src` 当成顶层 `Page` 导航或新 tab 证据。
- 不改变真实 `popup`、`download`、`switch_tab`、`close_tab` 的强语义。
- 不把空提取、弱 selector 或页面慢加载变成新的录制前置拦截。

### 推荐方案

在 `TraceSkillCompiler` 中新增保守的相邻 trace postcondition 推断。

当当前 trace 是手动 `click` 或 `press`，下一条 trace 是 iframe-scoped manual action，且当前 trace 没有强副作用证据时，当前 trace 的 action 后追加等待：

```python
await current_page.get_by_text('操作', exact=True).click()
await _wait_for_frame_target(
    current_page,
    next_trace_frame_candidate_paths,
    next_trace_locator_candidates,
    logger=_trace_logger,
    timeout_ms=60000,
)
```

`_wait_for_frame_target(...)` 只等待，不执行下一步动作。下一条 iframe trace 仍然通过 `_resolve_frame_target(...)` 解析并执行自己的 click/fill/press/select 等操作。

### 触发条件

只在以下条件全部满足时启用：

1. 当前 trace 是 `RPATraceType.MANUAL_ACTION`。
2. 当前 action 是 `click` 或 `press`。
3. 当前 trace 没有 `signals.popup`。
4. 当前 trace 没有 `signals.download`。
5. 当前 action 不是 `switch_tab` 或 `close_tab`。
6. 下一条 trace 是 `RPATraceType.MANUAL_ACTION`。
7. 下一条 trace 有 iframe evidence：
   - `next_trace.frame_path`；或
   - `next_trace.signals.reported_frame_path`；或
   - `next_trace.signals.frame.reported_frame_path`。
8. 下一条 trace 有可用 locator candidates，或至少有 fallback locator 可用于 probe。

建议暂时不要对已有 `navigate_click` / `navigate_press` 自动叠加 iframe postcondition，除非实现时确认其 navigation 语义与 iframe wait 不冲突。若当前 action 已经有 `post_navigation`、`expect_navigation` 或强导航证据，应优先保持原语义。

### 实现建议

目标文件：

- `RpaClaw/backend/rpa/trace_skill_compiler.py`
- `RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py`

建议分解：

1. 新增判断函数：

```python
def _next_frame_target_postcondition(
    self,
    trace: RPAAcceptedTrace,
    next_trace: Optional[RPAAcceptedTrace],
) -> Optional[FrameTargetPostcondition]:
    ...
```

也可以先不引入新 dataclass，直接返回 `(frame_candidate_paths, target_locator_candidates)`，但不要让判断逻辑散落在 `_render_manual_action_trace()` 里。

2. 让 `_render_trace()` / `_render_manual_action_trace()` 可以看到 `next_trace`。

当前渲染链路只显式传入 `previous_traces`，第四阶段需要把 `traces[index + 1]` 传给 manual action 渲染。保持其他 trace 类型行为不变。

3. 新增生成脚本 helper：

```python
async def _wait_for_frame_target(current_page, frame_candidate_paths, locator_candidates, logger=None, timeout_ms=60000):
    deadline = time.perf_counter() + (timeout_ms / 1000)
    last_error = None
    while time.perf_counter() < deadline:
        try:
            await _resolve_frame_target(current_page, frame_candidate_paths, locator_candidates, logger=None)
            return
        except Exception as exc:
            last_error = exc
            await current_page.wait_for_timeout(1000)
    diagnostics = await _frame_target_diagnostics(current_page, frame_candidate_paths)
    _frame_diag_emit(logger, _json.dumps(diagnostics, ensure_ascii=False, default=str)[:12000])
    raise RuntimeError(f'iframe postcondition target did not appear within {timeout_ms}ms: {last_error}')
```

注意：循环内部不建议把 logger 传给 `_resolve_frame_target()`，避免每秒输出一大段 `FRAME_DIAG`。只在最终失败时输出一次诊断。

4. 复用第三阶段已有能力：

- `_frame_candidate_paths(next_trace)`
- `_target_locator_candidates(next_trace.locator_candidates, fallback_locator=...)`
- `_locator_expression(...)`
- `_resolve_frame_target(...)`
- `_frame_target_diagnostics(...)`

不应新增第二套 frame/locator 解析逻辑。

### 必加 TDD 测试矩阵

1. `test_click_before_iframe_trace_waits_for_next_frame_target`
   - 构造 click trace 后紧跟 iframe fill/click trace。
   - 断言 click 后生成 `_wait_for_frame_target(...)`。
   - 断言 wait 使用下一条 trace 的 frame candidates 与 locator candidates。

2. `test_plain_click_without_following_iframe_trace_does_not_wait`
   - 普通 click 后普通 action，不生成 `_wait_for_frame_target(...)`。

3. `test_popup_click_does_not_use_iframe_postcondition_wait`
   - 当前 trace 有 `signals.popup` 时仍走 `expect_popup()`，不生成 iframe postcondition wait。

4. `test_download_click_does_not_use_iframe_postcondition_wait`
   - 当前 trace 有 `signals.download` 时仍走 download 逻辑，不生成 iframe postcondition wait。

5. `test_switch_and_close_tab_are_not_affected_by_iframe_postcondition`
   - 显式 tab 行为不触发 iframe postcondition。

6. `test_iframe_postcondition_wait_failure_emits_frame_diag_once`
   - wait 超时只输出一次 `FRAME_DIAG`，不要在轮询中刷屏。

7. `test_iframe_trace_itself_still_uses_resolve_frame_target`
   - 下一条 iframe trace 自身仍执行 `_resolve_frame_target(...)` 与实际动作，不被 postcondition 替代。

### 验证命令

Focused：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q -k "iframe or popup or switch_tab or navigation or download"
```

Compiler full：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q
```

If main compile flow changes:

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_e2e.py -q
```

Diff hygiene：

```powershell
git diff --check -- RpaClaw/backend/rpa/trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py docs/superpowers/specs/2026-05-20-rpa-frame-context-facts-design.md
```

### 验收标准

- 用户场景中 trace 7 点击 `操作` 后不再只等待固定 500ms，而是等待 trace 8 的 iframe/textbox postcondition。
- 如果 iframe 成功出现，trace 8 继续用 `_resolve_frame_target(...)` 点击 textbox，trace 9 继续填值。
- 如果 iframe 仍未出现，失败日志应明确显示 postcondition 超时，并输出 `FRAME_DIAG`，不再误导为单纯 iframe selector 问题。
- 普通 click、popup、download、switch tab、close tab、same-tab navigation 的现有测试不回退。
- 不引入任何站点名或业务路径特例；`shoppingcar/index.html` 只能来自 trace evidence 的泛化候选，不应作为硬编码规则写入触发条件。

### 交接状态

- Worktree: `E:\Work-Project\OtherWork\ScienceClaw\.worktrees\rpa-frame-context-facts`
- Branch: `codex/rpa-frame-context-facts`
- 已推送提交：
  - `011cba2 fix: keep iframe traces on current page`
  - `7649d1c fix: resolve iframe frame scope candidates`
  - `3c788b7 fix: resolve iframe target locators`
  - `7cf60dc chore: log iframe resolver diagnostics`
- 第四阶段已完成本地实现，尚未提交/推送，等待内网回放验证。

### 第四阶段实现进展（2026-05-21）

本轮按 TDD 实现相邻 trace iframe postcondition wait：

1. `TraceSkillCompiler` 新增 `_next_frame_target_postcondition(...)`，只在当前 trace 是手动 `click` / `press`、下一条 trace 是 iframe-scoped manual action、且当前 trace 没有 popup/download/switch/close/navigation 强副作用语义时启用。
2. 生成脚本新增 `_wait_for_frame_target(...)`，复用 `_resolve_frame_target(...)` 的 `frame_candidate_paths × locator_candidates` 解析矩阵；轮询期间关闭 resolver 诊断，最终失败时只输出一次 `FRAME_DIAG` 并抛出 `iframe postcondition target did not appear...`。
3. 触发 wait 的 click 不再依赖固定 `wait_for_timeout(500)` 作为业务状态保证；普通 click 仍保持既有 500ms 兼容等待。
4. 下一条 iframe trace 自身仍通过 `_resolve_frame_target(...)` 执行实际 fill/click/press，不被 postcondition wait 替代。
5. popup、download、switch_tab、close_tab、navigate_click / navigate_press 语义未被 postcondition wait 覆盖。

新增测试：

- `test_click_before_iframe_trace_waits_for_next_frame_target`
- `test_plain_click_without_following_iframe_trace_does_not_wait`
- `test_popup_click_does_not_use_iframe_postcondition_wait`
- `test_download_click_does_not_use_iframe_postcondition_wait`
- `test_switch_and_close_tab_are_not_affected_by_iframe_postcondition`
- `test_iframe_postcondition_wait_failure_emits_frame_diag_once`
- `test_iframe_trace_itself_still_uses_resolve_frame_target`

已跑验证：

```powershell
$env:PYTHONPATH='RpaClaw'
python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py::test_click_before_iframe_trace_waits_for_next_frame_target -q
# RED: failed because generated script did not contain await _wait_for_frame_target(...)

python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q -k "postcondition or click_before_iframe or plain_click_without_following_iframe or popup_click_does_not_use_iframe_postcondition or download_click_does_not_use_iframe_postcondition or switch_and_close_tab_are_not_affected or iframe_trace_itself"
# 7 passed

python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q -k "iframe or popup or switch_tab or navigation or download"
# 43 passed, 58 deselected

python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py -q
# 101 passed

python -m pytest RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_e2e.py -q
# 112 passed

git diff --check -- RpaClaw/backend/rpa/trace_skill_compiler.py RpaClaw/backend/tests/test_rpa_trace_skill_compiler.py docs/superpowers/specs/2026-05-20-rpa-frame-context-facts-design.md
# exit 0
```

下一步：提交并推送后，用用户内网 trace 重新生成脚本并回放，确认 trace 7 点击 `操作` 后会等待 trace 8 的 iframe/textbox 出现；若仍失败，应优先阅读 postcondition timeout 的 `FRAME_DIAG`，判断 iframe 是否仍未加载、frame candidate 是否不匹配，或 target locator 是否不匹配。
