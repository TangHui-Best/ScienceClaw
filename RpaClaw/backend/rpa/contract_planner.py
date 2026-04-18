from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from .contract_models import StepContract


CONTRACT_PLANNER_SYSTEM_PROMPT = """
You are the RPA Contract Planner. Return exactly one StepContract JSON object.

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
- The StepContract is the only semantic source for Compiler, Executor, Validator, and Skill Builder.
- Put all step-level constraints into structured fields, not only description.
- For cross-step dataflow, put dotted blackboard refs in inputs.refs and URL/value templates in target.url_template.
- If runtime_ai is selected, runtime_policy.requires_runtime_ai must be true and runtime_ai_reason must explain why.
- Prefer deterministic_script over runtime_ai when the rule is fully codable.
- Prefer runtime_ai over deterministic_script when the rule requires semantic understanding at execution time.

Return JSON only. Do not wrap it in prose.
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


def parse_step_contract_response(response: Any) -> StepContract:
    if isinstance(response, StepContract):
        return response
    if isinstance(response, dict):
        return StepContract(**response)
    if not isinstance(response, str):
        raise ValueError("planner response must be JSON text or dict")
    payload = _extract_json_object(response)
    return StepContract(**payload)


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
