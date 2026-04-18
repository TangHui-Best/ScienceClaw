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

SEMANTIC_DECISION_ACT_PROMPT_SUFFIX = (
    "Complete the requested browser action inside this AI instruction. "
    "Do not stop after only identifying the best match or returning explanatory text. "
    "If you need to express the selected target in a structured result, use target_url, url, href, path, or repo_path."
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
REACT_RUNTIME_SEMANTIC_UNDERSTANDING_PATTERNS = (
    "当前项目",
    "项目核心",
    "核心内容",
    "核心信息",
    "主要功能",
    "主要特点",
    "技术栈",
    "用途",
    "目标用户",
    "能力",
    "限制",
    "业务含义",
    "语义",
    "判断",
    "是否需要",
    "current project",
    "project core",
    "core content",
    "core information",
    "purpose",
    "capability",
    "capabilities",
    "limitation",
    "limitations",
    "business meaning",
    "semantic",
    "judgment",
)

DETERMINISTIC_SUMMARY_CODE_PATTERNS = (
    "summary statistics",
    "summary stats",
    "统计",
    "汇总统计",
    "数量统计",
    "计数",
    "总数",
    "counts",
    "count by",
    "total rows",
    "aggregate",
    "group by",
)

STRICT_ARRAY_EXTRACTION_PATTERNS = (
    "strict array",
    "strictly as an array",
    "output strictly as an array",
    "输出严格为数组",
    "严格为数组",
    "数组",
    "array",
)

RECORD_FIELD_TITLE_PATTERNS = (
    "title",
    "标题",
)

RECORD_FIELD_AUTHOR_PATTERNS = (
    "author",
    "creator",
    "创建人",
)

RECORD_FIELD_STATUS_PATTERNS = (
    "status",
    "state",
)

SEMANTIC_RELEVANCE_SELECTION_PATTERNS = (
    "most relevant",
    "most related",
    "best match",
    "best matching",
    "relevance",
    "relevant to",
    "related to",
    "\u6700\u76f8\u5173",
    "\u6700\u5339\u914d",
    "\u76f8\u5173\u5ea6",
)

SEMANTIC_SELECTION_TARGET_PATTERNS = (
    "project",
    "repo",
    "repository",
    "item",
    "result",
    "link",
    "\u9879\u76ee",
    "\u4ed3\u5e93",
    "\u7ed3\u679c",
    "\u94fe\u63a5",
)

GENERIC_CHROME_TEXT_PATTERNS = (
    "navigation menu",
    "menu",
    "sign in",
    "github",
)

STABLE_SUBPAGE_HINTS = (
    ("/pulls", ("pull requests", "pull request", "/pulls", "pr list", "prs")),
    ("/issues", ("issues", "/issues", "issue list")),
    ("/actions", ("actions", "/actions")),
    ("/releases", ("releases", "/releases")),
    ("/wiki", ("wiki", "/wiki")),
    ("/discussions", ("discussions", "/discussions")),
    ("/commits", ("commits", "/commits")),
)

JS_CODE_GUARD_PATTERNS = (
    "const ",
    "let ",
    "var ",
    "=>",
    "page.evaluate",
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

STEP_TYPE_CLASSIFICATION_GUIDANCE = """
- structured step for atomic browser actions
- ai_script for runtime page data plus deterministic, encodable rules
- ai_instruction for runtime page data plus semantic/business judgment
- If the user explicitly requests an AI instruction or says not to expand the rule into fixed script, return ai_instruction for that requested step
- Do not classify by isolated words alone. For example, "star" or "summary" is only a signal, not a step type decision
""".strip()

STEP_TYPE_FEW_SHOTS = """
Mini examples:
- structured
  User goal fragment: "Click the Stars tab"
  Good next step: operation=click with target_hint for the Stars tab
- ai_script
  User goal fragment: "Find the project with the most stars and open it"
  Good next step: code that computes the choice from current page data, then returns target_url/repo_path
- ai_instruction
  User goal fragment: "Summarize the current project, focusing on purpose, capabilities, and limitations"
  Good next step: ai_instruction whose prompt only describes that local semantic summary step
""".strip()

STRUCTURED_STALL_REFLECTION_MESSAGE = (
    "Previous step proposal was rejected. "
    "The current structured-action path did not make reliable progress toward the target content. "
    "Re-evaluate whether this subtask is better completed as one deterministic ai_script or one ai_instruction, "
    "instead of more repeated structured actions."
)

# Legacy compatibility prompt for direct RPAAssistant.chat() callers.
# The recording route now uses REACT_SYSTEM_PROMPT as the active classification contract.
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
    # Chat is now a compatibility entry point for the unified ReAct recorder.
    return True


def _react_step_violates_explicit_ai_instruction_request(
    goal: str,
    ai_instruction_step: Optional[Dict[str, Any]],
    structured_intent: Optional[Dict[str, Any]] = None,
) -> bool:
    if ai_instruction_step:
        return False
    if not RPAAssistant._should_force_ai_instruction(goal):
        return False
    if _is_structured_runtime_ai_setup_step(structured_intent):
        return False
    return True


def _is_structured_runtime_ai_setup_step(structured_intent: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(structured_intent, dict):
        return False

    action = str(structured_intent.get("action") or "").strip().lower()
    if action == "navigate":
        value = str(structured_intent.get("value") or "").strip()
        return value.startswith("http://") or value.startswith("https://")

    if action not in {"click", "fill", "press", "extract_text", "select"}:
        return False

    if structured_intent.get("collection_hint") or structured_intent.get("ordinal"):
        return False

    target_hint = structured_intent.get("target_hint")
    if not isinstance(target_hint, dict):
        return False

    hint_name = " ".join(
        str(target_hint.get(key) or "").strip().lower()
        for key in ("name", "text", "placeholder", "label", "title")
    ).strip()
    if not hint_name:
        return False

    generic_runtime_terms = (
        "project",
        "repo",
        "repository",
        "item",
        "result",
        "项目",
        "仓库",
        "结果",
        "列表项",
    )
    return not any(term in hint_name for term in generic_runtime_terms)


def _structured_step_requires_ai_script(
    goal: str,
    thought: str,
    description: str,
    structured_intent: Optional[Dict[str, Any]],
) -> bool:
    if not isinstance(structured_intent, dict):
        return False

    action = str(structured_intent.get("action") or "").strip().lower()
    if action not in {"click", "navigate"}:
        return False

    payload = " ".join(
        part for part in (
            goal or "",
            thought or "",
            description or "",
            json.dumps(structured_intent, ensure_ascii=False),
        )
        if part
    ).lower()

    deterministic_selection_patterns = (
        "highest",
        "largest",
        "most",
        "latest",
        "oldest",
        "top ",
        "maximum",
        "minimum",
        "最高",
        "最多",
        "最大",
        "最新",
        "最旧",
        "第一",
    )
    selection_target_patterns = (
        "open",
        "click",
        "repo",
        "repository",
        "project",
        "item",
        "result",
        "link",
        "打开",
        "点击",
        "项目",
        "仓库",
        "结果",
        "链接",
        "star",
        "stars",
    )

    if not any(pattern in payload for pattern in deterministic_selection_patterns):
        return False
    if not any(pattern in payload for pattern in selection_target_patterns):
        return False
    if _is_structured_runtime_ai_setup_step(structured_intent):
        return False
    return True


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
    if any(pattern in normalized for pattern in DETERMINISTIC_SUMMARY_CODE_PATTERNS):
        return False
    if not any(pattern in normalized for pattern in REACT_RUNTIME_SEMANTIC_UNDERSTANDING_PATTERNS):
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
    if any(pattern in blob for pattern in DETERMINISTIC_SUMMARY_CODE_PATTERNS):
        return False
    action = str(step.get("action") or "").strip().lower()
    instruction_kind = str(step.get("instruction_kind") or "").strip().lower()
    if action == "ai_instruction" and instruction_kind in {"semantic_extract", "semantic_decision"}:
        return True
    return any(pattern in blob for pattern in REACT_RUNTIME_SEMANTIC_UNDERSTANDING_PATTERNS)


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


def _is_runtime_act_ai_instruction(step: Dict[str, Any]) -> bool:
    if not isinstance(step, dict):
        return False
    if str(step.get("action") or "").strip().lower() != "ai_instruction":
        return False
    output_expectation = step.get("output_expectation") or {}
    return str(output_expectation.get("mode") or "").strip().lower() == "act"


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

        if distilled and _is_superseded_stable_subpage_helper(distilled[-1], step):
            distilled[-1] = step
            continue
        if distilled and _is_superseded_extract_result_step(distilled[-1], step):
            distilled[-1] = step
            continue
        if distilled and _is_superseded_ai_instruction_followup_navigation(distilled[-1], step):
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


def _stable_subpage_suffix_from_step(step: Dict[str, Any]) -> str:
    if not isinstance(step, dict):
        return ""

    for candidate in (step.get("value"), step.get("url")):
        if isinstance(candidate, str):
            normalized = candidate.strip().lower()
            for suffix, _signals in STABLE_SUBPAGE_HINTS:
                if normalized.endswith(suffix):
                    return suffix

    text_parts: List[str] = []
    for key in ("description", "prompt"):
        value = step.get(key)
        if isinstance(value, str):
            text_parts.append(value.lower())
    target_hint = step.get("target_hint")
    if isinstance(target_hint, dict):
        for key in ("name", "text", "role"):
            value = target_hint.get(key)
            if isinstance(value, str):
                text_parts.append(value.lower())

    blob = " ".join(part for part in text_parts if part)
    for suffix, signals in STABLE_SUBPAGE_HINTS:
        if any(signal in blob for signal in signals):
            return suffix
    return ""


def _is_superseded_stable_subpage_helper(previous_step: Dict[str, Any], current_step: Dict[str, Any]) -> bool:
    previous_action = str(previous_step.get("action") or "").strip().lower()
    current_action = str(current_step.get("action") or "").strip().lower()
    if current_action != "navigate":
        return False
    if previous_action not in {"click", "navigate"}:
        return False

    previous_suffix = _stable_subpage_suffix_from_step(previous_step)
    current_suffix = _stable_subpage_suffix_from_step(current_step)
    if not previous_suffix or not current_suffix:
        return False
    return previous_suffix == current_suffix


def _normalize_recorded_step_after_success(step: Dict[str, Any], current_url: str) -> Dict[str, Any]:
    if not isinstance(step, dict):
        return step

    action = str(step.get("action") or "").strip().lower()
    normalized_url = str(current_url or "").strip()
    if action != "click" or not normalized_url:
        return step

    stable_suffix = _stable_subpage_suffix_from_step(step)
    if not stable_suffix or not normalized_url.lower().endswith(stable_suffix):
        return step

    normalized_step = dict(step)
    normalized_step["action"] = "navigate"
    normalized_step["url"] = normalized_url
    normalized_step["value"] = normalized_url
    normalized_step["target"] = ""
    normalized_step["frame_path"] = []
    normalized_step["locator_candidates"] = []
    normalized_step["collection_hint"] = {}
    normalized_step["item_hint"] = {}
    normalized_step["ordinal"] = None
    normalized_diagnostics = dict(normalized_step.get("assistant_diagnostics") or {})
    normalized_diagnostics["selected_locator_kind"] = "navigate"
    normalized_step["assistant_diagnostics"] = normalized_diagnostics
    return normalized_step


def _extract_result_key(step: Dict[str, Any]) -> str:
    if not isinstance(step, dict):
        return ""
    action = str(step.get("action") or "").strip().lower()
    if action != "extract_text":
        return ""
    result_key = step.get("result_key")
    if isinstance(result_key, str) and result_key.strip():
        return result_key.strip().lower()
    return ""


def _is_superseded_extract_result_step(previous_step: Dict[str, Any], current_step: Dict[str, Any]) -> bool:
    previous_result_key = _extract_result_key(previous_step)
    current_result_key = _extract_result_key(current_step)
    return bool(previous_result_key and previous_result_key == current_result_key)


def _is_superseded_ai_instruction_followup_navigation(previous_step: Dict[str, Any], current_step: Dict[str, Any]) -> bool:
    if not _is_runtime_act_ai_instruction(previous_step):
        return False
    current_action = str(current_step.get("action") or "").strip().lower()
    return current_action == "navigate"


def _extract_record_list_candidate(raw_output: Any) -> Optional[List[Any]]:
    if isinstance(raw_output, list):
        return raw_output
    if isinstance(raw_output, dict):
        prioritized_keys = ("pr_list", "items", "rows", "results", "data", "output")
        for key in prioritized_keys:
            value = raw_output.get(key)
            if isinstance(value, list):
                return value
        for value in raw_output.values():
            if isinstance(value, list):
                return value
    return None


def _looks_like_record_array_request(*values: Any) -> bool:
    normalized = " ".join(str(value or "") for value in values).strip().lower()
    if not normalized:
        return False
    if any(pattern in normalized for pattern in STRICT_ARRAY_EXTRACTION_PATTERNS):
        return True
    return (
        any(pattern in normalized for pattern in ("top", "first", "前", "pull request", "pull requests", "pr", "issue", "list"))
        and any(pattern in normalized for pattern in RECORD_FIELD_TITLE_PATTERNS)
        and any(pattern in normalized for pattern in RECORD_FIELD_AUTHOR_PATTERNS)
    )


def _looks_like_single_value_field_request(*values: Any) -> bool:
    normalized = " ".join(str(value or "") for value in values).strip().lower()
    if not normalized or _looks_like_record_array_request(*values):
        return False
    field_patterns = (
        "title",
        "name",
        "headline",
        "subject",
        "summary",
        "description",
        "caption",
        "heading",
        "header",
    )
    return any(pattern in normalized for pattern in field_patterns)


def _requires_runtime_semantic_selection(*values: Any) -> bool:
    normalized = " ".join(str(value or "") for value in values).strip().lower()
    if not normalized:
        return False
    return (
        any(pattern in normalized for pattern in SEMANTIC_RELEVANCE_SELECTION_PATTERNS)
        and any(pattern in normalized for pattern in SEMANTIC_SELECTION_TARGET_PATTERNS)
    )


def _infer_ai_script_output_shape(*values: Any) -> str:
    if _looks_like_record_array_request(*values):
        return "record_array"
    return "unspecified"


def _infer_ai_script_record_fields(*values: Any) -> List[str]:
    normalized = " ".join(str(value or "") for value in values).strip().lower()
    fields: List[str] = []
    if any(pattern in normalized for pattern in RECORD_FIELD_TITLE_PATTERNS):
        fields.append("title")
    if any(pattern in normalized for pattern in RECORD_FIELD_AUTHOR_PATTERNS):
        fields.append("author")
    if any(pattern in normalized for pattern in RECORD_FIELD_STATUS_PATTERNS):
        fields.append("status")
    return fields


def _infer_ai_script_item_limit(ordinal: Any, *values: Any) -> Optional[int]:
    if isinstance(ordinal, int):
        return ordinal if ordinal > 0 else None
    ordinal_text = str(ordinal or "").strip().lower()
    if ordinal_text.isdigit():
        numeric = int(ordinal_text)
        return numeric if numeric > 0 else None

    normalized = " ".join(str(value or "") for value in values).strip().lower()
    for pattern in (
        r"\btop\s+(\d+)\b",
        r"\bfirst\s+(\d+)\b",
        r"\b(\d+)\s+(?:pull requests|pull request|prs|issues|items|rows|records)\b",
    ):
        match = re.search(pattern, normalized)
        if not match:
            continue
        try:
            numeric = int(match.group(1))
        except Exception:
            continue
        if numeric > 0:
            return numeric

    if any(token in normalized for token in ("first item", "latest issue", "latest pr")):
        return 1
    return None


def _infer_ai_script_selection_scope(*values: Any) -> str:
    normalized = " ".join(str(value or "") for value in values).strip().lower()
    if not normalized:
        return "current_view"
    if any(
        pattern in normalized
        for pattern in (
            "regardless of status",
            "any state",
            "all states",
            "open and closed",
            "whether open or closed",
        )
    ):
        return "all_states"
    return "current_view"


def _infer_ai_script_stable_subpage_hint(*values: Any) -> str:
    normalized = " ".join(str(value or "") for value in values).strip().lower()
    if not normalized:
        return ""
    for suffix, signals in STABLE_SUBPAGE_HINTS:
        if any(signal in normalized for signal in signals):
            return suffix
    return ""


def _infer_ai_script_entity_hint(stable_subpage_hint: str, *values: Any) -> str:
    if stable_subpage_hint == "/pulls":
        return "pull_requests"
    if stable_subpage_hint == "/issues":
        return "issues"
    normalized = " ".join(str(value or "") for value in values).strip().lower()
    if any(token in normalized for token in ("pull requests", "pull request", "prs", " pr ")):
        return "pull_requests"
    if any(token in normalized for token in ("issues", "issue list", " issue ")):
        return "issues"
    return ""


def _normalize_optional_positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value or "").strip()
    if text.isdigit():
        numeric = int(text)
        return numeric if numeric > 0 else None
    return None


def _build_ai_script_output_contract(
    output_shape: str,
    record_fields: List[str],
    item_limit: Optional[int],
    min_items: Optional[int],
) -> Dict[str, Any]:
    contract_type = "array" if output_shape == "record_array" else "unspecified"
    return {
        "type": contract_type,
        "required_fields": list(record_fields or []),
        "max_items": item_limit,
        "min_items": min_items,
    }


def _build_ai_script_brief(
    description: str,
    value: Any,
    item_limit: Optional[int],
    selection_scope: str,
) -> str:
    parts = [str(description or "").strip() or "Execute the current ai_script subtask."]
    value_text = str(value or "").strip()
    if value_text and value_text not in parts[0]:
        parts.append(f"Additional instruction: {value_text}")
    if item_limit:
        parts.append(
            f"Interpret the requested count as an upper bound: collect at most {item_limit} item(s), "
            "not a required count. If fewer matching records exist in the correct scope, return the records that exist."
        )
    if selection_scope == "all_states":
        parts.append(
            "Interpret all states/all statuses as the data-source scope. This is not a fill-to-quota strategy; "
            "do not merge unrelated views merely to reach the maximum item count."
        )
    return " ".join(part for part in parts if part).strip()


def _is_valid_record_title(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip()
    if not normalized:
        return False
    if re.fullmatch(r"\d+(\s+comments?)?", normalized.lower()):
        return False
    return True


def _is_valid_record_author(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    return bool(normalized and normalized != "unknown")


def _normalize_record_field_name(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"creator", "created_by", "owner", "user"}:
        return "author"
    return normalized


def _ai_script_contract_record_fields(ai_script_plan: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(ai_script_plan, dict):
        return []

    fields: List[str] = []
    raw_record_fields = ai_script_plan.get("record_fields")
    if isinstance(raw_record_fields, list):
        fields.extend(_normalize_record_field_name(field) for field in raw_record_fields)

    output_contract = ai_script_plan.get("output_contract")
    if isinstance(output_contract, dict):
        required_fields = output_contract.get("required_fields")
        if isinstance(required_fields, list):
            fields.extend(_normalize_record_field_name(field) for field in required_fields)

    deduped: List[str] = []
    for field in fields:
        if field and field not in deduped:
            deduped.append(field)
    return deduped


def _ai_script_contract_expects_record_array(ai_script_plan: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(ai_script_plan, dict):
        return False
    if str(ai_script_plan.get("output_shape") or "").strip().lower() == "record_array":
        return True
    output_contract = ai_script_plan.get("output_contract")
    if isinstance(output_contract, dict):
        return str(output_contract.get("type") or "").strip().lower() == "array"
    return False


def _ai_script_quality_issue(
    goal: str,
    description: str,
    raw_output: Any,
    ai_script_plan: Optional[Dict[str, Any]] = None,
) -> str:
    normalized = str(description or "").strip().lower()
    contract_fields = _ai_script_contract_record_fields(ai_script_plan)
    expects_record_array = _ai_script_contract_expects_record_array(ai_script_plan)
    if not expects_record_array:
        expects_record_array = _looks_like_record_array_request(description)
    records = _extract_record_list_candidate(raw_output)
    if not expects_record_array and records is not None:
        expects_record_array = True
    if not expects_record_array:
        return ""

    if records is None:
        return "AI script did not return the requested record array."
    if not records:
        return "AI script returned an empty record array even though the target list should be visible."

    if contract_fields:
        requires_title = "title" in contract_fields
        requires_author = "author" in contract_fields
    else:
        requires_title = any(pattern in normalized for pattern in RECORD_FIELD_TITLE_PATTERNS) or any(
            isinstance(item, dict) and "title" in item for item in records
        )
        requires_author = any(pattern in normalized for pattern in RECORD_FIELD_AUTHOR_PATTERNS) or any(
            isinstance(item, dict) and ("author" in item or "creator" in item) for item in records
        )
    if not (requires_title or requires_author):
        return ""

    valid_items = 0
    for item in records:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        author = item.get("author")
        if author is None:
            author = item.get("creator")

        title_ok = _is_valid_record_title(title) if requires_title else True
        author_ok = _is_valid_record_author(author) if requires_author else True
        if title_ok and author_ok:
            valid_items += 1

    if valid_items * 5 < len(records) * 4:
        return "AI script returned a low-quality record array with missing or misaligned title/author fields."
    return ""


def _structured_result_quality_issue(intent: Dict[str, Any], result: Dict[str, Any]) -> str:
    action = str(intent.get("action") or "").strip().lower()
    if action != "extract_text":
        return ""

    description = intent.get("description", "")
    prompt = intent.get("prompt", "")
    result_key = intent.get("result_key", "")
    output = str(result.get("output", "") or "").strip()
    expects_record_array = _looks_like_record_array_request(description, prompt, result_key)
    expects_single_value_field = _looks_like_single_value_field_request(description, prompt, result_key)
    if not expects_record_array and not expects_single_value_field:
        return ""
    if not output:
        if expects_record_array:
            return "Structured extract_text returned empty output for a batch array extraction task."
        return "Structured extract_text returned empty output for a required field extraction task."
    if output.lower() in GENERIC_CHROME_TEXT_PATTERNS:
        if expects_record_array:
            return "Structured extract_text captured generic page chrome instead of the requested batch array; return ai_script instead."
        return "Structured extract_text captured generic page chrome instead of the requested field value; refine the target or return a different step."
    if expects_record_array:
        return "Structured extract_text cannot satisfy this batch array extraction task; return ai_script instead."
    return ""


def _step_completion_fact(step: Dict[str, Any], current_url: str) -> str:
    action = str(step.get("action") or "").strip().lower() or "step"
    description = str(step.get("description") or action).strip()
    fact = f"- {action}: {description}"
    if current_url:
        fact += f" | current_page_url={current_url}"

    result_key = step.get("result_key")
    if isinstance(result_key, str) and result_key.strip():
        fact += f" | result_key={result_key.strip()}"

    return fact


def _safe_parse_json_output(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        return value
    if not normalized.startswith(("{", "[")):
        return value
    try:
        return json.loads(normalized)
    except Exception:
        return value


def _summarize_execution_output(output: Any) -> Dict[str, Any]:
    parsed = _safe_parse_json_output(output)
    if isinstance(parsed, list):
        fields: List[str] = []
        for item in parsed:
            if isinstance(item, dict):
                fields = sorted(str(key) for key in item.keys())
                break
        return {
            "output_type": "array",
            "array_length": len(parsed),
            "fields": fields,
            "output_preview": parsed[:3],
        }
    if isinstance(parsed, dict):
        return {
            "output_type": "object",
            "fields": sorted(str(key) for key in parsed.keys()),
            "output_preview": parsed,
        }
    text = str(parsed if parsed is not None else "")
    return {
        "output_type": "text",
        "output_preview": text[:800],
    }


def _build_execution_observation(step: Dict[str, Any], output: Any, current_url: str) -> str:
    payload: Dict[str, Any] = {
        "step_status": "success",
        "step_action": step.get("action"),
        "description": step.get("description"),
        "result_key": step.get("result_key"),
        "current_page_url": current_url,
    }
    payload.update(_summarize_execution_output(output))
    return "Latest execution observation:\n" + json.dumps(payload, ensure_ascii=False, default=str)


def _store_ai_script_execution_result(
    execution_results: Dict[str, Any],
    candidate: Dict[str, Any],
    result: Dict[str, Any],
) -> None:
    if not isinstance(execution_results, dict):
        return
    result_key = (
        ((candidate.get("ai_script_plan") or {}).get("result_key"))
        or ((candidate.get("parsed") or {}).get("result_key"))
    )
    if not isinstance(result_key, str) or not result_key.strip():
        return
    payload = result.get("raw_output")
    if payload is None:
        payload = result.get("output")
    execution_results[result_key.strip()] = payload


def _candidate_contract_kind(candidate: Dict[str, Any]) -> str:
    if candidate.get("ai_instruction_step"):
        return "ai_instruction"
    if candidate.get("structured_intent"):
        return "structured"
    if candidate.get("ai_script_plan") or str(candidate.get("code") or "").strip():
        return "ai_script"
    return "unknown"


def _candidate_contract_result_key(candidate: Dict[str, Any]) -> Optional[str]:
    if not isinstance(candidate, dict):
        return None
    for section_key in ("ai_script_plan", "ai_instruction_step", "structured_intent"):
        section = candidate.get(section_key)
        if not isinstance(section, dict):
            continue
        result_key = section.get("result_key")
        if isinstance(result_key, str) and result_key.strip():
            return result_key.strip()
    parsed = candidate.get("parsed")
    if isinstance(parsed, dict):
        result_key = parsed.get("result_key")
        if isinstance(result_key, str) and result_key.strip():
            return result_key.strip()
    return None


def _restore_candidate_result_key(candidate: Dict[str, Any], result_key: Optional[str]) -> Dict[str, Any]:
    if not result_key:
        return candidate
    restored = dict(candidate)
    for section_key in ("ai_script_plan", "ai_instruction_step", "structured_intent"):
        section = restored.get(section_key)
        if isinstance(section, dict):
            restored[section_key] = dict(section)
            restored[section_key]["result_key"] = result_key
    parsed = dict(restored.get("parsed") or {})
    parsed["result_key"] = result_key
    restored["parsed"] = parsed
    if restored.get("ai_script_plan"):
        restored["action_payload"] = json.dumps(restored["ai_script_plan"], ensure_ascii=False, default=str)
    elif restored.get("ai_instruction_step"):
        restored["action_payload"] = json.dumps(restored["ai_instruction_step"], ensure_ascii=False, default=str)
    elif restored.get("structured_intent"):
        restored["action_payload"] = json.dumps(restored["structured_intent"], ensure_ascii=False, default=str)
    return restored


def _compact_react_history_after_success(
    history_prefix: List[Dict[str, str]],
    goal_message: str,
    successful_trace_steps: List[Dict[str, Any]],
    current_url: str,
    latest_execution_observation: str = "",
) -> List[Dict[str, str]]:
    if not successful_trace_steps:
        return history_prefix + [{"role": "user", "content": goal_message}]

    recent_facts = [
        _step_completion_fact(step, current_url if index == len(successful_trace_steps) - 1 else "")
        for index, step in enumerate(successful_trace_steps[-6:])
    ]
    summary = (
        "Completed subtask facts (already finished; do not revisit or roll back to them unless a later execution "
        "explicitly fails and proves that state is wrong):\n"
        + "\n".join(recent_facts)
        + "\nContinue only from the current page and the remaining unfinished subtask."
    )
    return history_prefix + [
        {"role": "user", "content": goal_message},
        {"role": "user", "content": summary},
        *([{"role": "user", "content": latest_execution_observation}] if latest_execution_observation else []),
    ]


async def _capture_page_observation(page: Page) -> Dict[str, Any]:
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


def _looks_like_javascript_code(code: str) -> bool:
    normalized = (code or "").strip().lower()
    if not normalized:
        return False
    if normalized.startswith("async def run(") or normalized.startswith("def run("):
        return any(
            pattern in normalized
            for pattern in (
                "page.evaluate",
                "document.queryselector",
                "document.queryselectorall",
                "window.location",
                "=>",
            )
        )
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


def _structured_intent_signature(intent: Optional[Dict[str, Any]]) -> str:
    if not isinstance(intent, dict):
        return ""

    signature = {
        "action": intent.get("action"),
        "target_hint": intent.get("target_hint"),
        "collection_hint": intent.get("collection_hint"),
        "ordinal": intent.get("ordinal"),
        "value": intent.get("value"),
        "result_key": intent.get("result_key"),
    }
    compact_signature = {key: value for key, value in signature.items() if value not in (None, "", {}, [])}
    if not compact_signature:
        return ""
    return json.dumps(compact_signature, ensure_ascii=False, sort_keys=True)


def _should_reflect_on_stalled_structured_path(
    structured_intent: Optional[Dict[str, Any]],
    last_structured_signature: str,
    stall_score: int,
) -> bool:
    current_signature = _structured_intent_signature(structured_intent)
    if not current_signature:
        return False
    if last_structured_signature and current_signature == last_structured_signature:
        return True
    return stall_score >= 2


REACT_SYSTEM_PROMPT = """You are an RPA automation agent.

You receive a goal and must iteratively observe the current page, decide the next small step, execute it, and continue until the goal is complete.

The final recorded result must follow this step type classification contract:
""" + STEP_TYPE_CLASSIFICATION_GUIDANCE + """

Use these examples as the default interpretation pattern:
""" + STEP_TYPE_FEW_SHOTS + """

Do not collapse the whole goal into one giant ai_instruction. Break complex goals into multiple small executable steps.

Return exactly one JSON object per turn, not wrapped in markdown.

Preferred format:
{
  "thought": "brief reasoning about the current page and next step",
  "action": "execute|done|abort",
  "step_type": "structured|ai_script|ai_instruction",
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
  "output_shape": "record_array|single_value|unspecified",
  "record_fields": ["title", "author"],
  "item_limit": 10,
  "selection_scope": "current_view|all_states",
  "entity_hint": "pull_requests|issues|table_rows|cards|...",
  "stable_subpage_hint": "/pulls|/issues|/actions|...",
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
3. For runtime page data plus deterministic, encodable rules such as ranking, sorting, numeric comparison, fixed filtering, or looping over stable page structures, set step_type to ai_script.
3a. For deterministic batch extraction tasks such as collecting top N items, returning a strict array, or gathering repeated title/author/status fields, prefer one ai_script over repeated structured clicks.
3b. When step_type is ai_script, describe the subtask using a complete ai_script subtask contract: description, result_key, output_shape, record_fields, item_limit, selection_scope, entity_hint, stable_subpage_hint, target_hint, collection_hint, ordinal, value, and any value_from/url_from/target_from reference fields that apply. Do not return Python code here; a dedicated ai_script generator will produce the code.
3c. If a stable subpage is already implied by the goal or current repo context, such as /issues or /pulls, express that target in the ai_script planning fields instead of navigating to the parent page and repeatedly clicking tabs.
3d. The ai_script contract is the semantic source of truth for the generator. Do not leave important constraints only inside description or value when they can be represented by contract fields such as record_fields, item_limit, selection_scope, entity_hint, or stable_subpage_hint.
4. Use ai_instruction for runtime page data plus semantic/business judgment whose correctness depends on understanding current-page meaning.
5. For summary/explanation/judgment tasks, the ai_instruction prompt should describe only that local semantic step, not the entire original goal.
5a. Classify by the rule above, not by isolated words. For example, "star" or "summary" alone is only a signal, not a step type decision.
6. Use collection semantics for first, last, and nth requests. Do not hard-code dynamic titles or href values.
7. For opening a website or jumping to a known URL, use operation=navigate with the URL in value. Do not refer to the browser address bar as a page textbox.
8. The backend resolves iframe context automatically from the snapshot. Do not invent iframe selectors unless the user explicitly names a frame.
9. Only use the code field for custom Playwright code when the action cannot be expressed as one atomic structured action.
10. For irreversible operations such as submit, delete, pay, or authorize, set risk to high.
11. For extraction tasks, use operation=extract_text, describe what data is being extracted, and include result_key as a short ASCII snake_case key such as latest_issue_title.
12. Do not mark the task done just because the data is visible on the page.
13. Execute the extraction step first and return the extracted value.
14. For example, if the user asks to get or read a title, first run extract_text on the target element, set result_key to something like latest_issue_title, then summarize the extracted value in description.
15. For deterministic "find the best item and open it" steps, prefer step_type=ai_script and describe that the dedicated ai_script should return the selected target URL/path (or a dict containing target_url/repo_path) after computing the choice. Do not hard-code that chosen item into later summary prompts.
16. When a summary step follows navigation, summarize the current page/repository generically. Do not bake a specific repo name or URL into the ai_instruction prompt.
"""

STEP_LOCAL_REPAIR_SYSTEM_PROMPT = """You are repairing exactly one failed RPA step.

You receive:
- the current page snapshot
- the original user goal
- the previously proposed step
- the execution or quality failure reason

Return exactly one JSON object, not wrapped in markdown.

Rules:
1. Repair only the current subtask. Do not restart the whole task or revisit earlier committed steps.
2. Keep the scope narrow and return one next step only.
3. Preserve the failed step kind unless the runtime explicitly says this step is allowed to change kind.
4. Preserve result_key, script_brief, output_contract, and other task-contract fields exactly when present.
5. If the previous structured step failed because the target shape was wrong, you may upgrade it only when the current failed step contract explicitly permits that upgrade.
6. If the previous ai_script failed, return one corrected ai_script step. Do not fall back to exploratory repeated clicks.
7. Do not repeat the same broken selector or the same broken DOM-guessing strategy.
8. Prefer stable navigation targets such as direct URLs or stable subpages over dynamic tab labels.
9. The code field must contain valid Python async Playwright code only.
""".strip()

AI_SCRIPT_GENERATION_SYSTEM_PROMPT = """You are a dedicated ai_script generator.

The planner has already decided that the current subtask must be implemented as exactly one ai_script step.

Return exactly one JSON object, not wrapped in markdown:
{
  "thought": "brief note",
  "action": "execute",
  "description": "short ai_script summary",
  "result_key": "optional_ascii_snake_case_key",
  "code": "async def run(page): ..."
}

Rules:
1. Generate only one ai_script step. Do not return structured actions or ai_instruction.
2. The complete ai_script subtask contract is the primary source of task semantics. Read and obey all contract fields, including output_shape, record_fields, item_limit, selection_scope, entity_hint, stable_subpage_hint, output_contract, target_hint, collection_hint, and reference fields.
2a. script_brief is only supplemental natural-language context. Do not let script_brief override, narrow, expand, or redefine structured contract fields.
3. Use the provided page snapshot to pick stable page structures. Prefer stable collections, containers, and direct target URLs over brittle DOM trivia.
4. Do not use page.evaluate or browser-side JavaScript. Use Python Playwright locators, query_selector/query_selector_all, and element handles instead.
5. The code field must contain valid Python async Playwright code only.
6. When the task requests a strict array or repeated records, return one deterministic list payload from code instead of multiple partial values.
7. If a stable navigation target or stable subpage hint is implied, have code return the selected target URL/path rather than hard-coding a click on dynamic tab labels.
8. Treat output_contract.max_items as an upper bound, not a required count. If fewer records exist in the correct scope, return the records that exist unless output_contract.min_items is explicitly set.
9. Treat scope phrases like all states/all statuses as data-source scope constraints, not as permission to merge unrelated views just to fill max_items.
""".strip()

AI_SCRIPT_REPAIR_SYSTEM_PROMPT = """You are repairing exactly one failed ai_script step.

Return exactly one JSON object, not wrapped in markdown:
{
  "thought": "brief note",
  "action": "execute",
  "description": "short ai_script summary",
  "result_key": "optional_ascii_snake_case_key",
  "code": "async def run(page): ..."
}

Rules:
1. Repair only the current ai_script subtask. Do not restart the whole task.
2. Preserve the complete ai_script subtask contract exactly, including output_shape, record_fields, item_limit, selection_scope, entity_hint, stable_subpage_hint, output_contract, script_brief, and result_key.
2a. Do not redefine contract fields from script_brief, description, previous broken code, or the repair failure message.
3. Do not use page.evaluate or browser-side JavaScript. Use Python Playwright locators, query_selector/query_selector_all, and element handles instead.
4. Do not repeat the same failing DOM-guessing pattern.
5. Prefer more stable collection/container scoping, stable href patterns, or direct target URLs.
6. Keep the result shape aligned with the requested fields and output format.
7. The code field must contain valid Python async Playwright code only.
8. Treat output_contract.max_items as an upper bound, not a required count, unless output_contract.min_items is explicitly set.
""".strip()




class RPAReActAgent:
    """ReAct-based autonomous agent: Observe → Think → Act loop."""

    MAX_STEPS = 20

    def __init__(self):
        self._confirm_event: Optional[asyncio.Event] = None
        self._confirm_approved: bool = False
        self._aborted: bool = False
        self._history: List[Dict[str, str]] = []  # persists across turns
        self._last_ai_script_generation_failure: str = ""

    def resolve_confirm(self, approved: bool) -> None:
        self._confirm_approved = approved
        if self._confirm_event:
            self._confirm_event.set()

    def abort(self) -> None:
        self._aborted = True
        if self._confirm_event:
            self._confirm_event.set()

    @staticmethod
    def _candidate_retry_budget(
        structured_intent: Optional[Dict[str, Any]],
        ai_instruction_step: Optional[Dict[str, Any]],
        code: str,
    ) -> int:
        if ai_instruction_step:
            return 1
        if structured_intent:
            return 1
        if str(code or "").strip():
            return 1
        return 0

    @staticmethod
    def _candidate_kind(
        ai_script_plan: Optional[Dict[str, Any]],
        structured_intent: Optional[Dict[str, Any]],
        ai_instruction_step: Optional[Dict[str, Any]],
        code: str,
    ) -> str:
        if ai_instruction_step:
            return "ai_instruction"
        if structured_intent:
            return "structured"
        if ai_script_plan:
            return "ai_script"
        if str(code or "").strip():
            return "ai_script"
        return "unknown"

    @staticmethod
    def _is_ai_script_candidate(
        action: str,
        ai_script_plan: Optional[Dict[str, Any]],
        structured_intent: Optional[Dict[str, Any]],
        ai_instruction_step: Optional[Dict[str, Any]],
        code: str,
    ) -> bool:
        return (
            str(action or "").strip().lower() == "execute"
            and bool(ai_script_plan or str(code or "").strip())
            and not structured_intent
            and not ai_instruction_step
        )

    @staticmethod
    def _candidate_requires_runtime_semantic_ai_instruction(
        goal: str,
        thought: str,
        description: str,
        ai_script_plan: Optional[Dict[str, Any]],
        structured_intent: Optional[Dict[str, Any]],
        ai_instruction_step: Optional[Dict[str, Any]],
        code: str,
    ) -> bool:
        if ai_instruction_step:
            return False
        if isinstance(structured_intent, dict) and _is_structured_runtime_ai_setup_step(structured_intent):
            return False
        if isinstance(structured_intent, dict):
            action = str(structured_intent.get("action") or "").strip().lower()
            if action == "navigate":
                value = str(structured_intent.get("value") or "").strip()
                if value.startswith(("http://", "https://")):
                    return False
        payload_parts: List[str] = [goal or "", thought or "", description or ""]
        if isinstance(ai_script_plan, dict):
            payload_parts.append(json.dumps(ai_script_plan, ensure_ascii=False))
        if isinstance(structured_intent, dict):
            payload_parts.append(json.dumps(structured_intent, ensure_ascii=False))
        if code:
            payload_parts.append(code)
        return _requires_runtime_semantic_selection(*payload_parts)

    @staticmethod
    def _candidate_requires_deterministic_ai_script(
        goal: str,
        thought: str,
        description: str,
        structured_intent: Optional[Dict[str, Any]],
        ai_instruction_step: Optional[Dict[str, Any]],
    ) -> bool:
        if isinstance(ai_instruction_step, dict):
            return _looks_like_record_array_request(
                ai_instruction_step.get("description"),
                ai_instruction_step.get("prompt"),
                ai_instruction_step.get("result_key"),
            )
        if isinstance(structured_intent, dict):
            action = str(structured_intent.get("action") or "").strip().lower()
            if action == "extract_text":
                return _looks_like_record_array_request(
                    description,
                    structured_intent.get("description"),
                    structured_intent.get("prompt"),
                    structured_intent.get("result_key"),
                    structured_intent.get("ordinal"),
                    structured_intent.get("collection_hint"),
                )
        return _structured_step_requires_ai_script(goal, thought, description, structured_intent)

    @staticmethod
    def _coerce_candidate_to_runtime_semantic_ai_instruction(
        candidate: Dict[str, Any],
        goal: str,
    ) -> Dict[str, Any]:
        description = str(candidate.get("description") or "").strip() or str(goal or "").strip() or "Execute semantic runtime instruction"
        parsed = {
            "action": "ai_instruction",
            "description": description,
            "prompt": description,
            "instruction_kind": "semantic_decision",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "act"},
            "execution_hint": {
                "requires_dom_snapshot": True,
                "allow_navigation": True,
                "max_reasoning_steps": AI_INSTRUCTION_DEFAULT_MAX_REASONING_STEPS,
                "planning_timeout_s": float(AI_INSTRUCTION_DEFAULT_PLANNING_TIMEOUT_S),
            },
        }
        coerced = RPAReActAgent._parse_step_candidate(
            parsed,
            goal,
            force_ai_instruction=False,
        )
        coerced["thought"] = candidate.get("thought") or coerced.get("thought", "")
        return coerced

    @staticmethod
    def _coerce_candidate_to_ai_script_plan(
        candidate: Dict[str, Any],
        goal: str,
    ) -> Dict[str, Any]:
        ai_instruction_step = candidate.get("ai_instruction_step") or {}
        structured_intent = candidate.get("structured_intent") or {}
        description = (
            str(ai_instruction_step.get("description") or "").strip()
            or str(candidate.get("description") or "").strip()
            or str(structured_intent.get("description") or "").strip()
            or "Execute ai_script step"
        )
        result_key = (
            ai_instruction_step.get("result_key")
            or structured_intent.get("result_key")
            or (candidate.get("parsed") or {}).get("result_key")
        )
        value = (
            ai_instruction_step.get("prompt")
            or structured_intent.get("prompt")
            or description
        )
        parsed = {
            "action": "execute",
            "step_type": "ai_script",
            "description": description,
            "result_key": result_key,
            "value": value,
        }
        coerced = RPAReActAgent._parse_step_candidate(
            parsed,
            goal,
            force_ai_instruction=False,
        )
        coerced["thought"] = candidate.get("thought") or coerced.get("thought", "")
        return coerced

    @staticmethod
    def _parse_step_candidate(
        parsed: Dict[str, Any],
        goal: str,
        force_ai_instruction: bool,
        allow_ai_script_code: bool = False,
    ) -> Dict[str, Any]:
        thought = parsed.get("thought", "")
        action = parsed.get("action", "execute")
        structured_intent = RPAReActAgent._extract_structured_execute_intent(parsed, goal)
        ai_instruction_step = RPAReActAgent._extract_execute_ai_instruction(
            parsed,
            goal,
            prefer_user_prompt=force_ai_instruction,
        )
        raw_code = parsed.get("code", "")
        ai_script_plan = RPAReActAgent._extract_ai_script_plan(parsed)
        code = raw_code if allow_ai_script_code and ai_script_plan else ""
        description = parsed.get("description", "Execute step")
        risk = parsed.get("risk", "none")
        risk_reason = parsed.get("risk_reason", "")
        action_payload = code or ""
        if structured_intent:
            action_payload = json.dumps(structured_intent, ensure_ascii=False)
        elif ai_instruction_step:
            action_payload = json.dumps(ai_instruction_step, ensure_ascii=False)
        elif ai_script_plan:
            action_payload = json.dumps(ai_script_plan, ensure_ascii=False)
        return {
            "thought": thought,
            "action": action,
            "ai_script_plan": ai_script_plan,
            "structured_intent": structured_intent,
            "ai_instruction_step": ai_instruction_step,
            "code": code,
            "description": description,
            "risk": risk,
            "risk_reason": risk_reason,
            "action_payload": action_payload,
            "parsed": parsed,
        }

    @staticmethod
    def _extract_ai_script_plan(parsed: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        step_type = str(parsed.get("step_type", "") or "").strip().lower()
        action = str(parsed.get("action", "") or "").strip().lower()
        if action in {"done", "abort"}:
            return None

        explicit_plan = parsed.get("ai_script")
        if isinstance(explicit_plan, dict):
            plan_payload = dict(explicit_plan)
        elif step_type == "ai_script":
            plan_payload = {}
        elif str(parsed.get("code", "") or "").strip():
            # Backward-compatible fallback: old planner outputs may still emit code.
            # We intentionally ignore the planner code and keep only planning hints.
            plan_payload = {}
        else:
            return None

        for key in (
            "description",
            "result_key",
            "target_hint",
            "collection_hint",
            "ordinal",
            "value",
            "output_shape",
            "record_fields",
            "item_limit",
            "min_items",
            "selection_scope",
            "entity_hint",
            "stable_subpage_hint",
            "script_brief",
            "output_contract",
            "value_from",
            "url_from",
            "target_from",
        ):
            if parsed.get(key) is not None and key not in plan_payload:
                plan_payload[key] = parsed.get(key)

        description = str(plan_payload.get("description", "") or "").strip()
        if not description:
            description = str(parsed.get("description", "") or "").strip()
        if not description:
            description = "Execute ai_script step"
        plan_payload["description"] = description
        result_key = plan_payload.get("result_key")
        if isinstance(result_key, str):
            result_key = result_key.strip()
        plan_payload["result_key"] = result_key or None

        output_shape = str(plan_payload.get("output_shape") or "").strip().lower()
        if output_shape not in {"record_array", "single_value", "unspecified"}:
            output_shape = ""
        if not output_shape:
            output_shape = _infer_ai_script_output_shape(
                description,
                plan_payload.get("value"),
                plan_payload.get("result_key"),
            )
        if output_shape != "unspecified":
            plan_payload["output_shape"] = output_shape

        raw_record_fields = plan_payload.get("record_fields")
        record_fields = [
            str(field).strip()
            for field in raw_record_fields
            if str(field).strip()
        ] if isinstance(raw_record_fields, list) else []
        if not record_fields:
            record_fields = _infer_ai_script_record_fields(
                description,
                plan_payload.get("value"),
                plan_payload.get("result_key"),
            )
        if record_fields:
            plan_payload["record_fields"] = record_fields

        item_limit = _normalize_optional_positive_int(plan_payload.get("item_limit"))
        if not item_limit:
            item_limit = _infer_ai_script_item_limit(
                plan_payload.get("ordinal"),
                description,
                plan_payload.get("value"),
                plan_payload.get("result_key"),
            )
        if item_limit:
            plan_payload["item_limit"] = item_limit

        selection_scope = str(plan_payload.get("selection_scope") or "").strip().lower()
        if selection_scope not in {"current_view", "all_states"}:
            selection_scope = _infer_ai_script_selection_scope(
                description,
                plan_payload.get("value"),
                plan_payload.get("target_hint"),
            )
        if selection_scope != "current_view":
            plan_payload["selection_scope"] = selection_scope

        stable_subpage_hint = str(plan_payload.get("stable_subpage_hint") or "").strip()
        if not stable_subpage_hint:
            stable_subpage_hint = _infer_ai_script_stable_subpage_hint(
                description,
                plan_payload.get("value"),
                plan_payload.get("target_hint"),
                plan_payload.get("collection_hint"),
            )
        if stable_subpage_hint:
            plan_payload["stable_subpage_hint"] = stable_subpage_hint

        entity_hint = str(plan_payload.get("entity_hint") or "").strip()
        if not entity_hint:
            entity_hint = _infer_ai_script_entity_hint(
                stable_subpage_hint,
                description,
                plan_payload.get("value"),
                plan_payload.get("target_hint"),
                plan_payload.get("collection_hint"),
            )
        if entity_hint:
            plan_payload["entity_hint"] = entity_hint

        min_items = _normalize_optional_positive_int(plan_payload.get("min_items"))
        plan_payload["script_brief"] = str(plan_payload.get("script_brief") or "").strip() or _build_ai_script_brief(
            description,
            plan_payload.get("value"),
            item_limit,
            selection_scope,
        )
        plan_payload["output_contract"] = plan_payload.get("output_contract") or _build_ai_script_output_contract(
            output_shape,
            record_fields,
            item_limit,
            min_items,
        )
        plan_payload["step_type"] = "ai_script"
        return plan_payload

    @staticmethod
    def _build_step_data_from_result(
        result: Dict[str, Any],
        ai_instruction_step: Optional[Dict[str, Any]],
        structured_intent: Optional[Dict[str, Any]],
        parsed: Dict[str, Any],
        code: str,
        description: str,
        goal: str,
        current_url: str,
    ) -> Dict[str, Any]:
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
            parsed_result_key = parsed.get("result_key")
            if isinstance(parsed_result_key, str) and parsed_result_key.strip():
                step_data["result_key"] = parsed_result_key.strip()
        return _normalize_recorded_step_after_success(step_data, current_url)

    @staticmethod
    def _result_issue_for_candidate(
        goal: str,
        description: str,
        structured_intent: Optional[Dict[str, Any]],
        ai_instruction_step: Optional[Dict[str, Any]],
        result: Dict[str, Any],
        ai_script_plan: Optional[Dict[str, Any]] = None,
    ) -> str:
        if ai_instruction_step:
            return ""
        if structured_intent:
            return _structured_result_quality_issue(structured_intent, result)
        return _ai_script_quality_issue(goal, description, result.get("raw_output"), ai_script_plan=ai_script_plan)

    @staticmethod
    async def _stream_llm_with_system_prompt(
        history: List[Dict[str, str]],
        system_prompt: str,
        model_config: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

        model = get_llm_model(config=model_config, streaming=True)
        lc_messages = [SystemMessage(content=system_prompt)]
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

    async def _request_step_local_repair(
        self,
        goal: str,
        snapshot: Dict[str, Any],
        candidate: Dict[str, Any],
        failure_reason: str,
        model_config: Optional[Dict[str, Any]],
        force_ai_instruction: bool,
    ) -> Optional[Dict[str, Any]]:
        step_kind = self._candidate_kind(
            candidate.get("ai_script_plan"),
            candidate.get("structured_intent"),
            candidate.get("ai_instruction_step"),
            candidate.get("code", ""),
        )
        previous_step = {
            "description": candidate.get("description"),
            "ai_script_plan": candidate.get("ai_script_plan"),
            "structured_intent": candidate.get("structured_intent"),
            "ai_instruction": candidate.get("ai_instruction_step"),
            "code": candidate.get("code"),
        }
        immutable_contract = {
            "step_kind": step_kind,
            "result_key": (
                (candidate.get("ai_script_plan") or {}).get("result_key")
                or (candidate.get("ai_instruction_step") or {}).get("result_key")
                or (candidate.get("structured_intent") or {}).get("result_key")
            ),
            "script_brief": (candidate.get("ai_script_plan") or {}).get("script_brief"),
            "output_contract": (candidate.get("ai_script_plan") or {}).get("output_contract"),
        }
        frame_lines = _snapshot_frame_lines(snapshot)
        repair_history = [
            {
                "role": "user",
                "content": (
                    f"Goal: {goal}\n"
                    f"Current page URL: {snapshot.get('url', '')}\n"
                    f"Current page title: {snapshot.get('title', '')}\n"
                    f"Current page snapshot:\n{chr(10).join(frame_lines) or '(no observable elements)'}\n\n"
                    f"Failed step kind: {step_kind}\n"
                    f"Failed step payload: {json.dumps(previous_step, ensure_ascii=False, default=str)}\n"
                    f"Immutable step contract: {json.dumps(immutable_contract, ensure_ascii=False, default=str)}\n"
                    f"Failure reason: {failure_reason}\n"
                    "Return exactly one corrected next-step JSON object that preserves the immutable step contract."
                ),
            }
        ]
        repair_response = ""
        async for chunk_text in self._stream_llm_with_system_prompt(
            repair_history,
            STEP_LOCAL_REPAIR_SYSTEM_PROMPT,
            model_config,
        ):
            repair_response += chunk_text

        parsed = self._parse_json(repair_response)
        if not parsed:
            return None
        repaired_candidate = self._parse_step_candidate(
            parsed,
            goal,
            force_ai_instruction,
            allow_ai_script_code=True,
        )
        original_kind = _candidate_contract_kind(candidate)
        repaired_kind = _candidate_contract_kind(repaired_candidate)
        if original_kind != "unknown" and repaired_kind != original_kind:
            return None
        return _restore_candidate_result_key(
            repaired_candidate,
            _candidate_contract_result_key(candidate),
        )

    async def _request_ai_script_candidate(
        self,
        goal: str,
        snapshot: Dict[str, Any],
        candidate: Dict[str, Any],
        model_config: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        generated_candidate = await self._request_ai_script_candidate_with_prompt(
            goal=goal,
            snapshot=snapshot,
            candidate=candidate,
            system_prompt=AI_SCRIPT_GENERATION_SYSTEM_PROMPT,
            model_config=model_config,
            failure_reason="",
        )
        if generated_candidate:
            return generated_candidate

        initial_failure = (
            self._last_ai_script_generation_failure
            or "ai_script_generator_returned_no_candidate"
        )
        repaired_candidate = await self._request_ai_script_repair(
            goal=goal,
            snapshot=snapshot,
            candidate=candidate,
            failure_reason=initial_failure,
            model_config=model_config,
        )
        if repaired_candidate:
            repaired_candidate["_generation_repair_attempted"] = True
            repaired_candidate["_generation_failure_reason"] = initial_failure
            return repaired_candidate

        repair_failure = self._last_ai_script_generation_failure
        if repair_failure and repair_failure != initial_failure:
            self._last_ai_script_generation_failure = (
                f"{initial_failure}; repair_failed: {repair_failure}"
            )
        else:
            self._last_ai_script_generation_failure = initial_failure
        return None

    async def _request_ai_script_repair(
        self,
        goal: str,
        snapshot: Dict[str, Any],
        candidate: Dict[str, Any],
        failure_reason: str,
        model_config: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        return await self._request_ai_script_candidate_with_prompt(
            goal=goal,
            snapshot=snapshot,
            candidate=candidate,
            system_prompt=AI_SCRIPT_REPAIR_SYSTEM_PROMPT,
            model_config=model_config,
            failure_reason=failure_reason,
        )

    async def _request_ai_script_candidate_with_prompt(
        self,
        goal: str,
        snapshot: Dict[str, Any],
        candidate: Dict[str, Any],
        system_prompt: str,
        model_config: Optional[Dict[str, Any]],
        failure_reason: str = "",
    ) -> Optional[Dict[str, Any]]:
        self._last_ai_script_generation_failure = ""
        frame_lines = _snapshot_frame_lines(snapshot)
        ai_script_plan = candidate.get("ai_script_plan") or {}
        planner_payload = dict(ai_script_plan)
        planner_payload["thought"] = candidate.get("thought")
        planner_payload["description"] = (
            planner_payload.get("description")
            or candidate.get("description")
        )
        planner_payload["result_key"] = (
            planner_payload.get("result_key")
            or (candidate.get("parsed") or {}).get("result_key")
        )
        planner_payload["script_brief"] = (
            planner_payload.get("script_brief")
            or planner_payload.get("description")
            or candidate.get("description")
        )
        request_lines = [
            f"Global goal: {goal}",
            f"Current page URL: {snapshot.get('url', '')}",
            f"Current page title: {snapshot.get('title', '')}",
            f"Current page snapshot:\n{chr(10).join(frame_lines) or '(no observable elements)'}",
            "",
            f"Current ai_script subtask contract: {json.dumps(planner_payload, ensure_ascii=False, default=str)}",
        ]
        if failure_reason:
            request_lines.extend(
                [
                    "",
                    f"Previous ai_script failure: {failure_reason}",
                ]
            )
        request_lines.extend(
            [
                "",
                "Return exactly one corrected ai_script JSON object.",
            ]
        )
        ai_script_history = [{"role": "user", "content": "\n".join(request_lines)}]

        ai_script_response = ""
        async for chunk_text in self._stream_llm_with_system_prompt(
            ai_script_history,
            system_prompt,
            model_config,
        ):
            ai_script_response += chunk_text

        parsed = self._parse_json(ai_script_response)
        if not parsed:
            self._last_ai_script_generation_failure = (
                "ai_script_generator_parse_failed"
            )
            return None
        parsed.setdefault("action", "execute")
        parsed.setdefault("description", candidate.get("description") or "Execute ai_script step")
        prior_result_key = (candidate.get("parsed") or {}).get("result_key")
        if isinstance(prior_result_key, str) and prior_result_key.strip() and not parsed.get("result_key"):
            parsed["result_key"] = prior_result_key.strip()
        generated_candidate = self._parse_step_candidate(
            parsed,
            goal,
            force_ai_instruction=False,
            allow_ai_script_code=True,
        )
        if self._candidate_kind(
            generated_candidate.get("ai_script_plan"),
            generated_candidate.get("structured_intent"),
            generated_candidate.get("ai_instruction_step"),
            generated_candidate.get("code", ""),
        ) != "ai_script":
            self._last_ai_script_generation_failure = (
                "ai_script_generator_kind_mismatch"
            )
            return None
        if not str(generated_candidate.get("code") or "").strip():
            self._last_ai_script_generation_failure = (
                "ai_script_generator_missing_code"
            )
            return None
        if _looks_like_javascript_code(str(generated_candidate.get("code") or "")):
            self._last_ai_script_generation_failure = (
                "ai_script_generator_rejected_javascript_code"
            )
            return None
        if ai_script_plan:
            preserved_plan = dict(ai_script_plan)
            generated_candidate["ai_script_plan"] = preserved_plan
            generated_candidate["description"] = str(
                preserved_plan.get("description")
                or candidate.get("description")
                or generated_candidate.get("description")
                or "Execute ai_script step"
            )
            preserved_result_key = preserved_plan.get("result_key")
            if isinstance(preserved_result_key, str) and preserved_result_key.strip():
                generated_candidate.setdefault("parsed", {})
                generated_candidate["parsed"]["result_key"] = preserved_result_key.strip()
            generated_candidate["action_payload"] = json.dumps(preserved_plan, ensure_ascii=False, default=str)
        elif not generated_candidate.get("ai_script_plan"):
            generated_candidate["ai_script_plan"] = {}
        generated_candidate["thought"] = candidate.get("thought") or generated_candidate.get("thought", "")
        generated_candidate["description"] = generated_candidate.get("description") or candidate.get("description") or "Execute ai_script step"
        self._last_ai_script_generation_failure = ""
        return generated_candidate

    @staticmethod
    def _summarize_failure_reason(reason: str) -> str:
        text = str(reason or "").strip()
        if not text:
            return "Unknown error"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return text[:300]
        non_traceback_lines = [
            line for line in lines
            if not line.startswith("Traceback")
            and not line.startswith("File ")
            and line != "^"
        ]
        if non_traceback_lines:
            return non_traceback_lines[-1][:300]
        return lines[-1][:300]

    @classmethod
    def _build_bounded_failure_payload(
        cls,
        failure_kind: str,
        attempts_used: int,
        repair_attempted: bool,
        step_description: str,
        last_error: str,
        total_steps: int,
    ) -> Dict[str, Any]:
        summarized_error = cls._summarize_failure_reason(last_error)
        if failure_kind == "ai_script":
            repair_text = "and one local repair were attempted" if repair_attempted else "was attempted"
            diagnostic_text = (
                f" Last error: {summarized_error}."
                if summarized_error and summarized_error != "Unknown error"
                else ""
            )
            reason = (
                f"ai_script step could not reliably converge after {attempts_used} bounded attempt(s). "
                f"A dedicated ai_script generation {repair_text}, but the current DOM abstraction or scripted "
                "extraction strategy cannot reliably converge."
                f"{diagnostic_text} Stopping here to avoid polluting recorded steps."
            )
            return {
                "reason": reason,
                "total_steps": total_steps,
                "failure_kind": "ai_script",
                "bounded_attempts": attempts_used,
                "repair_attempted": repair_attempted,
                "step_description": step_description,
                "last_error": summarized_error,
                "stop_reason": "ai_script_non_convergent",
            }
        if failure_kind == "ai_instruction":
            repair_text = "and one local repair were attempted" if repair_attempted else "was attempted"
            return {
                "reason": (
                    f"ai_instruction step failed after {attempts_used} bounded attempt(s). "
                    f"The runtime ai_instruction execution {repair_text}, but the semantic extraction/action plan "
                    "still could not be executed reliably. Stopping here to avoid polluting recorded steps."
                ),
                "total_steps": total_steps,
                "failure_kind": "ai_instruction",
                "bounded_attempts": attempts_used,
                "repair_attempted": repair_attempted,
                "step_description": step_description,
                "last_error": summarized_error,
                "stop_reason": "ai_instruction_non_convergent",
            }
        return {
            "reason": (
                f"Failed to complete the current {failure_kind or 'step'} after {attempts_used} bounded attempt(s): "
                f"{summarized_error}"
            ),
            "total_steps": total_steps,
            "failure_kind": failure_kind or "unknown",
            "bounded_attempts": attempts_used,
            "repair_attempted": repair_attempted,
            "step_description": step_description,
            "last_error": summarized_error,
            "stop_reason": "bounded_step_failure",
        }

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
        working_trace_steps: List[Dict[str, Any]] = []
        committed_steps: List[Dict[str, Any]] = []
        last_structured_signature = ""
        stall_score = 0
        execution_results: Dict[str, Any] = {}
        force_ai_instruction = RPAAssistant._should_force_ai_instruction(goal)
        history_prefix = list(self._history)

        # Append new user goal to persistent history
        steps_summary = ""
        if existing_steps:
            lines = [f"{i+1}. {s.get('description', s.get('action', ''))}" for i, s in enumerate(existing_steps)]
            steps_summary = "\nExisting steps:\n" + "\n".join(lines) + "\n"
        goal_message = f"Goal: {goal}{steps_summary}"
        self._history.append({"role": "user", "content": goal_message})

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

            candidate = self._parse_step_candidate(parsed, goal, force_ai_instruction)
            thought = candidate["thought"]
            action = candidate["action"]
            ai_script_plan = candidate.get("ai_script_plan")
            structured_intent = candidate["structured_intent"]
            ai_instruction_step = candidate["ai_instruction_step"]
            code = candidate["code"]
            description = candidate["description"]
            risk = candidate["risk"]
            risk_reason = candidate["risk_reason"]
            action_payload = candidate["action_payload"]

            if action == "done":
                if thought:
                    yield {"event": "agent_thought", "data": {"text": thought}}
                recorded_steps = _distill_react_recorded_steps(goal, committed_steps)
                yield {"event": "agent_recorded_steps", "data": {"steps": recorded_steps}}
                yield {"event": "agent_done", "data": {"total_steps": steps_done}}
                return

            if action == "abort":
                if thought:
                    yield {"event": "agent_thought", "data": {"text": thought}}
                yield {"event": "agent_aborted", "data": {"reason": thought}}
                return

            if _react_step_violates_explicit_ai_instruction_request(
                goal,
                ai_instruction_step,
                structured_intent=structured_intent,
            ):
                self._history.append(
                    {
                        "role": "user",
                        "content": (
                            "Previous step proposal was rejected. "
                            "The user explicitly requested a runtime AI instruction or asked not to expand the rule "
                            "into a fixed script. Return ai_instruction for this step instead of structured action or code."
                        ),
                    }
                )
                continue

            if self._candidate_requires_runtime_semantic_ai_instruction(
                goal,
                thought,
                description,
                ai_script_plan,
                structured_intent,
                ai_instruction_step,
                code,
            ):
                candidate = self._coerce_candidate_to_runtime_semantic_ai_instruction(candidate, goal)
                thought = candidate["thought"]
                action = candidate["action"]
                ai_script_plan = candidate.get("ai_script_plan")
                structured_intent = candidate["structured_intent"]
                ai_instruction_step = candidate["ai_instruction_step"]
                code = candidate["code"]
                description = candidate["description"]
                risk = candidate["risk"]
                risk_reason = candidate["risk_reason"]
                action_payload = candidate["action_payload"]

            if not force_ai_instruction and self._candidate_requires_deterministic_ai_script(
                goal,
                thought,
                description,
                structured_intent,
                ai_instruction_step,
            ):
                candidate = self._coerce_candidate_to_ai_script_plan(candidate, goal)
                thought = candidate["thought"]
                action = candidate["action"]
                ai_script_plan = candidate.get("ai_script_plan")
                structured_intent = candidate["structured_intent"]
                ai_instruction_step = candidate["ai_instruction_step"]
                code = candidate["code"]
                description = candidate["description"]
                risk = candidate["risk"]
                risk_reason = candidate["risk_reason"]
                action_payload = candidate["action_payload"]

            if _structured_step_requires_ai_script(goal, thought, description, structured_intent):
                self._history.append(
                    {
                        "role": "user",
                        "content": (
                            "Previous step proposal was rejected. "
                            "This subtask depends on runtime page data plus deterministic ranking, comparison, or "
                            "selection logic. Return one ai_script step instead of a structured action."
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

            if self._is_ai_script_candidate(action, ai_script_plan, structured_intent, ai_instruction_step, code):
                generated_ai_script_candidate = await self._request_ai_script_candidate(
                    goal=goal,
                    snapshot=snapshot,
                    candidate=candidate,
                    model_config=model_config,
                )
                if generated_ai_script_candidate:
                    candidate = generated_ai_script_candidate
                    candidate["thought"] = thought or candidate.get("thought", "")
                    thought = candidate["thought"]
                    action = candidate["action"]
                    ai_script_plan = candidate.get("ai_script_plan")
                    structured_intent = candidate["structured_intent"]
                    ai_instruction_step = candidate["ai_instruction_step"]
                    code = candidate["code"]
                    description = candidate["description"]
                    risk = candidate["risk"]
                    risk_reason = candidate["risk_reason"]
                    action_payload = candidate["action_payload"]

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

            if _should_reflect_on_stalled_structured_path(
                structured_intent,
                last_structured_signature=last_structured_signature,
                stall_score=stall_score,
            ):
                self._history.append(
                    {
                        "role": "user",
                        "content": STRUCTURED_STALL_REFLECTION_MESSAGE,
                    }
                )
                stall_score = 0
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

            active_candidate = candidate
            active_snapshot = snapshot
            retry_budget = self._candidate_retry_budget(structured_intent, ai_instruction_step, code)
            generation_repair_attempted = bool(active_candidate.get("_generation_repair_attempted"))
            if generation_repair_attempted and self._candidate_kind(
                active_candidate.get("ai_script_plan"),
                active_candidate.get("structured_intent"),
                active_candidate.get("ai_instruction_step"),
                active_candidate.get("code", ""),
            ) == "ai_script":
                retry_budget = 0
            local_attempt = 0
            committed_step_data: Optional[Dict[str, Any]] = None
            committed_output = ""
            abort_reason = ""
            last_failure_kind = self._candidate_kind(
                active_candidate["ai_script_plan"],
                active_candidate["structured_intent"],
                active_candidate["ai_instruction_step"],
                active_candidate["code"],
            )
            repair_attempted = generation_repair_attempted

            while True:
                yield {
                    "event": "agent_action",
                    "data": {
                        "description": active_candidate["description"],
                        "code": active_candidate["action_payload"],
                    },
                }
                current_page = page_provider() if page_provider else page
                if current_page is None:
                    yield {"event": "agent_aborted", "data": {"reason": "No active page available"}}
                    return
                before_observation = await _capture_page_observation(current_page)

                active_structured_intent = active_candidate["structured_intent"]
                active_ai_script_plan = active_candidate["ai_script_plan"]
                active_ai_instruction_step = active_candidate["ai_instruction_step"]
                active_code = active_candidate["code"]
                active_description = active_candidate["description"]
                active_parsed = active_candidate["parsed"]
                last_failure_kind = self._candidate_kind(
                    active_candidate["ai_script_plan"],
                    active_structured_intent,
                    active_ai_instruction_step,
                    active_code,
                )

                if active_ai_instruction_step:
                    from backend.rpa.runtime_ai_instruction import execute_ai_instruction

                    result = await execute_ai_instruction(
                        current_page,
                        active_ai_instruction_step,
                        results=execution_results,
                        model_config=model_config,
                    )
                    failure_reason = ""
                elif active_structured_intent:
                    resolved_intent = resolve_structured_intent(active_snapshot, active_structured_intent)
                    result = await execute_structured_intent(
                        current_page,
                        resolved_intent,
                        results=execution_results,
                    )
                    failure_reason = (
                        self._result_issue_for_candidate(
                            goal,
                            active_description,
                            active_structured_intent,
                            active_ai_instruction_step,
                            result,
                            ai_script_plan=active_ai_script_plan,
                        )
                        if result.get("success")
                        else str(result.get("error", "Unknown error"))
                    )
                else:
                    executable = self._wrap_code(active_code)
                    result = await _execute_on_page(current_page, executable)
                    if result.get("success"):
                        _store_ai_script_execution_result(execution_results, active_candidate, result)
                    failure_reason = (
                        self._result_issue_for_candidate(
                            goal,
                            active_description,
                            active_structured_intent,
                            active_ai_instruction_step,
                            result,
                            ai_script_plan=active_ai_script_plan,
                        )
                        if result.get("success")
                        else str(result.get("error", "Unknown error"))
                    )
                    if result.get("success") and not failure_reason:
                        nav_target = _extract_ai_script_navigation_target(
                            getattr(current_page, "url", ""),
                            result.get("raw_output"),
                        )
                        if nav_target and getattr(current_page, "url", "").rstrip("/") != nav_target.rstrip("/"):
                            try:
                                await current_page.goto(nav_target)
                                await current_page.wait_for_load_state("domcontentloaded")
                            except Exception as nav_error:
                                failure_reason = f"selected target {nav_target} but navigation did not complete: {nav_error}"

                if result.get("success") and not failure_reason:
                    current_url = str(getattr(current_page, "url", "") or "")
                    committed_step_data = self._build_step_data_from_result(
                        result=result,
                        ai_instruction_step=active_ai_instruction_step,
                        structured_intent=active_structured_intent,
                        parsed=active_parsed,
                        code=active_code,
                        description=active_description,
                        goal=goal,
                        current_url=current_url,
                    )
                    committed_output = result.get("output", "")
                    working_trace_steps.append(
                        {
                            "status": "committed",
                            "step": committed_step_data,
                            "attempt": local_attempt,
                        }
                    )
                    break

                working_trace_steps.append(
                    {
                        "status": "failed_attempt",
                        "kind": self._candidate_kind(
                            active_candidate["ai_script_plan"],
                            active_structured_intent,
                            active_ai_instruction_step,
                            active_code,
                        ),
                        "description": active_description,
                        "error": failure_reason or str(result.get("error", "Unknown error")),
                        "attempt": local_attempt,
                    }
                )
                if local_attempt >= retry_budget:
                    abort_reason = failure_reason or str(result.get("error", "Unknown error"))
                    break

                repair_page = page_provider() if page_provider else page
                if repair_page is None:
                    abort_reason = "No active page available"
                    break
                repair_snapshot = active_snapshot
                after_observation = await _capture_page_observation(repair_page)
                if _has_observable_page_change(before_observation, after_observation):
                    repair_snapshot = await build_page_snapshot(repair_page, build_frame_path_from_frame)
                repair_attempted = True
                if last_failure_kind == "ai_script":
                    repaired_candidate = await self._request_ai_script_repair(
                        goal=goal,
                        snapshot=repair_snapshot,
                        candidate=active_candidate,
                        failure_reason=failure_reason or str(result.get("error", "Unknown error")),
                        model_config=model_config,
                    )
                else:
                    repaired_candidate = await self._request_step_local_repair(
                        goal=goal,
                        snapshot=repair_snapshot,
                        candidate=active_candidate,
                        failure_reason=failure_reason or str(result.get("error", "Unknown error")),
                        model_config=model_config,
                        force_ai_instruction=force_ai_instruction,
                    )
                if not repaired_candidate or repaired_candidate.get("action") in {"done", "abort"}:
                    abort_reason = failure_reason or str(result.get("error", "Unknown error"))
                    break
                active_snapshot = repair_snapshot
                active_candidate = repaired_candidate
                local_attempt += 1

            if committed_step_data is None:
                yield {
                    "event": "agent_aborted",
                    "data": self._build_bounded_failure_payload(
                        failure_kind=last_failure_kind,
                        attempts_used=local_attempt + 1,
                        repair_attempted=repair_attempted,
                        step_description=active_candidate.get("description", ""),
                        last_error=abort_reason,
                        total_steps=steps_done,
                    ),
                }
                return

            steps_done += 1
            current_structured_signature = _structured_intent_signature(
                committed_step_data if committed_step_data.get("action") in {"navigate", "click", "fill", "extract_text", "press"} else None
            )
            if not current_structured_signature and structured_intent:
                current_structured_signature = _structured_intent_signature(structured_intent)
            if current_structured_signature:
                stall_score = 1
                last_structured_signature = current_structured_signature
            else:
                stall_score = 0
                last_structured_signature = ""
            committed_steps.append(committed_step_data)
            current_url = str(getattr((page_provider() if page_provider else page), "url", "") or "")
            latest_execution_observation = _build_execution_observation(
                committed_step_data,
                committed_output,
                current_url,
            )
            self._history = _compact_react_history_after_success(
                history_prefix=history_prefix,
                goal_message=goal_message,
                successful_trace_steps=committed_steps,
                current_url=current_url,
                latest_execution_observation=latest_execution_observation,
            )
            yield {
                "event": "agent_recorded_steps",
                "data": {"steps": _distill_react_recorded_steps(goal, committed_steps)},
            }
            if committed_output and committed_output != "ok" and committed_output != "None":
                yield {"event": "agent_step_done", "data": {"step": committed_step_data, "output": committed_output}}
            else:
                yield {"event": "agent_step_done", "data": {"step": committed_step_data}}

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
        for key in (
            "target_hint",
            "collection_hint",
            "ordinal",
            "value",
            "result_key",
            "value_from",
            "url_from",
            "target_from",
        ):
            value = parsed.get(key)
            if value is not None:
                intent[key] = value
        return intent

    @staticmethod
    def _extract_execute_ai_instruction(
        parsed: Dict[str, Any],
        prompt: str,
        prefer_user_prompt: bool = False,
    ) -> Optional[Dict[str, Any]]:
        candidate = parsed.get("ai_instruction")
        if not isinstance(candidate, dict):
            if str(parsed.get("action", "") or "").strip().lower() == "ai_instruction":
                candidate = parsed
            else:
                return None

        candidate_payload = dict(candidate)
        candidate_payload.setdefault("action", "ai_instruction")
        return RPAAssistant._coerce_to_ai_instruction(
            prompt,
            candidate_payload,
            prefer_user_prompt=prefer_user_prompt,
        )

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

    @classmethod
    def _coerce_to_ai_instruction(
        cls,
        user_message: str,
        parsed: Optional[Dict[str, Any]] = None,
        prefer_user_prompt: bool = False,
    ) -> Dict[str, Any]:
        output_expectation = cls._infer_ai_instruction_output_mode(user_message, parsed)
        parsed_kind = cls._infer_ai_instruction_kind(user_message, parsed)

        description = (parsed or {}).get("description")
        if cls._is_placeholder_text(description):
            description = user_message

        parsed_prompt = (parsed or {}).get("prompt")
        if prefer_user_prompt:
            prompt = user_message
            if cls._is_placeholder_text(prompt):
                prompt = parsed_prompt
        else:
            prompt = parsed_prompt
            if cls._is_placeholder_text(prompt):
                prompt = user_message

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
        if parsed_kind == "semantic_decision" and output_expectation.get("mode") == "act":
            allow_navigation = True
            normalized_prompt = str(prompt or user_message).strip()
            if SEMANTIC_DECISION_ACT_PROMPT_SUFFIX.lower() not in normalized_prompt.lower():
                prompt = (
                    f"{normalized_prompt}\n\n{SEMANTIC_DECISION_ACT_PROMPT_SUFFIX}"
                    if normalized_prompt
                    else SEMANTIC_DECISION_ACT_PROMPT_SUFFIX
                )

        return {
            "action": "ai_instruction",
            "source": "ai",
            "description": description or user_message,
            "prompt": prompt or user_message,
            "global_goal": user_message,
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
        execution_results: Dict[str, Any] = {}
        result, final_response, code, resolution, retry_notice = await self._execute_with_retry(
            page=page,
            page_provider=page_provider,
            snapshot=snapshot,
            full_response=full_response,
            user_message=message,
            force_ai_instruction=force_ai_instruction,
            messages=messages,
            model_config=model_config,
            execution_results=execution_results,
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
        execution_results: Dict[str, Any],
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
                model_config=model_config,
                execution_results=execution_results,
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
                model_config=model_config,
                execution_results=execution_results,
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
        model_config: Optional[Dict[str, Any]] = None,
        execution_results: Optional[Dict[str, Any]] = None,
    ) -> tuple[Dict[str, Any], Optional[str], Optional[Dict[str, Any]]]:
        execution_results = execution_results if isinstance(execution_results, dict) else {}
        parsed_response = self._parse_json(full_response) or {}
        ai_instruction = self._extract_ai_instruction(full_response)
        if ai_instruction:
            from backend.rpa.runtime_ai_instruction import execute_ai_instruction

            step = self._coerce_to_ai_instruction(user_message, ai_instruction)
            result = await execute_ai_instruction(
                current_page,
                step,
                results=execution_results,
                model_config=model_config,
            )
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

            step = self._coerce_to_ai_instruction(
                user_message,
                structured_intent,
                prefer_user_prompt=True,
            )
            result = await execute_ai_instruction(
                current_page,
                step,
                results=execution_results,
                model_config=model_config,
            )
            success = result.get("success", True)
            return {
                "success": success,
                "output": result.get("output") or ("ai_instruction executed" if success else ""),
                "error": result.get("error"),
                "step": step,
            }, None, None
        if structured_intent:
            resolved_intent = resolve_structured_intent(snapshot, structured_intent)
            result = await execute_structured_intent(
                current_page,
                resolved_intent,
                results=execution_results,
            )
            return result, None, resolved_intent

        code = self._extract_code(full_response)
        if force_ai_instruction and code:
            from backend.rpa.runtime_ai_instruction import execute_ai_instruction

            step = self._coerce_to_ai_instruction(
                user_message,
                prefer_user_prompt=True,
            )
            result = await execute_ai_instruction(
                current_page,
                step,
                results=execution_results,
                model_config=model_config,
            )
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
        if result.get("success"):
            _store_ai_script_execution_result(execution_results, {"parsed": parsed_response}, result)
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



