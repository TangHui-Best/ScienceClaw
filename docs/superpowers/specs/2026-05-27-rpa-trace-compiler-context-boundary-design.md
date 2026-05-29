# RPA Trace Compiler 上下文边界设计

## 状态

本文档创建于 2026-05-27，当前只作为设计沉淀，不立即实施。
文档记录的是完整目标方案；真正落地时，第一阶段应采用小修复，而不是借机做大规模 compiler 重构。

## 来源上下文

- 当前分支：`codex/rpa-region-selection-optimization-v2`
- 相关设计与特性上下文：
  - `docs/superpowers/specs/2026-05-26-rpa-selected-region-text-extract-design.md`
  - `docs/features/F001-rpa-trace-source-convergence.md`
  - `docs/features/F011-rpa-region-scoped-snapshot.md`
- 当前分支已经完成的能力收敛包括：
  - selected-region 自由文本提取分类
  - 随机 / 动态 locator 拒绝
  - iframe frame-context 回放
  - popup trace 同步
- 本次 PR review 暴露出两个新的边界回归：
  1. `tab` 证据会把本可确定性编译的提取 trace 赶回 runtime-AI 或 embedded-AI 路径。
  2. `heading_scoped_text` 新增了确定性提取路径，但没有完整继承 selected-region 已有的 locator 安全边界。

## 问题定义

这不是两个孤立 bug，而是 compiler 决策边界不清导致的系统性问题。

当前系统把两类本质不同的证据混在一起使用：

1. **执行上下文证据**
   - `tab`
   - `frame_path`
   - `reported_frame_path`
   - 其他 page / frame 对齐信息
2. **行为副作用证据**
   - popup
   - download
   - navigation 及 post-navigation
   - file upload
   - action-targeting 语义

这两类证据回答的问题不同：

- 执行上下文证据回答：**回放应在什么 page / frame 中执行？**
- 行为副作用证据回答：**这一步是否仍然必须保留动作语义，而不能被纯提取逻辑接管？**

一旦让上下文证据参与 side-effect 分类，就会出现“脚本还能跑，但确定性提取 silently 退化”的问题。
这类问题最危险，因为它不一定立刻报错，却会让生成技能变弱、变脆，后续也很难从用户反馈里快速定位根因。

与此同时，确定性文本提取的资格判断已经分散到了多条路径上：

- `selected_region_text_extract`
- `heading_scoped_text`
- 现有 region extract 分支

当资格判断没有统一成一个共享 gate 时，任何新路径都可能绕过旧路径刚补好的安全边界。当前 `heading_scoped_text` 的问题就是这个模式的直接体现。

## 设计锚点

Trace-first 并不意味着 accepted trace 中的所有证据都应以同样方式影响 compiler 决策。
Compiler 必须明确区分三条边界：

1. **上下文对齐边界**
   - 只负责让 replay 落到正确 page / frame
   - 不能单独决定这一步是否失去确定性编译资格
2. **确定性提取资格边界**
   - 只有强、明确、可回放的证据才允许进入确定性文本提取
   - 弱证据必须回退到 runtime AI
3. **行为保持边界**
   - 真正的动作语义必须继续是动作语义
   - 提取逻辑不能抢占 popup / download / action-targeting 这类 trace

## 目标

- 将执行上下文证据与行为副作用证据在 compiler 决策中明确分层。
- 将确定性文本提取资格统一为一个共享 gate，并同时供 producer 与 compiler 使用。
- 保持 `single_value`、`table_region`、`list_region`、安全的 `heading_scoped_text`、安全的 selected-region 文本提取的确定性编译能力。
- 保持 popup、download、navigation、file upload、显式 action-targeting trace 的动作语义优先级。
- 第一阶段修复范围尽量小，适合在合并前安全落地。
- 将验证重点放在 harness 式分类测试，而不是继续堆站点特例。

## 非目标

- 不在这一轮把整个 trace compiler 重写成新的状态机。
- 不新增站点特化 selector 规则。
- 不让 compiler 根据 bbox、文本长度、局部 DOM 结构去“猜”更好的 locator。
- 不引入多轮 repair 或录制期稳定性硬拦截。
- 不把 trace-first 录制改造成 contract-first 流程。
- 不试图在一轮改动里解决所有文本提取策略问题。

## 根因分析

### 根因一：上下文证据泄漏到了 side-effect 分类

当前 compiler 把 `tab` 当成 side-effect evidence，这是概念上错误的。

`tab` 往往只表达“这一步发生在另一个已记录页面上下文中”，对纯提取 trace 来说，它应该只影响 page 选择，不应该改变 extraction strategy。

一旦 `tab` 在 region extract 分类之前就参与 side-effect 判断，就会导致已有稳定 locator 和稳定 renderer 的提取 trace 被提前踢出确定性路径。

### 根因二：确定性文本提取资格判断被复制到了多条路径

`selected_region_text_extract` 这一侧已经有较强的安全意识：

- 拒绝 unstable identity
- 拒绝 structural region header
- 拒绝 observed-text-driven locator

但 `heading_scoped_text` 目前基本还是“只要 heading locator 合法就能编译”。
这对新的 replay surface 来说过弱。

系统因此缺少一个统一答案：

> 什么样的文本提取证据，允许进入最终的确定性 replay 逻辑？

没有这个统一答案，每条新路径都会局部重定义边界，长期一定继续回归。

## 总体方案

### 一、将 compiler 证据拆成两层

#### 1. 执行上下文证据层

只用于对齐 replay 作用域：

- `signals.tab`
- `trace.frame_path`
- `signals.reported_frame_path`
- 后续可能补充的 page / frame 恢复证据

这层证据可以：

- 选择 `current_page`
- 选择 frame scope
- 阻止错误的 page materialization

这层证据不可以：

- 单独把 trace 标记成 side-effectful
- 单独迫使纯提取 trace 回退到 runtime AI
- 抢占本已存在的确定性提取 renderer

#### 2. 行为副作用证据层

只用于保持动作语义：

- `popup`
- `download`
- `navigation`
- `post_navigation`
- `set_input_files`
- `region_context_decision.used_as == action_targeting`
- 明确动作形态的 output

这层证据可以：

- 保留 runtime AI
- 保留 embedded AI code
- 让动作回放优先于 region extract

这层证据不应由裸 `tab` 或 frame context 推导出来。

### 二、定义一个共享的确定性文本提取资格 gate

引入一个共享概念：

`is_deterministic_text_extract_eligible(trace_or_signal) -> bool`

这个 gate 应同时被两处消费：

- recording-time signal 生产
- compile-time defensive recheck

该 gate 至少要求：

- 明确的 extraction intent
- 允许的 region kind
- 稳定、可回放的 locator 证据
- 不是 observed-value-driven locator
- 不是 structural region header locator
- 不是 unstable identity locator
- 没有更强的 structured extraction shape 应优先接管

简化表达就是：

> 只有当 trace 已经证明“该文本目标可确定性回放”时，才允许编译成确定性文本提取。

### 三、把文本提取能力统一到同一层级树中

Compiler 应把文本提取看成一组从强到弱的策略，而不是彼此并列、互相抢占的局部分支：

1. 结构化 snapshot 字段提取
2. 结构化 region 提取
   - `single_value`
   - `table_region`
   - `list_region`
3. 确定性文本提取
   - 安全的 `selected_region_text_extract`
   - 安全的 `heading_scoped_text`
4. runtime AI 文本提取兜底

关键规则是：

> 确定性文本提取只能消费 trace 已经明确证明的目标，不能消费 compiler 的“猜测”。

### 四、将 `heading_scoped_text` 重新归类为确定性文本提取子类

`heading_scoped_text` 仍然有价值，但它不能再作为一个绕过通用安全边界的特例。

它必须满足与其他确定性文本提取一致的回放安全要求：

- heading relation 仍限制在显式支持集合，例如 `inside_heading`、`preceding_heading`
- heading locator 必须通过共享稳定性检查
- structural panel / collapse / accordion header 不能成为确定性 replay 事实
- anchor 证据弱时，应回退到 runtime AI，而不是强行生成确定性读取

这样做的收益是：

- 保留 bounded-section 的有效能力
- 避免新路径重新打开刚被 selected-region 方案封住的同类漏洞

### 五、显式保持动作优先级

Compiler 决策树中必须保持一个不变式：

> region 结构证据不能抢走本质上仍然是动作的 trace。

因此，即便存在 region context，只要 trace 仍表达 download / popup / action-targeting 等动作语义，动作路径仍应优先于确定性提取。

这与 `F011.6` 当前方向一致，后续修复不能把这条边界又削弱回去。

## 目标决策顺序

对 AI-operation trace，目标决策顺序应为：

1. 安全的 selected-region 确定性文本提取
2. 安全的 snapshot 结构化字段提取
3. 安全的 heading-scoped 确定性文本提取
4. 安全的 region 确定性提取
   - single value
   - table
   - list
5. 动作保持路径
   - 必须保留行为语义时走 embedded AI code
   - 仍需运行时语义判断时走 runtime AI
6. 通用 runtime AI 兜底

同时加两条附加约束：

- 上下文对齐是正交能力，可以包裹任何确定性分支
- side-effect 分类时不得把裸 `tab` 当成动作证据

## 第一阶段落地策略

第一阶段必须刻意收敛范围。

### Phase 1：小修复

范围只包括：

- `tab` 不再参与行为副作用分类
- `heading_scoped_text` 接入与确定性文本提取一致的 replay-safety gate
- 增加锁定 compiler 边界的测试

这是推荐的合并前修复方式，因为 blast radius 小，且能直接解决当前 review blocker。

### Phase 2：共享谓词清理

范围包括：

- 去掉 `RecordingRuntimeAgent` 与 `TraceSkillCompiler` 中重复的 eligibility 逻辑
- 抽出共享 helper 或共享本地 policy surface

这一阶段有价值，但如果 Phase 1 已能安全守住边界，它不必阻塞第一阶段合并。

### Phase 3：Harness 强化

范围包括：

- 增加矩阵式 compile classification tests
- 记录“为什么该 trace 被编译成这种策略”的证据
- 让后续分支工作更容易验证，而不是依赖站点特例复现

## 对现有功能的影响评估

### 预期保持不变的能力

以下行为应保持不变：

- 稳定的 `single_value` 提取继续走确定性 locator-based replay
- 稳定的 `table_region` 提取继续走确定性 structured replay
- 稳定的 `list_region` 提取继续走确定性 structured replay
- popup / download / navigation 动作 trace 继续保持动作语义
- iframe context alignment 继续有效
- selected-region 弱证据继续回退到 runtime AI

### 预期应改变的行为

以下行为应被修正：

1. 带 `signals.tab` 的纯提取 trace，不应再因为上下文证据而 silently 退化成 runtime / embedded AI。
2. 使用动态 id 或结构性 heading locator 的 `heading_scoped_text`，不应再被编译为确定性 locator 读取。
3. 弱或结构性 heading anchor 应回退到 runtime AI，而不是生成脆弱 replay 逻辑。

### 风险面

这里最大的风险不是“立刻报错”，而是“分类漂移”。

如果第一阶段修得过宽，可能会：

- 过度收缩确定性提取覆盖率
- 把原本有效的确定性 trace 推回 runtime AI
- 误伤 table / list / single-value 现有能力

因此第一阶段必须范围小、且由分类测试兜底。

## 验证策略

不要只依赖端到端站点场景。站点复现有价值，但不够稳定，也不足以证明边界设计正确。

必须增加直接断言 compiler 意图的边界测试。

### 必需的测试矩阵

1. **仅有上下文型 `tab` 证据**
   - 同一 extraction trace，分别带和不带 `signals.tab`
   - 期望：当底层提取证据稳定时，compile strategy 保持确定性不变

2. **heading-scoped anchor 矩阵**
   - stable heading anchor
   - dynamic generated id anchor
   - structural collapse / panel header anchor
   - observed-text-driven anchor
   - 期望：只有 stable anchor 保留确定性编译

3. **selected-region 与 heading-scoped 一致性**
   - 两条路径都应遵守同一套 unstable / structural / observed-value-driven locator 边界

4. **动作优先级**
   - region evidence 与 download / popup / action output 同时存在
   - 期望：提取逻辑不能抢走动作语义

5. **frame 与 tab 正交性**
   - 上下文对齐只改变 scope 选择
   - 期望：不改变 extraction-vs-runtime 的分类结果

### Harness 方向

未来每个相关回归都应能用一句话解释清楚：

- trace 当时到底拥有什么证据
- compiler 为什么选了确定性 replay 或 runtime AI
- 还缺哪类更强证据才会改变当前决策

这才是 Agent 时代真正有价值的 harness：不是继续堆代码，而是让分类结果可解释、可追溯、可恢复。

## 回滚路径

如果第一阶段修复引入非预期影响，安全回滚方式应为：

- 关闭对应的新确定性分支
- 让相关文本提取回退到 runtime AI

这是可接受的，因为危险的失败模式不是“暂时保守”，而是“把 observed value 或 unstable locator 硬编码进最终脚本”。

换句话说：

- runtime AI fallback 是安全降级态
- brittle hardcoded replay logic 不是

## 文档后续更新

当后续真正修复落地后，应补充更新：

- `docs/features/F001-rpa-trace-source-convergence.md`
- `docs/features/F011-rpa-region-scoped-snapshot.md`
- 对应 `EV-001` / `EV-011` evidence

文档层面应明确记录两条决策：

- 上下文证据不等于 side-effect 证据
- 确定性文本提取必须经过共享 replay-safety gate

## 决策结论

如果当前分支尚未合并，这个问题应在合并前修复。
但修复方式应是**窄边界修复**，而不是泛化 compiler 重写。

完整目标方案包括：

- 将上下文对齐与 side-effect 分类彻底分层
- 将确定性文本提取资格统一成共享 gate
- 显式保持动作优先级
- 用 harness 式分类测试锁住边界

真正第一步实现时，只落其中最小必要子集，以最小扰动恢复正确边界。
