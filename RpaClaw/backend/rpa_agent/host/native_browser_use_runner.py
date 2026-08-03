"""Browser-use runner for the vNext AIInstructionStep contract.

It deliberately emits no action history. The only user-visible state is owned
by ``rpa_agent.recording``; Browser-use history remains an ephemeral runtime
diagnostic inside the runner.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from browser_use import Agent

from ..recording.ai_execution import (
    BrowserUseExecutionRequest,
    BrowserUseExecutionResult,
)

from .next_browser_use_runtime import (
    BrowserUseSession,
    focus_next_browser_use_page,
    next_openai_compatible_model_for,
    resolve_next_model,
)


class NativeBrowserUseRunner:
    def __init__(
        self,
        *,
        owner_id: str,
        model_factory: Callable[..., Awaitable[object]] = next_openai_compatible_model_for,
        agent_factory: Callable[..., object] = Agent,
        browser_session_factory: Callable[..., object] = BrowserUseSession,
    ) -> None:
        self._owner_id = owner_id
        self._model_factory = model_factory
        self._agent_factory = agent_factory
        self._browser_session_factory = browser_session_factory

    async def execute(
        self, request: BrowserUseExecutionRequest
    ) -> BrowserUseExecutionResult:
        model = await resolve_next_model(
            self._model_factory, self._owner_id, request.model_ref
        )
        browser_session = self._browser_session_factory(
            cdp_url=request.cdp_url, keep_alive=True
        )
        await browser_session.start()
        try:
            await focus_next_browser_use_page(browser_session, request.page)
            agent = self._agent_factory(
                task=request.instruction,
                llm=model,
                browser_session=browser_session,
                use_vision=False,
                enable_signal_handler=False,
            )
            history = await agent.run()
            if history.is_done() is not True or history.is_successful() is not True:
                raise RuntimeError("browser_use_host.instruction_failed")
            return BrowserUseExecutionResult(result_summary="Browser-use completed.")
        finally:
            await browser_session.stop()
