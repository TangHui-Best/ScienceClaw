from __future__ import annotations

import inspect
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from .recording_runtime_agent import RecordingAgentResult, _page_state
from .trace_models import RPAAcceptedTrace, RPAAIExecution, RPATraceDiagnostic, RPATraceType


BrowserUseRunner = Callable[..., Awaitable[Any]]
CdpUrlResolver = Callable[[Any, Optional[Dict[str, Any]]], Awaitable[str] | str]


class BrowserUseTaskFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        actions: Optional[list[Dict[str, Any]]] = None,
        action_results: Optional[list[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(message)
        self.actions = list(actions or [])
        self.action_results = list(action_results or [])


class BrowserUseRecordingOperator:
    """Run one recording instruction through browser-use and store it as a semantic trace."""

    def __init__(
        self,
        *,
        model_config: Optional[Dict[str, Any]] = None,
        cdp_url_resolver: Optional[CdpUrlResolver] = None,
        browser_use_runner: Optional[BrowserUseRunner] = None,
        max_steps: Optional[int] = None,
    ) -> None:
        self.model_config = model_config or {}
        self.cdp_url_resolver = cdp_url_resolver or _default_cdp_url_resolver
        self.browser_use_runner = browser_use_runner or _run_browser_use_agent
        self.max_steps = max_steps or int(os.environ.get("BROWSER_USE_MAX_STEPS", "12"))

    async def run(
        self,
        *,
        page: Any,
        instruction: str,
        runtime_results: Optional[Dict[str, Any]] = None,
        debug_context: Optional[Dict[str, Any]] = None,
        region_context: Optional[Dict[str, Any]] = None,
    ) -> RecordingAgentResult:
        before = await _page_state(page)
        try:
            cdp_url = await _maybe_await(self.cdp_url_resolver(page, debug_context))
            if not str(cdp_url or "").strip():
                raise RuntimeError("browser-use requires a CDP URL to reuse the current recording browser.")
            history = await self.browser_use_runner(
                instruction=instruction,
                cdp_url=str(cdp_url),
                model_config=self.model_config,
                runtime_results=runtime_results or {},
                region_context=region_context or {},
                max_steps=self.max_steps,
                current_url=before.url,
            )
            actions = _history_model_actions(history)
            action_results = _history_action_results(history)
            failure_reason = _browser_use_failure_reason(history, actions, action_results)
            if failure_reason:
                raise BrowserUseTaskFailure(failure_reason, actions=actions, action_results=action_results)
            after = await _page_state(page)
            extracted_content = _history_extracted_content(history)
            output = {
                "extracted_content": extracted_content,
                "action_count": len(actions),
            }
            trace = RPAAcceptedTrace(
                trace_type=RPATraceType.AI_OPERATION,
                source="browser_use",
                user_instruction=instruction,
                description=instruction,
                before_page=before,
                after_page=after,
                signals={
                    "runtime_ai": {
                        "preserve": True,
                        "reason": "browser_use_recording",
                        "provider": "browser_use",
                    },
                    "browser_use": {
                        "actions": actions,
                        "action_results": action_results,
                        "extracted_content": extracted_content,
                        "max_steps": self.max_steps,
                    },
                },
                region_context=dict(region_context or {}),
                output=output,
                ai_execution=RPAAIExecution(
                    language="browser_use",
                    code="",
                    output=output,
                ),
            )
            return RecordingAgentResult(
                success=True,
                trace=trace,
                output=output,
                message="browser-use recording command completed.",
            )
        except Exception as exc:
            return RecordingAgentResult(
                success=False,
                diagnostics=[
                    RPATraceDiagnostic(
                        source="browser_use",
                        message=str(exc),
                        raw=_diagnostic_raw(exc),
                    )
                ],
                message=f"browser-use recording command failed: {exc}",
            )


async def _execute_browser_use_runtime_instruction(
    page: Any,
    results: Dict[str, Any],
    kwargs: Dict[str, Any],
    instruction: str,
    output_key: str,
) -> Any:
    runtime_context = kwargs.get("_runtime_context") if isinstance(kwargs, dict) else {}
    browser_use_context = runtime_context.get("browser_use") if isinstance(runtime_context, dict) else {}
    cdp_url = browser_use_context.get("cdp_url") if isinstance(browser_use_context, dict) else None
    model_config = _runtime_model_config(kwargs)
    operator = BrowserUseRecordingOperator(
        model_config=model_config,
        cdp_url_resolver=lambda _page, _debug_context: cdp_url or "",
    )
    outcome = await operator.run(page=page, instruction=instruction, runtime_results=results)
    if not outcome.success:
        detail = "; ".join(str(item.message) for item in outcome.diagnostics) or outcome.message
        raise RuntimeError(f"browser-use runtime instruction failed: {detail}")
    payload = outcome.output
    if output_key:
        results[output_key] = payload
    return payload


async def _default_cdp_url_resolver(page: Any, debug_context: Optional[Dict[str, Any]]) -> str:
    if isinstance(debug_context, dict):
        explicit = str(debug_context.get("cdp_url") or "").strip()
        if explicit:
            return explicit
        session_id = str(debug_context.get("session_id") or "").strip()
        user_id = str(debug_context.get("user_id") or "").strip() or None
    else:
        session_id = ""
        user_id = None
    if not session_id:
        return ""
    from backend.rpa.cdp_connector import get_cdp_connector

    connector = get_cdp_connector()
    fetcher = getattr(connector, "_fetch_cdp_url", None)
    if not callable(fetcher):
        return ""
    return await fetcher(session_id=session_id, user_id=user_id)


async def _run_browser_use_agent(
    *,
    instruction: str,
    cdp_url: str,
    model_config: Dict[str, Any],
    runtime_results: Dict[str, Any],
    region_context: Dict[str, Any],
    max_steps: int,
    current_url: str = "",
) -> Any:
    _configure_browser_use_runtime_env()
    _ensure_browser_use_import_path()
    from browser_use import Agent
    from browser_use.browser.session import BrowserSession
    from browser_use.llm.openai.chat import ChatOpenAI

    llm = ChatOpenAI(
        model=_model_name(model_config),
        api_key=_model_api_key(model_config),
        base_url=_model_base_url(model_config),
        temperature=0,
        max_completion_tokens=int(os.environ.get("BROWSER_USE_MAX_COMPLETION_TOKENS", "4096")),
    )
    session = BrowserSession(cdp_url=cdp_url, keep_alive=False)
    _disable_browser_use_screenshots_if_configured(session)
    task = _build_browser_use_task(instruction, runtime_results, region_context)
    agent = Agent(
        task=task,
        llm=llm,
        browser_session=session,
        available_file_paths=_available_file_paths(),
        initial_actions=_initial_browser_use_actions(current_url),
        max_actions_per_step=int(os.environ.get("BROWSER_USE_MAX_ACTIONS_PER_STEP", "5")),
        use_vision=os.environ.get("BROWSER_USE_USE_VISION", "false").strip().lower() == "true",
    )
    _ensure_browser_use_agent_timing(agent)
    return await agent.run(max_steps=max_steps)


def _configure_browser_use_runtime_env() -> None:
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
    os.environ.setdefault("BROWSER_USE_CLOUD_SYNC", "false")
    os.environ.setdefault("BROWSER_USE_VERSION_CHECK", "false")


def _ensure_browser_use_agent_timing(agent: Any) -> None:
    start_time = time.time()
    if not hasattr(agent, "_session_start_time"):
        setattr(agent, "_session_start_time", start_time)
    if not hasattr(agent, "_task_start_time"):
        setattr(agent, "_task_start_time", start_time)


def _disable_browser_use_screenshots_if_configured(session: Any) -> None:
    enabled = os.environ.get("BROWSER_USE_FORCE_NO_SCREENSHOTS", "true").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return
    original = getattr(session, "get_browser_state_summary", None)
    if not callable(original):
        return

    async def get_browser_state_summary_without_screenshot(*args: Any, **kwargs: Any) -> Any:
        kwargs["include_screenshot"] = False
        return await original(*args, **kwargs)

    object.__setattr__(session, "get_browser_state_summary", get_browser_state_summary_without_screenshot)


def _ensure_browser_use_import_path() -> None:
    try:
        import browser_use  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    configured = os.environ.get("BROWSER_USE_REPO_PATH", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(Path(__file__).resolve().parents[4] / "browser-use")
    for candidate in candidates:
        if candidate and (candidate / "browser_use").exists():
            sys.path.insert(0, str(candidate))
            return


def _build_browser_use_task(
    instruction: str,
    runtime_results: Dict[str, Any],
    region_context: Dict[str, Any],
) -> str:
    available_file_paths = _available_file_paths()
    lines = [
        "Complete this single ScienceClaw recording instruction in the current browser tab.",
        "Do not continue into unrelated workflow steps after the requested browser-visible goal is satisfied.",
        "Preserve the current page state. Do not navigate, reload, or reopen the same URL unless the user explicitly asks you to navigate.",
        "Use browser-use action schemas exactly. Use input with {index,text,clear} and click with {index} for indexed browser_state elements. For page text search, use search_page with {pattern}, not {query}. For scrolling upward, use scroll with {down:false, pages:1}; an empty scroll action scrolls downward. For native <select>, use select_dropdown with {index, text}. For JavaScript, use evaluate with {code}, not {script}; code must be a single wrapped IIFE expression, return a short string, and use only browser DOM APIs. For file inputs, use upload_file with {index, path}; never type a file path into the input and never click a file input to open a native dialog. There is no screenshot action.",
        "If find_elements reports matching inputs or buttons, prefer input/click by browser_state index when available. If no index is available, use evaluate with an IIFE to set input values, dispatch input/change events, and click the matching button by textContent or id.",
        "Treat tool results such as 'Typed ... into element' and 'Clicked button ...' as evidence that real browser actions executed. Do not repeat the same input/click pair more than once; after that, verify the DOM/status text with evaluate or call done if the requested visible goal is satisfied.",
        f"Instruction: {instruction}",
    ]
    if available_file_paths and _instruction_mentions_upload(instruction):
        lines.append(f"Available upload file paths: {available_file_paths}")
    if runtime_results:
        lines.append(f"Available prior runtime results: {runtime_results}")
    if region_context:
        lines.append(f"Selected region context: {region_context}")
    return "\n".join(lines)


def _instruction_mentions_upload(instruction: str) -> bool:
    lowered = instruction.lower()
    return any(token in lowered for token in ("upload", "上传", "附件", "file input", "选择文件"))


def _initial_browser_use_actions(current_url: str) -> list[dict[str, dict[str, Any]]] | None:
    enabled = os.environ.get("BROWSER_USE_INITIAL_NAVIGATE", "false").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return None
    url = str(current_url or "").strip()
    if not url or url == "about:blank":
        return None
    return [{"navigate": {"url": url}}]


def _available_file_paths() -> list[str]:
    raw = os.environ.get("BROWSER_USE_AVAILABLE_FILE_PATHS", "").strip()
    if not raw:
        return []
    return [path.strip() for path in raw.split(";") if path.strip()]


def _runtime_model_config(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    runtime_context = kwargs.get("_runtime_context") if isinstance(kwargs, dict) else None
    runtime_ai = runtime_context.get("runtime_ai") if isinstance(runtime_context, dict) else None
    model_config = runtime_ai.get("model_config") if isinstance(runtime_ai, dict) else None
    return dict(model_config or kwargs.get("_model_config") or {})


def _model_name(model_config: Dict[str, Any]) -> str:
    from backend.config import settings

    return str(model_config.get("model_name") or model_config.get("model") or settings.model_ds_name)


def _model_api_key(model_config: Dict[str, Any]) -> str:
    from backend.config import settings

    return str(model_config.get("api_key") or settings.model_ds_api_key)


def _model_base_url(model_config: Dict[str, Any]) -> str:
    from backend.config import settings

    return str(model_config.get("base_url") or settings.model_ds_base_url)


def _history_model_actions(history: Any) -> list[Dict[str, Any]]:
    method = getattr(history, "model_actions", None)
    if not callable(method):
        return []
    value = method()
    if not isinstance(value, list):
        return []
    actions: list[Dict[str, Any]] = []
    for item in value:
        normalized = _json_safe_browser_use_value(item)
        if isinstance(normalized, dict):
            actions.append(normalized)
    return actions


def _json_safe_browser_use_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe_browser_use_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_browser_use_value(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_safe_browser_use_value(value.model_dump(mode="json", exclude_none=True))
    return _browser_use_object_snapshot(value)


def _browser_use_object_snapshot(value: Any) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {"type": value.__class__.__name__}
    for attr in (
        "tag_name",
        "xpath",
        "x_path",
        "attributes",
        "text",
        "highlight_index",
        "css_selector",
    ):
        if not hasattr(value, attr):
            continue
        attr_value = getattr(value, attr)
        if attr_value is not None:
            snapshot[attr] = _json_safe_browser_use_value(attr_value)
    return snapshot


def _history_extracted_content(history: Any) -> list[str]:
    method = getattr(history, "extracted_content", None)
    if callable(method):
        value = method()
        if isinstance(value, list):
            return [str(item) for item in value]
    return []


def _history_action_results(history: Any) -> list[Dict[str, Any]]:
    method = getattr(history, "action_results", None)
    if not callable(method):
        return []
    results = []
    for item in method() or []:
        if hasattr(item, "model_dump"):
            results.append(_json_safe_browser_use_value(item.model_dump(mode="json", exclude_none=True)))
        else:
            results.append(
                _json_safe_browser_use_value(
                    {
                        "extracted_content": getattr(item, "extracted_content", None),
                        "long_term_memory": getattr(item, "long_term_memory", None),
                        "error": getattr(item, "error", None),
                        "is_done": getattr(item, "is_done", None),
                        "success": getattr(item, "success", None),
                    }
                )
            )
    return results


def _history_successful(history: Any) -> Optional[bool]:
    method = getattr(history, "is_successful", None)
    if callable(method):
        value = method()
        return bool(value) if value is not None else None
    return None


def _browser_use_failure_reason(
    history: Any,
    actions: list[Dict[str, Any]],
    action_results: list[Dict[str, Any]],
) -> str:
    has_done_success = any(
        isinstance(item, dict) and item.get("is_done") is True and item.get("success") is True
        for item in action_results
    )
    errors = [str(item.get("error")) for item in action_results if isinstance(item, dict) and item.get("error")]
    if errors and not has_done_success:
        return f"browser-use action failed: {errors[-1]}"
    successful = _history_successful(history)
    if successful is False:
        return "browser-use reported task failure."
    if successful is True:
        return ""
    if has_done_success:
        return ""
    if len(actions) <= 1 and _only_initial_navigation(actions):
        return "browser-use did not complete a browser-visible action beyond the initial navigation."
    return "browser-use did not provide explicit task success evidence."


def _only_initial_navigation(actions: list[Dict[str, Any]]) -> bool:
    if not actions:
        return True
    if len(actions) != 1:
        return False
    action = actions[0]
    return isinstance(action, dict) and "navigate" in action


def _diagnostic_raw(exc: Exception) -> Dict[str, Any]:
    raw: Dict[str, Any] = {"type": type(exc).__name__}
    if isinstance(exc, BrowserUseTaskFailure):
        raw["browser_use"] = {
            "actions": exc.actions,
            "action_results": exc.action_results,
        }
    return raw


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
