"""LLM integration for API Monitor.

Two prompts:
1. DOM element safety analysis - classify interactive elements as safe/skip
2. API call -> YAML tool definition generation
"""

import json
import logging
import re
from typing import AsyncGenerator, Dict, List, Optional

from backend.deepagent.engine import get_llm_model

from .models import CapturedApiCall

logger = logging.getLogger(__name__)

# ── Element analysis prompt ──────────────────────────────────────────

ELEMENT_ANALYSIS_SYSTEM = """\
You are a web automation safety analyzer. Given a list of interactive elements on a web page, \
classify each one as either "safe_to_probe" or "skip".

Rules for "skip":
- Elements with text containing: delete, remove, logout, sign out, sign out, cancel subscription, \
  reset, purge, drop, uninstall, deactivate, disable, revoke, eject, reject, decline, block, ban
- Elements that navigate to a different domain (external links)
- Elements that trigger file downloads
- Form submit buttons on payment/checkout forms
- Elements with role="destructive"

Rules for "safe_to_probe":
- Navigation within the same site
- Search buttons, filter buttons, pagination
- Tab switches, accordion toggles
- Form inputs (text, select, checkbox)
- Dialog/modal open buttons
- "Load more" / "Show more" buttons
- Table row clicks, list item clicks

Return a JSON object with keys "safe" and "skip", each containing a list of element indices (0-based).
Only return valid JSON, no markdown fences.
"""

ELEMENT_ANALYSIS_USER = """\
Page URL: {url}

Interactive elements:
{elements_json}

Classify each element. Return JSON: {{"safe": [0, 2, 5, ...], "skip": [1, 3, 4, ...]}}
"""

# ── Tool generation prompt ───────────────────────────────────────────

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

# ── LLM call helpers ─────────────────────────────────────────────────


async def _call_llm(
    system_prompt: str,
    user_prompt: str,
    model_config: Optional[Dict] = None,
) -> str:
    """Call LLM with system + user messages and return full text response."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    model = get_llm_model(config=model_config, streaming=False)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    response = await model.ainvoke(messages)
    text = ""
    if isinstance(response, AIMessage):
        text = response.content or ""
    elif hasattr(response, "content"):
        text = str(response.content)
    else:
        text = str(response)
    return text.strip()


# ── Public API ───────────────────────────────────────────────────────


async def analyze_elements(
    url: str,
    elements: List[Dict],
    model_config: Optional[Dict] = None,
) -> Dict[str, List[int]]:
    """Classify interactive elements as safe or skip.

    Returns {"safe": [indices], "skip": [indices]}.
    """
    if not elements:
        return {"safe": [], "skip": []}

    user_prompt = ELEMENT_ANALYSIS_USER.format(
        url=url,
        elements_json=json.dumps(elements, indent=2, ensure_ascii=False),
    )

    raw = await _call_llm(ELEMENT_ANALYSIS_SYSTEM, user_prompt, model_config)

    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw)

    try:
        result = json.loads(raw)
        return {
            "safe": result.get("safe", []),
            "skip": result.get("skip", []),
        }
    except json.JSONDecodeError:
        logger.warning("[ApiMonitor] Failed to parse element analysis response: %s", raw[:200])
        return {"safe": list(range(len(elements))), "skip": []}


def _host_and_endpoint_path_for_prompt(url: str) -> tuple[str, str]:
    """Return host and path-only endpoint context for the tool generation prompt."""
    from urllib.parse import urlparse

    parsed = urlparse(url or "")
    host = parsed.hostname or ""
    if parsed.port and parsed.port not in (80, 443):
        host = f"{host}:{parsed.port}"
    endpoint_path = parsed.path or "/"
    return host, endpoint_path


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
    endpoint_path = url_pattern.split("?", 1)[0] or "/"
    if samples and samples[0].request.url:
        host, sample_endpoint_path = _host_and_endpoint_path_for_prompt(samples[0].request.url)
        endpoint_path = sample_endpoint_path or endpoint_path
        host_info = host

    dom_context_section = f"DOM context (form structure):\n{dom_context}" if dom_context else ""
    step_context_section = f"Observed context:{step_context}" if step_context else ""

    user_prompt = TOOL_GEN_USER.format(
        method=method,
        url_pattern=url_pattern,
        host_info=host_info,
        endpoint_path=endpoint_path,
        page_context=page_context or "Unknown page",
        dom_context_section=dom_context_section,
        step_context_section=step_context_section,
        samples_json=json.dumps(sample_data, indent=2, ensure_ascii=False),
    )

    raw = await _call_llm(TOOL_GEN_SYSTEM, user_prompt, model_config)
    raw = re.sub(r"^```(?:ya?ml)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw)
    return raw.strip()
