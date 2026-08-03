"""vNext-only Browser-use model and exact-page adapters.

This module deliberately owns the narrow runtime boundary required by
``AIInstructionStep``.  It must not import the legacy recording host: Next
accepts only the application's OpenAI-compatible model contract and focuses
Browser-use on the already-owned Playwright page.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from browser_use import BrowserSession as BrowserUseSession
from browser_use.llm.openai.chat import ChatOpenAI


def build_next_openai_compatible_model(config: Mapping[str, object]) -> object:
    """Build the only model type supported by the F032 runtime contract."""

    model = config.get("model_name")
    api_key = config.get("api_key")
    if not isinstance(model, str) or not model or not isinstance(api_key, str) or not api_key:
        raise RuntimeError("rpa_agent_next.model_invalid")

    provider = str(config.get("provider") or "openai").strip().lower()
    if provider in {"anthropic", "gemini"}:
        raise RuntimeError("rpa_agent_next.model_protocol_unsupported")

    base_url = config.get("base_url")
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url if isinstance(base_url, str) and base_url else None,
    )


async def next_openai_compatible_model_for(
    owner_id: str, model_ref: str | None = None
) -> object:
    """Resolve an active user model and adapt it to Browser-use's OpenAI path."""

    from backend.models import get_model_config, resolve_default_model_config

    if model_ref:
        selected = await get_model_config(model_ref)
        if selected is None or not selected.is_active or (
            not selected.is_system and selected.user_id != owner_id
        ):
            raise RuntimeError("rpa_agent_next.model_unavailable")
        config: Mapping[str, object] | None = selected.model_dump(mode="python")
    else:
        config = await resolve_default_model_config(owner_id)

    if not isinstance(config, Mapping):
        raise RuntimeError("rpa_agent_next.model_unavailable")
    return build_next_openai_compatible_model(config)


async def resolve_next_model(
    factory: Callable[..., Awaitable[object]], owner_id: str, model_ref: str | None
) -> object:
    """Keep injected test doubles compatible with the original one-argument port."""

    if model_ref is None:
        return await factory(owner_id)
    try:
        return await factory(owner_id, model_ref)
    except TypeError:
        return await factory(owner_id)


async def focus_next_browser_use_page(browser_session: object, page: object) -> None:
    """Attach Browser-use to the exact Playwright target, not merely its context."""

    context = getattr(page, "context", None)
    create_cdp = getattr(context, "new_cdp_session", None)
    focus = getattr(browser_session, "get_or_create_cdp_session", None)
    if not callable(create_cdp) or not callable(focus):
        raise RuntimeError("rpa_agent_next.exact_page_focus_unavailable")

    playwright_cdp = await create_cdp(page)
    try:
        response = await playwright_cdp.send("Target.getTargetInfo")
    finally:
        detach = getattr(playwright_cdp, "detach", None)
        if callable(detach):
            await detach()

    info = response.get("targetInfo") if isinstance(response, Mapping) else None
    target_id = info.get("targetId") if isinstance(info, Mapping) else None
    if not isinstance(target_id, str) or not target_id:
        raise RuntimeError("rpa_agent_next.target_id_unavailable")
    await focus(target_id=target_id, focus=True)


__all__ = [
    "BrowserUseSession",
    "build_next_openai_compatible_model",
    "focus_next_browser_use_page",
    "next_openai_compatible_model_for",
    "resolve_next_model",
]
