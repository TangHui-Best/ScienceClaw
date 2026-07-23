from __future__ import annotations

import inspect
import logging
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Literal, Optional

from pydantic import BaseModel, Field

from .recording_runtime_agent import RecordingAgentResult, _page_state
from .trace_models import RPAAcceptedTrace, RPAAIExecution, RPATraceDiagnostic, RPATraceType


BrowserUseRunner = Callable[..., Awaitable[Any]]
CdpUrlResolver = Callable[[Any, Optional[Dict[str, Any]]], Awaitable[str] | str]
logger = logging.getLogger(__name__)


BROWSER_USE_CAPTURE_EXTRACTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "key": {
            "type": "string",
            "description": (
                "A concise semantic ASCII snake_case key for the extracted business data, "
                "for example reimbursement_info or order_data."
            ),
        },
        "data": {
            "type": "object",
            "description": "The extracted business data. Use the requested field names as object keys.",
        },
    },
    "required": ["key", "data"],
}


class BrowserUseDoneOutput(BaseModel):
    """The application-owned payload inside browser-use's native structured done action."""

    kind: Literal["capture", "action"] = Field(
        description="capture when the user needs page data for later reuse; otherwise action."
    )
    key: str = Field(default="", description="Semantic ASCII snake_case key. Required only when kind is capture.")
    value: Any = Field(
        default_factory=dict,
        description="JSON-serializable business data for a capture. Leave empty when kind is action.",
    )
    message: str = Field(default="", description="Completion message for an action. Leave empty when kind is capture.")


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
        output_key: Optional[str] = None,
    ) -> RecordingAgentResult:
        before = await _page_state(page)
        try:
            cdp_url = await _maybe_await(self.cdp_url_resolver(page, debug_context))
            if not str(cdp_url or "").strip():
                raise RuntimeError("browser-use requires a CDP URL to reuse the current recording browser.")
            history = await self.browser_use_runner(
                instruction=instruction,
                cdp_url=str(cdp_url),
                cdp_target_id=_debug_cdp_target_id(debug_context),
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
            try:
                structured_done = _history_structured_done_output(history)
            except ValueError as exc:
                raise BrowserUseTaskFailure(
                    str(exc),
                    actions=actions,
                    action_results=action_results,
                ) from exc
            capture_output_key: Optional[str] = None
            if structured_done is None:
                output = {
                    "extracted_content": extracted_content,
                    "action_count": len(actions),
                }
            elif structured_done.kind == "capture":
                output = structured_done.value
                if output_key is not None:
                    capture_output_key = str(output_key).strip()
                else:
                    capture_output_key = _normalize_capture_key(structured_done.key)
                    if capture_output_key:
                        capture_output_key = _deduplicate_capture_key(capture_output_key, runtime_results or {})
                if not capture_output_key:
                    raise BrowserUseTaskFailure(
                        "browser-use structured done output returned an invalid semantic key.",
                        actions=actions,
                        action_results=action_results,
                    )
            else:
                output = {"message": structured_done.message}
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
                        "cdp_target_id": _debug_cdp_target_id(debug_context),
                        "scienceclaw_page": before.model_dump(mode="json"),
                        "focus_diagnostics": _history_focus_diagnostics(history),
                        "actions": actions,
                        "action_results": action_results,
                        "extracted_content": extracted_content,
                        "done_output": structured_done.model_dump(mode="json") if structured_done else None,
                        "max_steps": self.max_steps,
                    },
                },
                region_context=dict(region_context or {}),
                output_key=capture_output_key,
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
                output_key=capture_output_key,
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
    output_key: Optional[str],
) -> Any:
    runtime_context = kwargs.get("_runtime_context") if isinstance(kwargs, dict) else {}
    browser_use_context = runtime_context.get("browser_use") if isinstance(runtime_context, dict) else {}
    cdp_url = browser_use_context.get("cdp_url") if isinstance(browser_use_context, dict) else None
    cdp_target_id = browser_use_context.get("cdp_target_id") if isinstance(browser_use_context, dict) else None
    model_config = _runtime_model_config(kwargs)
    operator = BrowserUseRecordingOperator(
        model_config=model_config,
        cdp_url_resolver=lambda _page, _debug_context: cdp_url or "",
    )
    debug_context = {"cdp_target_id": cdp_target_id} if cdp_target_id else None
    outcome = await operator.run(
        page=page,
        instruction=instruction,
        runtime_results=results,
        debug_context=debug_context,
        output_key=output_key,
    )
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
    cdp_target_id: str = "",
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
    session = BrowserSession(cdp_url=cdp_url, keep_alive=True)
    try:
        _disable_browser_use_screenshots_if_configured(session)
        focus_diagnostics = await _focus_browser_use_target(
            session,
            target_id=cdp_target_id,
            expected_url=current_url,
        )
        task = _build_browser_use_task(instruction, runtime_results, region_context)
        agent = Agent(
            task=task,
            llm=llm,
            browser_session=session,
            available_file_paths=_available_file_paths(),
            use_vision=os.environ.get("BROWSER_USE_USE_VISION", "false").strip().lower() == "true",
            output_model_schema=BrowserUseDoneOutput,
            extraction_schema=BROWSER_USE_CAPTURE_EXTRACTION_SCHEMA,
        )
        _ensure_browser_use_agent_timing(agent)
        history = await agent.run(max_steps=max_steps)
        try:
            setattr(history, "_scienceclaw_focus_diagnostics", focus_diagnostics)
        except Exception:
            pass
        return history
    finally:
        try:
            await session.stop()
        except Exception as exc:
            logger.warning("Failed to detach browser-use session without closing host browser: %s", exc)


async def _focus_browser_use_target(session: Any, *, target_id: str = "", expected_url: str = "") -> Dict[str, Any]:
    requested_target_id = str(target_id or "").strip()
    diagnostics: Dict[str, Any] = {
        "requested_target_id": requested_target_id,
        "expected_url": str(expected_url or ""),
        "focused_target_id": "",
        "focused_page": {},
        "tabs": [],
    }
    await session.start()
    if requested_target_id:
        try:
            await session.get_or_create_cdp_session(target_id=requested_target_id, focus=True)
        except Exception as exc:
            diagnostics["error"] = str(exc)
            diagnostics["tabs"] = await _browser_use_tabs_snapshot(session)
            logger.warning("Failed to focus browser-use target %s: %s", requested_target_id, exc)
            raise RuntimeError(
                f"browser-use could not focus ScienceClaw CDP target {requested_target_id}; "
                f"expected_url={expected_url}; tabs={diagnostics['tabs']}"
            ) from exc
    diagnostics["focused_target_id"] = str(getattr(session, "agent_focus_target_id", "") or "")
    diagnostics["focused_page"] = await _browser_use_focused_page_snapshot(session)
    diagnostics["tabs"] = await _browser_use_tabs_snapshot(session)
    logger.info(
        "browser-use focus diagnostics: requested_target_id=%s focused_target_id=%s expected_url=%s focused_url=%s",
        diagnostics["requested_target_id"],
        diagnostics["focused_target_id"],
        diagnostics["expected_url"],
        diagnostics["focused_page"].get("url", ""),
    )
    return diagnostics


async def _browser_use_focused_page_snapshot(session: Any) -> Dict[str, str]:
    return {
        "url": await _call_str(session, "get_current_page_url"),
        "title": await _call_str(session, "get_current_page_title"),
    }


async def _browser_use_tabs_snapshot(session: Any) -> list[Dict[str, str]]:
    get_tabs = getattr(session, "get_tabs", None)
    if not callable(get_tabs):
        return []
    try:
        tabs = await get_tabs()
    except Exception as exc:
        return [{"error": str(exc)}]
    return [_browser_use_tab_snapshot(tab) for tab in tabs or []]


def _browser_use_tab_snapshot(tab: Any) -> Dict[str, str]:
    if isinstance(tab, dict):
        return {
            "target_id": str(tab.get("target_id") or tab.get("targetId") or ""),
            "url": str(tab.get("url") or ""),
            "title": str(tab.get("title") or ""),
        }
    return {
        "target_id": str(getattr(tab, "target_id", "") or getattr(tab, "targetId", "") or ""),
        "url": str(getattr(tab, "url", "") or ""),
        "title": str(getattr(tab, "title", "") or ""),
    }


async def _call_str(obj: Any, method_name: str) -> str:
    method = getattr(obj, method_name, None)
    if not callable(method):
        return ""
    try:
        return str(await _maybe_await(method()) or "")
    except Exception as exc:
        return f"<error: {exc}>"


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
        "Complete this ScienceClaw instruction in the currently focused browser tab.",
        "Stop when the requested browser-visible goal is satisfied; do not continue into unrelated workflow steps.",
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


def _debug_cdp_target_id(debug_context: Optional[Dict[str, Any]]) -> str:
    if not isinstance(debug_context, dict):
        return ""
    return str(debug_context.get("cdp_target_id") or "").strip()


def _history_focus_diagnostics(history: Any) -> Dict[str, Any]:
    value = getattr(history, "_scienceclaw_focus_diagnostics", None)
    normalized = _json_safe_browser_use_value(value)
    return normalized if isinstance(normalized, dict) else {}


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


def _history_structured_done_output(history: Any) -> Optional[BrowserUseDoneOutput]:
    """Read browser-use's final native structured done output, if the runner provides it."""
    try:
        value = getattr(history, "structured_output", None)
    except Exception as exc:
        raise ValueError(f"browser-use structured done output is invalid: {exc}") from exc
    if callable(value):
        value = value()
    if value is None:
        return None
    if isinstance(value, BrowserUseDoneOutput):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return BrowserUseDoneOutput.model_validate(value)
    raise ValueError("browser-use structured done output has an unsupported type.")


def _normalize_capture_key(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if not text:
        return None
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return None
    if text[0].isdigit():
        text = f"result_{text}"
    return text[:64]


def _deduplicate_capture_key(key: str, runtime_results: Dict[str, Any]) -> str:
    if key not in runtime_results:
        return key
    suffix = 2
    while f"{key}_{suffix}" in runtime_results:
        suffix += 1
    return f"{key}_{suffix}"


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
