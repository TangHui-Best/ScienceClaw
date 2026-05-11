from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml


TOOL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TEMPLATE_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")
SINGLE_TEMPLATE_RE = re.compile(r"^\s*{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}\s*$")
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "token",
}
SENSITIVE_PREVIEW_KEY_NAMES = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "token",
    "access_token",
    "refresh_token",
    "credential",
    "secret",
    "password",
    "key",
}


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


def parse_api_monitor_tool_yaml(yaml_definition: str) -> ApiMonitorToolContract:
    """Parse an OpenAPI 2.0 spec (or legacy format) into a tool contract."""
    try:
        parsed = yaml.safe_load(yaml_definition) or {}
    except Exception as exc:  # noqa: BLE001
        return ApiMonitorToolContract(
            valid=False,
            yaml_definition=yaml_definition,
            validation_errors=[f"Invalid YAML: {exc}"],
        )

    if not isinstance(parsed, dict):
        return ApiMonitorToolContract(
            valid=False,
            yaml_definition=yaml_definition,
            raw_definition=parsed,
            validation_errors=["YAML root must be an object"],
        )

    # Detect OpenAPI 2.0 format
    if parsed.get("swagger") == "2.0":
        return _parse_openapi_2_spec(parsed, yaml_definition)

    # Fallback: legacy format parsing
    return _parse_legacy_format(parsed, yaml_definition)


def _parse_openapi_2_spec(data: dict, yaml_str: str) -> ApiMonitorToolContract:
    """Parse a standard OpenAPI 2.0 specification."""
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

    errors: list[str] = []
    if not name:
        errors.append("operationId is required")
    if name and not TOOL_NAME_RE.match(name):
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

    name = _string_value(data.get("name"))
    description = _string_value(data.get("description"))
    method = _string_value(data.get("method")).upper()
    url = _string_value(data.get("url"))

    if not name:
        errors.append("name is required")
    elif not TOOL_NAME_RE.match(name):
        errors.append("name must match ^[A-Za-z_][A-Za-z0-9_]*$")
    if not description:
        errors.append("description is required")
    if not method:
        errors.append("method is required")
    elif method not in ALLOWED_METHODS:
        errors.append("method must be one of GET, POST, PUT, PATCH, DELETE")
    if not url:
        errors.append("url is required")

    parameters_raw = data.get("parameters")
    parameters = _as_dict(parameters_raw)
    input_schema: dict[str, Any] = parameters
    properties = _as_dict(parameters.get("properties")) if parameters else {}
    if parameters_raw is None:
        errors.append("parameters is required")
    elif not isinstance(parameters_raw, dict):
        errors.append("parameters must be an object")
    elif _string_value(parameters.get("type")) != "object":
        errors.append("parameters.type must be object")
    if parameters and not isinstance(parameters.get("properties"), dict):
        errors.append("parameters.properties must be an object")

    request_raw = data.get("request")
    request: dict[str, Any] = {}
    if request_raw is None:
        pass
    elif isinstance(request_raw, dict):
        request = request_raw
    else:
        errors.append("request must be an object")

    path_mapping, path_errors = _validate_mapping_section("request.path", request.get("path"), properties)
    query_mapping, query_errors = _validate_mapping_section("request.query", request.get("query"), properties)
    body_mapping, body_errors = _validate_mapping_section("request.body", request.get("body"), properties)
    header_mapping, headers_errors = _validate_mapping_section("request.headers", request.get("headers"), properties)

    # Auto-derive mappings from parameter "in" annotations when request mappings are absent.
    if not request:
        auto_path: dict[str, Any] = {}
        auto_query: dict[str, Any] = {}
        auto_body: dict[str, Any] = {}
        auto_header: dict[str, Any] = {}
        for prop_name, prop_value in properties.items():
            if not isinstance(prop_value, dict):
                continue
            location = _string_value(prop_value.get("in")).lower()
            template = "{{" + prop_name + "}}"
            if location == "path":
                auto_path[prop_name] = template
            elif location == "query":
                auto_query[prop_name] = template
            elif location == "body":
                auto_body[prop_name] = template
            elif location == "header":
                auto_header[prop_name] = template
            else:
                # Default: query for GET/DELETE, body for POST/PUT/PATCH
                if method in ("POST", "PUT", "PATCH"):
                    auto_body[prop_name] = template
                else:
                    auto_query[prop_name] = template
        path_mapping = auto_path
        query_mapping = auto_query
        body_mapping = auto_body
        header_mapping = auto_header
    errors.extend(path_errors)
    errors.extend(query_errors)
    errors.extend(body_errors)
    errors.extend(headers_errors)

    response_raw = data.get("response")
    if response_raw is None:
        response_schema: dict[str, Any] = {}
    elif isinstance(response_raw, dict):
        response_schema = response_raw
    else:
        response_schema = {}
        errors.append("response must be an object")

    return ApiMonitorToolContract(
        valid=not errors,
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
        validation_errors=errors,
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


def render_template_value(value: Any, arguments: dict[str, Any] | Any) -> Any:
    if isinstance(value, str):
        single_match = SINGLE_TEMPLATE_RE.match(value)
        if single_match:
            return arguments.get(single_match.group(1))

        def replace(match: re.Match[str]) -> str:
            argument_value = arguments.get(match.group(1), "")
            return "" if argument_value is None else str(argument_value)

        return TEMPLATE_RE.sub(replace, value)
    if isinstance(value, dict):
        return render_mapping(value, arguments)
    if isinstance(value, list):
        return [render_template_value(item, arguments) for item in value]
    return value


def render_mapping(mapping: dict[str, Any] | Any, arguments: dict[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        return {}
    return {key: render_template_value(value, arguments) for key, value in mapping.items()}


def sanitize_headers(headers: dict[str, Any] | Any) -> dict[str, Any]:
    return sanitize_preview_mapping(headers)


def sanitize_preview_mapping(value: dict[str, Any] | list[Any] | Any) -> dict[str, Any] | list[Any] | Any:
    return _sanitize_preview_value(value)


def sanitize_preview_url(
    url: str,
    *,
    url_template: str = "",
    arguments: dict[str, Any] | None = None,
) -> str:
    if not url:
        return ""

    parsed = urlsplit(url)
    sanitized_path = _sanitize_preview_path(parsed.path, url_template, arguments or {})
    sanitized_query = _sanitize_preview_query_string(parsed.query)
    sanitized_fragment = _sanitize_preview_fragment(parsed.fragment)
    return urlunsplit((parsed.scheme, parsed.netloc, sanitized_path, sanitized_query, sanitized_fragment))


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _extract_template_variables(value: str) -> list[str]:
    seen: set[str] = set()
    variables: list[str] = []
    for variable in TEMPLATE_RE.findall(value):
        if variable not in seen:
            seen.add(variable)
            variables.append(variable)
    return variables


def _is_sensitive_header_name(name: str) -> bool:
    return _is_sensitive_preview_key_name(name)


def _sanitize_preview_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***" if _is_sensitive_preview_key_name(key) else _sanitize_preview_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_preview_value(item) for item in value]
    return value


def _is_sensitive_preview_key_name(name: str) -> bool:
    normalized = str(name).strip().lower()
    if not normalized:
        return False
    if normalized in SENSITIVE_PREVIEW_KEY_NAMES or normalized in SENSITIVE_HEADER_NAMES:
        return True
    camel_spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name).strip())
    parts = re.split(r"[^a-z0-9]+", camel_spaced.lower())
    return any(part in SENSITIVE_PREVIEW_KEY_NAMES or part in SENSITIVE_HEADER_NAMES for part in parts if part)


def _sanitize_preview_query_string(query: str) -> str:
    if not query:
        return ""
    query_pairs = parse_qsl(query, keep_blank_values=True)
    return urlencode(
        [
            (key, "***" if _is_sensitive_preview_key_name(key) else value)
            for key, value in query_pairs
        ],
        doseq=True,
        safe="*",
    )


def _sanitize_preview_fragment(fragment: str) -> str:
    if not fragment:
        return ""
    if "=" not in fragment and "&" not in fragment:
        return "****"
    return _sanitize_preview_query_string(fragment)


def _sanitize_preview_path(path: str, url_template: str, arguments: dict[str, Any]) -> str:
    if not path:
        return ""

    template_segments = urlsplit(url_template).path.split("/") if url_template else []
    path_segments = path.split("/")
    sanitized_segments: list[str] = []
    mask_next_segment = False

    for index, segment in enumerate(path_segments):
        if not segment:
            sanitized_segments.append(segment)
            continue

        template_segment = template_segments[index] if index < len(template_segments) else ""
        sanitized_segment = segment

        if mask_next_segment:
            sanitized_segment = "***"
            mask_next_segment = False
        elif template_segment:
            if _template_segment_has_sensitive_placeholder(template_segment):
                sanitized_segment = "***"
            else:
                single_match = SINGLE_TEMPLATE_RE.match(template_segment)
                if single_match and _is_sensitive_preview_key_name(single_match.group(1)):
                    sanitized_segment = "***"
                elif _is_sensitive_preview_key_name(template_segment):
                    mask_next_segment = True
        elif "=" in segment:
            key, value = segment.split("=", 1)
            if _is_sensitive_preview_key_name(key):
                sanitized_segment = f"{key}=***"
        elif _is_sensitive_preview_key_name(segment):
            mask_next_segment = True

        sanitized_segments.append(sanitized_segment)

    return "/".join(sanitized_segments)


def _template_segment_has_sensitive_placeholder(template_segment: str) -> bool:
    for match in TEMPLATE_RE.findall(template_segment):
        if _is_sensitive_preview_key_name(match):
            return True
    return False


def _validate_mapping_section(
    prefix: str,
    section_value: Any,
    allowed_properties: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    if section_value is None:
        return {}, []
    if not isinstance(section_value, dict):
        return {}, [f"{prefix} must be an object"]
    return section_value, _validate_mapping_variables(prefix, section_value, allowed_properties)


def _validate_mapping_variables(
    prefix: str,
    mapping: dict[str, Any],
    allowed_properties: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for key, value in mapping.items():
        current_path = f"{prefix}.{key}"
        if isinstance(value, str):
            for variable in _extract_template_variables(value):
                if variable not in allowed_properties:
                    errors.append(f"{current_path} references unknown parameter '{variable}'")
        elif isinstance(value, dict):
            errors.extend(_validate_mapping_variables(current_path, value, allowed_properties))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                item_path = f"{current_path}[{index}]"
                if isinstance(item, str):
                    for variable in _extract_template_variables(item):
                        if variable not in allowed_properties:
                            errors.append(f"{item_path} references unknown parameter '{variable}'")
                elif isinstance(item, dict):
                    errors.extend(_validate_mapping_variables(item_path, item, allowed_properties))
    return errors
