from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from rpa_agent.host.browser_session import HostBrowserEvent
from rpa_agent.host.recording_listener_gate import ManualRecordingListenerGate
from rpa_agent.recording import BrowserUseInstructionCoordinator, RecordingSession
from rpa_agent.recording.ai_execution import BrowserUseExecutionResult


class _Port:
    def __init__(self) -> None:
        self.callbacks = {}
        self.released: list[str] = []

    def subscribe(self, kind, callback):
        self.callbacks[kind] = callback

        def release() -> None:
            self.released.append(kind)

        return release


def _event() -> HostBrowserEvent:
    return HostBrowserEvent(
        kind="navigation",
        observed_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        source_page_runtime_ref="page_1",
        source_frame_runtime_ref="frame_1",
        runtime_page_ref="page_1",
    )


def test_listener_gate_routes_human_events_and_drops_events_while_ai_is_running() -> None:
    async def scenario() -> None:
        port = _Port()
        received = []
        gate = ManualRecordingListenerGate(port=port, event_sink=received.append)
        gate.attach()

        port.callbacks["navigation"](_event())
        await gate.pause_manual_recording()
        port.callbacks["navigation"](_event())
        await gate.resume_manual_recording()
        port.callbacks["navigation"](_event())

        assert len(received) == 2
        await gate.aclose()
        assert port.released == ["download", "new_page", "navigation"]

    asyncio.run(scenario())


def test_listener_gate_rejects_double_attach() -> None:
    gate = ManualRecordingListenerGate(port=_Port(), event_sink=lambda event: None)
    gate.attach()
    try:
        gate.attach()
    except ValueError as error:
        assert str(error) == "next_recording_listener.already_attached"
    else:
        raise AssertionError("expected duplicate attach to fail")


def test_coordinator_pauses_the_real_listener_gate_for_ai_browser_events() -> None:
    async def scenario() -> None:
        port = _Port()
        port.browser_use_cdp_url = "http://cdp.example.test"
        port.active_page_object = lambda: object()
        received = []
        gate = ManualRecordingListenerGate(port=port, event_sink=received.append)
        gate.attach()
        session = RecordingSession(session_id="session_1")
        session.queue_ai_instruction(
            step_id="step_1",
            instruction="打开订单",
            model_ref="model_1",
            context_snapshot_ref="context_1",
            created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )

        class Runner:
            async def execute(self, request):
                port.callbacks["navigation"](_event())
                return BrowserUseExecutionResult()

        await BrowserUseInstructionCoordinator(
            session=session, manual_control=gate, runner=Runner()
        ).execute(step_id="step_1", host=type("Host", (), {"port": port})())

        assert received == []
        port.callbacks["navigation"](_event())
        assert len(received) == 1
        assert session.timeline().items[0].execution.status == "succeeded"

    asyncio.run(scenario())
