# API Monitor MCP — 批量意图裁剪设计

日期：2026-05-20

## 1. 背景

当前 API Monitor MCP 的接口筛选分两步：

1. 先用规则置信度评分过滤低质量候选。
2. 对高置信候选逐个调用 LLM，判断该接口是否与用户意图相关。

这个设计在节省工具生成 token 上已经有效，但“逐个二分”的意图判断对误留问题不够强。特别是以下场景：

- 页面初始化接口：用户信息、菜单、配置、权限、字典等接口经常是高置信 JSON 请求，但不是用户想生成的业务工具。
- 同页相邻业务接口：例如用户想要订单接口，但订单页同时触发客户、库存、物流等接口。单独看它们都像业务接口，LLM 容易判成相关。
- 少量行为副产物：点击或搜索时触发的预加载、推荐、通知、轮询等接口偶尔被保留。

根因是当前 `filter_by_intent(calls) -> relevant bool` 只看到单个候选，无法在同一批候选之间比较“谁才是本次意图的主线接口”。它也只有相关/不相关两个结果，不能表达“辅助但不应默认发布”“同页但偏题”“页面初始化”等中间状态。

## 2. 目标

本设计要优先降低“无关接口误留”，避免噪声接口进入 MCP 工具集：

1. 将意图筛选从逐个二分升级为批量候选裁剪。
2. 让 LLM 在同一批高置信候选之间做相对判断，而不是孤立判断。
3. 明确区分核心接口、辅助接口、相邻业务、页面初始化和噪声接口。
4. 只有核心接口自动进入正式工具集。
5. 辅助接口可以生成候补工具，但默认不发布。
6. 被过滤接口保留解释和强制生成入口，方便人工纠偏。
7. 不引入完整“意图槽位规划”方案，避免系统复杂度过高。

## 3. 非目标

- 不改变规则置信度评分的基础分值体系。
- 不重写 API 捕获、分组、去重和工具发布流程。
- 不做完整的用户意图拆槽位、工具能力规划或多轮推理系统。
- 不要求前端新增复杂向导；只增强候选状态展示。
- 不以经验库、站点模板或关键词规则替代 LLM 的语义判断。

## 4. 当前实现摘要

相关文件：

- `RpaClaw/backend/rpa/api_monitor/confidence.py`
- `RpaClaw/backend/rpa/api_monitor/intent_filter.py`
- `RpaClaw/backend/rpa/api_monitor/manager.py`
- `RpaClaw/backend/rpa/api_monitor/models.py`
- `RpaClaw/backend/route/api_monitor.py`
- `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue`

当前流程：

```text
API 调用捕获
  -> 分组去重
  -> score_api_candidate
      <80: confidence_rejected，不生成工具
      >=80 且无意图: 生成工具
      >=80 且有意图: filter_by_intent 单接口二分
          relevant=true: 生成工具
          relevant=false: intent_filtered
```

当前 `intent_filter.py` 的输出只有：

```python
@dataclass(frozen=True)
class IntentFilterResult:
    relevant: bool
    reason: str
```

这个接口无法表达候选的相对优先级，也无法稳定分离页面初始化、相邻业务和辅助接口。

前端当前已有“候补”分组，但它实际展示的是 `confidence_rejected` 和 `intent_filtered` 这类未生成工具的候选。后端 `ApiToolDefinition` 尚未提供 `is_reserve` 字段，因此还没有“已生成但默认不发布”的候补工具语义。本设计会把两者区分开：

- 过滤候选：没有生成工具定义，只保留解释和强制生成入口。
- 候补工具：已经生成工具定义，但 `is_reserve=True`、`selected=False`，默认不发布；前端并入“不采用”分组，用“候补”标签标识。

当前前端分组顺序是“采用 -> 候补/未生成候选 -> 不采用”。本设计需要调整为“采用 -> 不采用 -> 未生成/过滤候选”，避免已经生成但暂不采用的工具被压到未生成候选下方。

## 5. 设计概览

新增“批量意图裁剪”阶段，替代高置信候选的逐个二分。

```text
API 调用捕获
  -> 分组去重
  -> 第一轮规则置信度评分
      <80: confidence_rejected
      >=80: 进入高置信候选包
  -> 第二轮批量意图裁剪
      primary: 自动生成正式工具，默认 selected=true
      supporting: 自动生成候补工具，默认 selected=false
      adjacent: intent_filtered，不生成
      bootstrap: intent_filtered，不生成
      noise: intent_filtered，不生成
      uncertain: intent_review，不自动生成，保留人工入口
```

批量裁剪的核心变化是：LLM 一次看到同批高置信候选，并按用户意图做相对分类。这样页面初始化接口即使自身很像业务 API，也会因为不直接服务用户意图而归为 `bootstrap`；同页相邻业务接口会归为 `adjacent`；真正完成用户目标的接口归为 `primary`。

## 6. 意图裁剪分类

新增候选分组枚举 `IntentGroup`：

```python
IntentGroup = Literal[
    "primary",
    "supporting",
    "adjacent",
    "bootstrap",
    "noise",
    "uncertain",
]
```

### 6.1 primary

直接服务用户意图的核心接口。

行为：

- 自动生成工具定义。
- 工具默认 `selected=True`。
- 工具不是候补。

示例：

- 用户意图“查询订单列表”，`POST /api/orders/search` 返回订单列表。
- 用户意图“查看订单详情”，`GET /api/orders/{id}` 返回订单详情。

### 6.2 supporting

可能辅助核心接口，但不是用户明确要求的能力。

行为：

- 自动生成候补工具。
- 工具默认 `selected=False`。
- 工具新增 `is_reserve=True`。
- 发布 MCP 时默认不包含，用户可手动采用。

示例：

- 用户意图“查询订单”，接口 `GET /api/order/status-options` 返回订单状态枚举。
- 用户意图“导出报表”，接口 `GET /api/report/template-options` 返回可选模板。

### 6.3 adjacent

同页面或同业务域，但不服务本次用户意图。

行为：

- 候选状态设为 `intent_filtered`。
- 不生成工具定义。
- 保留过滤理由和强制生成入口。

示例：

- 用户意图“订单列表”，订单页触发 `GET /api/customers/list`。
- 用户意图“客户管理”，页面同时触发 `GET /api/products/list`。

### 6.4 bootstrap

页面初始化、身份、菜单、权限、配置、字典等基础数据接口。

行为：

- 候选状态设为 `intent_filtered`。
- 不生成工具定义。
- 保留过滤理由和强制生成入口。

示例：

- `GET /api/user/profile`
- `GET /api/menu/tree`
- `GET /api/config`
- `GET /api/permissions`
- `GET /api/dict/order-status`

### 6.5 noise

埋点、遥测、轮询、推荐、预加载、通知、心跳等副产物。

行为：

- 候选状态设为 `intent_filtered`。
- 不生成工具定义。
- 保留过滤理由和强制生成入口。

示例：

- `POST /api/track`
- `GET /api/notifications/poll`
- `GET /api/recommendations`
- `POST /api/telemetry`

### 6.6 uncertain

LLM 无法稳定判断，或证据不足。

行为：

- 候选状态设为新增 `intent_review`。
- 不自动生成工具。
- 保留原因、分类证据和强制生成入口。

说明：

当前单接口二分 prompt 要求“不确定时判相关”，这会提高误留。新目标是降低误留，因此不确定时不自动晋级，而是进入人工复核状态。

## 7. 后端模型变更

### 7.1 ApiToolDefinition

新增字段：

```python
is_reserve: bool = False
intent_group: Optional[str] = None
intent_reason: Optional[str] = None
intent_score: Optional[int] = None
```

字段含义：

- `is_reserve`：候补工具标记。发布 MCP 时默认不包含。
- `intent_group`：生成该工具时的意图裁剪分类。
- `intent_reason`：LLM 给出的简短中文理由。
- `intent_score`：0 到 100 的相关性分数，仅用于排序和解释，不参与规则置信度计算。

### 7.2 ApiToolGenerationCandidate

新增字段：

```python
intent_group: Optional[str] = None
intent_reason: Optional[str] = None
intent_score: Optional[int] = None
intent_rank: Optional[int] = None
intent_batch_id: Optional[str] = None
```

`GenerationStatus` 新增：

```python
"intent_review"
```

字段含义：

- `intent_group`：批量裁剪分类。
- `intent_reason`：裁剪理由。
- `intent_score`：0 到 100 的意图相关性分数。
- `intent_rank`：同批候选内的排序，`primary` 组从 1 开始。
- `intent_batch_id`：同一轮批量裁剪的批次 ID，便于调试和前端分组。

## 8. 批量裁剪模块

新增模块：

```text
RpaClaw/backend/rpa/api_monitor/intent_pruner.py
```

公开接口：

```python
@dataclass(frozen=True)
class IntentPruneItem:
    candidate_key: str
    intent_group: str
    intent_score: int
    intent_rank: int | None
    reason: str

@dataclass(frozen=True)
class IntentPruneResult:
    batch_id: str
    items: list[IntentPruneItem]

async def prune_candidates_by_intent(
    candidates: list[IntentPruneCandidate],
    intent: str,
    *,
    page_context: str = "",
    model_config: dict | None = None,
) -> IntentPruneResult:
    ...
```

`IntentPruneCandidate` 是传给 LLM 的轻量结构，不直接暴露 Pydantic 模型：

```python
@dataclass(frozen=True)
class IntentPruneCandidate:
    candidate_key: str
    method: str
    url_pattern: str
    confidence_score: int
    confidence_reasons: list[str]
    request_summary: str
    response_summary: str
    step_summary: str
    page_url: str
    title: str
```

### 8.1 LLM 输入

每个候选最多包含：

- 候选 ID 或 dedup key。
- method 和 URL pattern。
- 规则置信度分数和理由。
- 请求体摘要，最多 500 字符。
- 响应体摘要，最多 800 字符。
- 页面 URL 和标题。
- 触发操作摘要，最多 3 条。

不把完整响应体、完整 DOM 或完整 headers 送入裁剪 prompt，避免 token 过大。

### 8.2 LLM 输出

要求只返回 JSON：

```json
{
  "items": [
    {
      "candidate_key": "POST /api/orders/search",
      "group": "primary",
      "score": 95,
      "rank": 1,
      "reason": "该接口返回订单列表并直接服务查询订单的目标。"
    }
  ]
}
```

输出约束：

- `group` 必须是 `primary/supporting/adjacent/bootstrap/noise/uncertain` 之一。
- `score` 必须是 0 到 100。
- `rank` 只对 `primary` 必填。
- 每个输入候选必须有且只有一个输出项。
- 不确定时使用 `uncertain`，不要为了保守而归为 `primary`。

### 8.3 Prompt 策略

系统 prompt 的关键规则：

- 你是 API Monitor 的候选裁剪器，不是工具生成器。
- 目标是减少无关工具误留。
- 只把直接服务用户意图的接口标为 `primary`。
- 页面初始化接口必须优先归为 `bootstrap`，即使它们是 JSON 且由页面脚本触发。
- 同页但不服务本次意图的业务接口归为 `adjacent`。
- 辅助数据接口归为 `supporting`，但不能替代核心接口。
- 埋点、推荐、预加载、轮询、心跳归为 `noise`。
- 不确定时归为 `uncertain`，不要自动晋级。

## 9. Manager 流程变更

### 9.1 批量分析路径

当前 `_generate_tools_from_calls` 对每个 group 独立执行规则评分和意图过滤。

改为：

1. 按 dedup key 分组。
2. 对每组执行 `score_api_candidate`。
3. `<80` 的候选立即创建 `confidence_rejected`。
4. `>=80` 的候选先创建或保留为高置信候选包。
5. 如果无用户意图，保持旧逻辑：高置信候选直接生成正式工具。
6. 如果有用户意图，调用 `prune_candidates_by_intent`。
7. 根据裁剪结果执行：
   - `primary`：生成工具，`selected=True`，`is_reserve=False`。
   - `supporting`：生成工具，`selected=False`，`is_reserve=True`。
   - `adjacent/bootstrap/noise`：候选 `intent_filtered`，不生成工具。
   - `uncertain`：候选 `intent_review`，不生成工具。

### 9.2 实时录制路径

实时录制中 `_process_single_candidate` 可能一次只处理一个候选。直接对单候选批量裁剪会退化成当前问题。

新增短窗口聚合：

- 对 `>=80` 且有意图的候选，不立即生成。
- 放入 session 级 pending prune buffer。
- debounce 2 到 4 秒，或累计到 8 个候选时触发批量裁剪。
- 批量裁剪后按分类生成或过滤。

建议默认参数：

```python
INTENT_PRUNE_DEBOUNCE_SECONDS = 3.0
INTENT_PRUNE_MAX_BATCH_SIZE = 8
INTENT_PRUNE_MAX_WAIT_SECONDS = 8.0
```

如果录制停止时还有 pending prune buffer，停止前 flush 一次，避免候选长期停留。

### 9.3 强制生成

现有 `force_generate_candidate(..., skip_filter=True)` 保留。

变更：

- `confidence_rejected`、`intent_filtered`、`intent_review` 都允许强制生成。
- 强制生成的工具设置 `is_reserve=True`、`selected=False`，除非用户后续手动采用。
- 强制生成不重新执行批量裁剪。

### 9.4 Fallback

批量裁剪失败时：

- 不应悄悄全部生成，避免误留回潮。
- 候选状态设为 `intent_review`。
- 记录 `intent_reason="意图裁剪失败，需人工确认"`。
- 前端提供强制生成入口。

没有用户意图时：

- 跳过批量裁剪。
- 保持高置信候选直接生成的现有行为。

## 10. 前端展示

### 10.1 工具分组

工具和候选展示为三个连续分区。当前前端“候补”分组展示的是过滤候选，本设计实施后需要迁移为“未生成/过滤候选”分区；已生成的候补工具并入“不采用”分区，通过标签区分来源：

- 采用：已生成工具，`selected=True` 且 `is_reserve=False`
- 不采用：已生成工具，`selected=False`，包含普通未采用工具和 `is_reserve=True` 的候补工具
- 未生成/过滤候选：`confidence_rejected`、`intent_filtered`、`intent_review` 等未生成工具的候选

发布 MCP 时默认只发布正式工具。

顺序必须是：

```text
采用
不采用
未生成/过滤候选
```

`is_reserve=True` 的工具在“不采用”分区内显示“候补”标签。过滤候选继续保留在候选列表或候选子分组中，不混同为已生成工具。这个顺序也适用于当前还没有 `is_reserve` 的过渡阶段：应先展示“采用”，再展示“不采用”，最后展示未生成的过滤候选。

### 10.2 候选状态

候选列表新增展示：

- `intent_filtered + bootstrap`：页面初始化
- `intent_filtered + adjacent`：相邻业务
- `intent_filtered + noise`：噪声接口
- `intent_review`：需确认
- `supporting` 已生成工具：在“不采用”分区显示“候补”标签

每个状态显示 `intent_reason`。

### 10.3 i18n

新增翻译键：

- `apiMonitor.intentGroupPrimary`
- `apiMonitor.intentGroupSupporting`
- `apiMonitor.intentGroupAdjacent`
- `apiMonitor.intentGroupBootstrap`
- `apiMonitor.intentGroupNoise`
- `apiMonitor.intentGroupUncertain`
- `apiMonitor.intentReview`
- `apiMonitor.reserveToolBadge`

## 11. 发布 MCP 行为

发布时过滤规则：

```python
publishable_tools = [
    tool for tool in session.tool_definitions
    if tool.selected and not tool.is_reserve
]
```

用户手动采用候补工具时：

- `selected=True`
- `is_reserve=False`
- 保留 `intent_group="supporting"` 作为来源说明

用户手动取消正式工具时：

- `selected=False`
- `is_reserve=False`

## 12. 可观测性

新增 SSE 事件：

```text
api_candidate_intent_pruned
```

payload 包含：

```json
{
  "batch_id": "...",
  "candidate_id": "...",
  "intent_group": "bootstrap",
  "intent_score": 20,
  "intent_rank": null,
  "intent_reason": "该接口加载菜单配置，不直接服务订单查询。"
}
```

日志要求：

- 每个批量裁剪记录 batch_id、候选数量、各 group 数量。
- LLM JSON 解析失败记录原始响应前 500 字符。
- Fallback 到 `intent_review` 时记录 warning。

## 13. 测试计划

### 13.1 单元测试

新增测试文件：

```text
RpaClaw/backend/tests/test_api_monitor_intent_pruner.py
```

覆盖：

- 能解析合法 LLM JSON。
- markdown fence 包裹的 JSON 能解析。
- 缺失候选输出时补为 `uncertain`。
- 非法 group 补为 `uncertain`。
- score 超界时 clamp 到 0 到 100。
- LLM 解析失败时所有候选进入 `uncertain`。

### 13.2 Manager 流程测试

扩展：

```text
RpaClaw/backend/tests/test_api_monitor_realtime_generation.py
```

覆盖：

- 批量分析中 `primary` 自动生成正式工具。
- `supporting` 自动生成候补工具，默认不 selected。
- `bootstrap/adjacent/noise` 不生成工具，候选为 `intent_filtered`。
- `uncertain` 不生成工具，候选为 `intent_review`。
- 批量裁剪失败不会全部生成，而是进入 `intent_review`。
- 强制生成 `intent_review` 候选时跳过裁剪并生成候补工具。

### 13.3 回归测试

继续运行现有测试：

```bash
cd RpaClaw/backend
uv run pytest \
  tests/test_api_monitor_confidence.py \
  tests/test_api_monitor_realtime_generation.py \
  tests/test_api_monitor_publish_mcp.py
```

### 13.4 场景测试

构造 A/B/C 三类样例：

1. A 类：订单意图 + profile/menu/config/dict + order search。预期只有 order search 为 `primary`，dict 最多为 `supporting`，profile/menu/config 为 `bootstrap`。
2. B 类：订单意图 + order/customer/inventory/logistics。预期 order 为 `primary`，其他为 `adjacent` 或 `supporting`。
3. C 类：搜索意图 + search API + telemetry/recommendations/poll。预期 search 为 `primary`，其余为 `noise`。

## 14. 兼容性与迁移

- 新字段均提供默认值，旧 session 数据可正常加载。
- 没有用户意图时保持现有行为。
- `filter_by_intent` 可暂时保留，作为旧测试或极端 fallback 的兼容函数，但主流程不再调用它。
- 前端如果暂未识别新字段，候选仍可通过原有 status 展示，不影响基础操作。

## 15. 风险与缓解

### 15.1 误杀增加

新策略为了降低误留，会比旧策略更严格。

缓解：

- `supporting` 自动生成候补工具，不直接丢失。
- `intent_review` 明确保留人工入口。
- 所有过滤候选保留强制生成。

### 15.2 实时录制延迟

debounce 会让实时工具生成延迟 2 到 4 秒。

缓解：

- 只在有用户意图且候选高置信时启用。
- 达到 batch size 立即 flush。
- 录制停止时立即 flush。

### 15.3 LLM 输出不稳定

缓解：

- 强 JSON schema 约束。
- 解析失败进入 `intent_review`，不自动生成。
- 补齐缺失候选，避免状态悬空。

### 15.4 Token 增加

批量裁剪会一次发送多个候选，但它替代了逐个意图判断，且可以减少后续工具生成调用。

缓解：

- 摘要输入严格截断。
- 单批最多 8 个候选。
- 只对规则高置信候选执行。

## 16. 实施顺序

1. 扩展模型字段和状态枚举。
2. 新增 `intent_pruner.py` 和单元测试。
3. 改造批量分析路径，接入批量裁剪。
4. 改造实时录制路径，增加 debounce buffer 和 flush。
5. 调整工具生成逻辑，支持 `is_reserve`。
6. 调整 MCP 发布过滤逻辑。
7. 增强前端候选和候补工具展示。
8. 补充回归测试和 A/B/C 场景测试。
