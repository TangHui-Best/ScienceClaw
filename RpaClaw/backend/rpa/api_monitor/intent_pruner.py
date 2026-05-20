"""Batch LLM intent pruning for API Monitor generation candidates."""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Optional

from .llm_analyzer import _call_llm

logger = logging.getLogger(__name__)

VALID_GROUPS = {"primary", "supporting", "adjacent", "bootstrap", "noise", "uncertain"}

INTENT_PRUNER_SYSTEM = """\
You are an API Monitor candidate pruner. Given a user's intent and a batch of high-confidence API candidates,
classify each candidate by how it should be handled for MCP tool generation.

Goal: reduce irrelevant tool retention.

Groups:
- primary: directly serves the user's intent. Only these should become selected tools.
- supporting: useful auxiliary data for the primary APIs, but not a user-requested capability.
- adjacent: same page or business domain, but not useful for this intent.
- bootstrap: page initialization such as user profile, menu, config, permissions, dictionaries.
- noise: telemetry, tracking, polling, recommendations, preloads, heartbeat, notifications.
- uncertain: insufficient evidence or ambiguous; do not auto-promote.

Rules:
- Return exactly one item for every input candidate.
- Mark only APIs that directly satisfy the user intent as primary.
- Prefer bootstrap for identity, menu, config, permission, and dictionary APIs even if they are JSON and high confidence.
- Prefer adjacent for business APIs that belong to a nearby domain but do not satisfy the intent.
- Use uncertain when unsure. Do not mark uncertain APIs as primary.
- Return only valid JSON, no markdown fences.
"""

INTENT_PRUNER_USER = """\
用户意图：
{intent}

页面上下文：
{page_context}

候选 API：
{candidates_json}

请返回 JSON：
{{
  "items": [
    {{
      "candidate_key": "<same candidate_key>",
      "group": "primary|supporting|adjacent|bootstrap|noise|uncertain",
      "score": 0,
      "rank": null,
      "reason": "一句中文理由"
    }}
  ]
}}
"""


@dataclass(frozen=True)
class IntentPruneCandidate:
    candidate_key: str
    method: str
    url_pattern: str
    confidence_score: int
    confidence_reasons: list[str]
    request_summary: str
    response_summary: str
    step_summary: str
    page_url: str
    title: str


@dataclass(frozen=True)
class IntentPruneItem:
    candidate_key: str
    intent_group: str
    intent_score: int
    intent_rank: int | None
    intent_reason: str


@dataclass(frozen=True)
class IntentPruneResult:
    batch_id: str
    items: list[IntentPruneItem]


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _clamp_score(value: object) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        score = 0
    return max(0, min(100, score))


def _normalize_rank(value: object, group: str) -> int | None:
    if group != "primary":
        return None
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return None
    return rank if rank > 0 else None


def _uncertain_item(candidate_key: str, reason: str) -> IntentPruneItem:
    return IntentPruneItem(
        candidate_key=candidate_key,
        intent_group="uncertain",
        intent_score=0,
        intent_rank=None,
        intent_reason=reason,
    )


def _fallback_result(
    candidates: list[IntentPruneCandidate],
    *,
    batch_id: str,
    reason: str,
) -> IntentPruneResult:
    return IntentPruneResult(
        batch_id=batch_id,
        items=[_uncertain_item(candidate.candidate_key, reason) for candidate in candidates],
    )


def _parse_prune_response(
    raw: str,
    candidates: list[IntentPruneCandidate],
    *,
    batch_id: str,
) -> IntentPruneResult:
    keys = [candidate.candidate_key for candidate in candidates]
    try:
        parsed = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        logger.warning("[IntentPruner] Failed to parse LLM response: %s", raw[:500])
        return _fallback_result(candidates, batch_id=batch_id, reason="意图裁剪失败，需人工确认")

    raw_items = parsed.get("items", []) if isinstance(parsed, dict) else []
    by_key: dict[str, IntentPruneItem] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("candidate_key") or "")
        if key not in keys or key in by_key:
            continue
        group = str(item.get("group") or "uncertain")
        if group not in VALID_GROUPS:
            by_key[key] = _uncertain_item(key, "意图裁剪返回了无效分类，需人工确认")
            continue
        reason = str(item.get("reason") or "意图裁剪未提供理由")
        by_key[key] = IntentPruneItem(
            candidate_key=key,
            intent_group=group,
            intent_score=_clamp_score(item.get("score")),
            intent_rank=_normalize_rank(item.get("rank"), group),
            intent_reason=reason,
        )

    items = [
        by_key.get(candidate.candidate_key)
        or _uncertain_item(candidate.candidate_key, "意图裁剪缺少该候选结果，需人工确认")
        for candidate in candidates
    ]
    return IntentPruneResult(batch_id=batch_id, items=items)


def _candidate_payload(candidate: IntentPruneCandidate) -> dict:
    return {
        "candidate_key": candidate.candidate_key,
        "method": candidate.method,
        "url_pattern": candidate.url_pattern,
        "confidence_score": candidate.confidence_score,
        "confidence_reasons": candidate.confidence_reasons,
        "request_summary": candidate.request_summary[:500],
        "response_summary": candidate.response_summary[:800],
        "step_summary": candidate.step_summary[:500],
        "page_url": candidate.page_url,
        "title": candidate.title,
    }


async def prune_candidates_by_intent(
    candidates: list[IntentPruneCandidate],
    intent: str,
    *,
    page_context: str = "",
    model_config: Optional[dict] = None,
) -> IntentPruneResult:
    batch_id = f"intent_prune_{uuid.uuid4().hex[:12]}"
    if not candidates:
        return IntentPruneResult(batch_id=batch_id, items=[])
    payload = [_candidate_payload(candidate) for candidate in candidates]
    user_prompt = INTENT_PRUNER_USER.format(
        intent=intent,
        page_context=page_context or "(无)",
        candidates_json=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    try:
        raw = await _call_llm(INTENT_PRUNER_SYSTEM, user_prompt, model_config)
    except Exception as exc:
        logger.warning("[IntentPruner] LLM call failed: %s", exc)
        return _fallback_result(candidates, batch_id=batch_id, reason="意图裁剪失败，需人工确认")
    return _parse_prune_response(raw, candidates, batch_id=batch_id)
