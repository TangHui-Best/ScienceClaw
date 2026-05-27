# API Monitor Regenerate Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 API Monitor MCP 工具重新生成的缩水链路，并让新生成的 OpenAPI YAML 直接用 `paths` key 表达 endpoint，不再输出 `basePath`。

**Architecture:** 保留现有 `ApiMonitorSessionManager` 和 `ApiToolGenerationCandidate` 结构，把 `regenerate_tool()` 改成 candidate-first 的主链路复用。OpenAPI 解析继续兼容历史 `basePath`，但生成 prompt 和新测试只要求 `paths` key 是完整 endpoint path。

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, pytest, LangChain model wrapper, OpenAPI 2.0 YAML.

---

## File Structure

- Modify: `RpaClaw/backend/rpa/api_monitor/llm_analyzer.py`
  - 负责 LLM 工具 YAML 生成 prompt 和 host/path 上下文构造。
- Modify: `RpaClaw/backend/rpa/api_monitor_mcp_contract.py`
  - 负责解析 OpenAPI 2.0 YAML，兼容历史 `basePath`，新 YAML 缺失 `basePath` 时直接用 `paths` key 作为 `contract.url`。
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py`
  - 负责 candidate 主链路、重新生成入口、已有工具定向更新、缺失 DOM context 时失败。
- Modify: `RpaClaw/backend/tests/test_api_monitor_openapi_contract.py`
  - 覆盖不带 `basePath` 的 OpenAPI YAML 和历史 `basePath` 兼容。
- Modify: `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`
  - 覆盖重新生成复用 candidate、旧工具补建 candidate、缺 DOM context 失败、定向更新原工具。

---

### Task 1: OpenAPI YAML 不再生成 basePath

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/llm_analyzer.py`
- Modify: `RpaClaw/backend/tests/test_api_monitor_openapi_contract.py`

- [ ] **Step 1: 写 prompt 单元测试**

Add these tests near the OpenAPI parser tests in `RpaClaw/backend/tests/test_api_monitor_openapi_contract.py`:

```python
class TestOpenApiPromptContract:
    def test_tool_generation_prompt_omits_base_path(self):
        from backend.rpa.api_monitor import llm_analyzer

        assert "basePath:" not in llm_analyzer.TOOL_GEN_SYSTEM
        assert "basePath should be extracted" not in llm_analyzer.TOOL_GEN_SYSTEM
        assert "paths keys MUST be relative to basePath" not in llm_analyzer.TOOL_GEN_SYSTEM
        assert "Do NOT output basePath" in llm_analyzer.TOOL_GEN_SYSTEM

    def test_host_info_does_not_include_inferred_base_path(self):
        from backend.rpa.api_monitor.llm_analyzer import _host_and_endpoint_path_for_prompt

        host, endpoint_path = _host_and_endpoint_path_for_prompt(
            "https://api.example.com/isales/ssdmdoc/services/api/query?keyword=a"
        )

        assert host == "api.example.com"
        assert endpoint_path == "/isales/ssdmdoc/services/api/query"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_openapi_contract.py::TestOpenApiPromptContract -q
```

Expected: FAIL because `TOOL_GEN_SYSTEM` still contains `basePath:` and `_host_and_endpoint_path_for_prompt` does not exist.

- [ ] **Step 3: 修改 prompt 和 prompt helper**

In `RpaClaw/backend/rpa/api_monitor/llm_analyzer.py`, update `TOOL_GEN_SYSTEM` structure block to remove `basePath`, and replace the path guidance with this wording:

```python
TOOL_GEN_SYSTEM = """\
You are an API tool definition generator. Given HTTP API call samples captured from a web application, \
generate a standard OpenAPI 2.0 (Swagger) specification in YAML.

The YAML MUST have this exact structure:
```yaml
swagger: "2.0"
info:
  title: <snake_case_operation_id>
  description: <clear description of what this API endpoint does>
  version: "1.0"
host: <api_host>
schemes:
  - https
paths:
  <captured_endpoint_path>:
    <method>:
      operationId: <snake_case_operation_id>
      summary: <clear description>
      produces:
        - application/json
      parameters:
        - name: <param_name>
          in: <query|path|header>
          type: <string|integer|boolean|number|array>
          description: <what this parameter does>
          required: <true|false>
        - name: body
          in: body
          schema:
            type: object
            properties:
              <field_name>:
                type: <string|integer|boolean|number|array|object>
            required:
              - <required_field_names>
      responses:
        "200":
          description: Success
          schema:
            type: object
            properties:
              <field_name>:
                type: <type>
                description: <what this field contains>
```

Guidelines:
- operationId MUST be descriptive snake_case (e.g., list_users, create_order, search_products)
- Parameterize URL path segments that look like IDs: /users/123 -> /users/{user_id}
- For GET/DELETE: use query/path/header parameters (NOT body)
- For POST/PUT/PATCH: use a single "body" parameter with a schema object containing all fields
- Mark parameters as required only if they appear in every sample or seem essential
- Infer response schema from the captured response bodies
- Do NOT output basePath.
- The paths key MUST be the full captured endpoint path, without scheme, host, or query string.
- Example: captured URL "https://api.example.com/v1/users?active=true" -> host: api.example.com, paths key: /v1/users.
- Only return valid YAML, no markdown fences, no extra commentary

DOM Context Guidelines:
- If the captured API request has missing or empty parameters but the DOM context shows \
  related form inputs/fields, include those as optional parameters in the tool definition
- Use the label text and placeholder text from form inputs to generate parameter descriptions
- Map input types to OpenAPI types: text -> string, number -> integer/number, \
  date -> string (format: date), checkbox -> boolean, select -> enum
- If the same API endpoint is triggered by multiple buttons (e.g., "Search" and "Reset"), \
  generate only ONE tool that covers all use cases, with optional parameters
"""
```

Add this helper above `generate_tool_definition()`:

```python
def _host_and_endpoint_path_for_prompt(url: str) -> tuple[str, str]:
    """Return host and path-only endpoint context for the tool generation prompt."""
    from urllib.parse import urlparse

    parsed = urlparse(url or "")
    host = parsed.hostname or ""
    if parsed.port and parsed.port not in (80, 443):
        host = f"{host}:{parsed.port}"
    endpoint_path = parsed.path or "/"
    return host, endpoint_path
```

Then replace the current `host_info` extraction inside `generate_tool_definition()` with:

```python
    host_info = ""
    endpoint_path = url_pattern.split("?", 1)[0] or "/"
    if samples and samples[0].request.url:
        host, sample_endpoint_path = _host_and_endpoint_path_for_prompt(samples[0].request.url)
        endpoint_path = sample_endpoint_path or endpoint_path
        host_info = host
```

Update the `TOOL_GEN_USER` template so it no longer implies basePath:

```python
TOOL_GEN_USER = """\
Endpoint: {method} {url_pattern}
Host: {host_info}
Endpoint path: {endpoint_path}
Page context: {page_context}

{dom_context_section}

{step_context_section}

API call samples:
{samples_json}

Generate the OpenAPI 2.0 YAML specification. Use DOM context to infer parameters not present in samples.
"""
```

Pass `endpoint_path=endpoint_path` in the `.format(...)` call.

- [ ] **Step 4: 运行 prompt 测试确认通过**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_openapi_contract.py::TestOpenApiPromptContract -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/llm_analyzer.py RpaClaw/backend/tests/test_api_monitor_openapi_contract.py
git commit -m "fix: api monitor生成yaml不输出basePath"
```

---

### Task 2: OpenAPI parser 接受 path 即 endpoint

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor_mcp_contract.py`
- Modify: `RpaClaw/backend/tests/test_api_monitor_openapi_contract.py`

- [ ] **Step 1: 写 parser 测试**

In `RpaClaw/backend/tests/test_api_monitor_openapi_contract.py`, replace `test_path_must_be_relative_to_base_path` with these tests:

```python
    def test_path_key_is_endpoint_when_base_path_is_omitted(self):
        yaml_str = """\
swagger: "2.0"
info:
  title: query_contract_information
  version: "1.0"
host: isales.huawei.com
paths:
  /isales/ssdmdoc/services/api/solr/contractsearch/query/contract/information:
    post:
      operationId: query_contract_information
      responses:
        "200":
          description: Success
"""
        contract = parse_api_monitor_tool_yaml(yaml_str)

        assert contract.valid
        assert contract.method == "POST"
        assert (
            contract.url
            == "/isales/ssdmdoc/services/api/solr/contractsearch/query/contract/information"
        )
        assert "basePath" not in contract.openapi_spec

    def test_legacy_base_path_specs_still_parse(self):
        yaml_str = """\
swagger: "2.0"
info:
  title: get_user
  version: "1.0"
host: api.example.com
basePath: /v1
paths:
  /users/{user_id}:
    get:
      operationId: get_user
      parameters:
        - name: user_id
          in: path
          type: string
          required: true
      responses:
        "200":
          description: Success
"""
        contract = parse_api_monitor_tool_yaml(yaml_str)

        assert contract.valid
        assert contract.url == "/v1/users/{user_id}"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_openapi_contract.py::TestParseOpenApiValidation -q
```

Expected: PASS for the new path-as-endpoint tests. This task is still needed because the implementation currently carries an obsolete rejection helper and an obsolete test that encode basePath/path splitting as a required invariant.

- [ ] **Step 3: 放宽 parser 的 basePath/path 拒绝逻辑**

In `RpaClaw/backend/rpa/api_monitor_mcp_contract.py`, remove this block from `_parse_openapi_2_spec()`:

```python
    if _openapi_path_repeats_base_path(base_path, path_url):
        return ApiMonitorToolContract(
            valid=False,
            yaml_definition=yaml_str,
            validation_errors=[
                "OpenAPI path must be relative to basePath; do not repeat basePath in paths"
            ],
        )
```

Delete the now-unused `_openapi_path_repeats_base_path()` helper:

```python
def _openapi_path_repeats_base_path(base_path: str, path_url: str) -> bool:
    if not base_path or base_path == "/":
        return False
    normalized_base = "/" + base_path.strip("/")
    normalized_path = "/" + str(path_url or "").strip("/")
    return normalized_path == normalized_base or normalized_path.startswith(f"{normalized_base}/")
```

Keep this existing full path calculation:

```python
    base_path = str(data.get("basePath") or "").rstrip("/")
    path_url = next(iter(paths))
    full_path = base_path + path_url if base_path else path_url
```

- [ ] **Step 4: 运行 parser 测试确认通过**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_openapi_contract.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor_mcp_contract.py RpaClaw/backend/tests/test_api_monitor_openapi_contract.py
git commit -m "fix: api monitor解析path即endpoint"
```

---

### Task 3: 主生成链路支持定向更新原工具

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py`
- Modify: `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`

- [ ] **Step 1: 写定向更新测试**

Add this test inside `TestGenerateToolForCandidate` in `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`:

```python
    async def test_candidate_generation_updates_tool_id_target(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        call = _call("call-1", path="/api/orders")
        call.source_evidence = {
            "action_window_matched": True,
            "initiator_urls": ["https://example.com/app"],
            "js_stack_urls": [],
            "frame_url": "https://example.com/app",
        }
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(
            session_id,
            call,
            dom_context={"forms": [{"action": "/api/orders", "inputs": []}]},
            page_url="https://example.com/app",
        )
        original_tool = ApiToolDefinition(
            id="tool-existing",
            session_id=session_id,
            name="old_orders",
            description="Old description",
            method="GET",
            url_pattern="/api/orders",
            yaml_definition="name: old_orders",
            source_calls=["call-1"],
            selected=False,
            generation_candidate_id=None,
        )
        session.tool_definitions.append(original_tool)
        candidate.tool_id = original_tool.id

        async def fake_generate_tool_definition(**kwargs):
            assert kwargs["dom_context"] != "{}"
            return (
                'swagger: "2.0"\n'
                "info:\n"
                "  title: list_orders\n"
                "  version: \"1.0\"\n"
                "host: api.example.com\n"
                "paths:\n"
                "  /api/orders:\n"
                "    get:\n"
                "      operationId: list_orders\n"
                "      responses:\n"
                "        \"200\":\n"
                "          description: Success\n"
            )

        with patch(
            "backend.rpa.api_monitor.manager.generate_tool_definition",
            fake_generate_tool_definition,
        ):
            tool = await manager._generate_tool_for_candidate(
                session_id,
                candidate.id,
                skip_filter=True,
            )

        assert tool is original_tool
        assert [item.id for item in session.tool_definitions] == ["tool-existing"]
        assert tool.name == "list_orders"
        assert tool.generation_candidate_id == candidate.id
        assert candidate.tool_id == "tool-existing"
        assert tool.selected is False
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_realtime_generation.py::TestGenerateToolForCandidate::test_candidate_generation_updates_tool_id_target -q
```

Expected: FAIL because `_generate_tool_for_candidate()` currently only finds existing tools by `generation_candidate_id`, and it sets `selected=True`.

- [ ] **Step 3: 更新 `_generate_tool_for_candidate()` existing 查找逻辑**

In `RpaClaw/backend/rpa/api_monitor/manager.py`, replace the current `existing = next(...)` block inside `_generate_tool_for_candidate()` with:

```python
        existing = None
        if candidate.tool_id:
            existing = next(
                (tool for tool in session.tool_definitions if tool.id == candidate.tool_id),
                None,
            )
        if existing is None:
            existing = next(
                (tool for tool in session.tool_definitions if tool.generation_candidate_id == candidate.id),
                None,
            )
```

When updating an existing tool, set `generation_candidate_id` but preserve its prior selection:

```python
        else:
            tool = existing
            previous_selected = tool.selected
            tool.name = name
            tool.description = description
            tool.method = candidate.method
            tool.url_pattern = candidate.url_pattern
            tool.yaml_definition = yaml_def
            tool.source_calls = [call.id for call in samples]
            tool.generation_candidate_id = candidate.id
            tool.selected = previous_selected
            tool.updated_at = datetime.now()
```

Replace the unconditional selected assignment:

```python
        tool.selected = True
```

with:

```python
        if existing is None:
            tool.selected = True
```

Keep the existing validation, confidence, score, evidence, dedup, and event logic.

- [ ] **Step 4: 运行测试确认通过**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_realtime_generation.py::TestGenerateToolForCandidate::test_candidate_generation_updates_tool_id_target -q
```

Expected: PASS.

- [ ] **Step 5: 运行相关候选生成测试**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_realtime_generation.py::TestGenerateToolForCandidate -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_realtime_generation.py
git commit -m "fix: api monitor候选生成支持更新原工具"
```

---

### Task 4: regenerate_tool 复用 candidate 主链路且不补采 DOM

**Files:**
- Modify: `RpaClaw/backend/rpa/api_monitor/manager.py`
- Modify: `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`

- [ ] **Step 1: 写已有 candidate 的重新生成测试**

Add this class near the generation worker tests in `RpaClaw/backend/tests/test_api_monitor_realtime_generation.py`:

```python
class TestRegenerateTool(unittest.IsolatedAsyncioTestCase):
    async def test_regenerate_tool_reuses_existing_candidate_context(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        call = _call("call-1", path="/api/orders")
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(
            session_id,
            call,
            dom_context={"forms": [{"action": "/api/orders", "inputs": [{"name": "keyword"}]}]},
            page_url="https://example.com/app",
            title="Orders",
            dom_digest="digest-1",
        )
        tool = ApiToolDefinition(
            id="tool-1",
            session_id=session_id,
            name="old_orders",
            description="Old",
            method="GET",
            url_pattern="/api/orders",
            yaml_definition="name: old_orders",
            source_calls=["call-1"],
            selected=False,
            generation_candidate_id=candidate.id,
        )
        session.tool_definitions.append(tool)
        candidate.tool_id = tool.id

        async def fake_generate_tool_definition(**kwargs):
            assert '"keyword"' in kwargs["dom_context"]
            assert kwargs["page_context"] == "https://example.com/app"
            return (
                'swagger: "2.0"\n'
                "info:\n"
                "  title: list_orders\n"
                "  version: \"1.0\"\n"
                "host: api.example.com\n"
                "paths:\n"
                "  /api/orders:\n"
                "    get:\n"
                "      operationId: list_orders\n"
                "      responses:\n"
                "        \"200\":\n"
                "          description: Success\n"
            )

        with patch(
            "backend.rpa.api_monitor.manager.generate_tool_definition",
            fake_generate_tool_definition,
        ):
            regenerated = await manager.regenerate_tool(session_id, tool.id)

        assert regenerated is tool
        assert regenerated.name == "list_orders"
        assert regenerated.id == "tool-1"
        assert regenerated.selected is False
        assert candidate.status == "generated"
```

- [ ] **Step 2: 写旧工具补建 candidate 测试**

Add this second test to `TestRegenerateTool`:

```python
    async def test_regenerate_tool_backfills_candidate_from_historical_candidate_context(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        call = _call("call-1", path="/api/orders")
        session.captured_calls.append(call)
        historical_candidate = ApiToolGenerationCandidate(
            session_id=session_id,
            dedup_key=manager._candidate_dedup_key(call),
            method="GET",
            url_pattern="/api/orders",
            source_call_ids=["call-1"],
            sample_call_ids=["call-1"],
            capture_dom_context={"forms": [{"action": "/api/orders", "inputs": [{"name": "keyword"}]}]},
            capture_page_url="https://example.com/app",
            capture_title="Orders",
            capture_dom_digest="digest-1",
            status="generated",
        )
        session.generation_candidates.append(historical_candidate)
        tool = ApiToolDefinition(
            id="tool-legacy",
            session_id=session_id,
            name="old_orders",
            description="Old",
            method="GET",
            url_pattern="/api/orders",
            yaml_definition="name: old_orders",
            source_calls=["call-1"],
            selected=True,
            generation_candidate_id=None,
        )
        session.tool_definitions.append(tool)

        async def fake_generate_tool_definition(**kwargs):
            assert '"keyword"' in kwargs["dom_context"]
            return (
                'swagger: "2.0"\n'
                "info:\n"
                "  title: list_orders\n"
                "  version: \"1.0\"\n"
                "host: api.example.com\n"
                "paths:\n"
                "  /api/orders:\n"
                "    get:\n"
                "      operationId: list_orders\n"
                "      responses:\n"
                "        \"200\":\n"
                "          description: Success\n"
            )

        with patch(
            "backend.rpa.api_monitor.manager.generate_tool_definition",
            fake_generate_tool_definition,
        ):
            regenerated = await manager.regenerate_tool(session_id, tool.id)

        assert regenerated is tool
        assert tool.generation_candidate_id == historical_candidate.id
        assert historical_candidate.tool_id == "tool-legacy"
        assert tool.selected is True
        assert len(session.generation_candidates) == 1
```

- [ ] **Step 3: 写缺失 DOM context 失败测试**

Add this third test to `TestRegenerateTool`:

```python
    async def test_regenerate_tool_rejects_missing_historical_dom_context(self):
        manager, session_id = _manager_with_session()
        session = manager.sessions[session_id]
        call = _call("call-1", path="/api/orders")
        session.captured_calls.append(call)
        candidate, _ = manager._upsert_generation_candidate(session_id, call)
        tool = ApiToolDefinition(
            id="tool-1",
            session_id=session_id,
            name="old_orders",
            description="Old",
            method="GET",
            url_pattern="/api/orders",
            yaml_definition="name: old_orders",
            source_calls=["call-1"],
            generation_candidate_id=candidate.id,
        )
        session.tool_definitions.append(tool)

        with patch.object(manager, "_capture_generation_dom_context") as capture_dom:
            try:
                await manager.regenerate_tool(session_id, tool.id)
            except ValueError as exc:
                assert "missing historical DOM context" in str(exc)
            else:
                raise AssertionError("Expected missing DOM context error")

        capture_dom.assert_not_called()
```

- [ ] **Step 4: 运行测试确认失败**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_realtime_generation.py::TestRegenerateTool -q
```

Expected: FAIL because current `regenerate_tool()` uses `dom_context=""`, does not route through `_generate_tool_for_candidate()`, and does not reject missing DOM context.

- [ ] **Step 5: 添加 regenerate helper 方法**

In `RpaClaw/backend/rpa/api_monitor/manager.py`, add these helpers before `regenerate_tool()`:

```python
    def _candidate_has_dom_context(self, candidate: ApiToolGenerationCandidate) -> bool:
        return bool(candidate.capture_dom_context)

    def _candidate_for_tool_regeneration(
        self,
        session: ApiMonitorSession,
        tool: ApiToolDefinition,
    ) -> ApiToolGenerationCandidate | None:
        source_call_ids = set(tool.source_calls)
        source_calls = [call for call in session.captured_calls if call.id in source_call_ids]
        if not source_calls:
            return None
        dedup_key_value = self._candidate_dedup_key(source_calls[0])

        if tool.generation_candidate_id:
            candidate = next(
                (item for item in session.generation_candidates if item.id == tool.generation_candidate_id),
                None,
            )
            if candidate is not None and self._candidate_has_dom_context(candidate):
                return candidate

        return next(
            (
                item
                for item in session.generation_candidates
                if item.dedup_key == dedup_key_value and self._candidate_has_dom_context(item)
            ),
            None,
        )
```

This helper intentionally does not call `_capture_generation_dom_context()`.

- [ ] **Step 6: 重写 regenerate_tool() 为主链路复用**

Replace the body of `regenerate_tool()` in `RpaClaw/backend/rpa/api_monitor/manager.py` with:

```python
    async def regenerate_tool(
        self,
        session_id: str,
        tool_id: str,
        model_config: dict | None = None,
    ):
        """Regenerate a tool's YAML through the generation-candidate main path."""
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        tool = next((t for t in session.tool_definitions if t.id == tool_id), None)
        if not tool:
            raise ValueError(f"Tool {tool_id} not found")

        source_calls = [c for c in session.captured_calls if c.id in tool.source_calls]
        if not source_calls:
            raise ValueError(f"No source calls found for tool {tool_id}")

        candidate = self._candidate_for_tool_regeneration(session, tool)
        if candidate is None:
            raise ValueError(f"Tool {tool_id} is missing generation candidate context")
        if not self._candidate_has_dom_context(candidate):
            raise ValueError(f"Tool {tool_id} is missing historical DOM context")

        candidate.tool_id = tool.id
        candidate.method = tool.method
        candidate.url_pattern = tool.url_pattern
        candidate.source_call_ids = list(dict.fromkeys([*candidate.source_call_ids, *tool.source_calls]))
        for call_id in tool.source_calls:
            if call_id not in candidate.sample_call_ids and len(candidate.sample_call_ids) < 5:
                candidate.sample_call_ids.append(call_id)
        tool.generation_candidate_id = candidate.id
        candidate.status = "pending"
        candidate.error = ""
        candidate.retry_after = None
        candidate.updated_at = datetime.now()
        session.updated_at = datetime.now()

        regenerated = await self._generate_tool_for_candidate(
            session_id,
            candidate.id,
            model_config=model_config,
            skip_filter=True,
        )
        if regenerated is None:
            raise ValueError(candidate.error or f"Failed to regenerate tool {tool_id}")
        return regenerated
```

- [ ] **Step 7: 运行 regenerate 测试确认通过**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_realtime_generation.py::TestRegenerateTool -q
```

Expected: PASS.

- [ ] **Step 8: 运行相关生成测试**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_realtime_generation.py::TestGenerateToolForCandidate tests/test_api_monitor_realtime_generation.py::TestRegenerateTool -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_realtime_generation.py
git commit -m "fix: api monitor重新生成复用候选主链路"
```

---

### Task 5: 发布与 runtime URL 回归

**Files:**
- Modify: `RpaClaw/backend/tests/test_api_monitor_publish_mcp.py`
- Modify: `RpaClaw/backend/tests/test_api_monitor_openapi_contract.py`

- [ ] **Step 1: 写发布后 URL 文档测试**

Add this test to `RpaClaw/backend/tests/test_api_monitor_publish_mcp.py` near the registry replace/publish tests:

```python
@pytest.mark.asyncio
async def test_publish_openapi_without_base_path_stores_endpoint_url():
    server_repo = _MemoryRepo()
    tool_repo = _MemoryRepo()
    registry = ApiMonitorMcpRegistry(server_repository=server_repo, tool_repository=tool_repo)
    session = ApiMonitorSession(
        id="session_1",
        user_id="user-1",
        sandbox_session_id="sandbox_1",
        target_url="https://api.example.test/app",
        tool_definitions=[
            ApiToolDefinition(
                id="tool_1",
                session_id="session_1",
                name="query_contract_information",
                description="Query contract information",
                method="POST",
                url_pattern="/isales/ssdmdoc/services/api/solr/contractsearch/query/contract/information",
                yaml_definition="""swagger: "2.0"
info:
  title: query_contract_information
  version: "1.0"
host: isales.huawei.com
paths:
  /isales/ssdmdoc/services/api/solr/contractsearch/query/contract/information:
    post:
      operationId: query_contract_information
      responses:
        "200":
          description: Success
""",
                selected=True,
            )
        ],
    )

    result = await registry.publish_session(
        session=session,
        user_id="user-1",
        mcp_name="contracts",
        description="Contracts",
        overwrite=False,
    )

    tools = list(tool_repo.docs.values())
    assert result["tool_count"] == 1
    assert tools[0]["url"] == "/isales/ssdmdoc/services/api/solr/contractsearch/query/contract/information"
    assert "basePath" not in tools[0]["openapi_spec"]
```

- [ ] **Step 2: 写 runtime 拼接测试**

Add this test to `TestOpenApiExecutionParts` in `RpaClaw/backend/tests/test_api_monitor_openapi_contract.py`:

```python
    def test_execute_deep_endpoint_path_without_base_path(self):
        from backend.deepagent.mcp_runtime import _execute_openapi_request

        doc = {
            "method": "POST",
            "url": "/isales/ssdmdoc/services/api/solr/contractsearch/query/contract/information",
            "openapi_parameters": [
                {"name": "body", "in": "body", "schema": {"type": "object", "properties": {}}},
            ],
        }
        parts = _execute_openapi_request(doc, {"keyword": "abc"}, "https://isales.huawei.com")

        assert (
            parts["url"]
            == "https://isales.huawei.com/isales/ssdmdoc/services/api/solr/contractsearch/query/contract/information"
        )
        assert parts["body"] == {"keyword": "abc"}
```

- [ ] **Step 3: 运行回归测试**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_publish_mcp.py::test_publish_openapi_without_base_path_stores_endpoint_url tests/test_api_monitor_openapi_contract.py::TestOpenApiExecutionParts::test_execute_deep_endpoint_path_without_base_path -q
```

Expected: PASS. If this fails, inspect whether the registry is still parsing the YAML with the old basePath rejection or whether `_execute_openapi_request()` is receiving a URL that already includes host.

- [ ] **Step 4: Commit**

```bash
git add RpaClaw/backend/tests/test_api_monitor_publish_mcp.py RpaClaw/backend/tests/test_api_monitor_openapi_contract.py
git commit -m "test: 覆盖api monitor endpoint路径发布调用"
```

---

### Task 6: Full verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_openapi_contract.py tests/test_api_monitor_realtime_generation.py tests/test_api_monitor_publish_mcp.py -q
```

Expected: PASS.

- [ ] **Step 2: Run broader API Monitor tests**

Run:

```bash
cd RpaClaw/backend
uv run pytest tests/test_api_monitor_*.py -q
```

Expected: PASS. If unrelated existing failures appear, record the failing test names and error summaries before stopping.

- [ ] **Step 3: Check working tree**

Run:

```bash
git status --short
```

Expected: only unrelated pre-existing files remain, such as `AGENTS.md` and `.claude/`, unless implementation tasks intentionally changed additional files.

- [ ] **Step 4: Final commit for verification fixes**

When Step 1 or Step 2 requires additional code/test fixes, commit only those intended files:

```bash
git add RpaClaw/backend/rpa/api_monitor/llm_analyzer.py RpaClaw/backend/rpa/api_monitor_mcp_contract.py RpaClaw/backend/rpa/api_monitor/manager.py RpaClaw/backend/tests/test_api_monitor_openapi_contract.py RpaClaw/backend/tests/test_api_monitor_realtime_generation.py RpaClaw/backend/tests/test_api_monitor_publish_mcp.py
git commit -m "fix: 完成api monitor重新生成和endpoint回归"
```
