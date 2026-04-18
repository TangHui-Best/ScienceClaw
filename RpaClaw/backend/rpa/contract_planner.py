from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from .contract_models import StepContract


CONTRACT_PLANNER_SYSTEM_PROMPT = """
You are the RPA Contract Planner. Return a JSON object with a "steps" array of StepContract objects.

Your job is to classify the next SOP step into exactly one execution_strategy:

1. primitive_action
   Use only for directly known browser operations with a stable target:
   fixed navigation URL/template, click/fill/press/extract_text against a stable locator.
   Do not use primitive_action for batch extraction, ranking, comparison, or semantic judgment.

2. deterministic_script
   Use for dynamic page data + deterministic rules.
   Examples: parse a visible list, compute max/min/sort/filter by explicit numeric/text rules,
   extract repeated records with explicit fields, transform data, construct a URL from prior blackboard refs.
   deterministic_script must not call an LLM and must not perform semantic judgment.

3. runtime_ai
   Use for dynamic page data + runtime semantic judgment.
   Examples: most relevant/best match by meaning, summarize/analyze/classify visible content,
   infer business meaning that cannot be encoded as deterministic selectors/rules.
   runtime_ai must write structured JSON to outputs.blackboard_key with outputs.schema.
   Natural language is allowed only inside JSON fields such as reason, summary, or explanation.

Hard constraints:
- Each StepContract must use the exact schema keys: id, intent, target, operator, outputs, validation, runtime_policy.
- Use id, not step_id. Use operator.type and operator.execution_strategy, not target.action or target.execution_strategy.
- target.type is required. For navigation, use target.type="url" and target.url_template.
- runtime_policy.runtime_ai_reason and runtime_policy.side_effect_reason must be strings, never null.
- The StepContract is the only semantic source for Compiler, Executor, Validator, and Skill Builder.
- Put all step-level constraints into structured fields, not only description.
- For cross-step dataflow, put dotted blackboard refs in inputs.refs and URL/value templates in target.url_template.
- If runtime_ai is selected, runtime_policy.requires_runtime_ai must be true and runtime_ai_reason must explain why.
- Prefer deterministic_script over runtime_ai when the rule is fully codable.
- Prefer runtime_ai over deterministic_script when the rule requires semantic understanding at execution time.

Return JSON only. Prefer:
{"steps": [StepContract, StepContract, ...]}
For backward compatibility, a single StepContract object is also accepted.
Do not wrap it in prose.
""".strip()


async def plan_step_contract(
    goal: str,
    snapshot_view: Dict[str, Any],
    blackboard_values: Dict[str, Any],
    model_config: Optional[Dict[str, Any]] = None,
) -> StepContract:
    from langchain_core.messages import HumanMessage, SystemMessage

    from backend.deepagent.engine import get_llm_model

    model = get_llm_model(config=model_config, streaming=False)
    response = await model.ainvoke(
        [
            SystemMessage(content=CONTRACT_PLANNER_SYSTEM_PROMPT),
            HumanMessage(
                content=json.dumps(
                    {
                        "goal": goal,
                        "snapshot_view": snapshot_view,
                        "blackboard": blackboard_values,
                    },
                    ensure_ascii=False,
                    default=str,
                )
            ),
        ]
    )
    return parse_step_contract_response(_extract_response_text(response))


async def plan_sop_contracts(
    goal: str,
    snapshot_view: Dict[str, Any],
    blackboard_values: Dict[str, Any],
    model_config: Optional[Dict[str, Any]] = None,
) -> list[StepContract]:
    from langchain_core.messages import HumanMessage, SystemMessage

    from backend.deepagent.engine import get_llm_model

    model = get_llm_model(config=model_config, streaming=False)
    response = await model.ainvoke(
        [
            SystemMessage(content=CONTRACT_PLANNER_SYSTEM_PROMPT),
            HumanMessage(
                content=json.dumps(
                    {
                        "goal": goal,
                        "snapshot_view": snapshot_view,
                        "blackboard": blackboard_values,
                    },
                    ensure_ascii=False,
                    default=str,
                )
            ),
        ]
    )
    return parse_step_contracts_response(_extract_response_text(response))


def parse_step_contract_response(response: Any) -> StepContract:
    if isinstance(response, StepContract):
        return response
    if isinstance(response, dict):
        return StepContract(**_normalize_step_contract_payload(response))
    if not isinstance(response, str):
        raise ValueError("planner response must be JSON text or dict")
    payload = _extract_json_object(response)
    return StepContract(**_normalize_step_contract_payload(payload))


def parse_step_contracts_response(response: Any) -> list[StepContract]:
    if isinstance(response, StepContract):
        return [response]
    if isinstance(response, list):
        return [parse_step_contract_response(item) for item in response]

    payload = response
    if isinstance(response, str):
        payload = _extract_json_object(response)
    if isinstance(payload, dict) and isinstance(payload.get("steps"), list):
        return [parse_step_contract_response(item) for item in payload["steps"]]
    if isinstance(payload, dict):
        return [parse_step_contract_response(payload)]
    raise ValueError("planner response must be a StepContract or steps array")


def _extract_response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")


def _extract_json_object(text: str) -> Dict[str, Any]:
    cleaned = _strip_fenced_json(text.strip())
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ValueError("planner response did not contain a JSON object")
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("planner response JSON must be an object")
    return parsed


def _strip_fenced_json(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text


def _normalize_step_contract_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload)

    if "id" not in normalized and normalized.get("step_id"):
        normalized["id"] = normalized.get("step_id")

    description = str(normalized.get("description") or normalized.get("goal") or "").strip()
    if "intent" not in normalized or not isinstance(normalized.get("intent"), dict):
        normalized["intent"] = {"goal": description or str(normalized.get("id") or "rpa_step")}

    target = dict(normalized.get("target") or {})
    if "type" not in target:
        if target.get("url_template") or target.get("url"):
            target["type"] = "url"
        elif target.get("locator"):
            target["type"] = "locator"
        elif target.get("collection"):
            target["type"] = "visible_collection"
        else:
            target["type"] = "page"
    if "url_template" not in target and target.get("url"):
        target["url_template"] = target.get("url")
    normalized["target"] = target

    if "operator" not in normalized or not isinstance(normalized.get("operator"), dict):
        operator_type = (
            normalized.get("action")
            or target.get("action")
            or normalized.get("operator_type")
            or "navigate"
        )
        execution_strategy = (
            normalized.get("execution_strategy")
            or target.get("execution_strategy")
            or "primitive_action"
        )
        normalized["operator"] = {
            "type": operator_type,
            "execution_strategy": execution_strategy,
        }

    runtime_policy = dict(normalized.get("runtime_policy") or {})
    if runtime_policy.get("runtime_ai_reason") is None:
        runtime_policy["runtime_ai_reason"] = ""
    if runtime_policy.get("side_effect_reason") is None:
        runtime_policy["side_effect_reason"] = ""
    normalized["runtime_policy"] = runtime_policy

    normalized.setdefault("outputs", {"blackboard_key": None, "schema": None})
    normalized.setdefault("validation", {"must": []})

    return normalized
