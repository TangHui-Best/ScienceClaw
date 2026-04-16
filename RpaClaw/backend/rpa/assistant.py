import json
import logging
import re
import asyncio
from typing import Dict, List, Any, AsyncGenerator, Optional, Callable
from urllib.parse import urljoin

from playwright.async_api import Page
from backend.deepagent.engine import get_llm_model
from backend.rpa.assistant_runtime import (
    build_frame_path_from_frame,
    build_page_snapshot,
    execute_structured_intent,
    resolve_structured_intent,
    resolve_collection_target,
)

# Active ReAct agent instances keyed by session_id
_active_agents: Dict[str, "RPAReActAgent"] = {}

logger = logging.getLogger(__name__)

ELEMENT_EXTRACTION_TIMEOUT_S = 5.0
EXECUTION_TIMEOUT_S = 60.0
THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
THINK_CONTENT_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)
EXPLICIT_AI_INSTRUCTION_PATTERNS = (
    "使用ai指令",
    "使用 ai 指令",
    "use ai instruction",
    "运行时 ai 指令",
    "运行时ai指令",
    "runtime ai instruction",
    "save as runtime ai instruction",
    "不要把它展开成固定脚本",
    "不要展开成固定脚本",
    "do not expand it into fixed script",
    "do not compile it into a fixed script",
)
AI_INSTRUCTION_DECISION_PATTERNS = (
    "最高",
    "最大",
    "最多",
    "最少",
    "最低",
    "最新",
    "最旧",
    "最相关",
    "最匹配",
    "highest",
    "largest",
    "most",
    "least",
    "latest",
    "oldest",
    "best match",
    "most relevant",
)
AI_INSTRUCTION_EXTRACT_HINT_PATTERNS = (
    "总结",
    "汇总",
    "提取",
    "读取",
    "筛选",
    "summarize",
    "summary",
    "extract",
    "read",
    "filter",
)

AI_INSTRUCTION_DEFAULT_MAX_REASONING_STEPS = 10
AI_INSTRUCTION_DEFAULT_PLANNING_TIMEOUT_S = 60
AI_INSTRUCTION_PLACEHOLDER_HINTS = (
    "short semantic-rule summary",
    "the originalrule instruction",
    "the original rule instruction",
    "semantic_rule|semantic_extract|semantic_decision",
    "act|extract",
    "ascii_snake_case_key_when_output_mode_is_extract",
)
REACT_COMPLEX_CONNECTOR_PATTERNS = (
    "然后",
    "再",
    "接着",
    "之后",
    "最后",
    "并且",
    "进去后",
    "返回后",
    " after ",
    " then ",
    " and then ",
)
REACT_COMPLEX_VERB_PATTERNS = (
    "打开",
    "进入",
    "点击",
    "查找",
    "找到",
    "总结",
    "提炼",
    "返回",
    "筛选",
    "open ",
    "click ",
    "summarize",
    "extract",
    "filter",
    "go back",
)
DETERMINISTIC_SCRIPT_STEP_PATTERNS = (
    "最高",
    "最大",
    "最多",
    "最少",
    "latest",
    "highest",
    "largest",
    "most",
    "least",
    "star",
    "stars",
    "数量",
    "排序",
    "比较",
    "ranking",
    "compare",
    "sort",
    "filter",
)

BATCH_ARRAY_EXTRACTION_PATTERNS = (
    "前10",
    "前 10",
    "top 10",
    "first 10",
    "strict array",
    "strictly array",
    "输出严格为数组",
    "严格为数组",
    "数组",
    "array",
    "title",
    "author",
    "creator",
    "标题",
    "创建人",
)

REACT_SEMANTIC_SUMMARY_PATTERNS = (
    "总结",
    "概括",
    "提炼",
    "归纳",
    "核心内容",
    "核心信息",
    "主要功能",
    "主要特点",
    "技术栈",
    "用途",
    "目标用户",
    "summarize",
    "summary",
    "overview",
    "describe",
    "core content",
    "core information",
)

JS_CODE_GUARD_PATTERNS = (
    "const ",
    "let ",
    "var ",
    "=>",
    "document.queryselector",
    "document.queryselectorall",
    "window.location",
    ".map(",
    ".filter(",
    ".reduce(",
)


# JS to extract interactive elements from the page
EXTRACT_ELEMENTS_JS = r"""() => {
    const INTERACTIVE = 'a,button,input,textarea,select,[role=button],[role=link],[role=menuitem],[role=menuitemradio],[role=tab],[role=checkbox],[role=radio],[contenteditable=true]';
    const els = document.querySelectorAll(INTERACTIVE);
    const results = [];
    let index = 1;
    const seen = new Set();
    for (const el of els) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        if (el.disabled) continue;
        const style = getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

        const tag = el.tagName.toLowerCase();
        const role = el.getAttribute('role') || '';
        const name = (el.getAttribute('aria-label') || el.innerText || '').trim().substring(0, 80);
        const placeholder = el.getAttribute('placeholder') || '';
        const href = el.getAttribute('href') || '';
        const value = el.value || '';
        const type = el.getAttribute('type') || '';

        const key = tag + role + name + placeholder + href;
        if (seen.has(key)) continue;
        seen.add(key);

        const info = { index, tag };
        if (role) info.role = role;
        if (name) info.name = name.replace(/\s+/g, ' ');
        if (placeholder) info.placeholder = placeholder;
        if (href) info.href = href.substring(0, 120);
        if (value && tag !== 'input') info.value = value.substring(0, 80);
        if (type) info.type = type;
        const checked = el.checked;
        if (checked !== undefined) info.checked = checked;

        results.push(info);
        index++;
        if (index > 150) break;
    }
    return JSON.stringify(results);
}"""

SYSTEM_PROMPT = """You are an RPA recording assistant.

Prefer returning a structured JSON action instead of raw Playwright code.

For common atomic actions, respond with JSON in this shape:
{
  "action": "navigate|click|fill|extract_text|press",
  "description": "short action summary",
  "prompt": "original user instruction",
  "result_key": "short_ascii_snake_case_key_for_extracted_value",
  "target_hint": {
    "role": "button|link|textbox|...",
    "name": "semantic label if known"
  },
  "collection_hint": {
    "kind": "search_results|table_rows|cards"
  },
  "ordinal": "first|last|1|2|3",
  "value": "text to fill or key to press when relevant"
}

Rules:
1. If the user says first or nth, use collection semantics and avoid hard-coded dynamic content.
2. Prefer role, label, placeholder, and structural hints over concrete titles or dynamic href values.
3. For opening a website or navigating to a known URL, prefer `"action": "navigate"` with the URL in `value`. Do not model browser chrome such as the address bar as a page textbox.
4. The backend resolves frame context automatically, so do not invent iframe selectors unless the user explicitly names a frame.
5. Only output Python code for genuinely complex custom logic that cannot be expressed as one atomic structured action.
6. If you output Python, define async def run(page): and use Playwright async API.
7. For extract_text actions, include result_key as a short ASCII snake_case key such as latest_issue_title. Do not use Chinese, spaces, or hyphens.
8. If the user explicitly says to save the rule as a runtime AI instruction, or says not to expand it into a fixed script, you must return:
{
  "action": "ai_instruction",
  "description": "short semantic-rule summary",
  "prompt": "the original rule instruction",
  "instruction_kind": "semantic_rule|semantic_extract|semantic_decision",
  "input_scope": { "mode": "current_page" },
  "output_expectation": { "mode": "act|extract" },
  "execution_hint": {
    "requires_dom_snapshot": true,
    "allow_navigation": true,
    "max_reasoning_steps": 10
  },
  "result_key": "ascii_snake_case_key_when_output_mode_is_extract"
}
9. When the user explicitly requests a runtime AI instruction, do not convert it into extract_text, click/fill steps, or fixed Playwright code.
10. Do not use ai_instruction for deterministic ranking, numeric comparison, fixed filtering, or explicit field-based selection that can be implemented as a stable script.
11. Use ai_instruction only when correctness depends on runtime semantic understanding of the current page or business meaning, not merely because the scripted logic is somewhat complex.

Examples:
- User: "总结当前项目的核心信息，并提炼用途、能力和限制"
  Response:
  {
    "action": "ai_instruction",
    "description": "总结当前项目的核心信息",
    "prompt": "总结当前项目的核心信息，并提炼用途、能力和限制",
    "instruction_kind": "semantic_extract",
    "input_scope": { "mode": "current_page" },
    "output_expectation": { "mode": "extract" },
    "execution_hint": {
      "requires_dom_snapshot": true,
      "allow_navigation": false,
      "max_reasoning_steps": 10
    },
    "result_key": "project_summary"
  }

- User: "根据当前页面展示的信息，判断这条记录是否需要人工复核；如果需要，则打开详情页"
  Response:
  {
    "action": "ai_instruction",
    "description": "判断当前记录是否需要人工复核并在需要时打开详情",
    "prompt": "根据当前页面展示的信息，判断这条记录是否需要人工复核；如果需要，则打开详情页",
    "instruction_kind": "semantic_decision",
    "input_scope": { "mode": "current_page" },
    "output_expectation": { "mode": "act" },
    "execution_hint": {
      "requires_dom_snapshot": true,
      "allow_navigation": true,
      "max_reasoning_steps": 10
    }
  }

- User: "找到当前页面 star 数量最高的项目并点击打开它"
  Response:
  {
    "action": "code",
    "description": "use deterministic scripted logic instead of ai_instruction because this is an explicit numeric comparison",
    "code": "async def run(page): ..."
  }

Legacy examples below are backward-compatibility references. If they conflict with rules 10 and 11 or with the newer examples above, prefer the newer examples and the explicit rules.

- User: "总结当前项目内容"
  Response:
  {
    "action": "ai_instruction",
    "description": "总结当前项目内容",
    "prompt": "总结当前项目内容",
    "instruction_kind": "semantic_extract",
    "input_scope": { "mode": "current_page" },
    "output_expectation": { "mode": "extract" },
    "execution_hint": {
      "requires_dom_snapshot": true,
      "allow_navigation": false,
      "max_reasoning_steps": 10
    },
    "result_key": "project_summary"
  }

- User: "在当前页面中找出最符合规则的一项并点击进入"
  Response:
  {
    "action": "ai_instruction",
    "description": "在当前页面中找出最符合规则的一项并点击进入",
    "prompt": "在当前页面中找出最符合规则的一项并点击进入",
    "instruction_kind": "semantic_decision",
    "input_scope": { "mode": "current_page" },
    "output_expectation": { "mode": "act" },
    "execution_hint": {
      "requires_dom_snapshot": true,
      "allow_navigation": true,
      "max_reasoning_steps": 10
    }
  }
"""

async def _get_page_elements(page: Page) -> str:
    """Extract interactive elements directly from the page."""
    try:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=2000)
        except Exception:
            pass
        result = await asyncio.wait_for(
            page.evaluate(EXTRACT_ELEMENTS_JS),
            timeout=ELEMENT_EXTRACTION_TIMEOUT_S,
        )
        return result if isinstance(result, str) else json.dumps(result)
    except Exception as e:
        logger.warning(f"Failed to extract elements from {page.url!r}: {e}")
        return "[]"


def should_use_react_mode(user_message: str, requested_mode: str = "chat") -> bool:
    mode = (requested_mode or "chat").strip().lower()
    if mode == "react":
        return True

    normalized = f" {(user_message or '').strip().lower()} "
    if not normalized.strip():
        return False

    if any(pattern in normalized for pattern in REACT_COMPLEX_CONNECTOR_PATTERNS):
        return True

    matched_verbs = sum(1 for pattern in REACT_COMPLEX_VERB_PATTERNS if pattern in normalized)
    if matched_verbs >= 2 and ("，" in normalized or "," in normalized):
        return True

    return False


def _react_step_requires_scripted_logic(
    thought: str,
    description: str,
    structured_intent: Optional[Dict[str, Any]],
) -> bool:
    if not structured_intent:
        return False
    action = str(structured_intent.get("action") or "").strip().lower()
    normalized = f"{thought} {description}".strip().lower()

    if action == "click":
        return any(pattern in normalized for pattern in DETERMINISTIC_SCRIPT_STEP_PATTERNS)

    if action == "extract_text":
        has_batch_shape = any(pattern in normalized for pattern in BATCH_ARRAY_EXTRACTION_PATTERNS)
        has_collection_signal = any(pattern in normalized for pattern in ("list", "items", "pull request", "pr", "rows", "列表", "前", "first"))
        return has_batch_shape and has_collection_signal

    return False


def _react_step_requires_ai_instruction(
    thought: str,
    description: str,
    structured_intent: Optional[Dict[str, Any]],
    ai_instruction_step: Optional[Dict[str, Any]],
    code: str,
) -> bool:
    if ai_instruction_step:
        return False
    if structured_intent:
        return False
    if not code.strip():
        return False

    normalized = f"{thought} {description}".strip().lower()
    return any(pattern in normalized for pattern in REACT_SEMANTIC_SUMMARY_PATTERNS)


def _react_step_leaks_summary_helper_to_outer_trace(
    thought: str,
    description: str,
    structured_intent: Optional[Dict[str, Any]],
    ai_instruction_step: Optional[Dict[str, Any]],
    code: str,
) -> bool:
    if ai_instruction_step:
        return False

    normalized = f"{thought} {description}".strip().lower()
    if not any(pattern in normalized for pattern in REACT_SEMANTIC_SUMMARY_PATTERNS):
        return False

    payload_parts: List[str] = [normalized]
    if structured_intent:
        payload_parts.append(json.dumps(structured_intent, ensure_ascii=False))
    if code.strip():
        payload_parts.append(code)
    payload = " ".join(payload_parts).lower()

    helper_markers = (
        "readme",
        "readme.md",
        "blob/main/readme",
        "raw readme",
        "markdown-body",
        "project description",
        "view the documentation",
        "extract text from the readme",
        "提取 readme",
        "读取 readme",
        "点击 readme",
        "导航到 readme",
    )
    return any(marker in payload for marker in helper_markers)


def _step_text_blob(step: Dict[str, Any]) -> str:
    parts: List[str] = []
    # For step distillation, classify a step by its own persisted semantics rather
    # than by the original goal prompt. React trace steps often carry the full user
    # goal in `prompt`, which can contain later words like "总结/summary" and would
    # incorrectly make earlier navigate/ranking steps look like summary steps.
    for key in ("description", "instruction_kind", "result_key"):
        value = step.get(key)
        if value:
            parts.append(str(value))

    value = step.get("value")
    if isinstance(value, str) and value:
        parts.append(value)

    target = step.get("target")
    if isinstance(target, str) and target:
        parts.append(target)
    elif isinstance(target, dict):
        parts.append(json.dumps(target, ensure_ascii=False))

    return " ".join(parts).strip().lower()


def _is_semantic_summary_step(step: Dict[str, Any]) -> bool:
    blob = _step_text_blob(step)
    if not blob:
        return False
    return any(pattern in blob for pattern in REACT_SEMANTIC_SUMMARY_PATTERNS)


def _is_summary_helper_step(step: Dict[str, Any]) -> bool:
    blob = _step_text_blob(step)
    if not blob:
        return False

    action = str(step.get("action") or "").strip().lower()
    if "readme" in blob:
        return True
    if action == "navigate" and "blob/main/readme" in blob:
        return True
    if action in {"extract_text", "ai_script"} and any(
        pattern in blob for pattern in ("提取", "读取", "extract", "read", "markdown-body", "正文", "内容")
    ):
        return True
    return False


def _step_signature(step: Dict[str, Any]) -> str:
    action = str(step.get("action") or "").strip().lower()
    if action == "ai_instruction" and _is_semantic_summary_step(step):
        return "ai_instruction:semantic_summary"
    if action == "ai_script" and _is_summary_helper_step(step):
        return "ai_script:summary_helper"

    signature_source = {
        "action": action,
        "description": step.get("description"),
        "prompt": step.get("prompt"),
        "instruction_kind": step.get("instruction_kind"),
        "target": step.get("target"),
        "value": step.get("value") if isinstance(step.get("value"), str) else None,
    }
    return json.dumps(signature_source, ensure_ascii=False, sort_keys=True, default=str)


def _distill_react_recorded_steps(goal: str, trace_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not trace_steps:
        return []

    distilled: List[Dict[str, Any]] = []
    last_summary_index = -1
    for idx, step in enumerate(trace_steps):
        if _is_semantic_summary_step(step):
            last_summary_index = idx

    for idx, step in enumerate(trace_steps):
        if last_summary_index != -1 and idx < last_summary_index and _is_summary_helper_step(step):
            continue
        if last_summary_index != -1 and idx != last_summary_index and _is_semantic_summary_step(step):
            continue

        signature = _step_signature(step)
        if distilled and _step_signature(distilled[-1]) == signature:
            distilled[-1] = step
            continue
        distilled.append(step)

    return distilled


def _looks_like_navigation_target(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    return normalized.startswith("/") or normalized.startswith("http://") or normalized.startswith("https://")


def _extract_ai_script_navigation_target(current_url: str, raw_output: Any) -> str:
    candidates: List[str] = []
    if isinstance(raw_output, str):
        candidates.append(raw_output)
    elif isinstance(raw_output, dict):
        for key in ("target_url", "url", "repo_url", "repo_path", "repo", "href", "path"):
            value = raw_output.get(key)
            if isinstance(value, str):
                candidates.append(value)
        output_value = raw_output.get("output")
        if isinstance(output_value, str):
            candidates.append(output_value)

    for candidate in candidates:
        normalized = candidate.strip()
        if not _looks_like_navigation_target(normalized):
            continue
        if normalized.startswith("/"):
            return urljoin(current_url or "", normalized)
        return normalized
    return ""


def _looks_like_javascript_code(code: str) -> bool:
    normalized = (code or "").strip().lower()
    if not normalized:
        return False
    if normalized.startswith("async def run(") or normalized.startswith("def run("):
        return False
    return any(pattern in normalized for pattern in JS_CODE_GUARD_PATTERNS)


async def _execute_on_page(page: Page, code: str) -> Dict[str, Any]:
    """Execute AI-generated code directly on the page object."""
    try:
        await page.evaluate("window.__rpa_paused = true")
    except Exception:
        pass
    try:
        namespace: Dict[str, Any] = {"page": page}
        exec(compile(code, "<rpa_assistant>", "exec"), namespace)
        if "run" in namespace and callable(namespace["run"]):
            ret = await asyncio.wait_for(namespace["run"](page), timeout=EXECUTION_TIMEOUT_S)
            if ret is None:
                output = "ok"
            elif isinstance(ret, (dict, list)):
                output = json.dumps(ret, ensure_ascii=False, default=str)
            else:
                output = str(ret)
            return {"success": True, "output": output, "raw_output": ret, "error": None}
        else:
            return {"success": False, "output": "", "error": "No run(page) function defined"}
    except asyncio.TimeoutError:
        return {"success": False, "output": "", "error": f"Command execution timed out ({EXECUTION_TIMEOUT_S:.0f}s)"}
    except Exception:
        import traceback
        return {"success": False, "output": "", "error": traceback.format_exc()}
    finally:
        try:
            await page.evaluate("window.__rpa_paused = false")
        except Exception:
            pass


def _extract_llm_response_text(response: Any) -> str:
    """Normalize LangChain AIMessage content into a plain text response."""
    content = getattr(response, "content", "")
    additional_kwargs = getattr(response, "additional_kwargs", {}) or {}

    reasoning = additional_kwargs.get("reasoning_content", "")
    fallback_text = reasoning.strip() if isinstance(reasoning, str) else ""

    if isinstance(content, list):
        text_parts: List[str] = []
        thinking_parts: List[str] = []
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type", "")
                if block_type == "thinking":
                    thinking_parts.append(str(block.get("thinking", "")).strip())
                    continue
                text = block.get("text") or block.get("content")
                if text:
                    text_parts.append(str(text))
            elif isinstance(block, str):
                text_parts.append(block)
            elif block is not None:
                text_parts.append(str(block))
        clean = "\n".join(part.strip() for part in text_parts if str(part).strip()).strip()
        if clean:
            return clean
        thoughts = "\n".join(part for part in thinking_parts if part).strip()
        return thoughts or fallback_text

    if isinstance(content, str):
        clean = THINK_TAG_RE.sub("", content).strip()
        if clean:
            return clean
        if not fallback_text:
            matches = THINK_CONTENT_RE.findall(content)
            fallback_text = "\n".join(match.strip() for match in matches if match.strip()).strip()
        return fallback_text

    if content is None:
        return fallback_text

    text = str(content).strip()
    return text or fallback_text


def _extract_llm_chunk_text(chunk: Any) -> str:
    """Extract displayable text from a streamed chunk."""
    content = getattr(chunk, "content", "")
    if isinstance(content, list):
        text_parts: List[str] = []
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type", "")
                if block_type == "thinking":
                    continue
                text = block.get("text") or block.get("content")
                if text:
                    text_parts.append(str(text))
            elif isinstance(block, str):
                text_parts.append(block)
            elif block is not None:
                text_parts.append(str(block))
        return "".join(text_parts)
    if isinstance(content, str):
        return THINK_TAG_RE.sub("", content)
    return ""


def _extract_llm_chunk_fallback_text(chunk: Any) -> str:
    """Extract reasoning/thinking fallback text from a streamed chunk."""
    additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
    reasoning = additional_kwargs.get("reasoning_content", "")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning.strip()

    content = getattr(chunk, "content", "")
    if isinstance(content, list):
        thoughts: List[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                thought = str(block.get("thinking", "")).strip()
                if thought:
                    thoughts.append(thought)
        return "\n".join(thoughts).strip()

    if isinstance(content, str):
        matches = THINK_CONTENT_RE.findall(content)
        return "\n".join(match.strip() for match in matches if match.strip()).strip()

    return ""


def _snapshot_frame_lines(snapshot: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for container in snapshot.get("containers", []):
        lines.append(
            "Container: "
            f"{container.get('container_kind', 'container')} "
            f"{container.get('name', '')} "
            f"(actionable={len(container.get('child_actionable_ids') or [])}, "
            f"content={len(container.get('child_content_ids') or [])})"
        )
    for frame in snapshot.get("frames", []):
        lines.append(f"Frame: {frame.get('frame_hint', 'main document')}")
        for collection in frame.get("collections", []):
            lines.append(
                f"  Collection: {collection.get('kind', 'collection')} ({collection.get('item_count', 0)} items)"
            )
        for element in frame.get("elements", []):
            parts = [f"[{element.get('index', '?')}]"]
            if element.get("role"):
                parts.append(element["role"])
            parts.append(element.get("tag", "element"))
            if element.get("name"):
                parts.append(f'"{element["name"]}"')
            if element.get("placeholder"):
                parts.append(f'placeholder="{element["placeholder"]}"')
            if element.get("href"):
                parts.append(f'href="{element["href"]}"')
            if element.get("type"):
                parts.append(f'type={element["type"]}')
            lines.append("  " + " ".join(parts))
    return lines


REACT_SYSTEM_PROMPT = """You are an RPA automation agent.

You receive a goal and must iteratively observe the current page, decide the next small step, execute it, and continue until the goal is complete.

The final recorded result must be a sequence of existing RPA step types:
- structured step for atomic browser actions
- ai_script for deterministic scripted logic
- ai_instruction only when a single step truly requires runtime semantic understanding

Do not collapse the whole goal into one giant ai_instruction. Break complex goals into multiple small executable steps.

Return exactly one JSON object per turn, not wrapped in markdown.

Preferred format:
{
  "thought": "brief reasoning about the current page and next step",
  "action": "execute|done|abort",
  "operation": "navigate|click|fill|extract_text|press",
  "description": "short action summary",
  "result_key": "short_ascii_snake_case_key_for_extracted_value",
  "target_hint": {
    "role": "button|link|textbox|...",
    "name": "semantic label if known"
  },
  "collection_hint": {
    "kind": "search_results|table_rows|cards"
  },
  "ordinal": "first|last|1|2|3",
  "value": "text to fill or key to press when relevant",
  "code": "async def run(page): ... when deterministic scripted logic is needed",
  "ai_instruction": {
    "description": "short semantic step summary",
    "prompt": "the rule for this one step only",
    "instruction_kind": "semantic_rule|semantic_extract|semantic_decision",
    "input_scope": { "mode": "current_page" },
    "output_expectation": { "mode": "act|extract" },
    "execution_hint": {
      "requires_dom_snapshot": true,
      "allow_navigation": true,
      "max_reasoning_steps": 10
    },
    "result_key": "ascii_snake_case_key_when_output_mode_is_extract"
  },
  "risk": "none|high",
  "risk_reason": "required when risk is high"
}

Rules:
1. Each turn should plan only the next small step, not the entire goal.
2. Prefer structured atomic actions with operation/target_hint/collection_hint over raw Playwright code.
3. Use ai_script code only for deterministic scripted logic such as ranking, sorting, numeric comparison, fixed filtering, or looping over stable page structures.
4. Use ai_instruction only for a single step whose correctness depends on runtime semantic understanding of the current page or business meaning.
5. For summary/explanation/judgment tasks, the ai_instruction prompt should describe only that local semantic step, not the entire original goal.
6. Use collection semantics for first, last, and nth requests. Do not hard-code dynamic titles or href values.
7. For opening a website or jumping to a known URL, use operation=navigate with the URL in value. Do not refer to the browser address bar as a page textbox.
8. The backend resolves iframe context automatically from the snapshot. Do not invent iframe selectors unless the user explicitly names a frame.
9. Only use the code field for custom Playwright code when the action cannot be expressed as one atomic structured action.
10. For irreversible operations such as submit, delete, pay, or authorize, set risk to high.
11. For extraction tasks, use operation=extract_text, describe what data is being extracted, and include result_key as a short ASCII snake_case key such as latest_issue_title.
12. Do not mark the task done just because the data is visible on the page.
13. Execute the extraction step first and return the extracted value.
14. For example, if the user asks to get or read a title, first run extract_text on the target element, set result_key to something like latest_issue_title, then summarize the extracted value in description.
15. For deterministic "find the best item and open it" steps, prefer ai_script that returns the selected target URL/path (or a dict containing target_url/repo_path) after computing the choice. Do not hard-code that chosen item into later summary prompts.
16. When a summary step follows navigation, summarize the current page/repository generically. Do not bake a specific repo name or URL into the ai_instruction prompt.
17. The code field must contain Python async Playwright code only. Never return JavaScript, browser-page scripts, or page.evaluate-style code in the code field.
"""




class RPAReActAgent:
    """ReAct-based autonomous agent: Observe → Think → Act loop."""

    MAX_STEPS = 20

    def __init__(self):
        self._confirm_event: Optional[asyncio.Event] = None
        self._confirm_approved: bool = False
        self._aborted: bool = False
        self._history: List[Dict[str, str]] = []  # persists across turns

    def resolve_confirm(self, approved: bool) -> None:
        self._confirm_approved = approved
        if self._confirm_event:
            self._confirm_event.set()

    def abort(self) -> None:
        self._aborted = True
        if self._confirm_event:
            self._confirm_event.set()

    async def run(
        self,
        session_id: str,
        page: Page,
        goal: str,
        existing_steps: List[Dict[str, Any]],
        model_config: Optional[Dict[str, Any]] = None,
        page_provider: Optional[Callable[[], Optional[Page]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        self._aborted = False
        steps_done = 0
        successful_trace_steps: List[Dict[str, Any]] = []

        # Append new user goal to persistent history
        steps_summary = ""
        if existing_steps:
            lines = [f"{i+1}. {s.get('description', s.get('action', ''))}" for i, s in enumerate(existing_steps)]
            steps_summary = "\nExisting steps:\n" + "\n".join(lines) + "\n"
        self._history.append({"role": "user", "content": f"Goal: {goal}{steps_summary}"})

        for iteration in range(self.MAX_STEPS):
            if self._aborted:
                yield {"event": "agent_aborted", "data": {"reason": "用户中止"}}
                return

            # Observe
            current_page = page_provider() if page_provider else page
            if current_page is None:
                yield {"event": "agent_aborted", "data": {"reason": "No active page available"}}
                return
            snapshot = await build_page_snapshot(current_page, build_frame_path_from_frame)
            obs = self._build_observation(snapshot, steps_done)
            self._history.append({"role": "user", "content": obs})

            # Think — stream LLM response
            full_response = ""
            async for chunk in self._stream_llm(self._history, model_config):
                full_response += chunk

            self._history.append({"role": "assistant", "content": full_response})

            # Parse JSON
            parsed = self._parse_json(full_response)
            if not parsed:
                yield {"event": "agent_aborted", "data": {"reason": f"Unable to parse agent response: {full_response[:200]}"}}
                return

            thought = parsed.get("thought", "")
            action = parsed.get("action", "execute")
            structured_intent = self._extract_structured_execute_intent(parsed, goal)
            ai_instruction_step = self._extract_execute_ai_instruction(parsed, goal)
            code = parsed.get("code", "")
            description = parsed.get("description", "Execute step")
            risk = parsed.get("risk", "none")
            risk_reason = parsed.get("risk_reason", "")
            action_payload = code or ""
            if structured_intent:
                action_payload = json.dumps(structured_intent, ensure_ascii=False)
            elif ai_instruction_step:
                action_payload = json.dumps(ai_instruction_step, ensure_ascii=False)

            if action == "done":
                if thought:
                    yield {"event": "agent_thought", "data": {"text": thought}}
                recorded_steps = _distill_react_recorded_steps(goal, successful_trace_steps)
                yield {"event": "agent_recorded_steps", "data": {"steps": recorded_steps}}
                yield {"event": "agent_done", "data": {"total_steps": steps_done}}
                return

            if action == "abort":
                if thought:
                    yield {"event": "agent_thought", "data": {"text": thought}}
                yield {"event": "agent_aborted", "data": {"reason": thought}}
                return

            if _react_step_requires_scripted_logic(thought, description, structured_intent):
                self._history.append(
                    {
                        "role": "user",
                        "content": (
                            "Previous step proposal was rejected. "
                            "This next step involves deterministic ranking/comparison/filtering logic, "
                            "so return code for this one step instead of a direct structured click."
                        ),
                    }
                )
                continue

            if _react_step_requires_ai_instruction(
                thought,
                description,
                structured_intent,
                ai_instruction_step,
                code,
            ):
                self._history.append(
                    {
                        "role": "user",
                        "content": (
                            "Previous step proposal was rejected. "
                            "This next step is a semantic summary/judgment task, "
                            "so return a single-step ai_instruction instead of raw code extraction."
                        ),
                    }
                )
                continue

            if _react_step_leaks_summary_helper_to_outer_trace(
                thought,
                description,
                structured_intent,
                ai_instruction_step,
                code,
            ):
                self._history.append(
                    {
                        "role": "user",
                        "content": (
                            "Previous step proposal was rejected. "
                            "For semantic summary tasks, do not add external helper steps like clicking README, "
                            "navigating to README/raw docs, or extracting README text as separate recorded steps. "
                            "Return a single-step ai_instruction for the summary task instead; any content fallback "
                            "must stay internal to runtime execution."
                        ),
                    }
                )
                continue

            if code.strip() and _looks_like_javascript_code(code):
                self._history.append(
                    {
                        "role": "user",
                        "content": (
                            "Previous step proposal was rejected. "
                            "The code field must contain Python async Playwright code only. "
                            "Do not return JavaScript, browser-side scripts, or page.evaluate-style code. "
                            "Return Python code in the form async def run(page): ..."
                        ),
                    }
                )
                continue

            if thought:
                yield {"event": "agent_thought", "data": {"text": thought}}

            # High-risk confirmation
            if risk == "high":
                self._confirm_event = asyncio.Event()
                self._confirm_approved = False
                yield {"event": "confirm_required", "data": {
                    "description": description,
                    "risk_reason": risk_reason,
                    "code": action_payload,
                }}
                await self._confirm_event.wait()
                self._confirm_event = None
                if self._aborted:
                    yield {"event": "agent_aborted", "data": {"reason": "User aborted"}}
                    return
                if not self._confirm_approved:
                    self._history.append({"role": "user", "content": "User rejected that step. Continue with a safer next step or finish."})
                    continue

            # Act
            yield {
                "event": "agent_action",
                "data": {
                    "description": description,
                    "code": action_payload,
                },
            }
            current_page = page_provider() if page_provider else page
            if current_page is None:
                yield {"event": "agent_aborted", "data": {"reason": "No active page available"}}
                return
            if ai_instruction_step:
                from backend.rpa.runtime_ai_instruction import execute_ai_instruction

                result = await execute_ai_instruction(current_page, ai_instruction_step, results={})
            elif structured_intent:
                resolved_intent = resolve_structured_intent(snapshot, structured_intent)
                result = await execute_structured_intent(current_page, resolved_intent)
            else:
                executable = self._wrap_code(code)
                result = await _execute_on_page(current_page, executable)
            if result["success"]:
                if not ai_instruction_step and not structured_intent:
                    nav_target = _extract_ai_script_navigation_target(
                        getattr(current_page, "url", ""),
                        result.get("raw_output"),
                    )
                    if nav_target and getattr(current_page, "url", "").rstrip("/") != nav_target.rstrip("/"):
                        try:
                            await current_page.goto(nav_target)
                            await current_page.wait_for_load_state("domcontentloaded")
                        except Exception as nav_error:
                            self._history.append(
                                {
                                    "role": "user",
                                    "content": (
                                        f"Execution failed: selected target {nav_target} but navigation did not complete: {nav_error}\n"
                                        "Analyze the failure and adjust the strategy."
                                    ),
                                }
                            )
                            continue
                steps_done += 1
                if ai_instruction_step:
                    step_data = result.get("step") or ai_instruction_step
                else:
                    step_data = result.get("step") or {
                        "action": "ai_script",
                        "source": "ai",
                        "value": code,
                        "description": description,
                        "prompt": goal,
                    }
                successful_trace_steps.append(step_data)
                yield {
                    "event": "agent_recorded_steps",
                    "data": {"steps": _distill_react_recorded_steps(goal, successful_trace_steps)},
                }
                output = result.get("output", "")
                # If there's meaningful output, append to description for visibility
                if output and output != "ok" and output != "None":
                    yield {"event": "agent_step_done", "data": {"step": step_data, "output": output}}
                    self._history.append({"role": "user", "content": f"Step succeeded: {description}\nOutput: {output}"})
                else:
                    yield {"event": "agent_step_done", "data": {"step": step_data}}
                    self._history.append({"role": "user", "content": f"Step succeeded: {description}"})
            else:
                error_msg = result.get("error", "Unknown error")
                self._history.append({"role": "user", "content": f"Execution failed: {error_msg[:500]}\nAnalyze the failure and adjust the strategy."})

        yield {
            "event": "agent_aborted",
            "data": {
                "reason": f"Reached the maximum number of planning steps ({self.MAX_STEPS}) without completing the goal",
                "total_steps": steps_done,
            },
        }

    @staticmethod
    def _build_observation(snapshot: Dict[str, Any], steps_done: int) -> str:
        frame_lines = _snapshot_frame_lines(snapshot)
        return f"""Current page state:
URL: {snapshot.get('url', '')}
Title: {snapshot.get('title', '')}
Completed steps: {steps_done}

Current page snapshot:
{chr(10).join(frame_lines) or "(no observable elements)"}

Return the next JSON action."""

    @staticmethod
    def _extract_structured_execute_intent(parsed: Dict[str, Any], prompt: str) -> Optional[Dict[str, Any]]:
        action = str(parsed.get("action", "") or "").strip().lower()
        operation = str(parsed.get("operation", "") or "").strip().lower()
        atomic_actions = {"navigate", "click", "fill", "extract_text", "press"}

        if action in atomic_actions:
            operation = action
        if action not in {"", "execute"} and action not in atomic_actions:
            return None
        if operation not in atomic_actions:
            return None

        intent: Dict[str, Any] = {
            "action": operation,
            "description": parsed.get("description", operation),
            "prompt": prompt,
        }
        for key in ("target_hint", "collection_hint", "ordinal", "value", "result_key"):
            value = parsed.get(key)
            if value is not None:
                intent[key] = value
        return intent

    @staticmethod
    def _extract_execute_ai_instruction(parsed: Dict[str, Any], prompt: str) -> Optional[Dict[str, Any]]:
        candidate = parsed.get("ai_instruction")
        if not isinstance(candidate, dict):
            if str(parsed.get("action", "") or "").strip().lower() == "ai_instruction":
                candidate = parsed
            else:
                return None

        candidate_payload = dict(candidate)
        candidate_payload.setdefault("action", "ai_instruction")
        return RPAAssistant._coerce_to_ai_instruction(prompt, candidate_payload)

    @staticmethod
    def _parse_json(text: str) -> Optional[Dict[str, Any]]:
        # Try raw JSON first
        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        # Try extracting from code block
        m = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except Exception:
                pass
        # Try finding { ... } block
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return None

    @staticmethod
    def _wrap_code(code: str) -> str:
        """Wrap bare code in async def run(page) if not already wrapped."""
        stripped = code.strip()
        if stripped.startswith("async def run(") or stripped.startswith("def run("):
            return stripped
        indented = "\n".join("    " + line for line in stripped.splitlines())
        return f"async def run(page):\n{indented}"

    @staticmethod
    async def _stream_llm(
        history: List[Dict[str, str]],
        model_config: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
        model = get_llm_model(config=model_config, streaming=True)
        lc_messages = [SystemMessage(content=REACT_SYSTEM_PROMPT)]
        for m in history:
            if m["role"] == "user":
                lc_messages.append(HumanMessage(content=m["content"]))
            elif m["role"] == "assistant":
                lc_messages.append(AIMessage(content=m["content"]))
        if hasattr(model, "astream"):
            text_parts: List[str] = []
            fallback_parts: List[str] = []
            async for chunk in model.astream(lc_messages):
                text = _extract_llm_chunk_text(chunk)
                if text:
                    text_parts.append(text)
                    continue
                fallback = _extract_llm_chunk_fallback_text(chunk)
                if fallback:
                    fallback_parts.append(fallback)
            full_text = "".join(text_parts)
            if full_text.strip():
                yield full_text
                return
            fallback_text = "\n".join(part for part in fallback_parts if part).strip()
            if fallback_text:
                yield fallback_text
                return

        response = await model.ainvoke(lc_messages)
        yield _extract_llm_response_text(response)


class RPAAssistant:
    """Frame-aware AI recording assistant."""

    def __init__(self):
        self._histories: Dict[str, List[Dict[str, str]]] = {}

    def _get_history(self, session_id: str) -> List[Dict[str, str]]:
        if session_id not in self._histories:
            self._histories[session_id] = []
        return self._histories[session_id]

    def _trim_history(self, session_id: str, max_rounds: int = 10):
        hist = self._get_history(session_id)
        max_msgs = max_rounds * 2
        if len(hist) > max_msgs:
            self._histories[session_id] = hist[-max_msgs:]

    @staticmethod
    def _should_force_ai_instruction(user_message: str) -> bool:
        normalized = (user_message or "").strip().lower()
        return any(pattern in normalized for pattern in EXPLICIT_AI_INSTRUCTION_PATTERNS)

    @staticmethod
    def _is_placeholder_text(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        normalized = value.strip().lower()
        if not normalized:
            return True
        return any(hint in normalized for hint in AI_INSTRUCTION_PLACEHOLDER_HINTS)

    @staticmethod
    def _infer_ai_instruction_output_mode(user_message: str, parsed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if parsed and isinstance(parsed.get("output_expectation"), dict):
            mode = str(parsed["output_expectation"].get("mode", "")).strip().lower()
            if mode in {"act", "extract"}:
                return {"mode": mode}
        normalized = (user_message or "").strip().lower()
        if any(pattern in normalized for pattern in AI_INSTRUCTION_EXTRACT_HINT_PATTERNS):
            return {"mode": "extract"}
        return {"mode": "act"}

    @staticmethod
    def _infer_ai_instruction_kind(user_message: str, parsed: Optional[Dict[str, Any]] = None) -> str:
        parsed_kind = str((parsed or {}).get("instruction_kind", "")).strip().lower()
        if parsed_kind in {"semantic_rule", "semantic_extract", "semantic_decision"}:
            return parsed_kind
        normalized = (user_message or "").strip().lower()
        if any(pattern in normalized for pattern in AI_INSTRUCTION_EXTRACT_HINT_PATTERNS):
            return "semantic_extract"
        if any(pattern in normalized for pattern in AI_INSTRUCTION_DECISION_PATTERNS):
            return "semantic_decision"
        return "semantic_rule"

    @staticmethod
    def _looks_like_summary_instruction(*values: Any) -> bool:
        normalized = " ".join(str(value or "") for value in values).strip().lower()
        if not normalized:
            return False
        return any(pattern in normalized for pattern in REACT_SEMANTIC_SUMMARY_PATTERNS)

    @staticmethod
    def _prefer_chinese_prompt(text: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", text or ""))

    @classmethod
    def _generic_summary_prompt(cls, user_message: str) -> str:
        if cls._prefer_chinese_prompt(user_message):
            return (
                "阅读当前页面上的项目标题、简介（Description）以及可见的 README/正文内容。"
                "用中文总结当前项目的核心目标、主要功能特点、适用场景以及它解决的问题。"
            )
        return (
            "Read the repository title, description, and visible README/content on the current page. "
            "Summarize the current project's core purpose, key features, target use cases, and the problems it solves."
        )

    @classmethod
    def _generic_summary_description(cls, user_message: str) -> str:
        if cls._prefer_chinese_prompt(user_message):
            return "总结当前项目核心内容"
        return "Summarize current repository core content"

    @classmethod
    def _coerce_to_ai_instruction(
        cls,
        user_message: str,
        parsed: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        output_expectation = cls._infer_ai_instruction_output_mode(user_message, parsed)
        parsed_kind = cls._infer_ai_instruction_kind(user_message, parsed)

        description = (parsed or {}).get("description")
        if cls._is_placeholder_text(description):
            description = user_message

        prompt = (parsed or {}).get("prompt")
        if cls._is_placeholder_text(prompt):
            prompt = user_message

        if parsed_kind == "semantic_extract" and cls._looks_like_summary_instruction(
            user_message,
            description,
            prompt,
            (parsed or {}).get("instruction_kind"),
        ):
            description = cls._generic_summary_description(user_message)
            prompt = cls._generic_summary_prompt(user_message)

        raw_result_key = (parsed or {}).get("result_key")
        result_key = None
        if isinstance(raw_result_key, str) and re.fullmatch(r"[a-z_][a-z0-9_]*", raw_result_key.strip()):
            result_key = raw_result_key.strip()
        if output_expectation.get("mode") == "extract" and not result_key:
            result_key = "project_summary" if parsed_kind == "semantic_extract" else "runtime_ai_result"

        execution_hint = dict((parsed or {}).get("execution_hint") or {})
        max_reasoning_steps = execution_hint.get(
            "max_reasoning_steps", AI_INSTRUCTION_DEFAULT_MAX_REASONING_STEPS
        )
        try:
            max_reasoning_steps = int(max_reasoning_steps)
        except Exception:
            max_reasoning_steps = AI_INSTRUCTION_DEFAULT_MAX_REASONING_STEPS
        planning_timeout_s = execution_hint.get(
            "planning_timeout_s", AI_INSTRUCTION_DEFAULT_PLANNING_TIMEOUT_S
        )
        try:
            planning_timeout_s = max(float(planning_timeout_s), 1.0)
        except Exception:
            planning_timeout_s = float(AI_INSTRUCTION_DEFAULT_PLANNING_TIMEOUT_S)
        allow_navigation = execution_hint.get("allow_navigation")
        if not isinstance(allow_navigation, bool):
            allow_navigation = output_expectation.get("mode") != "extract"

        return {
            "action": "ai_instruction",
            "source": "ai",
            "description": description or user_message,
            "prompt": prompt or user_message,
            "instruction_kind": parsed_kind,
            "input_scope": (parsed or {}).get("input_scope") or {"mode": "current_page"},
            "output_expectation": output_expectation,
            "execution_hint": {
                "requires_dom_snapshot": bool(execution_hint.get("requires_dom_snapshot", True)),
                "allow_navigation": allow_navigation,
                "max_reasoning_steps": max_reasoning_steps,
                "planning_timeout_s": planning_timeout_s,
            },
            "result_key": result_key,
            "sensitive": bool((parsed or {}).get("sensitive", False)),
        }

    async def chat(
        self,
        session_id: str,
        page: Page,
        message: str,
        steps: List[Dict[str, Any]],
        model_config: Optional[Dict[str, Any]] = None,
        page_provider: Optional[Callable[[], Optional[Page]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        yield {"event": "message_chunk", "data": {"text": "正在分析当前页面......\n\n"}}
        current_page = page_provider() if page_provider else page
        if current_page is None:
            yield {"event": "error", "data": {"message": "No active page available"}}
            yield {"event": "done", "data": {}}
            return

        snapshot = await build_page_snapshot(current_page, build_frame_path_from_frame)
        history = self._get_history(session_id)
        force_ai_instruction = self._should_force_ai_instruction(message)
        messages = self._build_messages(message, steps, snapshot, history, force_ai_instruction=force_ai_instruction)

        full_response = ""
        async for chunk_text in self._stream_llm(messages, model_config):
            full_response += chunk_text
            yield {"event": "message_chunk", "data": {"text": chunk_text}}

        yield {"event": "executing", "data": {}}
        result, final_response, code, resolution, retry_notice = await self._execute_with_retry(
            page=page,
            page_provider=page_provider,
            snapshot=snapshot,
            full_response=full_response,
            user_message=message,
            force_ai_instruction=force_ai_instruction,
            messages=messages,
            model_config=model_config,
        )

        if retry_notice:
            yield {"event": "message_chunk", "data": {"text": retry_notice}}
        if resolution:
            yield {"event": "resolution", "data": {"intent": resolution}}

        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": final_response})
        self._trim_history(session_id)

        step_data = None
        if result["success"]:
            if result.get("step"):
                step_data = result["step"]
            elif code:
                body = self._extract_function_body(code)
                step_data = {
                    "action": "ai_script",
                    "source": "ai",
                    "value": body,
                    "description": message,
                    "prompt": message,
                }

        yield {
            "event": "result",
            "data": {
                "success": result["success"],
                "error": result.get("error"),
                "step": step_data,
                "output": result.get("output"),
            },
        }
        yield {"event": "done", "data": {}}

    async def _execute_with_retry(
        self,
        page: Page,
        page_provider: Optional[Callable[[], Optional[Page]]],
        snapshot: Dict[str, Any],
        full_response: str,
        user_message: str,
        force_ai_instruction: bool,
        messages: List[Dict[str, str]],
        model_config: Optional[Dict[str, Any]],
    ) -> tuple[Dict[str, Any], str, Optional[str], Optional[Dict[str, Any]], str]:
        current_page = page_provider() if page_provider else page
        if current_page is None:
            return {"success": False, "error": "No active page available", "output": ""}, full_response, None, None, ""

        try:
            result, code, resolution = await self._execute_single_response(
                current_page,
                snapshot,
                full_response,
                user_message=user_message,
                force_ai_instruction=force_ai_instruction,
            )
            if result["success"]:
                return result, full_response, code, resolution, ""
        except Exception as exc:
            result = {"success": False, "error": str(exc), "output": ""}
            code = None
            resolution = None

        retry_messages = messages + [
            {"role": "assistant", "content": full_response},
            {"role": "user", "content": f"Execution error: {result['error']}\nPlease fix it and retry."},
        ]
        retry_response = ""
        async for chunk_text in self._stream_llm(retry_messages, model_config):
            retry_response += chunk_text

        current_page = page_provider() if page_provider else page
        if current_page is None:
            return {"success": False, "error": "No active page available", "output": ""}, retry_response, None, None, "\n\nExecution failed. Retrying.\n\n"

        retry_snapshot = await build_page_snapshot(current_page, build_frame_path_from_frame)
        try:
            retry_result, retry_code, retry_resolution = await self._execute_single_response(
                current_page,
                retry_snapshot,
                retry_response,
                user_message=user_message,
                force_ai_instruction=force_ai_instruction,
            )
            return retry_result, retry_response, retry_code, retry_resolution, "\n\nExecution failed. Retrying.\n\n"
        except Exception as exc:
            return {"success": False, "error": str(exc), "output": ""}, retry_response, None, None, "\n\nExecution failed. Retrying.\n\n"

    async def _execute_single_response(
        self,
        current_page: Page,
        snapshot: Dict[str, Any],
        full_response: str,
        user_message: str,
        force_ai_instruction: bool = False,
    ) -> tuple[Dict[str, Any], Optional[str], Optional[Dict[str, Any]]]:
        ai_instruction = self._extract_ai_instruction(full_response)
        if ai_instruction:
            from backend.rpa.runtime_ai_instruction import execute_ai_instruction

            step = self._coerce_to_ai_instruction(user_message, ai_instruction)
            result = await execute_ai_instruction(current_page, step, results={})
            success = result.get("success", True)
            return {
                "success": success,
                "output": result.get("output") or ("ai_instruction executed" if success else ""),
                "error": result.get("error"),
                "step": step,
            }, None, None

        structured_intent = self._extract_structured_intent(full_response)
        if force_ai_instruction and structured_intent:
            from backend.rpa.runtime_ai_instruction import execute_ai_instruction

            step = self._coerce_to_ai_instruction(user_message, structured_intent)
            result = await execute_ai_instruction(current_page, step, results={})
            success = result.get("success", True)
            return {
                "success": success,
                "output": result.get("output") or ("ai_instruction executed" if success else ""),
                "error": result.get("error"),
                "step": step,
            }, None, None
        if structured_intent:
            resolved_intent = resolve_structured_intent(snapshot, structured_intent)
            result = await execute_structured_intent(current_page, resolved_intent)
            return result, None, resolved_intent

        code = self._extract_code(full_response)
        if force_ai_instruction and code:
            from backend.rpa.runtime_ai_instruction import execute_ai_instruction

            step = self._coerce_to_ai_instruction(user_message)
            result = await execute_ai_instruction(current_page, step, results={})
            success = result.get("success", True)
            return {
                "success": success,
                "output": result.get("output") or ("ai_instruction executed" if success else ""),
                "error": result.get("error"),
                "step": step,
            }, None, None
        if not code:
            raise ValueError("Unable to extract structured intent or executable code from assistant response")
        result = await self._execute_on_page(current_page, code)
        return result, code, None

    def _build_messages(
        self,
        user_message: str,
        steps: List[Dict[str, Any]],
        snapshot: Dict[str, Any],
        history: List[Dict[str, str]],
        force_ai_instruction: bool = False,
    ) -> List[Dict[str, str]]:
        steps_text = ""
        if steps:
            lines = []
            for i, step in enumerate(steps, 1):
                source = step.get("source", "record")
                desc = step.get("description", step.get("action", ""))
                lines.append(f"{i}. [{source}] {desc}")
            steps_text = "\n".join(lines)

        frame_lines = _snapshot_frame_lines(snapshot)

        ai_instruction_hint = ""
        if force_ai_instruction:
            ai_instruction_hint = """

## Special Requirement
Treat this request as a runtime AI instruction.
Return JSON with `"action": "ai_instruction"`.
Do not convert it into extract_text, click/fill, or fixed Playwright code.
Preserve the rule in `prompt`, set `input_scope.mode` to `current_page`, and choose `output_expectation.mode` as `extract` when the user asks to read/filter/summarize data.
"""

        context = f"""## History Steps
{steps_text or "(none)"}

## Current Page Snapshot
{chr(10).join(frame_lines) or "(no observable elements)"}

## User Instruction
{user_message}{ai_instruction_hint}"""

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": context})
        return messages

    async def _stream_llm(
        self,
        messages: List[Dict[str, str]],
        model_config: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        model = get_llm_model(config=model_config, streaming=True)
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        lc_messages = []
        for message in messages:
            if message["role"] == "system":
                lc_messages.append(SystemMessage(content=message["content"]))
            elif message["role"] == "user":
                lc_messages.append(HumanMessage(content=message["content"]))
            elif message["role"] == "assistant":
                lc_messages.append(AIMessage(content=message["content"]))

        async for chunk in model.astream(lc_messages):
            text = _extract_llm_chunk_text(chunk)
            if text:
                yield text
                continue
            fallback = _extract_llm_chunk_fallback_text(chunk)
            if fallback:
                yield fallback

    @staticmethod
    def _extract_structured_intent(text: str) -> Optional[Dict[str, Any]]:
        stripped = text.strip()
        try:
            parsed = json.loads(stripped)
        except Exception:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("action"):
            return parsed

        match = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1).strip())
            except Exception:
                return None
            if isinstance(parsed, dict) and parsed.get("action"):
                return parsed
        return None

    @staticmethod
    def _extract_ai_instruction(text: str) -> Optional[Dict[str, Any]]:
        def _normalize(parsed: Any) -> Optional[Dict[str, Any]]:
            if not isinstance(parsed, dict):
                return None
            if str(parsed.get("action", "") or "").strip().lower() != "ai_instruction":
                return None
            return {
                "action": "ai_instruction",
                "source": "ai",
                "description": parsed.get("description", "AI instruction"),
                "prompt": parsed.get("prompt") or parsed.get("description", ""),
                "instruction_kind": parsed.get("instruction_kind", "semantic_rule"),
                "input_scope": parsed.get("input_scope") or {"mode": "current_page"},
                "output_expectation": parsed.get("output_expectation") or {"mode": "act"},
                "execution_hint": parsed.get("execution_hint")
                or {
                    "requires_dom_snapshot": True,
                    "allow_navigation": True,
                    "max_reasoning_steps": AI_INSTRUCTION_DEFAULT_MAX_REASONING_STEPS,
                    "planning_timeout_s": AI_INSTRUCTION_DEFAULT_PLANNING_TIMEOUT_S,
                },
                "result_key": parsed.get("result_key"),
                "sensitive": bool(parsed.get("sensitive", False)),
            }

        stripped = text.strip()
        try:
            parsed = json.loads(stripped)
        except Exception:
            parsed = None
        normalized = _normalize(parsed)
        if normalized:
            return normalized

        match = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1).strip())
            except Exception:
                return None
            return _normalize(parsed)
        return None

    @staticmethod
    def _extract_code(text: str) -> Optional[str]:
        pattern = r"```python\s*\n(.*?)```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        pattern2 = r"(async def run\(page\):.*)"
        match2 = re.search(pattern2, text, re.DOTALL)
        if match2:
            return match2.group(1).strip()
        pattern3 = r"(def run\(page\):.*)"
        match3 = re.search(pattern3, text, re.DOTALL)
        if match3:
            return match3.group(1).strip()
        return None

    @staticmethod
    def _extract_function_body(code: str) -> str:
        lines = code.split("\n")
        body_lines = []
        in_body = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("async def run(") or stripped.startswith("def run("):
                in_body = True
                continue
            if in_body:
                if line.startswith("    "):
                    body_lines.append(line[4:])
                elif line.strip() == "":
                    body_lines.append("")
                else:
                    body_lines.append(line)
        return "\n".join(body_lines).strip()

    async def _get_page_elements(self, page: Page) -> str:
        return await _get_page_elements(page)

    async def _execute_on_page(self, page: Page, code: str) -> Dict[str, Any]:
        return await _execute_on_page(page, code)



