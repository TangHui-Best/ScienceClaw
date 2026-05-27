"""AI-based intent relevance filter for API Monitor tool candidates."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from .llm_analyzer import _call_llm
from .models import CapturedApiCall

logger = logging.getLogger(__name__)

INTENT_FILTER_SYSTEM = """\
You are an API relevance evaluator. Given a user's intent and an API endpoint, \
determine if the API is relevant to achieving the user's goal.

Rules:
- Be conservative: if you are unsure whether the API is relevant, respond "relevant"
- Consider the API's purpose based on its URL path, method, request body, and response
- An API is "not_relevant" only if you are confident it serves a completely different purpose \
  from the user's stated intent

Return a JSON object with exactly two fields:
- "relevant": boolean (true or false)
- "reason": string (brief explanation in Chinese, one sentence)
"""

INTENT_FILTER_USER = """\
用户意图：{intent}

API 端点：{method} {url}

请求体摘要：
{request_summary}

响应摘要：
{response_summary}

置信度理由：
{confidence_reasons}

判断此 API 是否与用户意图相关。返回 JSON。
"""


@dataclass(frozen=True)
class IntentFilterResult:
    relevant: bool
    reason: str


def _build_request_summary(calls: list[CapturedApiCall]) -> str:
    first = calls[0]
    body = first.request.body or ""
    if len(body) > 500:
        body = body[:500] + "..."
    return body if body else "(无请求体)"


def _build_response_summary(calls: list[CapturedApiCall]) -> str:
    first = calls[0]
    if not first.response:
        return "(无响应)"
    parts = [f"状态码: {first.response.status}"]
    if first.response.content_type:
        parts.append(f"Content-Type: {first.response.content_type}")
    body = first.response.body or ""
    if body:
        if len(body) > 500:
            body = body[:500] + "..."
        parts.append(f"响应体: {body}")
    return "\n".join(parts)


async def filter_by_intent(
    calls: list[CapturedApiCall],
    intent: str,
    confidence_reasons: list[str],
    *,
    model_config: Optional[dict] = None,
) -> IntentFilterResult:
    """Use LLM to judge whether an API candidate is relevant to user intent."""
    first = calls[0]
    user_prompt = INTENT_FILTER_USER.format(
        intent=intent,
        method=first.request.method,
        url=first.request.url,
        request_summary=_build_request_summary(calls),
        response_summary=_build_response_summary(calls),
        confidence_reasons="\n".join(f"- {r}" for r in confidence_reasons),
    )

    raw = await _call_llm(INTENT_FILTER_SYSTEM, user_prompt, model_config)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]

    try:
        parsed = json.loads(raw)
        relevant = bool(parsed.get("relevant", True))
        reason = str(parsed.get("reason", ""))
    except (json.JSONDecodeError, AttributeError):
        logger.warning("[IntentFilter] Failed to parse LLM response: %s", raw[:200])
        relevant = True
        reason = ""

    return IntentFilterResult(relevant=relevant, reason=reason)