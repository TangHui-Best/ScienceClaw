from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from .contract_models import (
    PlannerEnvelope,
    StepContract,
    SUPPORTED_DETERMINISTIC_OPERATORS,
    SUPPORTED_PRIMITIVE_OPERATORS,
)


_SUPPORTED_PRIMITIVE_OPERATORS_TEXT = ", ".join(sorted(SUPPORTED_PRIMITIVE_OPERATORS))
_SUPPORTED_DETERMINISTIC_OPERATORS_TEXT = ", ".join(sorted(SUPPORTED_DETERMINISTIC_OPERATORS))


CONTRACT_PLANNER_SYSTEM_PROMPT = f"""
You are the RPA Contract Planner. Return a JSON object planner envelope for exactly one next-step decision.

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
- Return one planner envelope object with:
  - status: one of next_step, done, need_user
  - current_step: a StepContract object only when status=next_step
  - message: optional string
- Each StepContract must use the exact schema keys: id, intent, target, operator, outputs, validation, runtime_policy.
- description and intent.goal must describe only the local next step, not repeat the full global SOP.
- Use id, not step_id. Use operator.type and operator.execution_strategy, not target.action or target.execution_strategy.
- target.type is required. For navigation, use target.type="url" and target.url_template.
- runtime_policy.runtime_ai_reason and runtime_policy.side_effect_reason must be strings, never null.
- The StepContract is the only semantic source for Compiler, Executor, Validator, and Skill Builder.
- Put all step-level constraints into structured fields, not only description.
- For cross-step dataflow, put dotted blackboard refs in inputs.refs and URL/value templates in target.url_template.
- If the next semantic step reasons over data that is already in blackboard, set target.type="blackboard_ref" and populate inputs.refs.
- Do not extract the same visible list again when the required records already exist in blackboard; consume the existing blackboard data instead.
- If the requested deliverable is already present in blackboard in the required structured shape, return status=done instead of planning another extraction step.
- If a previous successful step already wrote outputs.blackboard_key and nothing has invalidated that result, do not emit another step that only rewrites the same outputs.blackboard_key.
- For templated URLs or values, populate inputs.refs and use single-brace dotted refs such as {{selected_project.url}} or {{skill_repos.0.url}}.
- Do not use double braces like {{{{selected_project.url}}}} and do not use bracket index syntax like [0] inside refs.
- Supported primitive_action operator.type values only: {_SUPPORTED_PRIMITIVE_OPERATORS_TEXT}.
- Supported deterministic_script operator.type values only: {_SUPPORTED_DETERMINISTIC_OPERATORS_TEXT}.
- Do not invent operator names like extract_and_parse, parse_list, analyze_page, or select_best_item.
- For operator.type="rank_collection_numeric_max", operator.selection_rule must include:
  collection_selector, value_selector, link_selector, and optional url_prefix.
- rank_collection_numeric_max standard output is an object with required fields: name, url, score.
  Use outputs.schema={{"type":"object","required":["name","url","score"]}} unless the user requests additional fields.
  The compiler may also include title as a compatibility alias, but downstream refs should use .name and .url.
- For operator.type="extract_repeated_records", operator.selection_rule must include:
  row_selector, fields, and optional limit. fields must be an object of explicit field selectors.
- For extract_repeated_records, outputs.schema should be an array schema with items.required for required fields.
- For visible record collection requests such as "first/top N items" or "输出严格为数组", include validation.must with
  {{"type":"min_records","key":outputs.blackboard_key,"count":1}} unless the user explicitly says empty results are allowed.
- Example fields shape:
  "fields": {{"title": {{"selector": "a[id^='issue_']"}}, "creator": {{"selector": "a[href*='author%3A']"}}, "url": {{"selector": "a[id^='issue_']", "attribute": "href"}}}}
- deterministic_script steps must write structured data to outputs.blackboard_key.
- If runtime_ai is selected, runtime_policy.requires_runtime_ai must be true and runtime_ai_reason must explain why.
- If runtime_ai is selected, outputs.schema must be a real JSON schema with type="object" or type="array"; do not use shorthand schemas such as {{"name":"string"}}.
- If the user asks to open/click/navigate to the item selected by semantic relevance, make it one runtime_ai step with runtime_policy.allow_side_effect=true and structured outputs containing the selected item's url/name/reason. Do not split it into a semantic extract step followed by a hard-coded primitive navigate step.
- For runtime_ai semantic act steps, still write the selected target to outputs.blackboard_key so later manual or deterministic steps can use refs such as {{selected_python_project.url}}.
- Prefer deterministic_script over runtime_ai when the rule is fully codable.
- Prefer runtime_ai over deterministic_script when the rule requires semantic understanding at execution time.
- Do not plan future steps that depend on future pages. Plan only the next executable step from the current page state.
- If the current page is already on the required stable subpage, for example /pulls or /issues after a manual click,
  do not emit another navigation step before the extraction; extract from the current page.
- If the goal says to open/click/navigate to the item selected by a previous deterministic_script result and that
  result is already in blackboard, plan a primitive_action navigate step to that blackboard URL instead of stopping.
- Use status=need_user when precise UI targeting is ambiguous and should be done manually instead of guessing more selectors.
- Use status=done when the current natural-language instruction is already satisfied and no extra AI-generated step is needed.
- For click steps, avoid broad text locators when the page may contain duplicate labels. Prefer role-based locators with an exact accessible name.
- If a click target is ambiguous but the destination URL is deterministically derivable from blackboard data or current stable page structure, prefer a navigate step over an ambiguous click retry.

Return JSON only. Prefer:
{{"status": "next_step", "current_step": StepContract, "message": ""}}
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
    return parse_step_contract_response(_extract_response_text(response), fallback_goal=goal)


async def plan_next_step_envelope(
    goal: str,
    snapshot_view: Dict[str, Any],
    blackboard_values: Dict[str, Any],
    model_config: Optional[Dict[str, Any]] = None,
) -> PlannerEnvelope:
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
    return parse_planner_envelope_response(_extract_response_text(response), fallback_goal=goal)


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
    return parse_step_contracts_response(_extract_response_text(response), fallback_goal=goal)


def parse_step_contract_response(response: Any, fallback_goal: str = "") -> StepContract:
    if isinstance(response, StepContract):
        return response
    if isinstance(response, dict):
        return StepContract(**_normalize_step_contract_payload(response, fallback_goal=_primary_goal_text(fallback_goal)))
    if not isinstance(response, str):
        raise ValueError("planner response must be JSON text or dict")
    payload = _extract_json_object(response)
    return StepContract(**_normalize_step_contract_payload(payload, fallback_goal=_primary_goal_text(fallback_goal)))


def parse_step_contracts_response(response: Any, fallback_goal: str = "") -> list[StepContract]:
    if isinstance(response, StepContract):
        return [response]
    if isinstance(response, list):
        return [parse_step_contract_response(item, fallback_goal=fallback_goal) for item in response]

    payload = response
    if isinstance(response, str):
        payload = _extract_json_object(response)
    if isinstance(payload, dict) and isinstance(payload.get("steps"), list):
        return [parse_step_contract_response(item, fallback_goal=fallback_goal) for item in payload["steps"]]
    if isinstance(payload, dict):
        return [parse_step_contract_response(payload, fallback_goal=fallback_goal)]
    raise ValueError("planner response must be a StepContract or steps array")


def parse_planner_envelope_response(response: Any, fallback_goal: str = "") -> PlannerEnvelope:
    payload = response
    if isinstance(response, str):
        payload = _extract_json_object(response)
    if not isinstance(payload, dict):
        raise ValueError("planner envelope response must be a JSON object")

    status = str(payload.get("status") or "next_step").strip() or "next_step"
    current_step_payload = payload.get("current_step")
    current_step = None
    if isinstance(current_step_payload, dict):
        current_step = parse_step_contract_response(current_step_payload, fallback_goal=fallback_goal)
    return PlannerEnvelope(
        status=status,
        current_step=current_step,
        message=str(payload.get("message") or ""),
    )


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


def _normalize_step_contract_payload(payload: Dict[str, Any], fallback_goal: str = "") -> Dict[str, Any]:
    normalized = dict(payload)

    if "id" not in normalized and normalized.get("step_id"):
        normalized["id"] = normalized.get("step_id")
    if "source" not in normalized or not str(normalized.get("source") or "").strip():
        normalized["source"] = "ai"

    description = str(
        normalized.get("description")
        or normalized.get("goal")
        or fallback_goal
        or ""
    ).strip()
    if not str(normalized.get("description") or "").strip() and description:
        normalized["description"] = description
    if "intent" not in normalized or not isinstance(normalized.get("intent"), dict):
        normalized["intent"] = {"goal": description or str(normalized.get("id") or "rpa_step")}
    elif not str(normalized["intent"].get("goal") or "").strip() and description:
        normalized["intent"]["goal"] = description

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


def _primary_goal_text(goal: str) -> str:
    text = str(goal or "").strip()
    if not text:
        return ""
    separators = (
        "\n\nPrevious planner/compiler failure:",
        "\n\nPrevious step execution failed:",
    )
    for separator in separators:
        if separator in text:
            return text.split(separator, 1)[0].strip()
    return text
