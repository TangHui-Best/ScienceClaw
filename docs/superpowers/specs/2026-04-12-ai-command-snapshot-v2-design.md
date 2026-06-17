# AI 录制助手 Snapshot V2 设计文档

## 1. 背景与问题

当前 RPA 体系里，手动录制与 AI 录制助手使用的是两条质量明显不同的数据链路：

- 手动录制已经复用了 vendored Playwright recorder/runtime，能够生成更可靠的 `locator_candidates` 与 strict 校验结果。
- AI 录制助手此前依赖 [assistant_runtime.py](/D:/code/MyScienceClaw/.worktrees/fix-ai-command/RpaClaw/backend/rpa/assistant_runtime.py) 中的简化页面快照与简化 locator 推断逻辑，在复杂页面上容易选错目标或产出回放不稳的定位。

早期设计曾尝试在全页快照之外增加“容器识别 + 不确定性判断 + 局部二次展开”的第二阶段决策链，以提升复杂页面命中率。但实际验证结果表明，这条链路本身也引入了新的不稳定性：

1. 容器识别不稳定  
   复杂业务页面里的 `table/list/card_group/toolbar` 等结构并不总是能可靠识别，错误容器会直接放大后续误判。

2. 不确定性判断规则脆弱  
   “何时触发局部展开”的规则较难稳定泛化，容易出现误触发、漏触发，或者在本可直接命中的页面上增加无谓复杂度。

3. 局部展开放大了第一轮误差  
   如果局部展开不是一次新的高质量 DOM 采样，而只是对全页节点做二次排序，本质上仍然是在放大全页快照的误差。

因此，本次设计调整为更务实的方向：**保留 `snapshot_v2` 与真实 Playwright locator bundle，但删除自动局部二次展开，改为单次全页快照 + 单轮匹配决策。**

## 2. 设计目标

本次设计目标如下：

1. 统一 AI 与手动录制的 locator 真值来源  
   AI 侧不再维护第二套近似 locator 语义，而是直接复用 vendored Playwright runtime 生成的 locator bundle。

2. 用一次全页快照支撑主要 AI 指令场景  
   单次返回全页 `actionable_nodes + content_nodes + bbox + locator bundle`，不再依赖第二阶段自动展开。

3. 提升复杂页面操作命中率  
   对“点击第一个文件下载”“点击右侧按钮”“点击列表第一项”等相对描述，使用全页节点的语义信息与 `bbox` 做单轮排序。

4. 兼顾数据提取类指令  
   `extract_text` 不再只依赖交互控件，而是优先消费 `content_nodes`。

5. 保持回放稳定性  
   坐标与 `bbox` 只作为辅助排序信号；最终回放仍然依赖 locator，而不是裸坐标点击。

## 3. 非目标

本次设计不包括以下内容：

1. 不引入纯视觉坐标回放作为主执行路径。
2. 不要求 AI 助手在每个复杂页面都做二次 DOM 采样。
3. 不重构整个 recorder/manager/generator 架构。
4. 不将容器识别做成强依赖决策链；容器信息只作为辅助上下文保留。

## 4. 方案比较与选型

### 方案 A：单次全页 Snapshot V2

一次性返回全页：

- `actionable_nodes`
- `content_nodes`
- 每个节点的 `bbox`
- 每个可操作节点的真实 `locator bundle`

然后由 AI 在全页节点上做一次排序与选择。

优点：

- 决策链短，行为更可预测。
- 与当前 locator-based 回放体系天然兼容。
- 实现与调试成本明显低于多阶段展开方案。
- 对大多数“点击/输入/提取”场景已经足够。

缺点：

- 全页节点较多时，需要较严格的去重、截断与打分策略。
- 极复杂页面上的局部关系理解能力有限。

### 方案 B：全页 Snapshot V2 + 自动局部二次展开

先抓全页快照，再在“不确定”时自动展开目标容器，进行第二轮选择。

优点：

- 理论上更适合超复杂表格、列表、树形页面。

缺点：

- 决策链长，误差传播更严重。
- 容器识别与不确定性判断本身不稳定。
- 实测效果不理想，收益不足以覆盖复杂度成本。

### 方案 C：视觉/坐标优先

让 AI 更多依赖截图、坐标和视觉相对位置做操作。

优点：

- 对“左上角”“右边第一个”这类自然语言描述较直观。

缺点：

- 回放鲁棒性差。
- 布局变化、滚动、缩放都容易导致失败。
- 与现有 locator 驱动执行体系冲突。

### 选型结论

本次最终选择 **方案 A：单次全页 Snapshot V2**，并采用如下增强策略：

- 保留 `content_nodes`
- 保留 `bbox/is_visible/is_enabled/hit_test_ok`
- 保留真实 Playwright locator bundle
- 删除自动局部二次展开
- 对 `first/last/nth` 等相对描述改为基于全页节点的 `bbox` 排序

这是一种“方案一增强版”，目标是先把 AI 录制助手的主链路稳定下来。

## 5. 总体架构

### 5.1 快照分层

`snapshot_v2` 采用三层结构：

1. `actionable_nodes`  
   服务 `click/fill/press/select` 等操作。

2. `content_nodes`  
   服务 `extract_text` 等数据提取。

3. `containers`  
   保留为辅助上下文，不再驱动第二阶段自动展开。

### 5.2 总体流程

1. AI 执行前先获取一次全页 `snapshot_v2`
2. 根据意图类型选择候选池
   - 操作类优先使用 `actionable_nodes`
   - 提取类优先使用 `content_nodes`
3. 在对应候选池中做单轮打分
4. 若包含 `first/last/nth` 等相对描述，则在高分候选中按 `bbox` 做视觉顺序排序
5. 选择最终节点
6. 使用节点携带的真实 locator bundle 记录 step 并执行

整个流程不再包含自动局部二次展开。

## 6. Snapshot V2 数据结构

### 6.1 顶层结构

顶层包含：

- `url`
- `title`
- `viewport`
- `frames`
- `actionable_nodes`
- `content_nodes`
- `containers`

### 6.2 actionable_nodes

每个可操作节点至少包含：

- `node_id`
- `frame_path`
- `container_id`
- `tag`
- `role`
- `name`
- `text`
- `type`
- `placeholder`
- `title`
- `bbox`
- `center_point`
- `is_visible`
- `is_enabled`
- `hit_test_ok`
- `action_kinds`
- `locator`
- `locator_candidates`
- `validation`
- `element_snapshot`

其中：

- `locator / locator_candidates / validation` 必须直接来自 vendored Playwright locator runtime。
- `bbox` 用于排序与相对位置理解，不用于最终裸坐标回放。
- `hit_test_ok` 用于提升真实可点击节点的优先级。

### 6.3 content_nodes

每个可提取节点至少包含：

- `node_id`
- `frame_path`
- `container_id`
- `semantic_kind`
- `role`
- `text`
- `bbox`
- `locator`
- `element_snapshot`

`content_nodes` 用于覆盖以下场景：

- 标题
- 表格单元格
- 列表项文本
- 标签/值对
- 卡片主文本
- 摘要段落

### 6.4 containers

每个容器至少包含：

- `container_id`
- `frame_path`
- `container_kind`
- `name`
- `bbox`
- `summary`
- `child_actionable_ids`
- `child_content_ids`

容器信息的定位是：

- 用于提示词上下文展示
- 用于未来人工分析或后续增强
- 不再作为自动展开的主驱动机制

## 7. Locator 真值统一

这是本次设计最核心的约束。

### 7.1 当前问题

此前 AI 侧使用 `_build_locator_candidates_for_element()` 基于 `role/name/placeholder/href/tag` 生成简化候选，而手动录制使用的是 vendored Playwright runtime。两者语义不一致，直接导致：

- AI 选中的节点未必对应最稳定的 locator
- AI step 的 `locator_candidates` 不具备真实 strict 信息
- configure/test 页面中 AI step 与手动 step 的可回放性差异明显

### 7.2 设计要求

`actionable_nodes` 中的 locator 信息必须与手动录制保持统一语义：

- 相同页面、相同目标，应尽量生成相同或等价的 locator candidates
- `selected/strict/validation` 语义必须一致
- AI 只负责“选哪个节点”，不再自己“发明 locator”

## 8. 全页单轮匹配策略

### 8.1 操作类指令

对 `click/fill/press/select`：

- 候选池为 `actionable_nodes`
- 主要打分依据包括：
  - 文本匹配：`name/text/title/placeholder`
  - role 匹配：`button/link/textbox/...`
  - 动作能力匹配：是否支持当前 action
  - locator 质量：`validation.status`
  - 命中质量：`hit_test_ok`
  - 可见性与可操作性：`is_visible/is_enabled`

### 8.2 提取类指令

对 `extract_text`：

- 优先候选池为 `content_nodes`
- 若 `content_nodes` 无法命中，再 fallback 到 `actionable_nodes`
- 打分重点是：
  - `text`
  - `semantic_kind`
  - `role`
  - `bbox`

### 8.3 相对描述

对以下相对描述：

- 第一个
- 最后一个
- 第 N 个
- 左边/右边
- 上面/下面

处理方式改为：

1. 先基于语义和 locator 质量得到高分候选池
2. 再用 `bbox` 做视觉顺序排序

例如：

- `first`：按 `y` 升序，再按 `x` 升序
- `last`：按 `y` 降序，再按 `x` 降序
- `nth`：在同一排序序列中取第 N 个

## 9. 与现有代码的对应关系

### 9.1 需要升级的部分

- [assistant_runtime.py](/D:/code/MyScienceClaw/.worktrees/fix-ai-command/RpaClaw/backend/rpa/assistant_runtime.py)
  - 负责生成 `snapshot_v2`
  - 负责全页单轮匹配
  - 负责基于 `bbox` 的视觉顺序排序

- [assistant.py](/D:/code/MyScienceClaw/.worktrees/fix-ai-command/RpaClaw/backend/rpa/assistant.py)
  - 负责向模型展示 `snapshot_v2` 摘要
  - 负责消费新的 step diagnostics

- [assistant_snapshot_runtime.py](/D:/code/MyScienceClaw/.worktrees/fix-ai-command/RpaClaw/backend/rpa/assistant_snapshot_runtime.py)
  - 负责浏览器侧全页节点提取
  - 负责为 `actionable_nodes` 绑定真实 locator bundle

### 9.2 不再需要的部分

- 自动局部展开触发器
- 自动第二阶段容器展开决策链
- 依赖第二轮选择的 assistant diagnostics 字段

## 10. 风险与缓解

### 风险 1：全页快照体积过大

全页 `snapshot_v2` 可能明显大于旧版元素列表。

缓解：

- 限制 `actionable_nodes/content_nodes` 数量上限
- 对文本做截断
- 对重复节点做去重
- 优先保留可见且 `hit_test_ok` 为真的节点

### 风险 2：单轮匹配仍可能误选

复杂页面上仍可能存在多个高相似节点。

缓解：

- 增强全页打分逻辑，而不是增加第二阶段决策
- 使用 `bbox` 处理 `first/last/nth`
- 提高 `validation.status == ok` 与 `hit_test_ok` 的权重

### 风险 3：AI 与手动录制再次漂移

如果 AI 侧重新引入独立 locator 语义，问题会复发。

缓解：

- 严格要求 `actionable_nodes` 复用 vendored Playwright locator bundle
- 允许 `content_nodes` 使用轻量 locator，但操作类节点必须与手动录制统一

## 11. 分阶段实施建议

### 第一阶段

先落地最小可用版：

1. 引入 `snapshot_v2`
2. `actionable_nodes` 复用真实 locator bundle
3. 增加 `bbox/is_visible/is_enabled/hit_test_ok`
4. 增加 `content_nodes`
5. AI 在 `click/fill/extract_text` 上接入全页单轮匹配

### 第二阶段

在不改变主链路的前提下增强：

1. 更强的全页打分逻辑
2. 更细的 `semantic_kind`
3. 更稳的相对位置解析
4. 更好的全页节点去重与裁剪

## 12. 验收标准

满足以下条件即可认为设计达标：

1. AI 在复杂表格/列表页面中执行“点击第一个文件下载”“点击这行的操作按钮”时，命中率较旧版明显提升。
2. AI step 的 `locator_candidates` 与手动录制语义一致。
3. `extract_text` 不再局限于交互元素，能够稳定命中标题、单元格与标签值对。
4. 解析主链路中不再依赖自动局部二次展开。
5. 最终回放仍完全基于 locator，而不是坐标点击。

## 13. 结论

本次调整后的核心不是“给 AI 更多推理阶段”，而是把 AI 录制助手升级为：

- **统一 locator 真值**
- **区分操作节点与内容节点**
- **用一次全页 `snapshot_v2` 支撑主要决策**
- **用 `bbox` 处理相对位置，而不是引入自动第二阶段展开**

这个方向更务实，也更符合当前系统目标：先把 AI 录制助手的主链路稳定下来，再考虑是否需要更复杂的局部增强能力。
