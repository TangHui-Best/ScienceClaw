# API Monitor YAML 校验 + 重试 + Header 透传 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 API Monitor 添加 YAML 校验状态展示、失败工具重试、以及外部 MCP 调用 header 透传

**Architecture:** 三个独立改动：(1) 模型层新增校验字段，生成/编辑时自动校验；(2) 新增 regenerate 端点重新调用 LLM；(3) MCP gateway 将外部 agent headers 注入 caller_profile 透传到目标 API

**Tech Stack:** Python/FastAPI (backend), Vue 3/TypeScript (frontend), httpx (HTTP client)

---

## Task 1: 模型新增校验字段

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/models.py:54-75`

- [ ] **Step 1: 在 `ApiToolDefinition` 中新增 `validation_status` 和 `validation_errors` 字段**

在 `source_evidence` 字段之后（~L72）添加：

```python
    validation_status: str = "valid"  # "valid" | "invalid"
    validation_errors: List[str] = Field(default_factory=list)
```

- [ ] **Step 2: 验证模型导入无误**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && python -c "from backend.rpa.api_monitor.models import ApiToolDefinition; t = ApiToolDefinition(session_id='s', name='n', description='d', method='GET', url_pattern='/test', yaml_definition='test'); print(t.validation_status, t.validation_errors)"`

Expected: `valid []`

- [ ] **Step 3: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/models.py
git commit -m "feat: add validation_status and validation_errors to ApiToolDefinition"
```

---

## Task 2: 生成时校验 YAML

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py:1766-1793`

- [ ] **Step 1: 在 `_generate_tools_from_calls` 中，LLM 生成 YAML 后添加校验**

在 `name, description = self._parse_yaml_metadata(yaml_def)` 之后（~L1777），添加校验逻辑：

```python
                from backend.rpa.api_monitor_mcp_contract import parse_api_monitor_tool_yaml

                name, description = self._parse_yaml_metadata(yaml_def)
                contract = parse_api_monitor_tool_yaml(yaml_def)
                validation_status = "valid" if contract.valid else "invalid"
                validation_errors = contract.validation_errors if contract.validation_errors else []
```

然后在 `ApiToolDefinition(...)` 构造中添加这两个字段（~L1779）：

```python
                tool = ApiToolDefinition(
                    session_id=session_id,
                    name=name,
                    description=description,
                    method=method,
                    url_pattern=url_pattern,
                    yaml_definition=yaml_def,
                    source_calls=[c.id for c in samples],
                    source=source,
                    confidence=confidence_result.confidence,
                    score=confidence_result.score,
                    selected=True,
                    confidence_reasons=confidence_result.reasons,
                    source_evidence=confidence_result.evidence_summary,
                    validation_status=validation_status,
                    validation_errors=validation_errors,
                )
```

- [ ] **Step 2: 验证导入无误**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && python -c "from backend.rpa.api_monitor.manager import ApiMonitorManager; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py
git commit -m "feat: validate YAML after LLM generation in _generate_tools_from_calls"
```

---

## Task 3: 编辑工具时校验 YAML

**Files:**
- Modify: `RpaClaw/backend/route/api_monitor.py:460-477`

- [ ] **Step 1: 在 `update_tool` 端点中添加 YAML 校验**

替换整个 `update_tool` 函数：

```python
@router.put("/session/{session_id}/tools/{tool_id}")
async def update_tool(
    session_id: str,
    tool_id: str,
    request: UpdateToolRequest,
    current_user: User = Depends(get_current_user),
):
    session = api_monitor_manager.get_session(session_id)
    _verify_session_owner(session, current_user)

    for tool in session.tool_definitions:
        if tool.id == tool_id:
            tool.yaml_definition = request.yaml_definition
            from datetime import datetime
            tool.updated_at = datetime.now()

            from backend.rpa.api_monitor_mcp_contract import parse_api_monitor_tool_yaml
            contract = parse_api_monitor_tool_yaml(request.yaml_definition)
            tool.validation_status = "valid" if contract.valid else "invalid"
            tool.validation_errors = contract.validation_errors if contract.validation_errors else []

            return {"status": "success", "tool": tool.model_dump()}

    raise HTTPException(status_code=404, detail="Tool not found")
```

- [ ] **Step 2: Commit**

```bash
git add RpaClaw/backend/route/api_monitor.py
git commit -m "feat: validate YAML on tool update endpoint"
```

---

## Task 4: 新增 regenerate 端点

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py` — 新增 `regenerate_tool()` 方法
- Modify: `RpaClaw/backend/route/api_monitor.py` — 新增 `POST /session/{session_id}/tools/{tool_id}/regenerate`

- [ ] **Step 1: 在 manager.py 中新增 `regenerate_tool` 方法**

在 `retry_generation_candidate` 方法之前（~L2515）添加：

```python
    async def regenerate_tool(
        self,
        session_id: str,
        tool_id: str,
        model_config: dict | None = None,
    ) -> ApiToolDefinition:
        """Regenerate a tool's YAML from its source captured calls."""
        from backend.rpa.api_monitor.llm_analyzer import generate_tool_definition
        from backend.rpa.api_monitor_mcp_contract import parse_api_monitor_tool_yaml

        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        tool = next((t for t in session.tool_definitions if t.id == tool_id), None)
        if not tool:
            raise ValueError(f"Tool {tool_id} not found")

        source_calls = [c for c in session.captured_calls if c.id in tool.source_calls]
        if not source_calls:
            raise ValueError(f"No source calls found for tool {tool_id}")

        dom_context = ""
        yaml_def = await generate_tool_definition(
            method=tool.method,
            url_pattern=tool.url_pattern,
            samples=source_calls,
            page_context=session.target_url or "",
            dom_context=dom_context,
            model_config=model_config,
        )

        name, description = self._parse_yaml_metadata(yaml_def)
        contract = parse_api_monitor_tool_yaml(yaml_def)

        tool.yaml_definition = yaml_def
        tool.name = name
        tool.description = description
        tool.validation_status = "valid" if contract.valid else "invalid"
        tool.validation_errors = contract.validation_errors if contract.validation_errors else []
        tool.updated_at = datetime.now()

        logger.info(
            "[ApiMonitor] Regenerated tool '%s' (valid=%s)",
            name, contract.valid,
        )
        return tool
```

需要在文件顶部确认 `datetime` 和 `logger` 已导入（已有）。

- [ ] **Step 2: 在 route/api_monitor.py 中新增 regenerate 路由**

在 `update_tool` 端点之后（~L478）添加：

```python
@router.post("/session/{session_id}/tools/{tool_id}/regenerate")
async def regenerate_tool(
    session_id: str,
    tool_id: str,
    current_user: User = Depends(get_current_user),
):
    session = api_monitor_manager.get_session(session_id)
    _verify_session_owner(session, current_user)
    model_config = await _resolve_user_model_config(str(current_user.id))
    try:
        tool = await api_monitor_manager.regenerate_tool(
            session_id,
            tool_id,
            model_config=model_config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "success", "tool": tool.model_dump()}
```

- [ ] **Step 3: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/route/api_monitor.py
git commit -m "feat: add regenerate tool endpoint for re-calling LLM"
```

---

## Task 5: Header 透传 — extract_caller_auth_profile 支持 passthrough

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor_external_access.py:176-233`

- [ ] **Step 1: 新增常量和修改 `extract_caller_auth_profile` 函数签名**

在文件顶部常量区（~L11-12）添加：

```python
PASSTHROUGH_FILTERED_HEADERS = frozenset({
    "host", "content-length", "connection", "content-type", "transfer-encoding",
})
```

修改 `extract_caller_auth_profile` 函数，新增 `passthrough_headers` 参数。在创建 profile 后、认证处理前注入透传 headers：

```python
def extract_caller_auth_profile(
    arguments: Mapping[str, Any],
    *,
    requirements: Mapping[str, Any],
    request_headers: Mapping[str, Any] | None,
    passthrough_headers: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], ApiMonitorRuntimeProfile, dict[str, Any]]:
    cleaned = dict(arguments or {})
    auth_payload = cleaned.pop("_auth", None)
    profile = ApiMonitorRuntimeProfile()
    credential_type = str(requirements.get("credential_type") or PLACEHOLDER_CREDENTIAL_TYPE)

    # Inject passthrough headers first (lowest priority)
    if passthrough_headers:
        for name, value in passthrough_headers.items():
            if name.lower() not in PASSTHROUGH_FILTERED_HEADERS:
                profile.set_header(name, str(value), secret=False)

    if not requirements.get("required"):
        preview = {
            "credential_type": credential_type,
            "source": "",
            "headers": list(profile.headers.keys()),
            "injected": False,
        }
        if passthrough_headers:
            preview["passthrough_headers"] = [
                k for k in passthrough_headers if k.lower() not in PASSTHROUGH_FILTERED_HEADERS
            ]
        if auth_payload is not None:
            preview["ignored_fields"] = ["_auth"]
        return cleaned, profile, preview
```

后续的 `IDAAS_CREDENTIAL_TYPE` 和 `test` 分支不变 — `profile.set_header()` 会覆盖同名的透传 header。

- [ ] **Step 2: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor_external_access.py
git commit -m "feat: add passthrough_headers support to extract_caller_auth_profile"
```

---

## Task 6: Header 透传 — gateway 传入 passthrough headers

**Files:**
- Modify: `RpaClaw/backend/route/api_monitor_mcp_gateway.py:154-178`

- [ ] **Step 1: 在 gateway `tools/call` 分支提取并传入透传 headers**

在 `tools/call` 分支的 `extract_caller_auth_profile` 调用处，新增 `passthrough_headers` 参数：

```python
    if method == "tools/call":
        tool_name = str(params.get("name") or "").strip()
        docs = await _load_tool_docs(server_doc)
        if not any(str(doc.get("name") or "") == tool_name for doc in docs):
            return _json_rpc_error(request_id, -32602, "API Monitor tool not found")
        requirements = build_caller_auth_requirements(server_doc.get("api_monitor_auth") or {})
        try:
            cleaned_arguments, caller_profile, caller_preview = extract_caller_auth_profile(
                dict(params.get("arguments") or {}),
                requirements=requirements,
                request_headers=request.headers,
                passthrough_headers=dict(request.headers),
            )
        except CallerAuthError as exc:
            return _json_rpc_result(
                request_id,
                _tool_result_payload({"success": False, "error": str(exc)}),
            )
        result = await ApiMonitorMcpRuntime(
            _server_definition(server_doc),
            caller_only=True,
            caller_profile=caller_profile,
            caller_auth_preview=caller_preview,
        ).call_tool(tool_name, cleaned_arguments)
        await _mark_last_used(server_id)
        return _json_rpc_result(request_id, _tool_result_payload(result))
```

- [ ] **Step 2: Commit**

```bash
git add RpaClaw/backend/route/api_monitor_mcp_gateway.py
git commit -m "feat: pass caller headers through MCP gateway to target API"
```

---

## Task 7: 前端 API — 新增 regenerateTool

**Files:**
- Modify: `RpaClaw/frontend/src/api/apiMonitor.ts`

- [ ] **Step 1: 在 `updateToolSelection` 函数之后添加 `regenerateTool`**

```typescript
/**
 * Regenerate a tool's YAML by re-calling LLM with source calls.
 */
export async function regenerateTool(
  sessionId: string,
  toolId: string,
): Promise<ApiToolDefinition> {
  const response = await apiClient.post(
    `/api-monitor/session/${sessionId}/tools/${toolId}/regenerate`,
  )
  return response.data.tool
}
```

- [ ] **Step 2: Commit**

```bash
git add RpaClaw/frontend/src/api/apiMonitor.ts
git commit -m "feat: add regenerateTool API function"
```

---

## Task 8: 前端 UI — 校验状态展示 + 重试按钮

**Files:**
- Modify: `RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue`

- [ ] **Step 1: 导入 regenerateTool**

在 import 区（~L14）确认已导入 `regenerateTool`：

```typescript
import {
  // ... existing imports
  regenerateTool,
} from '@/api/apiMonitor'
```

- [ ] **Step 2: 新增 handleRegenerateTool 函数**

在 `handleDeleteTool` 函数附近添加：

```typescript
const handleRegenerateTool = async (toolId: string) => {
  if (!sessionId.value) return
  try {
    addLog('INFO', `正在重新生成工具: ${toolId}`)
    const updated = await regenerateTool(sessionId.value, toolId)
    const idx = tools.value.findIndex((t) => t.id === toolId)
    if (idx >= 0) {
      tools.value[idx] = updated
    }
    if (toolEdits[toolId] !== undefined) {
      toolEdits[toolId] = updated.yaml_definition
    }
    addLog('INFO', `工具重新生成完成: ${updated.name}`)
  } catch (e: any) {
    addLog('ERROR', `重新生成失败: ${e.message}`)
  }
}
```

- [ ] **Step 3: 在工具卡片标题栏添加校验 badge**

在 `getConfidenceLabelWithScore` badge 之后（~L1505）、`ChevronDown` 之前，添加校验状态 badge：

```html
<span
  v-if="tool.validation_status === 'invalid'"
  class="shrink-0 rounded-md border border-red-300 bg-red-50 px-2 py-0.5 text-[10px] font-bold text-red-600 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-400"
>
  YAML 无效
</span>
<span
  v-else
  class="shrink-0 rounded-md border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-600 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-400"
>
  有效
</span>
```

- [ ] **Step 4: 在展开详情中显示校验错误 + 重新生成按钮**

在 `confidence_reasons` div 之后、`textarea` 之前（~L1519），添加校验错误展示：

```html
<div v-if="tool.validation_status === 'invalid' && tool.validation_errors?.length" class="mb-3 rounded-xl bg-red-50 border border-red-200 px-3 py-2 dark:bg-red-500/10 dark:border-red-500/20">
  <p class="text-[10px] font-bold text-red-600 dark:text-red-400 mb-1">YAML 校验错误：</p>
  <ul class="text-[10px] text-red-500 dark:text-red-300 space-y-0.5">
    <li v-for="err in tool.validation_errors" :key="err">{{ err }}</li>
  </ul>
</div>
```

在"删除"按钮旁（~L1525-1531）添加"重新生成"按钮：

```html
<div class="flex justify-end gap-2 mt-3">
  <button
    v-if="tool.validation_status === 'invalid' && tool.source_calls?.length"
    @click="handleRegenerateTool(tool.id)"
    class="rounded-xl border border-sky-200 px-3 py-1.5 text-xs font-bold text-sky-600 transition hover:bg-sky-50 dark:border-sky-500/20 dark:text-sky-400 dark:hover:bg-sky-500/10"
  >
    重新生成
  </button>
  <button
    @click="handleDeleteTool(tool.id)"
    class="rounded-xl border border-red-200 px-3 py-1.5 text-xs font-bold text-red-600 transition hover:bg-red-50 dark:border-red-500/20 dark:text-red-400 dark:hover:bg-red-500/10"
  >
    删除
  </button>
</div>
```

- [ ] **Step 5: 验证前端构建通过**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/frontend && npm run build`

Expected: 构建成功，无 TypeScript 错误

- [ ] **Step 6: Commit**

```bash
git add RpaClaw/frontend/src/pages/rpa/ApiMonitorPage.vue
git commit -m "feat: show YAML validation status and add regenerate button"
```
