# API Monitor YAML 校验 + 重试 + Header 透传

## 背景

当前 API Monitor 存在三个问题：

1. **YAML 不校验** — LLM 生成的 YAML 可能格式错误或缺少必填字段，但前端不显示校验状态，用户直到发布 MCP 时才发现问题
2. **无重试按钮** — YAML 无效的工具只能手动编辑或删除，无法重新调用 LLM 重新生成
3. **Header 不透传** — 外部 agent 通过 MCP gateway 调用时，其请求头被完全丢弃，只有 `_auth` 中的认证信息被传递。调用方希望在目标 API 请求和 token flow 中保留原始请求头

校验逻辑已存在于 `parse_api_monitor_tool_yaml()`，但只在发布 MCP 时调用。

## 设计

### 1. Header 透传（方案 A：caller_profile 注入）

**原理**：将外部 agent 的非协议层 headers 注入 `ApiMonitorRuntimeProfile`，让 target request 和 token flow producer 自动继承。

**排除的协议层 headers**：`host`、`content-length`、`connection`、`content-type`、`transfer-encoding`

**注入顺序**：
1. 先设置透传 headers（来自外部 agent 请求）
2. 再由 `_auth` 认证信息覆盖/补充（如 Authorization）
3. 最后由 `header_mapping` 渲染覆盖

这保证认证 header 不会被透传值干扰，同时 token flow producer 使用 `profile.headers` 时自动继承所有 headers。

**改动文件**：

- `backend/route/api_monitor_mcp_gateway.py` — 在 `tools/call` 分支提取非协议 headers，传入 `extract_caller_auth_profile`
- `backend/rpa/api_monitor_external_access.py` — `extract_caller_auth_profile` 增加 `passthrough_headers` 参数，先写入 profile 再处理 `_auth`

### 2. YAML 校验

**模型扩展** — `backend/rpa/api_monitor/models.py` `ApiToolDefinition`：

```
validation_status: str = "valid"    # "valid" | "invalid"
validation_errors: List[str] = []
```

**生成时校验** — `backend/rpa/api_monitor/manager.py` `_generate_tools_from_calls`：

LLM 生成 YAML 后，调用 `parse_api_monitor_tool_yaml(yaml_def)` 校验，将结果写入新字段。校验失败的 tool 仍然保留（不删除），但前端标记为 invalid。

**编辑时校验** — `backend/route/api_monitor.py` `PUT /session/{session_id}/tools/{tool_id}`：

更新 `yaml_definition` 后调用 `parse_api_monitor_tool_yaml()` 重新校验，返回 `validation_status` 和 `validation_errors`。

### 3. 重试按钮

**后端** — 新增 `POST /session/{session_id}/tools/{tool_id}/regenerate`：

- 从 tool 的 `source_calls` 找到原始 captured calls（通过 `session.captured_calls` 匹配 id）
- 重新调用 `generate_tool_definition()` 生成新 YAML
- 校验新 YAML，更新 tool 的 `yaml_definition`、`validation_status`、`validation_errors`、`name`、`description`
- 返回更新后的 tool

**Manager 方法** — `backend/rpa/api_monitor/manager.py` 新增 `regenerate_tool(session_id, tool_id, model_config)`。

**前端**：

- 工具卡片标题栏显示校验 badge（绿色 `valid` / 红色 `invalid`）
- 展开详情时，如果 `validation_status === "invalid"`，显示 `validation_errors` 列表
- 在"删除"按钮旁增加"重新生成"按钮（invalid 状态时显示）
- 新增 `regenerateTool(sessionId, toolId)` API 调用

### 4. 文件清单

| 文件 | 改动内容 |
|------|---------|
| `backend/rpa/api_monitor/models.py` | `ApiToolDefinition` 新增 `validation_status`、`validation_errors` 字段 |
| `backend/rpa/api_monitor/manager.py` | `_generate_tools_from_calls` 生成后校验；新增 `regenerate_tool()` |
| `backend/route/api_monitor.py` | `update_tool` 编辑后校验；新增 `regenerate_tool` 端点 |
| `backend/route/api_monitor_mcp_gateway.py` | 提取透传 headers 传入 profile |
| `backend/rpa/api_monitor_external_access.py` | `extract_caller_auth_profile` 支持 `passthrough_headers` |
| `frontend/src/api/apiMonitor.ts` | 新增 `regenerateTool()` |
| `frontend/src/pages/rpa/ApiMonitorPage.vue` | 校验 badge + 错误展示 + 重新生成按钮 |
