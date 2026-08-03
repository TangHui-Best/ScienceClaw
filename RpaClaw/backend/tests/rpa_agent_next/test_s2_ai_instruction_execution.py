from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from rpa_agent.recording import BrowserUseInstructionCoordinator, RecordingSession
from rpa_agent.recording.ai_execution import BrowserUseExecutionResult


NOW = datetime(2026, 8, 2, tzinfo=timezone.utc)


class _ManualControl:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def pause_manual_recording(self) -> None:
        self.events.append("pause")

    async def resume_manual_recording(self) -> None:
        self.events.append("resume")


class _Port:
    browser_use_cdp_url = "http://cdp.example.test"

    def __init__(self) -> None:
        self.page = object()

    async def active_page_object(self) -> object:
        return self.page


class _Host:
    def __init__(self) -> None:
        self.port = _Port()


class _Runner:
    def __init__(self, outcome: str = "succeed") -> None:
        self.outcome = outcome
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        if self.outcome == "fail":
            raise RuntimeError("sensitive browser content must not leak")
        if self.outcome == "cancel":
            raise asyncio.CancelledError()
        return BrowserUseExecutionResult(result_summary="完成")


def _session() -> RecordingSession:
    session = RecordingSession(session_id="session_1")
    session.queue_ai_instruction(
        step_id="step_1",
        instruction="打开订单页面",
        model_ref="model_1",
        context_snapshot_ref="context_1",
        created_at=NOW,
    )
    return session


def test_ai_execution_uses_existing_host_page_and_resumes_manual_recording() -> None:
    async def scenario() -> None:
        session = _session()
        control = _ManualControl()
        runner = _Runner()
        host = _Host()

        await BrowserUseInstructionCoordinator(
            session=session, manual_control=control, runner=runner
        ).execute(step_id="step_1", host=host)

        step = session.timeline().items[0]
        assert step.execution.status == "succeeded"
        assert control.events == ["pause", "resume"]
        assert runner.requests[0].cdp_url == "http://cdp.example.test"
        assert runner.requests[0].page is host.port.page
        assert not hasattr(step, "observation_trace_refs")

    asyncio.run(scenario())


def test_ai_failure_is_sanitized_and_manual_recording_is_restored() -> None:
    async def scenario() -> None:
        session = _session()
        control = _ManualControl()
        runner = _Runner("fail")

        await BrowserUseInstructionCoordinator(
            session=session, manual_control=control, runner=runner
        ).execute(step_id="step_1", host=_Host())

        step = session.timeline().items[0]
        assert step.execution.status == "failed"
        assert step.execution.error_code == "browser_use_execution_failed"
        assert "sensitive" not in step.execution.error_message
        assert control.events == ["pause", "resume"]

    asyncio.run(scenario())


def test_ai_cancellation_sets_terminal_state_and_restores_manual_recording() -> None:
    async def scenario() -> None:
        session = _session()
        control = _ManualControl()

        with pytest.raises(asyncio.CancelledError):
            await BrowserUseInstructionCoordinator(
                session=session, manual_control=control, runner=_Runner("cancel")
            ).execute(step_id="step_1", host=_Host())

        step = session.timeline().items[0]
        assert step.execution.status == "cancelled"
        assert control.events == ["pause", "resume"]

    asyncio.run(scenario())
