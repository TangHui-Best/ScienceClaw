# API Monitor MCP 重新生成链路与 Endpoint YAML 设计

## 背景

API Monitor MCP 现在有两类相关问题：

1. 手动点击“重新生成工具”时，后端走 `regenerate_tool()` 的独立轻量链路，没有复用实时生成的 `ApiToolGenerationCandidate` 主链路。
2. 生成 OpenAPI 2.0 YAML 时，模型会把捕获到的 endpoint 拆成 `basePath` 和 `paths`，但这类拆分在深路径 API 上不稳定，导致 `basePath + path` 与真实 endpoint 不一致。

本设计只处理 API Monitor MCP 工具生成和重新生成链路，不改变 MCP 发布、鉴权、运行时请求执行模型。

## 目标

- 重新生成工具复用实时工具生成主链路，避免两套逻辑长期分叉。
- 重新生成时保留原工具卡片身份，不产生重复工具。
- OpenAPI YAML 中不再输出 `basePath`，`paths` 的唯一 key 直接是捕获到的完整 endpoint path。
- 移除“必须校验 `basePath + path == endpoint`”这个需求，用更简单的“path 就是 endpoint”规则规避模型拆分错误。

## 非目标

- 不重构 API Monitor MCP runtime 的请求执行模型。
- 不改变用户发布 MCP 时配置的 `base_url` / origin 逻辑。
- 不引入 OpenAPI 3.x。
- 不把历史数据库里的 YAML 批量迁移；只保证新生成和重新生成走新规则。

## 当前问题分析

### 重新生成缩水链路

实时生成主链路是：

`CapturedApiCall -> ApiToolGenerationCandidate -> _generate_tool_for_candidate() -> ApiToolDefinition`

这条链路会使用 candidate 上保存的 DOM context、页面 URL、操作上下文、置信度结果、意图过滤结果、generation status、stale/followup 状态和去重逻辑。

当前 `regenerate_tool()` 直接执行：

`tool.source_calls -> generate_tool_definition() -> parse_api_monitor_tool_yaml() -> 更新 tool`

这条链路缺少：

- candidate 状态和事件通知；
- `capture_dom_context`；
- `step_metadata` 生成的 observed context；
- 与实时生成一致的错误处理；
- `generation_candidate_id` 绑定；
- stale/followup 与 dedup 行为；
- selection/source/confidence 等字段的一致刷新策略。

结果是“重新生成”看起来是同一个功能，实际走的是一条缩水链路。

### basePath/path 拆分不稳定

当前 prompt 要求模型从 URL 中提取 `host`、`basePath` 和 `paths`，并要求 `paths` 相对 `basePath`。这对 `/v1/users` 这类短路径可行，但对业务系统中的深路径接口容易失败。

最新代码已经能拒绝 “path 重复 basePath” 的 YAML，但它仍然没有解决核心问题：模型仍要判断哪里是 basePath，哪里是 path。这个判断没有可靠事实来源，也没有必要存在。

## 方案

### 1. 统一重新生成入口

`regenerate_tool(session_id, tool_id, model_config)` 改为 candidate-first：

1. 查找目标 `ApiToolDefinition`。
2. 优先按 `tool.generation_candidate_id` 查找 candidate。
3. 如果旧工具没有 candidate，则用 `tool.source_calls` 对应的 captured calls 补建 candidate：
   - dedup key 使用现有 `_candidate_dedup_key()` / `dedup_key()` 规则；
   - `method` 和 `url_pattern` 优先沿用 tool；
   - `sample_call_ids` 来自 `tool.source_calls` 中最多 5 个仍存在的 call；
   - `capture_dom_context` 必须来自已有生成上下文，不能在重新生成时从当前页面补采；
   - 补建后把 `tool.generation_candidate_id` 绑定到 candidate。
4. 调用 `_generate_tool_for_candidate()` 重新生成。
5. 重新生成必须覆盖原工具，而不是追加新工具。

为支持第 5 点，主链路需要能在已有 `tool_id` 时定向更新该工具。可以采用以下最小扩展：

- candidate 增加或复用 `tool_id` 字段作为目标工具 id；
- `_generate_tool_for_candidate()` 查找 existing tool 时优先用 `candidate.tool_id`，其次用 `generation_candidate_id`；
- 如果找到 existing tool，则更新 YAML、name、description、method、url_pattern、source_calls、validation、confidence 等字段；
- 保留原 `tool.id`、`selected` 和用户可见卡片身份。

重新生成属于用户显式操作，应跳过置信度/意图过滤，避免一个已采用工具因为当前过滤规则变化而无法重新生成。置信度可以重新计算并写回展示字段，但不阻断生成。

重新生成不做 DOM 补采。DOM context 是捕获 API 时的事实上下文，如果重新生成时无法从 candidate 或历史生成上下文中找到 DOM，应返回明确错误，提示该工具缺失生成上下文。这比从当前页面临时扫描更可靠，因为当前页面可能已经与原 API 触发场景不一致。

### 2. YAML 生成不携带 basePath

LLM prompt 调整为：

- 不输出 `basePath` 字段；
- `paths` 只能包含一个 key；
- 这个 key 必须是捕获 endpoint 的完整 path，不含 scheme、host、query；
- 不允许把 endpoint 拆到 `basePath`；
- 示例统一使用：

```yaml
swagger: "2.0"
host: api.example.com
paths:
  /v1/users/{user_id}:
    get:
      operationId: get_user
```

`generate_tool_definition()` 中传给模型的 host 信息也要停止给出启发式 basePath，避免继续暗示模型拆分路径。推荐把 `Host: example.com` 和 `Endpoint path: /完整/path` 明确分开。

### 3. OpenAPI 解析规则

解析层继续支持 OpenAPI 2.0，并把 `contract.url` 设为 endpoint path。

新规则：

- 当 `basePath` 缺失时，`contract.url = path_url`。
- 新生成 YAML 不应包含 `basePath`。
- 为兼容历史 YAML，解析器可以继续接受非空 `basePath` 并按 OpenAPI 规则组合，但新 prompt 不再生成这种形式。
- 移除或放宽“path must be relative to basePath”的强拒绝校验，因为新规则不再依赖 basePath/path 拆分。

这样 runtime 不需要改变：发布后工具文档里的 `url` 就是完整 endpoint path，调用时仍由 `base_url + doc.url` 拼出最终 URL。

## 数据流

### 重新生成

```text
POST /api-monitor/session/{session_id}/tools/{tool_id}/regenerate
  -> manager.regenerate_tool()
  -> 查找/补建 ApiToolGenerationCandidate（必须带历史 DOM context）
  -> candidate.tool_id = tool_id
  -> _generate_tool_for_candidate(skip_filter=True)
  -> 更新原 ApiToolDefinition
  -> 返回更新后的 tool
```

### 新 YAML endpoint 表达

```text
Captured URL: https://api.example.com/isales/ssdmdoc/services/api/query
Prompt endpoint path: /isales/ssdmdoc/services/api/query
Generated YAML:
  paths:
    /isales/ssdmdoc/services/api/query:
Contract url:
  /isales/ssdmdoc/services/api/query
Runtime final URL:
  server base_url + contract url
```

## 错误处理

- 找不到 session 或 tool：保持现有 `ValueError`，route 转为 404。
- tool 没有可用 source calls：返回明确错误，不生成空工具。
- 重新生成时找不到历史 DOM context：返回明确错误，不从当前页面补采。
- LLM 失败或限流：复用 `_generate_tool_for_candidate()` 的 failed/rate_limited 状态。
- YAML 无效：仍保留工具并设置 `validation_status=invalid`、`validation_errors`，便于用户编辑或再次生成。

## 测试计划

### 单元测试

- `regenerate_tool()` 使用已有 `generation_candidate_id` 时，调用主链路并更新原 tool。
- 旧工具没有 `generation_candidate_id` 但存在历史 DOM context 时，能从 `source_calls` 补建 candidate，并绑定回原 tool。
- 重新生成时缺失历史 DOM context，返回明确错误，不调用当前页面 DOM 扫描。
- 重新生成不新增重复 tool，原 `tool.id` 不变。
- 重新生成显式跳过 confidence/intent 阻断，但刷新 confidence 展示字段。
- `_generate_tool_for_candidate()` 优先按 `candidate.tool_id` 更新目标工具。
- `generate_tool_definition()` prompt 不再包含启发式 `basePath: /前两段` 提示。
- OpenAPI YAML 省略 `basePath` 且使用完整 endpoint path 时，`contract.url` 等于 endpoint path。
- 调整现有 `path must be relative to basePath` 测试，避免它与新规则冲突。

### 集成测试

- 发布含新 YAML 的 API Monitor MCP 后，工具文档中的 `url` 是完整 endpoint path。
- MCP runtime 调用工具时，`base_url + url` 拼出正确最终请求 URL。

## 实施边界

建议按小步提交：

1. 先调整 prompt 和 OpenAPI parser 测试，确定 “path 就是 endpoint” 的 contract。
2. 再改 regenerate candidate-first 链路。
3. 最后补 runtime/publish 回归测试，确认最终 URL 不回退。
