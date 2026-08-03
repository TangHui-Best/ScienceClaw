"""Replay a freshly compiled vNext Skill in a fresh runtime and browser host."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Mapping, Protocol

from ..host import BrowserHostSession
from ..platform import RuntimeLease, RuntimeProviderPort
from ..recording.ai_execution import BrowserUseExecutionPort, BrowserUseExecutionRequest
from .contracts import (
    CompiledBrowserUseStep,
    CompiledPlaywrightStep,
    CompiledSkill,
    OutcomeAssertion,
)


class ReplayHostFactory(Protocol):
    async def create_replay(
        self, *, owner_id: str, lease: RuntimeLease, skill_id: str
    ) -> BrowserHostSession: ...


class PlaywrightReplayPort(Protocol):
    async def execute(
        self,
        trace: object,
        *,
        host: BrowserHostSession,
        inputs: Mapping[str, object],
    ) -> None: ...


class OutcomeAssertionPort(Protocol):
    async def evaluate(
        self,
        assertions: list[OutcomeAssertion],
        *,
        host: BrowserHostSession,
        inputs: Mapping[str, object],
    ) -> None: ...


class OutcomeAssertionFailedError(RuntimeError):
    """Preserve assertion failures as a quality signal, not a step failure."""


@dataclass(frozen=True)
class ReplayResult:
    replay_id: str
    skill_id: str
    status: str
    error_code: str | None = None


class IndependentSkillReplayer:
    """Never reuses the recording lease, host, page, or CDP endpoint."""

    def __init__(
        self,
        *,
        runtime_provider: RuntimeProviderPort,
        host_factory: ReplayHostFactory,
        playwright: PlaywrightReplayPort,
        browser_use_runner_factory,
        assertion_evaluator: OutcomeAssertionPort,
    ) -> None:
        self._runtime_provider = runtime_provider
        self._host_factory = host_factory
        self._playwright = playwright
        self._browser_use_runner_factory = browser_use_runner_factory
        self._assertion_evaluator = assertion_evaluator

    async def replay(
        self,
        *,
        skill: CompiledSkill,
        owner_id: str,
        inputs: Mapping[str, object],
        replay_id: str | None = None,
    ) -> ReplayResult:
        current_replay_id = replay_id or "rpr_" + secrets.token_hex(12)
        lease: RuntimeLease | None = None
        host: BrowserHostSession | None = None
        result: ReplayResult
        try:
            lease = await self._runtime_provider.acquire(
                current_replay_id, owner_id, "replay"
            )
            host = await self._host_factory.create_replay(
                owner_id=owner_id, lease=lease, skill_id=skill.skill_id
            )
            for step in skill.steps:
                if isinstance(step, CompiledPlaywrightStep):
                    await self._playwright.execute(step.trace, host=host, inputs=inputs)
                elif isinstance(step, CompiledBrowserUseStep):
                    await self._run_browser_use(step, host=host, owner_id=owner_id)
                else:
                    raise RuntimeError("next_skill_replay.step_invalid")
            if skill.config.outcome_assertions:
                try:
                    await self._assertion_evaluator.evaluate(
                        skill.config.outcome_assertions, host=host, inputs=inputs
                    )
                except Exception as error:
                    raise OutcomeAssertionFailedError(
                        "next_skill_replay.outcome_assertion_failed"
                    ) from error
            result = ReplayResult(current_replay_id, skill.skill_id, "succeeded")
        except OutcomeAssertionFailedError:
            result = ReplayResult(
                current_replay_id,
                skill.skill_id,
                "failed",
                "next_skill_replay.outcome_assertion_failed",
            )
        except Exception:
            result = ReplayResult(
                current_replay_id,
                skill.skill_id,
                "failed",
                "next_skill_replay.execution_failed",
            )
        cleanup_error = await self._cleanup(lease=lease, host=host)
        if cleanup_error is not None:
            return ReplayResult(
                current_replay_id,
                skill.skill_id,
                "failed",
                "next_skill_replay.cleanup_failed",
            )
        return result

    async def _run_browser_use(
        self,
        step: CompiledBrowserUseStep,
        *,
        host: BrowserHostSession,
        owner_id: str,
    ) -> None:
        port = host.port
        cdp_url = getattr(port, "browser_use_cdp_url", None)
        active_page = getattr(port, "active_page_object", None)
        if not isinstance(cdp_url, str) or not cdp_url or not callable(active_page):
            raise RuntimeError("next_skill_replay.browser_attachment_unavailable")
        page = active_page()
        if hasattr(page, "__await__"):
            page = await page
        runner: BrowserUseExecutionPort = self._browser_use_runner_factory(owner_id)
        await runner.execute(
            BrowserUseExecutionRequest(
                cdp_url=cdp_url,
                page=page,
                instruction=step.instruction,
                model_ref=step.model_ref,
            )
        )

    async def _cleanup(
        self, *, lease: RuntimeLease | None, host: BrowserHostSession | None
    ) -> BaseException | None:
        first_error: BaseException | None = None
        if host is not None:
            try:
                await host.aclose()
            except BaseException as error:
                first_error = error
        if lease is not None:
            try:
                await self._runtime_provider.release(
                    lease, "rpa_agent_next.skill_replay_closed"
                )
            except BaseException as error:
                if first_error is None:
                    first_error = error
        return first_error
