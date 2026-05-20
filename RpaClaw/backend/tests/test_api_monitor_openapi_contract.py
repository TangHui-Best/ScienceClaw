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
        assert contract.url == "/v1/orders"
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
        assert contract.url == "/v1/users/{user_id}"
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


class TestLegacyFormatFallback:
    def test_legacy_format_still_works(self):
        legacy_yaml = """\
name: search_orders
description: Search orders by keyword
method: GET
url: /api/orders
parameters:
  type: object
  properties:
    keyword:
      type: string
      in: query
      description: Search keyword
  required:
    - keyword
response:
  type: object
  properties:
    orders:
      type: array
"""
        contract = parse_api_monitor_tool_yaml(legacy_yaml)
        assert contract.valid
        assert contract.name == "search_orders"
        assert contract.method == "GET"
        assert contract.url == "/api/orders"
        assert contract.openapi_spec == {}  # No OpenAPI spec for legacy
        assert contract.query_mapping  # Should have auto-derived mappings


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

    def test_execute_no_openapi_params_returns_empty(self):
        from backend.deepagent.mcp_runtime import _execute_openapi_request

        doc = {"method": "GET", "url": "/api/test", "openapi_parameters": []}
        parts = _execute_openapi_request(doc, {}, "https://api.example.com")
        assert parts["query"] == {}
        assert parts["body"] == {}
        assert parts["url"] == "https://api.example.com/api/test"


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
