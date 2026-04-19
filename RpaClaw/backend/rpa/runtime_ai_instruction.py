from __future__ import annotations

import asyncio
import json
import re
import io
import tokenize
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin

from backend.deepagent.engine import get_llm_model
from backend.rpa.blackboard import Blackboard
from backend.rpa.assistant import _extract_llm_response_text
from backend.rpa.assistant_runtime import (
    build_frame_path_from_frame,
    build_page_snapshot,
    execute_structured_intent,
    resolve_structured_intent,
)

AI_INSTRUCTION_PLAN_TIMEOUT_S = 25.0
AI_INSTRUCTION_RUNTIME_SYSTEM_PROMPT = """You are the runtime planner for an RPA AI instruction step.

Return JSON only.

Supported output:
1. Structured plan:
{
  "plan_type": "structured",
  "actions": [
    {"action": "navigate|click|fill|extract_text|press", ...}
  ]
}

2. Code plan:
{
  "plan_type": "code",
  "code": "async def run(page, results): ..."
}

Rules:
- Respect the provided prompt, snapshot_summary, snapshot_meta, output_expectation, and execution_hint.
- When output_expectation.mode is extract, prefer returning a concise extracted summary/value in output.
- For semantic_extract requests that ask to summarize, explain, describe, compare, or synthesize the current page/project/content, prefer a code plan that reads and synthesizes page content. Do not reduce those tasks to a single extract_text selector.
- When output_expectation.mode is act, return a plan that performs a real browser action. Do not return an empty plan.
- Use code only when the rule cannot be expressed well as atomic structured actions.
- Keep code limited to Playwright page automation and page.evaluate(...). Do not use filesystem, network, shell, or system libraries.
- Never import or use requests, httpx, urllib, fetch, or any external HTTP client. Work only with the current page, its DOM, and Playwright APIs.
- For code plans in act mode, return a dict from run(page, results) that includes either a non-empty output or action_performed=true.
- For semantic selection tasks in act mode, do not stop at returning only a chosen identifier/path. Prefer a real click/navigate plan. If you must return the selected target, use target_url/url/href/path/repo_path so runtime can execute it.
- When opening a selected page or repository with a structured plan, prefer {"action":"navigate","url":"https://..."} over clicking a broad selector. Runtime also accepts target_url/href/path/repo_path aliases.
- If you must click a link by href, use an exact href selector such as a[href="/owner/repo"]. Do not use broad contains selectors such as a[href*="owner/repo"], because they can also match stargazers, forks, comments, or subpage links.
- If planning_feedback is present, treat it as a validation failure from the previous attempt and return a corrected replacement plan instead of repeating the same mistake.
- Keep the plan concise and executable within the provided reasoning budget.
"""

AI_INSTRUCTION_SUMMARY_SYSTEM_PROMPT = """You summarize extracted page content for a semantic extraction step.

Return plain text only.

Rules:
- Use the extracted content as your primary source of truth.
- Produce an actual summary, not a raw content dump.
- Keep the answer concise but specific.
- If the user asks in Chinese, answer in Chinese.
- If the extracted content is insufficient, say so briefly instead of inventing details.
"""

AI_INSTRUCTION_BLACKBOARD_SYSTEM_PROMPT = """You analyze structured blackboard data for a runtime AI instruction step.

Return JSON only, matching the requested output schema exactly.

Rules:
- Use only the provided prompt, global_goal, input_refs, input_data, and output_schema.
- Do not refer to the browser page or DOM when input_scope.mode is blackboard_ref.
- Do not return prose outside JSON.
- If output_schema.type is array, return a JSON array.
- If output_schema.type is object, return a JSON object.
- Keep field names exactly aligned with the schema.
"""


_DISALLOWED_CODE_TOKENS = (
    "import os",
    "import subprocess",
    "from os",
    "from subprocess",
    "open(",
    "pathlib",
    "requests",
    "httpx",
    "socket",
    "__import__",
    "eval(",
    "exec(",
)

_SEMANTIC_SUMMARY_PROMPT_PATTERNS = (
    "总结",
    "概括",
    "提炼",
    "归纳",
    "说明",
    "介绍",
    "summarize",
    "summary",
    "describe",
    "overview",
    "explain",
    "synthesize",
)

_SEMANTIC_CONTENT_SELECTORS = (
    ("readme", "#readme"),
    ("markdown_body", "article.markdown-body, .markdown-body"),
    ("role_main", "main, [role='main']"),
    ("article", "article"),
    ("pre", "pre"),
    ("body", "body"),
)


def _trim_semantic_summary_material(material: str, max_chars: int = 4000) -> str:
    text = str(material or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _extract_prefixed_line(material: str, prefix: str) -> str:
    for raw_line in str(material or "").splitlines():
        line = raw_line.strip()
        if line.lower().startswith(prefix.lower()):
            return line[len(prefix):].strip()
    return ""


def _build_best_effort_summary_from_material(step: Dict[str, Any], extracted_material: str) -> str:
    prompt = str(step.get("prompt") or "")
    prompt_lower = prompt.lower()
    prefer_chinese = any(token in prompt for token in ("总结", "概括", "提炼", "中文"))

    title = _extract_prefixed_line(extracted_material, "Title:")
    meta_description = _extract_prefixed_line(extracted_material, "Meta description:")

    content_sections = re.findall(r"\[(.*?)\]\s+(.*?)(?=\n\n\[|\Z)", extracted_material, re.DOTALL)
    content_body = ""
    if content_sections:
        content_body = str(content_sections[0][1]).strip()
    else:
        content_body = extracted_material

    sentences = [
        re.sub(r"\s+", " ", sentence).strip(" -\t")
        for sentence in re.split(r"(?<=[.!?。！？])\s+|\n+", content_body)
        if re.sub(r"\s+", " ", sentence).strip(" -\t")
    ]
    key_points = []
    for sentence in sentences:
        lowered = sentence.lower()
        if lowered.startswith(("title:", "meta description:", "headings:", "extracted content:")):
            continue
        if len(sentence) < 20:
            continue
        key_points.append(sentence)
        if len(key_points) >= 3:
            break

    if prefer_chinese:
        lines = []
        if title:
            lines.append(f"项目标题：{title}")
        if meta_description:
            lines.append(f"简介：{meta_description}")
        if key_points:
            lines.append("核心摘要：")
            lines.extend(f"- {point}" for point in key_points)
        return "\n".join(lines).strip() or "已提取到页面内容，但自动摘要未能完整生成。"

    lines = []
    if title:
        lines.append(f"Project title: {title}")
    if meta_description:
        lines.append(f"Description: {meta_description}")
    if key_points:
        lines.append("Key summary:")
        lines.extend(f"- {point}" for point in key_points)
    return "\n".join(lines).strip() or "Page content was extracted, but the summary could not be fully generated."


def _compact_text(value: Any, max_len: int = 120) -> str:
    text = str(value or "").strip().replace("\n", " ")
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _build_snapshot_summary(snapshot: Dict[str, Any]) -> str:
    lines = [
        f"Page: {_compact_text(snapshot.get('title') or '')}",
        f"URL: {_compact_text(snapshot.get('url') or '', max_len=180)}",
    ]

    containers = list(snapshot.get("containers") or [])[:8]
    if containers:
        lines.append("Containers:")
        for container in containers:
            lines.append(
                "- "
                f"{_compact_text(container.get('container_kind', 'container'), 32)} "
                f"{_compact_text(container.get('name', ''), 80)} "
                f"(actionable={len(container.get('child_actionable_ids') or [])}, "
                f"content={len(container.get('child_content_ids') or [])})"
            )

    actionable_nodes = list(snapshot.get("actionable_nodes") or [])[:15]
    if actionable_nodes:
        lines.append("Actionable nodes:")
        for node in actionable_nodes:
            lines.append(
                "- "
                f"{_compact_text(node.get('role') or node.get('semantic_kind') or 'node', 24)} "
                f"{_compact_text(node.get('name') or node.get('text') or '', 100)}"
            )

    content_nodes = list(snapshot.get("content_nodes") or [])[:15]
    if content_nodes:
        lines.append("Content nodes:")
        for node in content_nodes:
            lines.append(
                "- "
                f"{_compact_text(node.get('semantic_kind') or 'content', 24)} "
                f"{_compact_text(node.get('text') or node.get('name') or '', 100)}"
            )

    frames = list(snapshot.get("frames") or [])[:4]
    if frames:
        lines.append("Frames:")
        for frame in frames:
            lines.append(f"- {_compact_text(frame.get('frame_hint') or 'main document', 120)}")
            for collection in list(frame.get("collections") or [])[:4]:
                lines.append(
                    "  * "
                    f"{_compact_text(collection.get('kind') or 'collection', 40)} "
                    f"(items={collection.get('item_count', 0)})"
                )
                for item in list(collection.get("items") or [])[:3]:
                    lines.append(f"    - {_compact_text(item.get('name') or item.get('text') or '', 100)}")

    return "\n".join(line for line in lines if line.strip())


def _build_snapshot_meta(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "frame_count": len(snapshot.get("frames") or []),
        "container_count": len(snapshot.get("containers") or []),
        "actionable_count": len(snapshot.get("actionable_nodes") or []),
        "content_count": len(snapshot.get("content_nodes") or []),
    }


async def _capture_page_observation(page) -> Dict[str, Any]:
    title = ""
    try:
        title = await page.title()
    except Exception:
        title = ""
    return {
        "url": getattr(page, "url", "") or "",
        "title": title or "",
    }


def _has_observable_page_change(before: Dict[str, Any], after: Dict[str, Any]) -> bool:
    return (before.get("url") != after.get("url")) or (before.get("title") != after.get("title"))


def _parse_plan_response_text(text: str) -> Dict[str, Any]:
    normalized = str(text or "").strip()
    if not normalized:
        raise ValueError("AI instruction planner returned an empty response")

    try:
        parsed = json.loads(normalized)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    match = re.search(r"```(?:json)?\s*(.*?)```", normalized, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1).strip())
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            return parsed

    match = re.search(r"\{.*\}", normalized, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            return parsed

    excerpt = _compact_text(normalized, max_len=180)
    raise ValueError(f"AI instruction planner returned a non-JSON response: {excerpt}")


def _parse_json_value_response(text: str) -> Any:
    normalized = str(text or "").strip()
    if not normalized:
        raise ValueError("AI instruction returned an empty JSON response")

    try:
        return json.loads(normalized)
    except Exception:
        pass

    match = re.search(r"```(?:json)?\s*(.*?)```", normalized, re.DOTALL | re.IGNORECASE)
    if match:
        return json.loads(match.group(1).strip())

    match = re.search(r"(\{.*\}|\[.*\])", normalized, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    excerpt = _compact_text(normalized, max_len=180)
    raise ValueError(f"AI instruction returned a non-JSON response: {excerpt}")


def _resolve_input_refs(results: Dict[str, Any], input_refs: list[str]) -> Dict[str, Any]:
    board = Blackboard(values=dict(results or {}))
    resolved: Dict[str, Any] = {}
    for ref in input_refs:
        if not isinstance(ref, str) or not ref.strip():
            continue
        resolved[ref] = board.resolve_ref(ref.strip())
    return resolved


async def plan_ai_instruction(
    page,
    step: Dict[str, Any],
    model_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    model = get_llm_model(config=model_config, streaming=False)
    snapshot = await build_page_snapshot(page, build_frame_path_from_frame)
    snapshot_summary = _build_snapshot_summary(snapshot)
    instruction = {
        "prompt": step.get("prompt", ""),
        "global_goal": step.get("global_goal", ""),
        "instruction_kind": step.get("instruction_kind", "semantic_rule"),
        "input_scope": step.get("input_scope") or {"mode": "current_page"},
        "output_expectation": step.get("output_expectation") or {"mode": "act"},
        "execution_hint": step.get("execution_hint") or {"max_reasoning_steps": 10},
        "snapshot_summary": snapshot_summary,
        "snapshot_meta": _build_snapshot_meta(snapshot),
        "results": step.get("results") or {},
        "planning_feedback": step.get("planning_feedback") or "",
    }
    planning_timeout_s = float(
        (step.get("execution_hint") or {}).get("planning_timeout_s") or AI_INSTRUCTION_PLAN_TIMEOUT_S
    )
    response = await asyncio.wait_for(
        model.ainvoke(
            [
                {"role": "system", "content": AI_INSTRUCTION_RUNTIME_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(instruction, ensure_ascii=False)},
            ]
        ),
        timeout=planning_timeout_s,
    )
    return _parse_plan_response_text(_extract_llm_response_text(response))


def _is_retryable_code_plan_error(exc: Exception) -> bool:
    message = str(exc or "")
    return (
        "Disallowed code token in ai_instruction plan" in message
        or "requires code plan" in message
    )


def _is_retryable_execution_error(error: str) -> bool:
    normalized = str(error or "")
    lowered = normalized.lower()
    return (
        "disallowed code token" in lowered
        or
        "SyntaxError" in normalized
        or "syntaxerror" in lowered
        or "invalid syntax" in lowered
        or "Invalid or unexpected token" in normalized
        or "strict mode violation" in normalized
        or "EOF in multi-line string" in normalized
        or "unterminated string" in lowered
        or "tokenerror" in lowered
        or "expression cannot contain assignment" in lowered
        or 'perhaps you meant "=="' in lowered
    )


def _normalize_output_value(value: Any) -> Any:
    return value


def _candidate_extract_output(final_result: Dict[str, Any], result_key: Optional[str], results: Dict[str, Any]) -> Any:
    candidate = final_result.get("output")
    if candidate in (None, "") and result_key:
        candidate = results.get(result_key)
    if candidate in (None, "") and isinstance(final_result.get("data"), dict):
        candidate = final_result.get("data")
    return _normalize_output_value(candidate)


def _candidate_structured_output(
    final_result: Dict[str, Any],
    result_key: Optional[str],
    results: Dict[str, Any],
    output_schema: Any,
    current_url: str,
) -> Any:
    candidate = _candidate_extract_output(final_result, result_key, results)
    if candidate in (None, ""):
        candidate = final_result
    return _normalize_value_for_schema(candidate, output_schema, current_url)


def _normalize_value_for_schema(value: Any, schema: Any, current_url: str) -> Any:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return _normalize_output_value(value)
    if isinstance(value, dict):
        normalized = dict(value)
    elif value in (None, ""):
        normalized = {}
    else:
        normalized = {"value": value}

    required = set(schema.get("required") or [])
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    wants_url = "url" in required or "url" in properties
    if wants_url and not isinstance(normalized.get("url"), str):
        target = _extract_navigation_target_from_value(current_url, normalized) or str(current_url or "").strip()
        if target:
            normalized["url"] = target

    if "name" in required and not str(normalized.get("name") or "").strip() and isinstance(normalized.get("url"), str):
        normalized["name"] = _name_from_url(normalized["url"])

    if "reason" in required and not str(normalized.get("reason") or "").strip():
        normalized["reason"] = str(
            normalized.get("selection_reason")
            or normalized.get("explanation")
            or normalized.get("summary")
            or "Selected by runtime AI instruction."
        )

    return _normalize_output_value(normalized)


def _name_from_url(url: str) -> str:
    normalized = str(url or "").split("?", 1)[0].rstrip("/")
    parts = [part for part in normalized.split("/") if part]
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return normalized or "selected_target"


def _runtime_schema_matches(value: Any, schema: Any) -> bool:
    if schema is None or not isinstance(schema, dict):
        return True
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            return False
        return all(field in value for field in (schema.get("required") or []))
    if expected_type == "array":
        if not isinstance(value, list):
            return False
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        required = item_schema.get("required") or []
        for item in value:
            if not isinstance(item, dict):
                return False
            if not all(field in item for field in required):
                return False
        return True
    return True


def _build_extract_schema_replan_feedback(schema: Any, actual: Any) -> str:
    return (
        "Previous extract plan returned output that did not match output_expectation.schema. "
        f"Required schema: {json.dumps(schema, ensure_ascii=False, default=str)}. "
        f"Actual output excerpt: {_compact_text(actual, 240)}. "
        "Return a corrected replacement plan whose output is native JSON matching the schema exactly. "
        "For object schemas return a dict/object, for array schemas return a list/array. Do not return prose."
    )


def _build_act_schema_replan_feedback(schema: Any, actual: Any) -> str:
    return (
        "Previous act-mode plan performed or attempted a browser action but did not produce structured output "
        "matching output_expectation.schema. "
        f"Required schema: {json.dumps(schema, ensure_ascii=False, default=str)}. "
        f"Actual output excerpt: {_compact_text(actual, 240)}. "
        "Return a corrected replacement plan that performs the action and returns native JSON matching the schema. "
        "For selected projects/items, include url, name, and reason when requested."
    )


def _extract_navigation_target_from_value(current_url: str, value: Any) -> str:
    candidates = []
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return ""
        if (normalized.startswith("{") and normalized.endswith("}")) or (
            normalized.startswith("[") and normalized.endswith("]")
        ):
            try:
                parsed = json.loads(normalized)
            except Exception:
                parsed = None
            if parsed is not None:
                return _extract_navigation_target_from_value(current_url, parsed)
        candidates.append(normalized)
    elif isinstance(value, dict):
        for key in ("target_url", "url", "repo_url", "repo_path", "repo", "href", "path"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                candidates.append(candidate)
        for key in ("output", "data", "selected", "selection", "result"):
            nested = value.get(key)
            target = _extract_navigation_target_from_value(current_url, nested)
            if target:
                return target

    for candidate in candidates:
        stripped = candidate.strip()
        if not stripped:
            continue
        if stripped.startswith("/"):
            return urljoin(current_url or "", stripped)
        if stripped.startswith(("http://", "https://")):
            return stripped
    return ""


def _is_semantic_summary_extract_step(step: Dict[str, Any]) -> bool:
    if str(step.get("instruction_kind") or "").strip().lower() != "semantic_extract":
        return False
    output_mode = str((step.get("output_expectation") or {}).get("mode") or "").strip().lower()
    if output_mode != "extract":
        return False
    prompt = str(step.get("prompt") or "").strip().lower()
    return any(pattern in prompt for pattern in _SEMANTIC_SUMMARY_PROMPT_PATTERNS)


async def _acquire_semantic_summary_material(page, step: Dict[str, Any]) -> str:
    try:
        payload = await page.evaluate(
            """(selectors) => {
                const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
                const candidates = [];
                const seen = new Set();
                const addCandidate = (source, text) => {
                    const normalized = normalize(text);
                    if (!normalized || normalized.length < 80) return;
                    if (seen.has(normalized)) return;
                    seen.add(normalized);
                    candidates.push({ source, text: normalized });
                };

                const title = normalize(document.title || '');
                const metaDescription = normalize(document.querySelector('meta[name="description"]')?.content || '');
                const headings = Array.from(document.querySelectorAll('h1, h2'))
                    .map((el) => normalize(el.innerText || el.textContent || ''))
                    .filter(Boolean)
                    .slice(0, 8);

                for (const [source, selector] of selectors) {
                    const nodes = Array.from(document.querySelectorAll(selector)).slice(0, 3);
                    for (const node of nodes) {
                        addCandidate(source, node.innerText || node.textContent || '');
                    }
                }

                return {
                    title,
                    meta_description: metaDescription,
                    headings,
                    candidates,
                };
            }""",
            list(_SEMANTIC_CONTENT_SELECTORS),
        )
    except Exception:
        return ""

    if not isinstance(payload, dict):
        return ""

    parts = []
    if payload.get("title"):
        parts.append(f"Title: {_compact_text(payload.get('title'), 200)}")
    if payload.get("meta_description"):
        parts.append(f"Meta description: {_compact_text(payload.get('meta_description'), 400)}")

    headings = [str(item).strip() for item in (payload.get("headings") or []) if str(item).strip()]
    if headings:
        parts.append("Headings:\n- " + "\n- ".join(headings[:8]))

    candidates = list(payload.get("candidates") or [])
    if not candidates:
        return "\n\n".join(parts).strip()

    scored_candidates = sorted(
        (
            (
                (0 if candidate.get("source") == "body" else 2000)
                + min(len(str(candidate.get("text") or "")), 6000),
                candidate,
            )
            for candidate in candidates
        ),
        key=lambda item: item[0],
        reverse=True,
    )

    selected = []
    total_chars = 0
    for _, candidate in scored_candidates:
        text = str(candidate.get("text") or "").strip()
        if not text:
            continue
        excerpt = text[: min(len(text), 5000)]
        selected.append(f"[{candidate.get('source')}] {excerpt}")
        total_chars += len(excerpt)
        if len(selected) >= 2 or total_chars >= 7000:
            break

    if selected:
        parts.append("Extracted content:\n" + "\n\n".join(selected))

    return "\n\n".join(part for part in parts if part.strip()).strip()


async def _summarize_semantic_summary_material(
    step: Dict[str, Any],
    extracted_material: str,
    model_config: Optional[Dict[str, Any]] = None,
) -> str:
    model = get_llm_model(config=model_config, streaming=False)
    response = await model.ainvoke(
        [
            {"role": "system", "content": AI_INSTRUCTION_SUMMARY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "prompt": step.get("prompt", ""),
                        "instruction_kind": step.get("instruction_kind", "semantic_extract"),
                        "output_expectation": step.get("output_expectation") or {"mode": "extract"},
                        "extracted_material": extracted_material,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
    )
    return _extract_llm_response_text(response).strip()


def _validate_runtime_plan(step: Dict[str, Any], plan: Dict[str, Any]) -> None:
    plan_type = str(plan.get("plan_type", "")).strip().lower()
    if plan_type != "structured":
        return
    if _is_semantic_summary_extract_step(step):
        actions = list(plan.get("actions") or [])
        if any(str(action.get("action") or "").strip().lower() == "extract_text" for action in actions):
            raise ValueError(
                "Semantic summary extract requires code plan instead of structured extract_text actions"
            )


def _ensure_code_plan_is_allowed(code: str) -> None:
    normalized = code.lower()
    for token in _DISALLOWED_CODE_TOKENS:
        if token in normalized:
            raise ValueError(f"Disallowed code token in ai_instruction plan: {token}")


def _normalize_pythonish_code(code: str) -> str:
    replacements = {
        "true": "True",
        "false": "False",
        "null": "None",
    }
    tokens = []
    for token in tokenize.generate_tokens(io.StringIO(code).readline):
        token_type, token_string, start, end, line = token
        if token_type == tokenize.NAME and token_string in replacements:
            token_string = replacements[token_string]
        tokens.append((token_type, token_string))
    return tokenize.untokenize(tokens)


async def _execute_code_plan(page, code: str, results: Dict[str, Any]) -> Dict[str, Any]:
    if not code.strip():
        return {"success": False, "error": "Code plan is empty", "output": ""}

    try:
        _ensure_code_plan_is_allowed(code)
        normalized_code = _normalize_pythonish_code(code)

        namespace: Dict[str, Any] = {}
        exec(compile(normalized_code, "<ai_instruction>", "exec"), namespace)
        run = namespace.get("run")
        if not callable(run):
            return {"success": False, "error": "Code plan missing run(page, results)", "output": ""}

        outcome = await asyncio.wait_for(run(page, results), timeout=60)
    except asyncio.TimeoutError:
        return {"success": False, "error": "AI instruction code plan timed out after 60s", "output": ""}
    except SyntaxError as exc:
        return {"success": False, "error": f"SyntaxError: {exc}", "output": ""}
    except Exception as exc:
        return {"success": False, "error": str(exc), "output": ""}
    if isinstance(outcome, dict):
        return {
            "success": bool(outcome.get("success", True)),
            "output": _normalize_output_value(outcome.get("output", "")),
            "error": outcome.get("error"),
            **{k: v for k, v in outcome.items() if k not in {"success", "output", "error"}},
        }
    return {"success": True, "output": _normalize_output_value(str(outcome) if outcome is not None else "")}


async def _execute_blackboard_ref_ai_instruction(
    step: Dict[str, Any],
    results: Dict[str, Any],
    model_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    input_refs = [str(ref).strip() for ref in list(step.get("input_refs") or []) if str(ref).strip()]
    if not input_refs:
        return {
            "success": False,
            "error": "blackboard_ref input_scope requires input_refs",
            "output": "",
        }

    try:
        input_data = _resolve_input_refs(results, input_refs)
    except KeyError as exc:
        return {
            "success": False,
            "error": f"Missing blackboard ref: {exc}",
            "output": "",
        }

    model = get_llm_model(config=model_config, streaming=False)
    response = await model.ainvoke(
        [
            {"role": "system", "content": AI_INSTRUCTION_BLACKBOARD_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "prompt": step.get("prompt", ""),
                        "global_goal": step.get("global_goal", ""),
                        "instruction_kind": step.get("instruction_kind", "semantic_filter"),
                        "input_scope": step.get("input_scope") or {"mode": "blackboard_ref"},
                        "input_refs": input_refs,
                        "input_data": input_data,
                        "output_schema": (step.get("output_expectation") or {}).get("schema"),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ]
    )
    output = _parse_json_value_response(_extract_llm_response_text(response))
    result_key = step.get("result_key")
    if result_key:
        results[result_key] = output
    return {"success": True, "output": output}


async def _materialize_act_mode_result(
    page,
    final_result: Dict[str, Any],
    result_key: Optional[str],
    results: Dict[str, Any],
    before_observation: Optional[Dict[str, Any]],
) -> Tuple[bool, Dict[str, Any], str]:
    after_observation = await _capture_page_observation(page)
    action_performed = bool(final_result.get("action_performed"))
    if not action_performed and before_observation is not None:
        action_performed = _has_observable_page_change(before_observation, after_observation)

    if not action_performed:
        navigation_target = _extract_navigation_target_from_value(
            getattr(page, "url", "") or "",
            final_result,
        )
        if not navigation_target and result_key:
            navigation_target = _extract_navigation_target_from_value(
                getattr(page, "url", "") or "",
                results.get(result_key),
            )
        if navigation_target:
            try:
                await page.goto(navigation_target, wait_until="domcontentloaded")
                await page.wait_for_load_state("domcontentloaded")
            except Exception as exc:
                return (
                    False,
                    final_result,
                    f"selected navigation target {navigation_target} but navigation failed: {exc}",
                )
            after_observation = await _capture_page_observation(page)
            action_performed = bool(
                navigation_target.rstrip("/") == str(getattr(page, "url", "") or "").rstrip("/")
            )
            if not action_performed and before_observation is not None:
                action_performed = _has_observable_page_change(before_observation, after_observation)
            if action_performed:
                final_result["action_performed"] = True
                final_result["navigation_target"] = navigation_target

    if action_performed:
        if "navigation_target" not in final_result:
            observed_url = str(after_observation.get("url") or "").strip()
            if observed_url:
                final_result["navigation_target"] = observed_url
        return True, final_result, ""

    output = final_result.get("output", "")
    if output:
        return False, final_result, f"plan returned output without browser action: {output}"
    return False, final_result, "plan completed without observable browser action"


def _build_act_mode_replan_feedback(reason: str) -> str:
    return (
        f"Previous act-mode plan completed without an observable browser action: {reason}. "
        "This ai_instruction is in act mode, so the corrected replacement plan must perform a real "
        "browser click/navigation, return action_performed=true after doing the action, or return a "
        "direct navigation target using target_url, url, href, path, or repo_path."
    )


async def execute_ai_instruction(
    page,
    step: Dict[str, Any],
    results: Dict[str, Any],
    model_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    input_scope = step.get("input_scope") or {}
    input_mode = input_scope.get("mode")
    if input_mode == "blackboard_ref":
        return await _execute_blackboard_ref_ai_instruction(step, results, model_config=model_config)
    if input_mode != "current_page":
        return {
            "success": False,
            "error": f"Unsupported input_scope: {input_mode}",
            "output": "",
        }

    output_expectation = step.get("output_expectation") or {}
    output_schema = output_expectation.get("schema")
    result_key = step.get("result_key")
    act_mode = output_expectation.get("mode") == "act"

    if _is_semantic_summary_extract_step(step):
        extracted_material = await _acquire_semantic_summary_material(page, step)
        if extracted_material:
            planning_timeout_s = float(
                (step.get("execution_hint") or {}).get("planning_timeout_s") or AI_INSTRUCTION_PLAN_TIMEOUT_S
            )
            summary_attempt_materials = [extracted_material]
            trimmed_material = _trim_semantic_summary_material(extracted_material)
            if trimmed_material and trimmed_material != extracted_material:
                summary_attempt_materials.append(trimmed_material)

            for attempt_material in summary_attempt_materials:
                try:
                    summary = await asyncio.wait_for(
                        _summarize_semantic_summary_material(step, attempt_material, model_config=model_config),
                        timeout=planning_timeout_s,
                    )
                except (asyncio.TimeoutError, Exception):
                    continue

                normalized_summary = _normalize_output_value(summary)
                if normalized_summary not in (None, ""):
                    if result_key:
                        results[result_key] = normalized_summary
                    return {
                        "success": True,
                        "output": normalized_summary,
                    }

            fallback_summary = _normalize_output_value(
                _build_best_effort_summary_from_material(step, trimmed_material or extracted_material)
            )
            if fallback_summary not in (None, ""):
                if result_key:
                    results[result_key] = fallback_summary
                return {
                    "success": True,
                    "output": fallback_summary,
                }

    before_observation = await _capture_page_observation(page) if act_mode else None
    planning_timeout_s = float(
        (step.get("execution_hint") or {}).get("planning_timeout_s") or AI_INSTRUCTION_PLAN_TIMEOUT_S
    )
    current_step = dict(step)
    final_result: Dict[str, Any]

    for attempt in range(2):
        try:
            plan = await plan_ai_instruction(page, current_step, model_config=model_config)
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f"AI instruction planning timed out after {planning_timeout_s:.0f}s",
                "output": "",
            }
        except Exception as exc:
            return {
                "success": False,
                "error": f"AI instruction planning failed: {exc}",
                "output": "",
            }

        try:
            _validate_runtime_plan(current_step, plan)
        except ValueError as exc:
            if attempt == 0 and _is_retryable_code_plan_error(exc):
                current_step = {
                    **step,
                    "planning_feedback": (
                        f"Previous plan was rejected by runtime validation: {exc}. "
                        "Return a corrected replacement plan that uses code for semantic summarization and "
                        "keeps execution within Playwright page automation only."
                    ),
                }
                continue
            return {
                "success": False,
                "error": f"AI instruction planning failed: {exc}",
                "output": "",
            }

        plan_type = str(plan.get("plan_type", "")).strip().lower()

        try:
            if plan_type == "structured":
                actions = list(plan.get("actions") or [])
                if act_mode and not actions:
                    failure_reason = "AI instruction produced no executable actions for act mode"
                    if attempt == 0:
                        current_step = {
                            **step,
                            "planning_feedback": _build_act_mode_replan_feedback(failure_reason),
                        }
                        continue
                    return {"success": False, "error": failure_reason, "output": ""}
                snapshot = await build_page_snapshot(page, build_frame_path_from_frame)
                last_result: Dict[str, Any] = {"success": True, "output": ""}
                structured_action_performed = False
                action_observation_before = await _capture_page_observation(page)
                for index, action in enumerate(actions):
                    resolved = resolve_structured_intent(snapshot, action)
                    last_result = await execute_structured_intent(page, resolved, results=results)
                    if not last_result.get("success"):
                        return last_result
                    resolved_action = str(
                        resolved.get("action")
                        or resolved.get("type")
                        or action.get("action")
                        or ""
                    ).strip().lower()
                    if resolved_action in {"navigate", "click", "fill", "press"}:
                        structured_action_performed = True
                    if index == len(actions) - 1:
                        continue
                    action_observation_after = await _capture_page_observation(page)
                    if _has_observable_page_change(action_observation_before, action_observation_after):
                        snapshot = await build_page_snapshot(page, build_frame_path_from_frame)
                    action_observation_before = action_observation_after
                final_result = last_result
                if structured_action_performed and final_result.get("success") and act_mode:
                    final_result["action_performed"] = True
                if final_result.get("success") and act_mode:
                    action_ok, final_result, act_failure_reason = await _materialize_act_mode_result(
                        page,
                        final_result,
                        result_key,
                        results,
                        before_observation,
                    )
                    if not action_ok:
                        if attempt == 0:
                            current_step = {
                                **step,
                                "planning_feedback": _build_act_mode_replan_feedback(act_failure_reason),
                            }
                            continue
                        return {
                            "success": False,
                            "error": "AI instruction completed with no observable action in act mode",
                            "output": final_result.get("output", ""),
                        }
                    if result_key and output_schema:
                        candidate = _candidate_structured_output(
                            final_result,
                            result_key,
                            results,
                            output_schema,
                            getattr(page, "url", "") or "",
                        )
                        if not _runtime_schema_matches(candidate, output_schema):
                            if attempt == 0:
                                current_step = {
                                    **step,
                                    "planning_feedback": _build_act_schema_replan_feedback(output_schema, candidate),
                                }
                                continue
                            return {
                                "success": False,
                                "error": "AI instruction act output does not match schema",
                                "output": candidate,
                            }
                        final_result["output"] = candidate
                        results[result_key] = candidate
                if final_result.get("success") and output_expectation.get("mode") == "extract":
                    candidate = _candidate_extract_output(final_result, result_key, results)
                    if not _runtime_schema_matches(candidate, output_schema):
                        if attempt == 0:
                            current_step = {
                                **step,
                                "planning_feedback": _build_extract_schema_replan_feedback(output_schema, candidate),
                            }
                            continue
                        return {
                            "success": False,
                            "error": "AI instruction output does not match extract schema",
                            "output": candidate,
                        }
                    if candidate not in (None, ""):
                        final_result["output"] = candidate
                        if result_key:
                            results[result_key] = candidate
                break
            if plan_type == "code":
                final_result = await _execute_code_plan(page, plan.get("code", ""), results)
                if not final_result.get("success") and attempt == 0 and _is_retryable_execution_error(final_result.get("error", "")):
                    current_step = {
                        **step,
                        "planning_feedback": (
                            f"Previous code plan failed during execution: {final_result.get('error')}. "
                            "Return a corrected replacement plan that avoids invalid Python syntax, "
                            "invalid page.evaluate JavaScript, and uses Playwright APIs safely. "
                            "If the failure was a strict mode violation while opening a selected link, "
                            "return target_url/url for runtime navigation or use an exact href selector, "
                            "not a broad a[href*=...] selector."
                        ),
                    }
                    continue
                if final_result.get("success") and act_mode:
                    action_ok, final_result, act_failure_reason = await _materialize_act_mode_result(
                        page,
                        final_result,
                        result_key,
                        results,
                        before_observation,
                    )
                    if not action_ok:
                        if attempt == 0:
                            current_step = {
                                **step,
                                "planning_feedback": _build_act_mode_replan_feedback(act_failure_reason),
                            }
                            continue
                        return {
                            "success": False,
                            "error": "AI instruction completed with no observable action in act mode",
                            "output": final_result.get("output", ""),
                        }
                    if result_key and output_schema:
                        candidate = _candidate_structured_output(
                            final_result,
                            result_key,
                            results,
                            output_schema,
                            getattr(page, "url", "") or "",
                        )
                        if not _runtime_schema_matches(candidate, output_schema):
                            if attempt == 0:
                                current_step = {
                                    **step,
                                    "planning_feedback": _build_act_schema_replan_feedback(output_schema, candidate),
                                }
                                continue
                            return {
                                "success": False,
                                "error": "AI instruction act output does not match schema",
                                "output": candidate,
                            }
                        final_result["output"] = candidate
                        results[result_key] = candidate
                if final_result.get("success") and output_expectation.get("mode") == "extract":
                    candidate = _candidate_extract_output(final_result, result_key, results)
                    if not _runtime_schema_matches(candidate, output_schema):
                        if attempt == 0:
                            current_step = {
                                **step,
                                "planning_feedback": _build_extract_schema_replan_feedback(output_schema, candidate),
                            }
                            continue
                        return {
                            "success": False,
                            "error": "AI instruction output does not match extract schema",
                            "output": candidate,
                        }
                    if candidate not in (None, ""):
                        final_result["output"] = candidate
                        if result_key:
                            results[result_key] = candidate
                break
            return {
                "success": False,
                "error": f"Unsupported plan_type: {plan_type}",
                "output": "",
            }
        except ValueError as exc:
            if attempt == 0 and _is_retryable_code_plan_error(exc):
                current_step = {
                    **step,
                    "planning_feedback": (
                        f"Previous plan was rejected by runtime validation: {exc}. "
                        "Return a corrected replacement plan that stays within Playwright page automation only."
                    ),
                }
                continue
            return {
                "success": False,
                "error": f"AI instruction planning failed: {exc}",
                "output": "",
            }
    else:
        return {
            "success": False,
            "error": "AI instruction planning failed: unable to produce a valid plan",
            "output": "",
        }

    if final_result.get("success") and output_expectation.get("mode") == "extract":
        normalized_output = _candidate_extract_output(final_result, result_key, results)
        if normalized_output not in (None, ""):
            final_result["output"] = normalized_output
            if result_key:
                results[result_key] = normalized_output

    if final_result.get("success") and result_key:
        normalized_output = _candidate_extract_output(final_result, result_key, results)
        if normalized_output not in (None, "") and _runtime_schema_matches(normalized_output, output_schema):
            final_result["output"] = normalized_output
            results[result_key] = normalized_output

    return final_result
