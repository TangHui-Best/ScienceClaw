# API Monitor OpenAPI 2.0 全面重构

日期：2026-05-08

## 1. 背景

API Monitor MCP 生成的工具 YAML 使用自定义格式（类 OpenAI function calling），不是标准 OpenAPI 格式。这导致：
- 生成的 YAML 无法被标准 OpenAPI 工具（Swagger UI、代码生成器等）消费
- 格式不规范，参数位置（query/path/body/header）需要通过中间 mapping 层间接表达
- 与行业标准的 API 描述方式不一致

## 2. 目标

1. 每个工具生成一个完整的、合法的 OpenAPI 2.0（Swagger）spec 文档。
2. 解析和执行管道基于 OpenAPI 2.0 规范运作，移除中间 mapping 层。
3. 执行时直接从 OpenAPI parameters 构造 HTTP 请求（query/path/body/header）。
4. 已有的 MCP 发布、token flow、认证机制不被破坏。
5. 已有的 confidence 评分、工具生成触发逻辑不变。
6. 每个 `yaml_definition` 字段存储的是可直接用于 Swagger UI 的合法 OpenAPI 2.0 YAML。

## 3. 非目标

- 不升级到 OpenAPI 3.x（用户明确要求 2.0）。
- 不改变 MCP 协议本身。
- 不改变前端 UI。
- 不改变录制/分析流程。
- 不做旧格式迁移工具（已有工具重新生成即可）。

## 4. 设计方案

### 4.1 LLM Prompt 改为 OpenAPI 2.0 格式

重写 `llm_analyzer.py` 的 `TOOL_GEN_SYSTEM`，指导 LLM 生成标准 OpenAPI 2.0 文档。

每个工具是一个完整的 Swagger spec，只包含一个 path 和一个 operation：

```yaml
swagger: "2.0"
info:
  title: search_orders
  description: Search orders by keyword and filters
  version: "1.0"
host: api.example.com
basePath: /
schemes:
  - https
paths:
  /api/orders:
    get:
      operationId: search_orders
      summary: Search orders by keyword and filters
      produces:
        - application/json
      parameters:
        - name: keyword
          in: query
          type: string
          description: Search keyword
        - name: page
          in: query
          type: integer
          description: Page number
          default: 1
        - name: page_size
          in: query
          type: integer
          description: Items per page
          default: 20
      responses:
        "200":
          description: Successful response
          schema:
            type: object
            properties:
              orders:
                type: array
                items:
                  type: object
                  properties:
                    id:
                      type: string
                    total:
                      type: number
              total:
                type: integer
```

POST 请求的 body 参数：

```yaml
paths:
  /api/orders:
    post:
      operationId: create_order
      summary: Create a new order
      consumes:
        - application/json
      parameters:
        - name: body
          in: body
          required: true
          schema:
            type: object
            required:
              - product_id
              - quantity
            properties:
              product_id:
                type: string
                description: Product ID
              quantity:
                type: integer
                description: Order quantity
      responses:
        "201":
          description: Order created
```

Prompt 要点：
- `operationId` 必须是 snake_case（作为 MCP 工具名）
- `host` 和 `basePath` 从 captured request URL 推断
- URL 路径中的 ID 参数化为 `{param_name}` 形式
- GET/DELETE 用 query/path/header 参数
- POST/PUT/PATCH 用 body 参数（OpenAPI 2.0 标准写法：`in: body` + `schema`）
- `responses` 中描述 200/201 响应的 schema
- 如果 DOM context 中有表单信息，用于推断参数

### 4.2 Contract 解析重写

重写 `api_monitor_mcp_contract.py` 的 `parse_api_monitor_tool_yaml()` 函数。

**现状**：用 regex 从自定义格式提取 name、description、method、url、parameters，然后生成 mapping 字典。

**改为**：用 PyYAML 解析 OpenAPI 2.0 spec，直接提取结构化字段。

```python
def parse_openapi_tool_yaml(yaml_str: str) -> ApiMonitorToolContract:
    """Parse an OpenAPI 2.0 spec into a tool contract."""
    try:
        spec = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        return ApiMonitorToolContract(valid=False, validation_errors=[f"Invalid YAML: {e}"])

    # Validate OpenAPI 2.0 structure
    if spec.get("swagger") != "2.0":
        return ApiMonitorToolContract(valid=False, validation_errors=["Not an OpenAPI 2.0 spec"])

    paths = spec.get("paths", {})
    if len(paths) != 1:
        return ApiMonitorToolContract(valid=False, validation_errors=["Must have exactly one path"])

    path_url, path_item = next(iter(paths.items()))
    methods = [m for m in ("get", "post", "put", "patch", "delete") if m in path_item]
    if len(methods) != 1:
        return ApiMonitorToolContract(valid=False, validation_errors=["Must have exactly one operation"])

    method = methods[0].upper()
    operation = path_item[methods[0]]

    name = operation.get("operationId", "")
    description = operation.get("summary", "")
    parameters = operation.get("parameters", [])

    # Build input_schema from parameters
    input_schema = _build_input_schema_from_openapi_params(parameters)

    # Build response_schema from responses
    responses = operation.get("responses", {})
    response_schema = _extract_response_schema(responses)

    # Derive host/basePath for full URL
    host = spec.get("host", "")
    base_path = spec.get("basePath", "/")
    url = path_url

    return ApiMonitorToolContract(
        valid=True,
        yaml_definition=yaml_str,
        name=name,
        description=description,
        method=method,
        url=url,
        input_schema=input_schema,
        response_schema=response_schema,
        raw_definition=spec,
        # No more mapping dicts - OpenAPI parameters are used directly
    )
```

**`_build_input_schema_from_openapi_params`** 将 OpenAPI parameters 转为 JSON Schema：

```python
def _build_input_schema_from_openapi_params(parameters: list) -> dict:
    """Convert OpenAPI 2.0 parameters to JSON Schema input_schema."""
    properties = {}
    required = []

    for param in parameters:
        pname = param.get("name", "")
        if param.get("in") == "body" and "schema" in param:
            # Body parameter: flatten its schema properties
            body_schema = param["schema"]
            for prop_name, prop_def in body_schema.get("properties", {}).items():
                properties[prop_name] = _openapi_type_to_json_schema(prop_def)
            required.extend(body_schema.get("required", []))
        else:
            # query/path/header parameter
            prop = {"type": param.get("type", "string")}
            if param.get("description"):
                prop["description"] = param["description"]
            if "default" in param:
                prop["default"] = param["default"]
            if param.get("enum"):
                prop["enum"] = param["enum"]
            properties[pname] = prop
            if param.get("required"):
                required.append(pname)

    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema
```

**`ApiMonitorToolContract` 更新**：

```python
@dataclass
class ApiMonitorToolContract:
    valid: bool
    yaml_definition: str = ""
    name: str = ""
    description: str = ""
    method: str = ""
    url: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    response_schema: dict[str, Any] = field(default_factory=dict)
    # OpenAPI 2.0 spec stored directly
    openapi_spec: dict[str, Any] = field(default_factory=dict)
    # OpenAPI parameters list (for direct execution)
    openapi_parameters: list[dict] = field(default_factory=list)
    # Legacy fields removed: path_mapping, query_mapping, body_mapping, header_mapping
    validation_errors: list[str] = field(default_factory=list)
    raw_definition: Any = field(default_factory=dict)
```

### 4.3 DB 文档结构

工具文档增加 `openapi_spec` 和 `openapi_parameters` 字段，移除 mapping 字段：

```python
# 新 DB 文档结构
{
    "name": "search_orders",
    "description": "Search orders",
    "method": "GET",
    "url": "/api/orders",
    "validation_status": "valid",
    "yaml_definition": "swagger: \"2.0\"\n...",  # 原始 OpenAPI YAML
    "openapi_spec": { ... },           # 解析后的 OpenAPI dict
    "openapi_parameters": [ ... ],     # OpenAPI parameters 列表
    "input_schema": { ... },           # JSON Schema（从 OpenAPI parameters 转换）
    "response_schema": { ... },        # 响应 schema
    # 移除: query_mapping, body_mapping, path_mapping, header_mapping
}
```

### 4.4 Runtime 执行重构

`mcp_runtime.py` 的 `call_tool` 方法改为直接从 OpenAPI parameters 构造请求：

```python
async def _execute_openapi_request(
    self,
    doc: Mapping[str, Any],
    arguments: Mapping[str, Any],
    base_url: str,
) -> httpx.Response:
    """Construct and execute an HTTP request from OpenAPI parameters."""
    method = str(doc.get("method", "GET")).upper()
    url_pattern = str(doc.get("url", ""))
    openapi_params = doc.get("openapi_parameters", [])

    # Distribute arguments to query/path/body/header based on OpenAPI "in" field
    query_params = {}
    path_params = {}
    body_data = {}
    header_params = {}

    for param in openapi_params:
        pname = param.get("name", "")
        location = param.get("in", "query")
        value = arguments.get(pname)

        if value is None:
            continue

        if location == "query":
            query_params[pname] = value
        elif location == "path":
            path_params[pname] = value
        elif location == "header":
            header_params[pname] = value
        elif location == "body":
            # Body param: value might be the entire body or need flattening
            if isinstance(value, dict):
                body_data.update(value)
            else:
                body_data[pname] = value

    # Also handle any arguments not explicitly in OpenAPI params
    # (fallback for dynamic parameters)
    known_params = {p.get("name") for p in openapi_params}
    extra_args = {k: v for k, v in arguments.items() if k not in known_params}
    if extra_args:
        if method in ("GET", "DELETE"):
            query_params.update(extra_args)
        else:
            body_data.update(extra_args)

    # Build URL with path parameters
    url = url_pattern
    for pname, pvalue in path_params.items():
        url = url.replace("{" + pname + "}", str(pvalue))

    # Resolve against base URL
    if not url.startswith(("http://", "https://")):
        url = urljoin(base_url.rstrip("/") + "/", url.lstrip("/"))

    # Execute
    async with httpx.AsyncClient() as client:
        return await client.request(
            method,
            url,
            params=query_params or None,
            headers=header_params or None,
            json=body_data or None,
        )
```

### 4.5 list_tools 适配

`_api_monitor_tool_input_schema` 改为直接返回 DB 中存储的 `input_schema`（已在解析时从 OpenAPI parameters 转换好）：

```python
def _api_monitor_tool_input_schema(doc: Mapping[str, Any]) -> dict:
    # 直接使用解析时生成的 input_schema
    return dict(doc.get("input_schema") or {"type": "object", "properties": {}})
```

### 4.6 Publishing 适配

`publish_session` 和 `replace_tools` 不需要大改——它们调 `parse_api_monitor_tool_yaml()` 得到 contract，然后存 DB。只要新的 contract 字段正确传递到 DB 即可。

### 4.7 `host` 和 `basePath` 推断

LLM 生成的 OpenAPI spec 中 `host` 和 `basePath` 需要从 captured request URL 推断。在 `generate_tool_definition` 中传入 `host` 和 `base_path` 信息：

```python
# 在调用 LLM 时，从样本请求中提取 host
from urllib.parse import urlparse
parsed = urlparse(samples[0].request.url)
host = parsed.hostname
if parsed.port and parsed.port not in (80, 443):
    host = f"{host}:{parsed.port}"
base_path = "/" + "/".join(parsed.path.split("/")[:2])  # 取前两段作为 base
```

在 prompt 中传入这些信息，让 LLM 填入 `host` 和 `basePath`。

## 5. 文件变更清单

| 文件 | 变更 |
|------|------|
| `backend/rpa/api_monitor/llm_analyzer.py` | `TOOL_GEN_SYSTEM` prompt 重写为 OpenAPI 2.0 格式；`generate_tool_definition` 传入 host/base_path 信息 |
| `backend/rpa/api_monitor/manager.py` | `_parse_yaml_metadata` 改为从 OpenAPI 结构提取 name/description |
| `backend/rpa/api_monitor_mcp_contract.py` | `ApiMonitorToolContract` 移除 mapping 字段，增加 `openapi_spec`/`openapi_parameters`；`parse_api_monitor_tool_yaml()` 重写为 OpenAPI 解析；移除 mapping 生成逻辑；`render_mapping`/`render_template_value` 保留（auth flow 仍用） |
| `backend/deepagent/mcp_runtime.py` | `call_tool` 改为使用 `_execute_openapi_request`；`list_tools` 适配新 schema；移除 mapping-based 请求构造；`_build_api_monitor_url` 适配 path params |
| `backend/route/api_monitor.py` | publish 适配新 contract 字段 |

## 6. 风险与缓解

### 6.1 旧格式工具不兼容

已有 DB 中的工具使用旧格式（mapping 字段），新代码无法执行。

缓解：`call_tool` 中检测是否有 `openapi_parameters` 字段，如果没有则 fallback 到旧 mapping 逻辑。这样已有工具仍可执行，新工具走 OpenAPI 路径。

### 6.2 LLM 生成的 OpenAPI 不规范

LLM 可能生成不完全符合 OpenAPI 2.0 规范的 YAML。

缓解：解析时做严格校验（swagger 版本、paths 结构、operationId），校验失败时返回 validation_errors，不阻止工具创建但标记为 invalid。

### 6.3 host/basePath 推断错误

从 captured URL 推断的 host 可能不准确（如 CDN URL）。

缓解：publish 时让用户确认/覆盖 host。执行时 base_url 由 MCP server 配置提供，不依赖 OpenAPI spec 中的 host。

## 7. 验收标准

1. 生成的 `yaml_definition` 可以被 `swagger-parser` 或在线 Swagger Editor 成功解析。
2. 每个工具的 YAML 包含 `swagger: "2.0"`、`info`、`paths` 完整结构。
3. 工具执行正确：GET 请求参数在 query string，POST body 在 request body，path 参数在 URL 路径。
4. 已有 token flow 认证机制正常工作。
5. 旧格式工具（如果有）仍可执行（fallback）。
6. 全部已有测试通过 + 新增 OpenAPI 解析和执行测试。

## 8. 与现有设计的关系

本设计是对 API Monitor 工具定义格式的重构，与以下设计独立：
- 证据采集（`2026-05-08-api-monitor-evidence-awareness-design.md`）
- Initiator 稳定性（`2026-05-08-api-monitor-initiator-stability-design.md`）
- 窗口边界（`2026-05-06-api-monitor-capture-window-boundary-design.md`）

本设计不改变录制/分析流程、confidence 评分、token flow 检测算法。
