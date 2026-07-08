import json
import logging
import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, Any, Literal
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
import websockets
from websockets.exceptions import ConnectionClosed
import httpx
from fastapi.responses import Response as FastAPIResponse

from backend.rpa.manager import rpa_manager, RPASkillConfigDraft
from backend.rpa.executor import ScriptExecutor
from backend.rpa.skill_exporter import SkillExporter
from backend.rpa.assistant import RPAAssistant, RPAReActAgent, _active_agents
from backend.rpa.browser_use_recording_operator import BrowserUseRecordingOperator
from backend.rpa.recording_runtime_agent import RecordingRuntimeAgent, RecordingAgentResult
from backend.rpa.trace_models import RPAAcceptedTrace
from backend.rpa.trace_ordering import order_traces_by_recording_time
from backend.rpa.trace_timeline import build_trace_timeline_items
from backend.rpa.trace_skill_compiler import TraceSkillCompiler
from backend.rpa.mcp_step_projection import session_to_mcp_steps
from backend.rpa.cdp_connector import get_cdp_connector
from backend.rpa.screencast import SessionScreencastController
from backend.user.dependencies import (
    get_current_user,
    get_user_from_session_id,
    User,
)
from backend.config import settings
from backend.models import get_model_config, resolve_default_model_config
from backend.storage import get_repository
from backend.credential.vault import inject_credentials
from backend.rpa.runtime_context import inject_runtime_context_kwargs, runtime_requirements_from_traces
from backend.rpa.harness.config import harness_capture_enabled
from backend.rpa.region_context import (
    RPARegionElementBoundsRequest,
    RPARegionElementBoundsResponse,
    RPARegionAnalyzeRequest,
    RPARegionAnalyzeResponse,
    RPARegionContext,
    RPARegionEvidence,
    analyze_region_on_page,
    resolve_element_bounds_on_page,
)

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        logger.warning("Ignoring invalid float value for %s: %r", name, value)
        return default


RPA_TEST_TIMEOUT_S = _env_float("RPA_TEST_TIMEOUT_S", 180.0)
RPA_PAGE_TIMEOUT_MS = 60000

router = APIRouter(tags=["RPA"])
executor = ScriptExecutor()
exporter = SkillExporter()
assistant = RPAAssistant()
trace_compiler = TraceSkillCompiler()


class StartSessionRequest(BaseModel):
    sandbox_session_id: str


class StartHarnessCaptureRequest(BaseModel):
    capture_scope: Literal["full_sop", "selected_steps"]


class GenerateRequest(BaseModel):
    params: Dict[str, Any] = {}


class DeleteTimelineItemRequest(BaseModel):
    kind: str
    step_id: str | None = None
    trace_id: str | None = None


class SaveSkillRequest(BaseModel):
    skill_name: str
    description: str
    params: Dict[str, Any] = {}


class ChatRequest(BaseModel):
    message: str
    mode: str = "chat"
    model_config_id: str | None = None
    region_id: str | None = None


class ConfirmRequest(BaseModel):
    approved: bool


class NavigateRequest(BaseModel):
    url: str


class PromoteLocatorRequest(BaseModel):
    candidate_index: int


class SkillConfigDraftRequest(RPASkillConfigDraft):
    pass


def _generate_session_script(session, params: Dict[str, Any], *, test_mode: bool = False) -> str:
    traces_for_compile = _session_traces_for_compile(session)
    return trace_compiler.generate_script(
        traces_for_compile,
        params,
        is_local=(settings.storage_backend == "local"),
        test_mode=test_mode,
    )


def _session_model_config(session) -> dict | None:
    model_config = getattr(session, "llm_model_config", None)
    return model_config if isinstance(model_config, dict) and model_config else None


def _build_recording_operator(model_config: dict | None):
    if getattr(settings, "rpa_recording_operator", "native") == "browser_use":
        return BrowserUseRecordingOperator(
            model_config=model_config,
            max_steps=getattr(settings, "browser_use_max_steps", 12),
        )
    return RecordingRuntimeAgent(model_config=model_config)


def _model_dump_json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _build_session_timeline(session) -> list[dict[str, Any]]:
    return [
        item.model_dump(mode="json")
        for item in build_trace_timeline_items(
            traces=list(getattr(session, "traces", None) or []),
            trace_diagnostics=list(getattr(session, "trace_diagnostics", None) or []),
        )
    ]


def _build_session_response(session) -> dict[str, Any]:
    payload = session.model_dump(mode="json")
    for key in ("steps", "recorded_actions", "recording_diagnostics", "legacy_steps"):
        payload.pop(key, None)
    payload["trace_count"] = len(getattr(session, "traces", None) or [])
    payload["diagnostic_count"] = len(getattr(session, "trace_diagnostics", None) or [])
    return payload


def _order_traces_by_recording_time(traces: list[RPAAcceptedTrace]) -> list[RPAAcceptedTrace]:
    return order_traces_by_recording_time(traces)


def _session_traces_for_compile(session) -> list[RPAAcceptedTrace]:
    return _order_traces_by_recording_time(list(getattr(session, "traces", None) or []))


def _build_session_recording_meta(session) -> Dict[str, Any]:
    traces = _session_traces_for_compile(session)
    trace_diagnostics = [_model_dump_json(item) for item in getattr(session, "trace_diagnostics", None) or []]
    runtime_results = _model_dump_json(getattr(session, "runtime_results", {})) or {}

    return {
        "recording_source": "trace" if traces else "none",
        "traces": [trace.model_dump(mode="json") for trace in traces],
        "runtime_results": runtime_results,
        "runtime_requirements": runtime_requirements_from_traces(traces),
        "trace_diagnostics": trace_diagnostics,
    }


def _session_requires_runtime_ai(session) -> bool:
    return runtime_requirements_from_traces(_session_traces_for_compile(session)).get("runtime_ai") is True


def _session_requires_browser_use(session) -> bool:
    return runtime_requirements_from_traces(_session_traces_for_compile(session)).get("browser_use") is True


def _ensure_has_compile_traces(session) -> None:
    if not _session_traces_for_compile(session):
        raise HTTPException(
            status_code=400,
            detail="No trace facts available for script generation. Record or resolve at least one trace first.",
        )


def _failed_trace_retry_context(session, result: Dict[str, Any]) -> Dict[str, Any]:
    failed_trace_index = result.get("failed_trace_index")

    failed_trace_id = None
    failed_step_candidates = []
    traces = _session_traces_for_compile(session)
    if failed_trace_index is None:
        return {
            "failed_trace_id": failed_trace_id,
            "failed_trace_index": None,
            "failed_step_candidates": failed_step_candidates,
        }

    try:
        failed_trace_index = int(failed_trace_index)
    except (TypeError, ValueError):
        failed_trace_index = None

    if failed_trace_index is not None and 0 <= failed_trace_index < len(traces):
        failed_trace = traces[failed_trace_index]
        failed_trace_id = failed_trace.trace_id
        candidates = getattr(failed_trace, "locator_candidates", None) or []
        filtered = []
        for orig_idx, candidate in enumerate(candidates):
            entry = _model_dump_json(candidate)
            if not isinstance(entry, dict):
                continue
            if not entry.get("selected"):
                entry = dict(entry)
                entry["original_index"] = orig_idx
                filtered.append(entry)
        def _candidate_score(candidate: dict[str, Any]) -> float:
            try:
                value = float(candidate.get("score", 999))
            except (TypeError, ValueError):
                return 999.0
            return value

        failed_step_candidates = sorted(
            filtered,
            key=lambda candidate: (
                0 if candidate.get("strict_match_count") == 1 else 1,
                _candidate_score(candidate),
            ),
        )

    return {
        "failed_trace_id": failed_trace_id,
        "failed_trace_index": failed_trace_index,
        "failed_step_candidates": failed_step_candidates,
    }


def _ensure_no_unresolved_manual_diagnostics(session) -> None:
    diagnostics = getattr(session, "trace_diagnostics", None) or []
    if diagnostics:
        raise HTTPException(
            status_code=400,
            detail=f"{len(diagnostics)} unresolved diagnostics must be resolved before generation",
        )


def _ensure_session_owner(session, current_user: User) -> None:
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")


def _ensure_harness_capture_enabled() -> None:
    if not harness_capture_enabled(settings):
        raise HTTPException(status_code=404, detail="RPA Harness capture is disabled")


def _build_harness_capture_payload(session_id: str) -> dict[str, Any] | None:
    state = rpa_manager.get_harness_capture_session(session_id)
    return state.model_dump(mode="json") if state is not None else None


async def _apply_recording_agent_result(session_id: str, result: RecordingAgentResult) -> None:
    for diagnostic in result.diagnostics:
        await rpa_manager.append_trace_diagnostic(session_id, diagnostic)
    if result.trace:
        await rpa_manager.finalize_trace_side_effects(session_id, result.trace)
        await rpa_manager.append_trace(session_id, result.trace)
    if result.output_key:
        rpa_manager.write_runtime_result(session_id, result.output_key, result.output)


def _resolve_chat_region_context(
    session_id: str,
    region_id: str | None,
    current_url: str | None,
) -> dict[str, Any] | None:
    if not region_id:
        return None
    context = rpa_manager.resolve_region_context(
        session_id,
        region_id,
        current_url=current_url,
    )
    if context is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Selected region is unavailable or no longer matches the current page. "
                "Please reselect the region before sending this command."
            ),
        )
    return context.model_dump(mode="json")


def _preview_chat_region_context(region_context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not region_context:
        return None
    return RPARegionContext.model_validate(region_context).preview()


async def _get_ws_user(websocket: WebSocket) -> User | None:
    """Resolve the current user for a WebSocket request.

    Browser WebSocket APIs cannot attach custom Authorization headers in the
    same way axios does, so we accept a bearer token via query param as a
    fallback and keep the explicit no-auth local shortcut.
    """
    if getattr(settings, "auth_provider", "local") == "none":
        return await get_current_user(websocket)  # type: ignore[arg-type]

    session_id = (
        websocket.query_params.get("token")
        or websocket.cookies.get(settings.session_cookie)
    )
    return await get_user_from_session_id(session_id)


async def _get_http_user(request: Request) -> User | None:
    """Resolve the current user for normal HTTP requests.

    This mirrors websocket auth so iframe-based noVNC pages can use either
    the session cookie or a `token` query param.
    """
    if getattr(settings, "auth_provider", "local") == "none":
        return await get_current_user(request)

    session_id = (
        request.query_params.get("token")
        or request.cookies.get(settings.session_cookie)
    )
    return await get_user_from_session_id(session_id)


def _get_sandbox_vnc_ws_url() -> str:
    """Return the configured upstream sandbox VNC WebSocket URL."""
    return settings.sandbox_vnc_ws_url.rstrip("/")


def _get_sandbox_vnc_http_url(path: str) -> str:
    sandbox_base = settings.sandbox_base_url.rstrip("/")
    return f"{sandbox_base}/vnc/{path.lstrip('/')}"


def _get_sandbox_novnc_ws_url() -> str:
    sandbox_base = settings.sandbox_base_url.rstrip("/")
    parsed = urlparse(sandbox_base)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    return parsed._replace(scheme=ws_scheme, path="/websockify", query="", fragment="").geturl()


def _get_sandbox_proxy_headers() -> list[tuple[str, str]] | None:
    """Parse optional proxy request headers from env.

    Expected format:
      SANDBOX_PROXY_HEADERS={"Authorization":"Bearer xxx","X-API-Key":"yyy"}
    """
    raw = (getattr(settings, "sandbox_proxy_headers", "") or "").strip()
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Invalid SANDBOX_PROXY_HEADERS JSON; ignoring proxy headers")
        return None

    if not isinstance(parsed, dict):
        logger.warning("SANDBOX_PROXY_HEADERS must be a JSON object; ignoring proxy headers")
        return None

    headers: list[tuple[str, str]] = []
    for key, value in parsed.items():
        if value is None:
            continue
        headers.append((str(key), str(value)))
    return headers or None


def _get_sandbox_proxy_headers_dict() -> dict[str, str]:
    headers = _get_sandbox_proxy_headers() or []
    return {key: value for key, value in headers}


def _filter_proxy_query(params: dict[str, str] | Any) -> dict[str, str]:
    return {str(k): str(v) for k, v in dict(params).items() if k != "token"}


def _rewrite_vnc_html(html: str, session_id: str) -> str:
    proxy_prefix = f"/api/v1/rpa/vnc/page/{session_id}/"
    rewritten = html.replace('href="/vnc/', f'href="{proxy_prefix}')
    rewritten = rewritten.replace('src="/vnc/', f'src="{proxy_prefix}')
    rewritten = rewritten.replace('action="/vnc/', f'action="{proxy_prefix}')
    rewritten = rewritten.replace('url: "/vnc/', f'url: "{proxy_prefix}')
    rewritten = rewritten.replace("url: '/vnc/", f"url: '{proxy_prefix}")
    rewritten = rewritten.replace('path: "websockify"', f'path: "{proxy_prefix}websockify"')
    rewritten = rewritten.replace("path: 'websockify'", f"path: '{proxy_prefix}websockify'")
    rewritten = rewritten.replace('path = "websockify"', f'path = "{proxy_prefix}websockify"')
    rewritten = rewritten.replace("path = 'websockify'", f"path = '{proxy_prefix}websockify'")
    if "<head>" in rewritten:
        rewritten = rewritten.replace("<head>", f'<head><base href="{proxy_prefix}">', 1)
    return rewritten


async def _resolve_user_model_config(user_id: str, model_config_id: str | None = None) -> dict | None:
    """Resolve the user's model config for the RPA assistant.

    Priority: user's own models → system models → env defaults (None).
    """
    if model_config_id:
        model_config = await get_model_config(model_config_id)
        if not model_config:
            raise HTTPException(status_code=404, detail="Model not found")
        if not model_config.is_system and model_config.user_id != user_id:
            raise HTTPException(status_code=403, detail="Cannot use this model")
        return model_config.model_dump()

    try:
        model_config = await resolve_default_model_config(user_id)
    except RuntimeError:
        model_config = None
    if model_config:
        return model_config
    # Fall back to env defaults
    if (getattr(settings, "model_ds_api_key", None) or "").strip():
        return None  # get_llm_model(config=None) uses env defaults
    return None


async def _resolve_browser_use_cdp_url(session, user_id: str) -> str | None:
    if not _session_requires_browser_use(session):
        return None
    connector = get_cdp_connector()
    fetcher = getattr(connector, "_fetch_cdp_url", None)
    if not callable(fetcher):
        return None
    sandbox_session_id = getattr(session, "sandbox_session_id", None)
    return await fetcher(session_id=sandbox_session_id or None, user_id=user_id)


@router.post("/session/start")
async def start_rpa_session(
    request: StartSessionRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        session = await rpa_manager.create_session(
            user_id=str(current_user.id),
            sandbox_session_id=request.sandbox_session_id,
        )
        return {
            "status": "success",
            "session": _build_session_response(session),
            "timeline": _build_session_timeline(session),
        }
    except Exception as e:
        logger.error(f"Failed to start RPA session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/cleanup")
async def cleanup_rpa_sessions(
    max_idle_seconds: int = 7200,
    current_user: User = Depends(get_current_user),
):
    if getattr(current_user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    removed = await rpa_manager.cleanup_expired_sessions(max_idle_seconds=max_idle_seconds)
    return {"status": "success", "removed": removed}


@router.get("/session/{session_id}")
async def get_rpa_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    rpa_manager.touch_session(session_id)
    return {
        "status": "success",
        "session": _build_session_response(session),
        "timeline": _build_session_timeline(session),
    }


@router.get("/session/{session_id}/timeline")
async def get_session_timeline(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    rpa_manager.touch_session(session_id)
    return {"status": "success", "timeline": _build_session_timeline(session)}


@router.get("/session/{session_id}/skill-config-draft")
async def get_skill_config_draft(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_session_owner(session, current_user)
    rpa_manager.touch_session(session_id)
    return {
        "status": "success",
        "draft": session.skill_config_draft.model_dump(mode="json")
        if session.skill_config_draft
        else None,
    }


@router.put("/session/{session_id}/skill-config-draft")
async def update_skill_config_draft(
    session_id: str,
    request: SkillConfigDraftRequest,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_session_owner(session, current_user)
    draft = rpa_manager.update_skill_config_draft(session_id, request)
    return {
        "status": "success",
        "draft": draft.model_dump(mode="json"),
    }


@router.get("/session/{session_id}/tabs")
async def list_rpa_tabs(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    rpa_manager.touch_session(session_id)
    return {
        "status": "success",
        "tabs": rpa_manager.list_tabs(session_id),
        "active_tab_id": session.active_tab_id,
    }


@router.post("/session/{session_id}/region/analyze", response_model=RPARegionAnalyzeResponse)
async def analyze_rpa_region(
    session_id: str,
    request: RPARegionAnalyzeRequest,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_session_owner(session, current_user)

    page = rpa_manager.get_page_for_tab(session_id, request.tab_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Tab page not found")

    raw_evidence = await analyze_region_on_page(page, request)
    evidence = RPARegionEvidence(**raw_evidence)
    context = RPARegionContext(
        session_id=session_id,
        tab_id=request.tab_id,
        page_url=evidence.url,
        page_title=evidence.title,
        evidence=evidence,
    )
    stored_context = rpa_manager.store_region_context(session_id, context)
    preview = stored_context.preview()
    rpa_manager.touch_session(session_id)
    return RPARegionAnalyzeResponse(
        region_id=stored_context.region_id,
        summary=str(preview.get("summary", "")),
        inferred_kind=evidence.inferred_kind,
        evidence=evidence,
    )


@router.post("/session/{session_id}/region/element-bounds", response_model=RPARegionElementBoundsResponse)
async def resolve_rpa_region_element_bounds(
    session_id: str,
    request: RPARegionElementBoundsRequest,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_session_owner(session, current_user)

    page = rpa_manager.get_page_for_tab(session_id, request.tab_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Tab page not found")

    response = await resolve_element_bounds_on_page(page, request)
    rpa_manager.touch_session(session_id)
    return response


@router.post("/session/{session_id}/tabs/{tab_id}/activate")
async def activate_rpa_tab(
    session_id: str,
    tab_id: str,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    rpa_manager.touch_session(session_id)
    try:
        result = await rpa_manager.activate_tab(session_id, tab_id, source="user")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "status": "success",
        "result": result,
        "tabs": rpa_manager.list_tabs(session_id),
        "active_tab_id": session.active_tab_id,
    }


@router.post("/session/{session_id}/navigate")
async def navigate_rpa_session(
    session_id: str,
    request: NavigateRequest,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    rpa_manager.touch_session(session_id)
    try:
        result = await rpa_manager.navigate_active_tab(session_id, request.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "success",
        "result": result,
        "tabs": rpa_manager.list_tabs(session_id),
        "active_tab_id": session.active_tab_id,
    }


@router.post("/session/{session_id}/stop")
async def stop_rpa_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    rpa_manager.touch_session(session_id)
    await rpa_manager.stop_session(session_id)
    return {"status": "success", "session": _build_session_response(session)}


@router.get("/harness/config")
async def get_rpa_harness_config(
    current_user: User = Depends(get_current_user),
):
    return {
        "status": "success",
        "capture_enabled": harness_capture_enabled(settings),
    }


@router.post("/session/{session_id}/harness-capture/start")
async def start_harness_capture(
    session_id: str,
    request: StartHarnessCaptureRequest,
    current_user: User = Depends(get_current_user),
):
    _ensure_harness_capture_enabled()
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_session_owner(session, current_user)
    state = rpa_manager.start_harness_capture(
        session_id,
        capture_scope=request.capture_scope,
        enabled=True,
    )
    if state is not None:
        await rpa_manager.set_harness_capture_runtime_active(
            session_id,
            active=state.capture_scope == "full_sop",
        )
    return {"status": "success", "capture": state.model_dump(mode="json") if state else None}


@router.post("/session/{session_id}/harness-capture/steps/{step_index}/select")
async def select_harness_capture_step(
    session_id: str,
    step_index: int,
    current_user: User = Depends(get_current_user),
):
    _ensure_harness_capture_enabled()
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_session_owner(session, current_user)
    state = rpa_manager.mark_harness_step_selected(session_id, step_index=step_index)
    if state is None:
        raise HTTPException(status_code=400, detail="Harness capture has not started")
    return {"status": "success", "capture": state.model_dump(mode="json")}


@router.post("/session/{session_id}/harness-capture/next-natural-language-step/select")
async def select_next_natural_language_harness_capture_step(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    _ensure_harness_capture_enabled()
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_session_owner(session, current_user)
    state = rpa_manager.mark_harness_next_natural_language_step_selected(session_id)
    if state is None:
        raise HTTPException(status_code=400, detail="Harness capture has not started")
    return {"status": "success", "capture": state.model_dump(mode="json")}


@router.delete("/session/{session_id}/timeline-item")
async def delete_timeline_item(
    session_id: str,
    request: DeleteTimelineItemRequest,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    rpa_manager.touch_session(session_id)

    if request.kind == "trace":
        success = await rpa_manager.delete_trace(session_id, request.trace_id or "")
    else:
        raise HTTPException(status_code=400, detail="Invalid timeline item kind")

    if not success:
        raise HTTPException(status_code=400, detail="Invalid timeline item")
    return {"status": "success"}


@router.delete("/session/{session_id}/trace/{trace_id}")
async def delete_trace_item(
    session_id: str,
    trace_id: str,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    rpa_manager.touch_session(session_id)

    success = await rpa_manager.delete_trace(session_id, trace_id)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid trace")
    return {"status": "success"}


@router.delete("/session/{session_id}/diagnostic/{diagnostic_id}")
async def delete_diagnostic_item(
    session_id: str,
    diagnostic_id: str,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    rpa_manager.touch_session(session_id)

    success = await rpa_manager.delete_trace_diagnostic(session_id, diagnostic_id)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid diagnostic")
    return {"status": "success"}


@router.post("/session/{session_id}/trace/{trace_id}/locator")
async def promote_trace_locator(
    session_id: str,
    trace_id: str,
    request: PromoteLocatorRequest,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    rpa_manager.touch_session(session_id)

    try:
        trace = await rpa_manager.select_trace_locator_candidate(
            session_id,
            trace_id,
            request.candidate_index,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "success", "trace": trace}


@router.post("/session/{session_id}/diagnostic/{diagnostic_id}/resolve-locator")
async def resolve_diagnostic_locator(
    session_id: str,
    diagnostic_id: str,
    request: PromoteLocatorRequest,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    rpa_manager.touch_session(session_id)

    try:
        trace = await rpa_manager.resolve_trace_diagnostic_locator_candidate(
            session_id,
            diagnostic_id,
            request.candidate_index,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "success", "trace": trace, "timeline": _build_session_timeline(session)}


@router.post("/session/{session_id}/generate")
async def generate_script(
    session_id: str,
    request: GenerateRequest = GenerateRequest(),
    current_user: User = Depends(get_current_user),
):
    await rpa_manager.wait_for_pending_events(session_id)
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_session_owner(session, current_user)
    rpa_manager.touch_session(session_id)

    _ensure_no_unresolved_manual_diagnostics(session)
    _ensure_has_compile_traces(session)
    script = _generate_session_script(session, request.params)
    return {"status": "success", "script": script}


@router.post("/session/{session_id}/test")
async def test_script(
    session_id: str,
    request: GenerateRequest = GenerateRequest(),
    current_user: User = Depends(get_current_user),
):
    await rpa_manager.wait_for_pending_events(session_id)
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_session_owner(session, current_user)
    rpa_manager.touch_session(session_id)

    _ensure_no_unresolved_manual_diagnostics(session)
    _ensure_has_compile_traces(session)
    script = _generate_session_script(session, request.params, test_mode=True)

    logs = []
    browser = await get_cdp_connector().get_browser(
        session_id=session.sandbox_session_id,
        user_id=str(current_user.id),
    )

    downloads_dir = str(Path(settings.workspace_dir) / "rpa_downloads" / session_id)
    connector = get_cdp_connector()
    pw_loop_runner = getattr(connector, "run_in_pw_loop", None)

    # 本地模式：通过 pw_loop_runner 确保 Playwright 操作在正确的事件循环里执行
    if settings.storage_backend == "local":
        test_kwargs: Dict[str, Any] = {"_downloads_dir": downloads_dir}
        model_config = _session_model_config(session)
        browser_use_cdp_url = await _resolve_browser_use_cdp_url(session, str(current_user.id))
        if request.params:
            test_kwargs.update(await inject_credentials(str(current_user.id), request.params, {}))
        if _session_requires_runtime_ai(session):
            test_kwargs = await inject_runtime_context_kwargs(
                str(current_user.id),
                test_kwargs,
                session_model_config=model_config,
                browser_use_cdp_url=browser_use_cdp_url,
            )
        result = await executor.execute(
            browser,
            script,
            on_log=lambda msg: logs.append(msg),
            timeout=RPA_TEST_TIMEOUT_S,
            session_id=session_id,
            page_registry=rpa_manager._pages,
            session_manager=rpa_manager,
            kwargs=test_kwargs,
            downloads_dir=downloads_dir,
            pw_loop_runner=pw_loop_runner,
        )
    else:
        # Docker 模式：使用原有逻辑
        docker_kwargs: Dict[str, Any] = {}
        model_config = _session_model_config(session)
        browser_use_cdp_url = await _resolve_browser_use_cdp_url(session, str(current_user.id))
        if request.params:
            docker_kwargs = await inject_credentials(
                str(current_user.id), request.params, {}
            )
        if _session_requires_runtime_ai(session):
            docker_kwargs = await inject_runtime_context_kwargs(
                str(current_user.id),
                docker_kwargs,
                session_model_config=model_config,
                browser_use_cdp_url=browser_use_cdp_url,
            )
        result = await executor.execute(
            browser,
            script,
            on_log=lambda msg: logs.append(msg),
            timeout=RPA_TEST_TIMEOUT_S,
            session_id=session_id,
            page_registry=rpa_manager._pages,
            session_manager=rpa_manager,
            kwargs=docker_kwargs,
            downloads_dir=downloads_dir,
        )

    result_payload = dict(result)
    result_payload.pop("failed_step_index", None)
    failed_retry_context = _failed_trace_retry_context(session, result_payload)

    return {
        "status": "success" if result.get("success") else "failed",
        "result": result_payload,
        "logs": logs,
        "script": script,
        **failed_retry_context,
    }


@router.post("/session/{session_id}/save")
async def save_skill(
    session_id: str,
    request: SaveSkillRequest,
    current_user: User = Depends(get_current_user),
):
    await rpa_manager.wait_for_pending_events(session_id)
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_session_owner(session, current_user)
    rpa_manager.touch_session(session_id)

    _ensure_no_unresolved_manual_diagnostics(session)
    _ensure_has_compile_traces(session)
    script = _generate_session_script(session, request.params)
    recording_meta = _build_session_recording_meta(session)
    steps = session_to_mcp_steps(session)

    skill_name = await exporter.export_skill(
        user_id=str(current_user.id),
        skill_name=request.skill_name,
        description=request.description,
        script=script,
        params=request.params,
        recording_meta=recording_meta,
        steps=steps,
    )

    session.status = "saved"
    return {"status": "success", "skill_name": skill_name}


@router.post("/session/{session_id}/chat")
async def chat_with_assistant(
    session_id: str,
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")

    # Resolve user's model config
    model_config = await _resolve_user_model_config(str(current_user.id), request.model_config_id)
    if model_config:
        session.llm_model_config = model_config

    # Get the page object for this session
    page = rpa_manager.get_page(session_id)
    if not page:
        raise HTTPException(status_code=400, detail="No active page for this session")

    region_context = _resolve_chat_region_context(
        session_id,
        request.region_id,
        getattr(page, "url", None),
    )
    region_preview = _preview_chat_region_context(region_context)
    steps = [step.model_dump() for step in session.steps]

    async def event_generator():
        try:
            rpa_manager.pause_recording(session_id)

            if request.mode == "legacy_react":
                # Reuse existing agent for this session to preserve history across turns
                agent = _active_agents.get(session_id)
                if agent is None:
                    agent = RPAReActAgent()
                    _active_agents[session_id] = agent
                try:
                    async for event in agent.run(
                        session_id=session_id,
                        page=page,
                        goal=request.message,
                        existing_steps=steps,
                        model_config=model_config,
                        page_provider=lambda: rpa_manager.get_page(session_id),
                    ):
                        evt_type = event.get("event", "message")
                        evt_data = event.get("data", {})
                        if evt_type == "agent_step_done" and evt_data.get("step"):
                            await rpa_manager.add_step(session_id, evt_data["step"])
                        if evt_type == "agent_aborted":
                            _active_agents.pop(session_id, None)
                        yield {
                            "event": evt_type,
                            "data": json.dumps(evt_data, ensure_ascii=False),
                        }
                except Exception:
                    _active_agents.pop(session_id, None)
                    raise
            elif request.mode == "legacy_chat":
                async for event in assistant.chat(
                    session_id=session_id,
                    page=page,
                    message=request.message,
                    steps=steps,
                    model_config=model_config,
                    page_provider=lambda: rpa_manager.get_page(session_id),
                ):
                    evt_type = event.get("event", "message")
                    evt_data = event.get("data", {})
                    if evt_type == "result" and evt_data.get("success") and evt_data.get("step"):
                        await rpa_manager.add_step(session_id, evt_data["step"])
                    yield {
                        "event": evt_type,
                        "data": json.dumps(evt_data, ensure_ascii=False),
                    }
            else:
                before_trace_ids = {trace.trace_id for trace in session.traces}
                if region_preview is not None:
                    yield {
                        "event": "region_context",
                        "data": json.dumps(region_preview, ensure_ascii=False),
                    }
                harness_step_index = len(session.traces) + 1
                harness_before_state = await rpa_manager.prepare_harness_step_capture(
                    session_id,
                    step_index=harness_step_index,
                    page=page,
                )
                yield {
                    "event": "agent_thought",
                    "data": json.dumps({"text": "Planning one trace-first recording command."}, ensure_ascii=False),
                }
                agent = _build_recording_operator(model_config)
                result = await agent.run(
                    page=page,
                    instruction=request.message,
                    runtime_results=session.runtime_results.values,
                    debug_context={
                        "session_id": session.sandbox_session_id or session_id,
                        "recording_session_id": session_id,
                        "user_id": str(current_user.id),
                        "cdp_target_id": rpa_manager.get_active_tab_cdp_target_id(session_id),
                    },
                    region_context=region_context,
                )
                await _apply_recording_agent_result(session_id, result)
                if request.region_id and result.success:
                    rpa_manager.clear_region_context(session_id, request.region_id)
                if harness_before_state is not None:
                    trace_events = [
                        result.trace.model_dump(mode="json")
                    ] if result.trace is not None else []
                    await rpa_manager.capture_harness_step_checkpoint(
                        session_id,
                        step_index=harness_step_index,
                        step_id=result.trace.trace_id if result.trace else f"ai-step-{harness_step_index}",
                        step_intent=request.message,
                        recording_mode="natural_language",
                        before_state=harness_before_state,
                        after_page=page if result.success else None,
                        trace_events=trace_events,
                        runtime_status="success" if result.success else "failed",
                        error=None if result.success else result.message,
                    )
                run_trace_count = len([
                    trace for trace in session.traces
                    if trace.trace_id not in before_trace_ids
                ])
                session_trace_count = len(session.traces)

                if result.trace:
                    code = result.trace.ai_execution.code if result.trace.ai_execution else ""
                    harness_capture_payload = _build_harness_capture_payload(session_id)
                    yield {
                        "event": "agent_action",
                        "data": json.dumps(
                            {"description": result.trace.description, "code": code},
                            ensure_ascii=False,
                        ),
                    }
                    yield {
                        "event": "trace_added",
                        "data": json.dumps(result.trace.model_dump(mode="json"), ensure_ascii=False),
                    }
                    yield {
                        "event": "agent_step_done",
                        "data": json.dumps(
                            {
                                "success": result.success,
                                "description": result.trace.description,
                                "output": result.output,
                                "trace": result.trace.model_dump(mode="json"),
                                "capture": harness_capture_payload,
                            },
                            ensure_ascii=False,
                        ),
                    }

                if result.success:
                    yield {
                        "event": "agent_done",
                        "data": json.dumps(
                            {
                                "message": result.message,
                                "trace_count": run_trace_count,
                                "session_trace_count": session_trace_count,
                                "capture": _build_harness_capture_payload(session_id),
                            },
                            ensure_ascii=False,
                        ),
                    }
                else:
                    yield {
                        "event": "agent_aborted",
                        "data": json.dumps(
                            {
                                "reason": result.message,
                                "diagnostics": [d.model_dump(mode="json") for d in result.diagnostics],
                                "region": region_preview,
                                "capture": _build_harness_capture_payload(session_id),
                            },
                            ensure_ascii=False,
                        ),
                    }
        except Exception as e:
            logger.error(f"Chat error: {e}")
            yield {"event": "error", "data": json.dumps({"message": str(e)}, ensure_ascii=False)}
            yield {"event": "done", "data": "{}"}
        finally:
            rpa_manager.resume_recording(session_id)

    return EventSourceResponse(event_generator())


@router.post("/session/{session_id}/agent/confirm")
async def agent_confirm(
    session_id: str,
    body: ConfirmRequest,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_session_owner(session, current_user)
    agent = _active_agents.get(session_id)
    if agent:
        agent.resolve_confirm(body.approved)
    return {"ok": True}


@router.post("/session/{session_id}/agent/abort")
async def agent_abort(
    session_id: str,
    current_user: User = Depends(get_current_user),
):
    session = await rpa_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _ensure_session_owner(session, current_user)
    agent = _active_agents.get(session_id)
    if agent:
        agent.abort()
    return {"ok": True}


@router.websocket("/screencast/{session_id}")
async def rpa_screencast(websocket: WebSocket, session_id: str):
    """Session-scoped CDP screencast with active-tab switching."""
    logger.info(
        "Screencast websocket connect session=%s client=%s query=%s",
        session_id,
        getattr(websocket.client, "host", None),
        dict(websocket.query_params),
    )
    user = await _get_ws_user(websocket)
    await websocket.accept()
    if not user:
        logger.warning("Screencast websocket unauthenticated session=%s", session_id)
        await websocket.close(code=1008, reason="Not authenticated")
        return

    session = await rpa_manager.get_session(session_id)
    if not session:
        logger.warning("Screencast websocket missing session=%s user=%s", session_id, user.username)
        await websocket.close(code=1008, reason="Session not found")
        return
    if session.user_id != str(user.id):
        logger.warning(
            "Screencast websocket forbidden session=%s request_user=%s owner=%s",
            session_id,
            user.id,
            session.user_id,
        )
        await websocket.close(code=1008, reason="Not authorized")
        return

    active_page = rpa_manager.get_page(session_id)
    if active_page:
        logger.info(
            "Screencast websocket ready session=%s user=%s page_id=%s url=%s",
            session_id,
            user.username,
            id(active_page),
            getattr(active_page, "url", ""),
        )
    else:
        logger.info(
            "Screencast websocket waiting for active page session=%s user=%s",
            session_id,
            user.username,
        )

    screencast = SessionScreencastController(
        page_provider=lambda: rpa_manager.get_page(session_id),
        tabs_provider=lambda: rpa_manager.list_tabs(session_id),
    )
    try:
        await screencast.start(websocket)
    except WebSocketDisconnect:
        logger.info("Screencast websocket disconnected session=%s", session_id)
    except Exception as e:
        logger.exception("Screencast error session=%s: %s", session_id, e)
        try:
            await websocket.close(code=1011, reason="Screencast failed")
        except Exception:
            pass
    finally:
        await screencast.stop()


@router.get("/vnc/page/{session_id}")
@router.get("/vnc/page/{session_id}/{path:path}")
async def proxy_vnc_page(session_id: str, request: Request, path: str = "index.html"):
    logger.info(
        "noVNC page proxy request session=%s path=%s query=%s",
        session_id,
        path or "index.html",
        dict(request.query_params),
    )
    user = await _get_http_user(request)
    if not user:
        logger.warning("noVNC page proxy unauthenticated session=%s", session_id)
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = await rpa_manager.get_session(session_id)
    if session and session.user_id != str(user.id):
        logger.warning(
            "noVNC page proxy forbidden session=%s request_user=%s owner=%s",
            session_id,
            user.id,
            session.user_id,
        )
        raise HTTPException(status_code=403, detail="Not authorized")

    upstream_url = _get_sandbox_vnc_http_url(path or "index.html")
    query = _filter_proxy_query(request.query_params)
    logger.info(
        "noVNC page proxy upstream session=%s upstream=%s filtered_query=%s",
        session_id,
        upstream_url,
        query,
    )

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        upstream = await client.get(
            upstream_url,
            params=query,
            headers=_get_sandbox_proxy_headers_dict(),
        )
    logger.info(
        "noVNC page proxy response session=%s status=%s content_type=%s",
        session_id,
        upstream.status_code,
        upstream.headers.get("content-type", ""),
    )

    excluded_headers = {"content-length", "transfer-encoding", "connection", "content-encoding"}
    headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in excluded_headers
    }

    content_type = upstream.headers.get("content-type", "")
    content = upstream.content
    if "text/html" in content_type:
        content = _rewrite_vnc_html(upstream.text, session_id).encode("utf-8")
        headers["content-type"] = "text/html; charset=utf-8"

    return FastAPIResponse(
        content=content,
        status_code=upstream.status_code,
        headers=headers,
        media_type=None,
    )


@router.websocket("/vnc/page/{session_id}/websockify")
async def proxy_vnc_page_websocket(websocket: WebSocket, session_id: str):
    logger.info(
        "noVNC websocket proxy request session=%s query=%s client=%s",
        session_id,
        dict(websocket.query_params),
        getattr(websocket.client, "host", None),
    )
    user = await _get_ws_user(websocket)

    requested_protocols = [
        p.strip()
        for p in (websocket.headers.get("sec-websocket-protocol") or "").split(",")
        if p.strip()
    ]
    accepted_subprotocol = requested_protocols[0] if requested_protocols else None

    await websocket.accept(subprotocol=accepted_subprotocol)
    if not user:
        logger.warning("noVNC websocket proxy unauthenticated session=%s", session_id)
        await websocket.close(code=1008, reason="Not authenticated")
        return

    session = await rpa_manager.get_session(session_id)
    if session and session.user_id != str(user.id):
        logger.warning(
            "noVNC websocket proxy forbidden session=%s request_user=%s owner=%s",
            session_id,
            user.id,
            session.user_id,
        )
        await websocket.close(code=1008, reason="Not authorized")
        return

    upstream_url = _get_sandbox_novnc_ws_url()
    query = _filter_proxy_query(websocket.query_params)
    if query:
        from urllib.parse import urlencode
        upstream_url = f"{upstream_url}?{urlencode(query)}"

    logger.info(
        "Opening proxied noVNC websocket for user=%s session=%s upstream=%s subprotocols=%s",
        user.username,
        session_id,
        upstream_url,
        requested_protocols,
    )

    try:
        async with websockets.connect(
            upstream_url,
            subprotocols=requested_protocols or None,
            additional_headers=_get_sandbox_proxy_headers(),
            ping_interval=20,
            ping_timeout=20,
            max_size=None,
        ) as upstream:
            logger.info(
                "Proxied noVNC websocket upstream connected session=%s upstream_subprotocol=%s",
                session_id,
                getattr(upstream, "subprotocol", None),
            )

            async def client_to_upstream():
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        logger.info("noVNC websocket client disconnected session=%s", session_id)
                        break
                    if message.get("bytes") is not None:
                        await upstream.send(message["bytes"])
                    elif message.get("text") is not None:
                        await upstream.send(message["text"])

            async def upstream_to_client():
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            relay_tasks = {
                asyncio.create_task(client_to_upstream()),
                asyncio.create_task(upstream_to_client()),
            }
            done, pending = await asyncio.wait(
                relay_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            await asyncio.gather(*done, return_exceptions=True)
    except ConnectionClosed as exc:
        logger.info("Proxied noVNC websocket closed session=%s detail=%s", session_id, exc)
    except WebSocketDisconnect:
        logger.info("Proxied noVNC websocket local disconnect session=%s", session_id)
        pass
    except Exception as exc:
        logger.exception("Proxied noVNC websocket error session=%s: %s", session_id, exc)
        try:
            await websocket.close(code=1011, reason="noVNC proxy failed")
        except Exception:
            pass


@router.websocket("/vnc/{session_id}")
async def vnc_proxy(websocket: WebSocket, session_id: str):
    """Proxy frontend VNC WebSocket traffic through the backend.

    This keeps the sandbox or local browser endpoint private to the backend,
    so the browser only talks to `/api/v1/rpa/vnc/...`.
    """
    user = await _get_ws_user(websocket)

    requested_protocols = [
        p.strip()
        for p in (websocket.headers.get("sec-websocket-protocol") or "").split(",")
        if p.strip()
    ]
    accepted_subprotocol = requested_protocols[0] if requested_protocols else None

    await websocket.accept(subprotocol=accepted_subprotocol)
    if not user:
        await websocket.close(code=1008, reason="Not authenticated")
        return

    upstream_url = _get_sandbox_vnc_ws_url()
    logger.info(
        "Opening VNC proxy for user=%s session=%s upstream=%s",
        user.username,
        session_id,
        upstream_url,
    )

    try:
        async with websockets.connect(
            upstream_url,
            subprotocols=requested_protocols or None,
            additional_headers=_get_sandbox_proxy_headers(),
            ping_interval=20,
            ping_timeout=20,
            max_size=None,
        ) as upstream:

            async def client_to_upstream():
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    if message.get("bytes") is not None:
                        await upstream.send(message["bytes"])
                    elif message.get("text") is not None:
                        await upstream.send(message["text"])

            async def upstream_to_client():
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            relay_tasks = {
                asyncio.create_task(client_to_upstream()),
                asyncio.create_task(upstream_to_client()),
            }
            done, pending = await asyncio.wait(
                relay_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            await asyncio.gather(*done, return_exceptions=True)
    except ConnectionClosed as exc:
        logger.info("VNC proxy closed: %s", exc)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("VNC proxy error: %s", exc)
        try:
            await websocket.close(code=1011, reason="VNC proxy failed")
        except Exception:
            pass
