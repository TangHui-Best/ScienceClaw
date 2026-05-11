# OpenAPI 2.0 Full Pipeline Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor API Monitor MCP tool generation, parsing, storage, and execution to use standard OpenAPI 2.0 (Swagger) format.

**Architecture:** LLM generates OpenAPI 2.0 specs → parser extracts fields directly from OpenAPI structure → runtime constructs HTTP requests by iterating OpenAPI parameters → removes intermediate mapping layer. Backward compatibility via fallback for old-format tools.

**Tech Stack:** Python 3.13, PyYAML (already installed), httpx, MongoDB, pytest

---

### Task 1: Update `ApiMonitorToolContract` dataclass

**Files:**
- Modify: `backend/rpa/api_monitor_mcp_contract.py:39-72`

- [ ] **Step 1: Update the dataclass**

In `backend/rpa/api_monitor_mcp_contract.py`, replace the `ApiMonitorToolContract` dataclass (lines 39-72) with:

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
    # OpenAPI 2.0 native fields
    openapi_spec: dict[str, Any] = field(default_factory=dict)
    openapi_parameters: list[dict[str, Any]] = field(default_factory=list)
    # Legacy mapping fields (kept for backward compat with old DB docs)
    path_mapping: dict[str, Any] = field(default_factory=dict)
    query_mapping: dict[str, Any] = field(default_factory=dict)
    body_mapping: dict[str, Any] = field(default_factory=dict)
    header_mapping: dict[str, Any] = field(default_factory=dict)
    validation_errors: list[str] = field(default_factory=list)
    raw_definition: Any = field(default_factory=dict)

    def to_document(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "method": self.method,
            "url": self.url,
            "yaml_definition": self.yaml_definition,
            "input_schema": self.input_schema,
            "response_schema": self.response_schema,
            "openapi_spec": self.openapi_spec,
            "openapi_parameters": self.openapi_parameters,
            "validation_status": "valid" if self.valid else "invalid",
        }
        if self.validation_errors:
            doc["validation_errors"] = self.validation_errors
        # Include legacy mappings if present (for old tools)
        if self.path_mapping:
            doc["path_mapping"] = self.path_mapping
        if self.query_mapping:
            doc["query_mapping"] = self.query_mapping
        if self.body_mapping:
            doc["body_mapping"] = self.body_mapping
        if self.header_mapping:
            doc["header_mapping"] = self.header_mapping
        return doc
```

- [ ] **Step 2: Run existing tests to verify no breakage**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_realtime_generation.py -v -x 2>&1 | tail -20`
Expected: PASS (all existing tests still pass since we only added new fields)

- [ ] **Step 3: Commit**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add RpaClaw/backend/rpa/api_monitor_mcp_contract.py
git commit -m "refactor: add openapi_spec and openapi_parameters to ApiMonitorToolContract"
```

---

### Task 2: Rewrite LLM prompt for OpenAPI 2.0

**Files:**
- Modify: `backend/rpa/api_monitor/llm_analyzer.py:57-100` (`TOOL_GEN_SYSTEM`)
- Modify: `backend/rpa/api_monitor/llm_analyzer.py:102-114` (`TOOL_GEN_USER`)
- Modify: `backend/rpa/api_monitor/llm_analyzer.py:180-236` (`generate_tool_definition`)

- [ ] **Step 1: Replace `TOOL_GEN_SYSTEM` constant**

In `backend/rpa/api_monitor/llm_analyzer.py`, replace `TOOL_GEN_SYSTEM` (lines 57-100) with:

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
basePath: <base_path>
schemes:
  - https
paths:
  <url_path>:
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
- host and basePath should be extracted from the URL: "https://api.example.com/v1/users" -> host: api.example.com, basePath: /v1
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

- [ ] **Step 2: Update `TOOL_GEN_USER` to pass host info**

Replace `TOOL_GEN_USER` (lines 102-114) with:

```python
TOOL_GEN_USER = """\
Endpoint: {method} {url_pattern}
Host: {host_info}
Page context: {page_context}

{dom_context_section}

{step_context_section}

API call samples:
{samples_json}

Generate the OpenAPI 2.0 YAML specification. Use DOM context to infer parameters not present in samples.
"""
```

- [ ] **Step 3: Update `generate_tool_definition` to extract and pass host info**

Replace the `generate_tool_definition` function (lines 180-236) with:

```python
async def generate_tool_definition(
    method: str,
    url_pattern: str,
    samples: List[CapturedApiCall],
    page_context: str = "",
    dom_context: str = "",
    step_context: str = "",
    model_config: Optional[Dict] = None,
) -> str:
    """Generate an OpenAPI 2.0 tool definition YAML from captured API samples."""
    from urllib.parse import urlparse

    sample_data = []
    for call in samples[:5]:
        entry: Dict = {}
        if call.request.body:
            try:
                entry["request_body"] = json.loads(call.request.body)
            except (json.JSONDecodeError, TypeError):
                entry["request_body"] = call.request.body
        if call.response:
            entry["response_status"] = call.response.status
            if call.response.body:
                try:
                    entry["response_body"] = json.loads(call.response.body)
                except (json.JSONDecodeError, TypeError):
                    entry["response_body"] = call.response.body[:500]
        sample_data.append(entry)

    # Extract host info from first sample URL
    host_info = ""
    if samples and samples[0].request.url:
        parsed = urlparse(samples[0].request.url)
        host = parsed.hostname or ""
        if parsed.port and parsed.port not in (80, 443):
            host = f"{host}:{parsed.port}"
        path_parts = parsed.path.split("/")
        base_path = "/" + "/".join(path_parts[1:3]) if len(path_parts) > 2 else "/"
        host_info = f"{host} (basePath: {base_path})"

    dom_context_section = f"DOM context (form structure):\n{dom_context}" if dom_context else ""
    step_context_section = f"Observed context:{step_context}" if step_context else ""

    user_prompt = TOOL_GEN_USER.format(
        method=method,
        url_pattern=url_pattern,
        host_info=host_info,
        page_context=page_context or "Unknown page",
        dom_context_section=dom_context_section,
        step_context_section=step_context_section,
        samples_json=json.dumps(sample_data, indent=2, ensure_ascii=False),
    )

    raw = await _call_llm(TOOL_GEN_SYSTEM, user_prompt, model_config)
    raw = re.sub(r"^```(?:ya?ml)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw)
    return raw.strip()
```

- [ ] **Step 4: Run tests to verify no syntax errors**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run python -c "from backend.rpa.api_monitor.llm_analyzer import generate_tool_definition; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add RpaClaw/backend/rpa/api_monitor/llm_analyzer.py
git commit -m "feat: rewrite LLM prompt to generate OpenAPI 2.0 format"
```

---

### Task 3: Rewrite `parse_api_monitor_tool_yaml` for OpenAPI 2.0

**Files:**
- Modify: `backend/rpa/api_monitor_mcp_contract.py:75-198`
- Test: `backend/tests/test_api_monitor_openapi_contract.py` (new file)

- [ ] **Step 1: Create test file**

Create `backend/tests/test_api_monitor_openapi_contract.py`:

```python
"""Tests for OpenAPI 2.0 contract parsing."""
import pytest
from backend.rpa.api_monitor_mcp_contract import parse_api_monitor_tool_yaml


GET_OPENAPI_YAML = """\
swagger: "2.0"
info:
  title: search_orders
  description: Search orders by keyword
  version: "1.0"
host: api.example.com
basePath: /v1
schemes:
  - https
paths:
  /orders:
    get:
      operationId: search_orders
      summary: Search orders by keyword
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
      responses:
        "200":
          description: Success
          schema:
            type: object
            properties:
              orders:
                type: array
              total:
                type: integer
"""

POST_OPENAPI_YAML = """\
swagger: "2.0"
info:
  title: create_order
  description: Create a new order
  version: "1.0"
host: api.example.com
basePath: /v1
paths:
  /orders:
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
"""

PATH_PARAM_YAML = """\
swagger: "2.0"
info:
  title: get_user
  description: Get user by ID
  version: "1.0"
host: api.example.com
basePath: /v1
paths:
  /users/{user_id}:
    get:
      operationId: get_user
      summary: Get user by ID
      parameters:
        - name: user_id
          in: path
          type: string
          required: true
          description: User ID
      responses:
        "200":
          description: Success
"""


class TestParseOpenApiGet:
    def test_valid_get_spec(self):
        contract = parse_api_monitor_tool_yaml(GET_OPENAPI_YAML)
        assert contract.valid
        assert contract.name == "search_orders"
        assert contract.description == "Search orders by keyword"
        assert contract.method == "GET"
        assert contract.url == "/orders"
        assert len(contract.openapi_parameters) == 2
        assert contract.openapi_parameters[0]["name"] == "keyword"
        assert contract.openapi_parameters[0]["in"] == "query"

    def test_input_schema_from_query_params(self):
        contract = parse_api_monitor_tool_yaml(GET_OPENAPI_YAML)
        assert "keyword" in contract.input_schema["properties"]
        assert contract.input_schema["properties"]["keyword"]["type"] == "string"
        assert "page" in contract.input_schema["properties"]
        assert contract.input_schema["properties"]["page"]["default"] == 1

    def test_response_schema(self):
        contract = parse_api_monitor_tool_yaml(GET_OPENAPI_YAML)
        assert "orders" in contract.response_schema.get("properties", {})

    def test_openapi_spec_stored(self):
        contract = parse_api_monitor_tool_yaml(GET_OPENAPI_YAML)
        assert contract.openapi_spec["swagger"] == "2.0"
        assert contract.openapi_spec["host"] == "api.example.com"


class TestParseOpenApiPost:
    def test_valid_post_spec(self):
        contract = parse_api_monitor_tool_yaml(POST_OPENAPI_YAML)
        assert contract.valid
        assert contract.name == "create_order"
        assert contract.method == "POST"

    def test_body_params_flattened_to_input_schema(self):
        contract = parse_api_monitor_tool_yaml(POST_OPENAPI_YAML)
        assert "product_id" in contract.input_schema["properties"]
        assert "quantity" in contract.input_schema["properties"]
        assert "product_id" in contract.input_schema.get("required", [])


class TestParseOpenApiPathParam:
    def test_path_param_in_url(self):
        contract = parse_api_monitor_tool_yaml(PATH_PARAM_YAML)
        assert contract.valid
        assert contract.url == "/users/{user_id}"
        assert contract.openapi_parameters[0]["in"] == "path"


class TestParseOpenApiValidation:
    def test_invalid_yaml(self):
        contract = parse_api_monitor_tool_yaml("not: valid: yaml: {{{")
        assert not contract.valid
        assert any("YAML" in e for e in contract.validation_errors)

    def test_missing_swagger_version(self):
        yaml_str = 'info:\n  title: test\npaths:\n  /x:\n    get:\n      operationId: test\n'
        contract = parse_api_monitor_tool_yaml(yaml_str)
        assert not contract.valid

    def test_no_paths(self):
        yaml_str = 'swagger: "2.0"\ninfo:\n  title: test\n  version: "1.0"\npaths: {}\n'
        contract = parse_api_monitor_tool_yaml(yaml_str)
        assert not contract.valid

    def test_multiple_paths_rejected(self):
        yaml_str = 'swagger: "2.0"\ninfo:\n  title: test\n  version: "1.0"\npaths:\n  /a:\n    get:\n      operationId: a\n  /b:\n    get:\n      operationId: b\n'
        contract = parse_api_monitor_tool_yaml(yaml_str)
        assert not contract.valid
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_openapi_contract.py -v 2>&1 | tail -20`
Expected: FAIL — current parser doesn't understand OpenAPI structure

- [ ] **Step 3: Rewrite `parse_api_monitor_tool_yaml`**

In `backend/rpa/api_monitor_mcp_contract.py`, replace the `parse_api_monitor_tool_yaml` function (lines 75-198) with:

```python
def parse_api_monitor_tool_yaml(yaml_str: str) -> ApiMonitorToolContract:
    """Parse an OpenAPI 2.0 spec (or legacy format) into a tool contract."""
    errors: list[str] = []

    try:
        data = yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        return ApiMonitorToolContract(valid=False, validation_errors=[f"Invalid YAML: {e}"])

    if not isinstance(data, dict):
        return ApiMonitorToolContract(valid=False, validation_errors=["YAML must be a mapping"])

    # Detect OpenAPI 2.0 format
    if data.get("swagger") == "2.0":
        return _parse_openapi_2_spec(data, yaml_str)

    # Fallback: legacy format parsing
    return _parse_legacy_format(data, yaml_str)


def _parse_openapi_2_spec(data: dict, yaml_str: str) -> ApiMonitorToolContract:
    """Parse a standard OpenAPI 2.0 specification."""
    errors: list[str] = []

    paths = data.get("paths")
    if not paths or not isinstance(paths, dict):
        return ApiMonitorToolContract(valid=False, validation_errors=["OpenAPI spec must have paths"], yaml_definition=yaml_str)
    if len(paths) != 1:
        return ApiMonitorToolContract(valid=False, validation_errors=["OpenAPI spec must have exactly one path"], yaml_definition=yaml_str)

    path_url = next(iter(paths))
    path_item = paths[path_url]
    if not isinstance(path_item, dict):
        return ApiMonitorToolContract(valid=False, validation_errors=["Path item must be a mapping"], yaml_definition=yaml_str)

    http_methods = [m for m in ("get", "post", "put", "patch", "delete", "head", "options") if m in path_item]
    if len(http_methods) != 1:
        return ApiMonitorToolContract(valid=False, validation_errors=["Path must have exactly one HTTP method"], yaml_definition=yaml_str)

    method = http_methods[0].upper()
    operation = path_item[http_methods[0]]

    name = str(operation.get("operationId", "")).strip()
    description = str(operation.get("summary", "") or data.get("info", {}).get("description", "")).strip()
    parameters = operation.get("parameters", [])

    if not name:
        errors.append("operationId is required")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name or ""):
        errors.append(f"Invalid operationId: {name!r}")

    input_schema = _build_input_schema_from_openapi_params(parameters)
    response_schema = _extract_openapi_response_schema(operation.get("responses", {}))

    if errors:
        return ApiMonitorToolContract(
            valid=False, yaml_definition=yaml_str, name=name, description=description,
            method=method, url=path_url, validation_errors=errors,
        )

    return ApiMonitorToolContract(
        valid=True,
        yaml_definition=yaml_str,
        name=name,
        description=description,
        method=method,
        url=path_url,
        input_schema=input_schema,
        response_schema=response_schema,
        openapi_spec=data,
        openapi_parameters=parameters,
        raw_definition=data,
    )


def _parse_legacy_format(data: dict, yaml_str: str) -> ApiMonitorToolContract:
    """Parse the legacy (pre-OpenAPI) YAML format for backward compatibility."""
    errors: list[str] = []

    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    method = str(data.get("method", "")).strip().upper()
    url = str(data.get("url", "")).strip()

    if not name:
        errors.append("name is required")
    elif not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        errors.append(f"Invalid name: {name!r}")
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        errors.append(f"Invalid method: {method!r}")
    if not url:
        errors.append("url is required")

    parameters_data = data.get("parameters", {})
    input_schema: dict[str, Any] = {}
    if isinstance(parameters_data, dict) and "properties" in parameters_data:
        input_schema = dict(parameters_data)

    response_data = data.get("response", {})
    response_schema: dict[str, Any] = {}
    if isinstance(response_data, dict) and "properties" in response_data:
        response_schema = dict(response_data)

    if errors:
        return ApiMonitorToolContract(
            valid=False, yaml_definition=yaml_str, name=name, description=description,
            method=method, url=url, validation_errors=errors,
        )

    # Auto-derive legacy mappings
    path_mapping: dict[str, Any] = {}
    query_mapping: dict[str, Any] = {}
    body_mapping: dict[str, Any] = {}
    header_mapping: dict[str, Any] = {}

    props = input_schema.get("properties", {})
    for pname, pdef in props.items():
        location = pdef.get("in", "")
        template = "{{" + pname + "}}"
        if location == "path":
            path_mapping[pname] = template
        elif location == "query":
            query_mapping[pname] = template
        elif location == "header":
            header_mapping[pname] = template
        elif location == "body":
            body_mapping[pname] = template
        else:
            if method in ("GET", "DELETE"):
                query_mapping[pname] = template
            else:
                body_mapping[pname] = template

    request_section = data.get("request", {})
    if isinstance(request_section, dict):
        if "path" in request_section:
            path_mapping = request_section["path"]
        if "query" in request_section:
            query_mapping = request_section["query"]
        if "body" in request_section:
            body_mapping = request_section["body"]
        if "headers" in request_section:
            header_mapping = request_section["headers"]

    return ApiMonitorToolContract(
        valid=True,
        yaml_definition=yaml_str,
        name=name,
        description=description,
        method=method,
        url=url,
        input_schema=input_schema,
        response_schema=response_schema,
        path_mapping=path_mapping,
        query_mapping=query_mapping,
        body_mapping=body_mapping,
        header_mapping=header_mapping,
        raw_definition=data,
    )


def _build_input_schema_from_openapi_params(parameters: list) -> dict:
    """Convert OpenAPI 2.0 parameters list to JSON Schema input_schema."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param in parameters:
        if not isinstance(param, dict):
            continue
        pname = param.get("name", "")
        location = param.get("in", "")

        if location == "body" and "schema" in param:
            body_schema = param["schema"]
            if isinstance(body_schema, dict):
                for prop_name, prop_def in body_schema.get("properties", {}).items():
                    properties[prop_name] = _openapi_prop_to_json_schema(prop_def)
                required.extend(body_schema.get("required", []))
        else:
            prop: dict[str, Any] = {}
            ptype = param.get("type", "string")
            if ptype == "integer":
                prop["type"] = "integer"
            elif ptype == "number":
                prop["type"] = "number"
            elif ptype == "boolean":
                prop["type"] = "boolean"
            elif ptype == "array":
                prop["type"] = "array"
                if "items" in param:
                    prop["items"] = param["items"]
            else:
                prop["type"] = "string"
            if param.get("description"):
                prop["description"] = param["description"]
            if "default" in param:
                prop["default"] = param["default"]
            if param.get("enum"):
                prop["enum"] = param["enum"]
            properties[pname] = prop
            if param.get("required"):
                required.append(pname)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _openapi_prop_to_json_schema(prop_def: Any) -> dict:
    """Convert a single OpenAPI property definition to JSON Schema."""
    if not isinstance(prop_def, dict):
        return {"type": "string"}
    result: dict[str, Any] = {"type": prop_def.get("type", "string")}
    if "description" in prop_def:
        result["description"] = prop_def["description"]
    if "default" in prop_def:
        result["default"] = prop_def["default"]
    if "enum" in prop_def:
        result["enum"] = prop_def["enum"]
    if "items" in prop_def:
        result["items"] = prop_def["items"]
    if "properties" in prop_def:
        result["properties"] = prop_def["properties"]
    return result


def _extract_openapi_response_schema(responses: dict) -> dict:
    """Extract the response schema from OpenAPI responses section."""
    for status_code in ("200", "201", "default"):
        resp = responses.get(status_code, {})
        if isinstance(resp, dict) and "schema" in resp:
            return dict(resp["schema"])
    return {}
```

- [ ] **Step 4: Run the new tests**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_openapi_contract.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run existing tests to verify backward compat**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_realtime_generation.py -v -x 2>&1 | tail -10`
Expected: PASS (legacy format still works)

- [ ] **Step 6: Commit**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add RpaClaw/backend/rpa/api_monitor_mcp_contract.py RpaClaw/backend/tests/test_api_monitor_openapi_contract.py
git commit -m "feat: rewrite contract parser to support OpenAPI 2.0 with legacy fallback"
```

---

### Task 4: Update runtime execution to use OpenAPI parameters

**Files:**
- Modify: `backend/deepagent/mcp_runtime.py:246-403` (`call_tool`)
- Modify: `backend/deepagent/mcp_runtime.py:579-586` (`_api_monitor_tool_input_schema`)

- [ ] **Step 1: Add OpenAPI execution helper**

In `backend/deepagent/mcp_runtime.py`, add this function before the `ApiMonitorMcpRuntime` class (around line 218):

```python
def _execute_openapi_request(
    doc: Mapping[str, Any],
    arguments: Mapping[str, Any],
    base_url: str,
) -> dict[str, Any]:
    """Build request components (query, path, body, headers) from OpenAPI parameters."""
    openapi_params = doc.get("openapi_parameters", [])
    known_params = {p.get("name") for p in openapi_params if isinstance(p, dict)}

    query_params: dict[str, Any] = {}
    path_params: dict[str, Any] = {}
    body_data: dict[str, Any] = {}
    header_params: dict[str, Any] = {}

    for param in openapi_params:
        if not isinstance(param, dict):
            continue
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
            if isinstance(value, dict):
                body_data.update(value)
            else:
                body_data[pname] = value

    # Handle extra arguments not in OpenAPI spec
    extra_args = {k: v for k, v in arguments.items() if k not in known_params and k != "_auth"}
    method = str(doc.get("method", "GET")).upper()
    if extra_args:
        if method in ("GET", "DELETE"):
            query_params.update(extra_args)
        else:
            body_data.update(extra_args)

    # Build URL with path parameters
    url_pattern = str(doc.get("url", ""))
    url = url_pattern
    for pname, pvalue in path_params.items():
        url = url.replace("{" + pname + "}", str(pvalue))

    # Resolve against base_url
    if url.startswith(("http://", "https://")):
        final_url = url
    elif not base_url:
        final_url = ""
    else:
        final_url = urljoin(base_url.rstrip("/") + "/", url.lstrip("/"))

    return {
        "url": final_url,
        "query": query_params,
        "body": body_data,
        "headers": header_params,
    }
```

- [ ] **Step 2: Update `call_tool` to use OpenAPI path when available**

In `backend/deepagent/mcp_runtime.py`, in the `call_tool` method, find the section that resolves mappings (approximately lines 258-268). Find this block:

```python
        # Resolve mappings
        if doc.get("query_mapping") or doc.get("body_mapping") or doc.get("path_mapping") or doc.get("header_mapping"):
            query_mapping = dict(doc.get("query_mapping") or {})
```

Replace the entire mapping resolution block AND the URL building AND the request execution (up to but NOT including the token flow logic) with this logic that detects OpenAPI vs legacy:

Find the line after `arguments = {k: v for k, v in arguments.items() if k != "_auth"}` and before the token flow detection. Add:

```python
        # Determine execution path: OpenAPI or legacy
        has_openapi = bool(doc.get("openapi_parameters"))
```

Then find where `_build_api_monitor_url` is called and the query/body/headers are built. Replace that section with:

```python
        if has_openapi:
            req_parts = _execute_openapi_request(doc, arguments, base_url)
            url = req_parts["url"]
            query_mapping = req_parts["query"]
            body_mapping = req_parts["body"]
            header_mapping = req_parts["headers"]
        else:
            # Legacy mapping path
            if doc.get("query_mapping") or doc.get("body_mapping") or doc.get("path_mapping") or doc.get("header_mapping"):
                query_mapping = dict(doc.get("query_mapping") or {})
                body_mapping = dict(doc.get("body_mapping") or {})
                header_mapping = dict(doc.get("header_mapping") or {})
                path_mapping = dict(doc.get("path_mapping") or {})
            else:
                mappings = _auto_derive_mappings(method, doc.get("input_schema", {}))
                query_mapping = mappings.get("query", {})
                body_mapping = mappings.get("body", {})
                header_mapping = mappings.get("header", {})
                path_mapping = mappings.get("path", {})

            url = _build_api_monitor_url(base_url, _api_monitor_tool_url(doc), arguments)
            query_mapping = render_mapping(query_mapping, arguments)
            body_mapping = render_mapping(body_mapping, arguments)
            header_mapping = render_mapping(header_mapping, arguments)
```

**Important:** Do NOT change the token flow logic (V1/V2) or response handling — only change how query/body/headers/url are constructed. The rest of `call_tool` stays the same.

- [ ] **Step 3: Run existing tests**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_realtime_generation.py tests/test_api_monitor_openapi_contract.py -v 2>&1 | tail -20`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add RpaClaw/backend/deepagent/mcp_runtime.py
git commit -m "feat: add OpenAPI-native request execution to mcp_runtime"
```

---

### Task 5: Update publishing to store OpenAPI fields

**Files:**
- Modify: `backend/rpa/api_monitor_mcp_registry.py:95-130` (`replace_tools`)

- [ ] **Step 1: Update `replace_tools` to pass OpenAPI fields**

In `backend/rpa/api_monitor_mcp_registry.py`, in the `replace_tools` method, find where tool docs are built. Currently it builds a doc dict with fields from the session tool plus `contract.to_document()`. The `contract.to_document()` already includes the new `openapi_spec` and `openapi_parameters` fields from Task 1, so the publishing should work automatically.

Verify by reading the current `replace_tools` code and confirming it calls `contract.to_document()` and merges the result into the tool doc. If it does, no code change is needed for this step.

- [ ] **Step 2: Run full test suite**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_realtime_generation.py tests/test_api_monitor_openapi_contract.py tests/test_api_monitor_evidence.py -v 2>&1 | tail -20`
Expected: PASS

- [ ] **Step 3: Commit (only if changes were needed)**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add -A
git diff --cached --stat && git commit -m "refactor: update publishing for OpenAPI contract fields" || echo "No changes needed"
```

---

### Task 6: Update `_parse_yaml_metadata` in manager.py

**Files:**
- Modify: `backend/rpa/api_monitor/manager.py`

- [ ] **Step 1: Find and update `_parse_yaml_metadata`**

In `backend/rpa/api_monitor/manager.py`, search for `_parse_yaml_metadata` or the regex extraction of name/description from YAML. This is used in `_generate_tool_for_candidate` after calling `generate_tool_definition`.

The current code extracts name and description via regex from the YAML string. Update it to also try OpenAPI format:

Find the function or inline code that does:
```python
name_match = re.search(r"^name:\s*(.+)$", yaml_str, re.MULTILINE)
```

Replace with a helper that handles both formats:

```python
@staticmethod
def _parse_yaml_metadata(yaml_str: str) -> tuple:
    """Extract name and description from generated YAML (OpenAPI or legacy)."""
    name = "unnamed_tool"
    description = "Auto-generated API tool"
    try:
        data = yaml.safe_load(yaml_str)
        if isinstance(data, dict):
            if data.get("swagger") == "2.0":
                # OpenAPI 2.0 format
                paths = data.get("paths", {})
                for path_item in paths.values():
                    for method_key in ("get", "post", "put", "patch", "delete"):
                        if method_key in path_item:
                            op = path_item[method_key]
                            name = op.get("operationId", name)
                            description = op.get("summary", description)
                            break
                    break
            else:
                # Legacy format
                name = data.get("name", name)
                description = data.get("description", description)
    except Exception:
        pass
    return name, description
```

If `_parse_yaml_metadata` already exists as a static method, replace it. If the extraction is inline, refactor it into this helper. Add `import yaml` at the top of the file if not already present.

- [ ] **Step 2: Run tests**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_realtime_generation.py -v -x 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add RpaClaw/backend/rpa/api_monitor/manager.py
git commit -m "feat: update YAML metadata parser to handle OpenAPI 2.0 format"
```

---

### Task 7: End-to-end test and full suite verification

**Files:**
- Test: `backend/tests/test_api_monitor_openapi_contract.py`

- [ ] **Step 1: Add end-to-end OpenAPI execution test**

Append to `backend/tests/test_api_monitor_openapi_contract.py`:

```python
class TestOpenApiExecutionParts:
    def test_execute_get_request_parts(self):
        from backend.deepagent.mcp_runtime import _execute_openapi_request

        doc = {
            "method": "GET",
            "url": "/api/orders",
            "openapi_parameters": [
                {"name": "keyword", "in": "query", "type": "string"},
                {"name": "page", "in": "query", "type": "integer"},
            ],
        }
        parts = _execute_openapi_request(doc, {"keyword": "test", "page": 2}, "https://api.example.com")
        assert parts["url"] == "https://api.example.com/api/orders"
        assert parts["query"] == {"keyword": "test", "page": 2}
        assert parts["body"] == {}

    def test_execute_post_request_parts(self):
        from backend.deepagent.mcp_runtime import _execute_openapi_request

        doc = {
            "method": "POST",
            "url": "/api/orders",
            "openapi_parameters": [
                {"name": "body", "in": "body", "schema": {
                    "type": "object",
                    "properties": {"product_id": {"type": "string"}},
                }},
            ],
        }
        parts = _execute_openapi_request(doc, {"product_id": "abc"}, "https://api.example.com")
        assert parts["body"] == {"product_id": "abc"}
        assert parts["query"] == {}

    def test_execute_path_params(self):
        from backend.deepagent.mcp_runtime import _execute_openapi_request

        doc = {
            "method": "GET",
            "url": "/users/{user_id}",
            "openapi_parameters": [
                {"name": "user_id", "in": "path", "type": "string", "required": True},
            ],
        }
        parts = _execute_openapi_request(doc, {"user_id": "123"}, "https://api.example.com")
        assert parts["url"] == "https://api.example.com/users/123"

    def test_execute_extra_args_fallback(self):
        from backend.deepagent.mcp_runtime import _execute_openapi_request

        doc = {
            "method": "GET",
            "url": "/api/search",
            "openapi_parameters": [
                {"name": "q", "in": "query", "type": "string"},
            ],
        }
        parts = _execute_openapi_request(doc, {"q": "test", "extra": "val"}, "https://api.example.com")
        assert parts["query"]["q"] == "test"
        assert parts["query"]["extra"] == "val"
```

- [ ] **Step 2: Run the full test suite**

Run: `cd /Users/lzzd/project/RPA-Agent/ScienceClaw/RpaClaw/backend && uv run pytest tests/test_api_monitor_openapi_contract.py tests/test_api_monitor_realtime_generation.py tests/test_api_monitor_evidence.py tests/test_api_monitor_confidence.py tests/test_api_monitor_user_action.py -v`
Expected: PASS (all tests)

- [ ] **Step 3: Commit**

```bash
cd /Users/lzzd/project/RPA-Agent/ScienceClaw
git add RpaClaw/backend/tests/test_api_monitor_openapi_contract.py
git commit -m "test: add end-to-end OpenAPI execution tests"
```
