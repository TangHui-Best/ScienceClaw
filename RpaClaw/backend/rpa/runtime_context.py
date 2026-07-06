from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict, Optional

from backend.models import get_model_config, resolve_default_model_config


def _coerce_meta(meta: Any) -> Dict[str, Any]:
    if isinstance(meta, dict):
        return meta
    if isinstance(meta, str) and meta.strip():
        try:
            parsed = json.loads(meta)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _recording_traces_require_runtime_ai(meta: Dict[str, Any]) -> bool:
    recording = meta.get("recording")
    if not isinstance(recording, dict):
        return False
    raw_traces = recording.get("traces")
    if not isinstance(raw_traces, list):
        return False

    from backend.rpa.trace_models import RPAAcceptedTrace

    traces = []
    for raw_trace in raw_traces:
        if not isinstance(raw_trace, dict):
            continue
        try:
            traces.append(RPAAcceptedTrace.model_validate(raw_trace))
        except Exception:
            continue
    return runtime_requirements_from_traces(traces).get("runtime_ai") is True


def _user_matches(value: Any, user_id: str | None) -> bool:
    return str(value or "") == str(user_id or "")


def _is_usable_model_config(model_config: Any) -> bool:
    return isinstance(model_config, dict) and bool(model_config.get("model_name"))


def _can_use_model_config(model_config: Dict[str, Any], user_id: str | None) -> bool:
    if not _is_usable_model_config(model_config):
        return False
    if bool(model_config.get("is_system", False)):
        return True
    return bool(user_id) and _user_matches(model_config.get("user_id"), user_id)


def should_inject_runtime_ai_context(skill_meta: Any) -> bool:
    """Return whether a skill explicitly requires runtime AI replay context."""
    meta = _coerce_meta(skill_meta)
    if meta.get("kind") != "rpa-recording":
        return False
    requirements = meta.get("runtime_requirements")
    if isinstance(requirements, dict):
        return requirements.get("runtime_ai") is True
    return _recording_traces_require_runtime_ai(meta)


def runtime_requirements_from_traces(traces: Any) -> Dict[str, bool]:
    """Build runtime requirement metadata from accepted RPA traces."""
    trace_list = list(traces or [])
    from backend.rpa.trace_skill_compiler import _trace_uses_browser_use, traces_require_runtime_ai_replay

    return {
        "runtime_ai": traces_require_runtime_ai_replay(trace_list),
        "browser_use": any(_trace_uses_browser_use(trace) for trace in trace_list),
    }


async def resolve_runtime_ai_model_config(
    user_id: str | None,
    *,
    session_model_config: Optional[Dict[str, Any]] = None,
    explicit_model_config_id: str | None = None,
) -> tuple[Optional[Dict[str, Any]], str]:
    """Resolve the model config used by runtime AI instructions."""
    if session_model_config and _can_use_model_config(session_model_config, user_id):
        return deepcopy(session_model_config), "session_model_config"

    if explicit_model_config_id:
        model_config = await get_model_config(explicit_model_config_id)
        if model_config and (
            bool(model_config.is_system)
            or (bool(user_id) and _user_matches(model_config.user_id, user_id))
        ):
            return model_config.model_dump(), "explicit_model_config"
        return None, "explicit_model_config_forbidden"

    try:
        default_config = await resolve_default_model_config(user_id)
    except RuntimeError:
        default_config = None
    if default_config:
        source = (
            "system_default_model"
            if bool(default_config.get("is_system", False))
            else "user_default_model"
        )
        return default_config, source

    return None, "env_fallback"


async def inject_runtime_context_kwargs(
    user_id: str | None,
    kwargs: Dict[str, Any] | None,
    *,
    session_model_config: Optional[Dict[str, Any]] = None,
    explicit_model_config_id: str | None = None,
    browser_use_cdp_url: str | None = None,
) -> Dict[str, Any]:
    """Add runtime-only execution context while preserving normal skill kwargs."""
    merged: Dict[str, Any] = dict(kwargs or {})
    model_config, source = await resolve_runtime_ai_model_config(
        user_id,
        session_model_config=session_model_config,
        explicit_model_config_id=explicit_model_config_id,
    )
    runtime_context = dict(merged.get("_runtime_context") or {})
    runtime_context["runtime_ai"] = {
        "model_config": deepcopy(model_config) if model_config else None,
        "source": source,
    }
    if browser_use_cdp_url:
        browser_use_context = dict(runtime_context.get("browser_use") or {})
        browser_use_context["cdp_url"] = browser_use_cdp_url
        runtime_context["browser_use"] = browser_use_context
    merged["_runtime_context"] = runtime_context
    if model_config:
        merged["_model_config"] = deepcopy(model_config)
    return merged
