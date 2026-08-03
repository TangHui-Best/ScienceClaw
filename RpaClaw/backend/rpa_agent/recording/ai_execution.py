"""Coordinate AI instruction lifecycle without turning agent internals into facts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .session import RecordingSession


@dataclass(frozen=True)
class BrowserUseExecutionRequest:
    cdp_url: str
    page: object
    instruction: str
    model_ref: str


@dataclass(frozen=True)
class BrowserUseExecutionResult:
    result_summary: str | None = None


class BrowserUseExecutionPort(Protocol):
    async def execute(
        self, request: BrowserUseExecutionRequest
    ) -> BrowserUseExecutionResult: ...


class ManualRecordingControlPort(Protocol):
    async def pause_manual_recording(self) -> None: ...

    async def resume_manual_recording(self) -> None: ...


class BrowserUseInstructionCoordinator:
    """Owns only step state and recorder control; the runner owns browser resources."""

    def __init__(
        self,
        *,
        session: RecordingSession,
        manual_control: ManualRecordingControlPort,
        runner: BrowserUseExecutionPort,
    ) -> None:
        self._session = session
        self._manual_control = manual_control
        self._runner = runner

    async def execute(self, *, step_id: str, host: object) -> None:
        step = self._session.mark_ai_running(step_id=step_id, started_at=_now())
        paused = False
        try:
            cdp_url, page = await _host_attachment(host)
            await self._manual_control.pause_manual_recording()
            paused = True
            result = await self._runner.execute(
                BrowserUseExecutionRequest(
                    cdp_url=cdp_url,
                    page=page,
                    instruction=step.instruction,
                    model_ref=step.execution.attempts[0].model_ref,
                )
            )
            self._session.finish_ai(
                step_id=step_id,
                finished_at=_now(),
                result_summary=result.result_summary,
            )
        except asyncio.CancelledError:
            self._session.cancel_ai(step_id=step_id, finished_at=_now())
            raise
        except Exception:
            self._session.finish_ai(
                step_id=step_id,
                finished_at=_now(),
                error_code="browser_use_execution_failed",
                error_message="Browser-use execution failed.",
            )
        finally:
            if paused:
                await self._manual_control.resume_manual_recording()


async def _host_attachment(host: object) -> tuple[str, object]:
    port = getattr(host, "port", None)
    cdp_url = getattr(port, "browser_use_cdp_url", None)
    active_page = getattr(port, "active_page_object", None)
    if not isinstance(cdp_url, str) or not cdp_url or not callable(active_page):
        raise RuntimeError("browser_use_host.attachment_unavailable")
    page = active_page()
    if hasattr(page, "__await__"):
        page = await page
    return cdp_url, page


def _now() -> datetime:
    return datetime.now(timezone.utc)
