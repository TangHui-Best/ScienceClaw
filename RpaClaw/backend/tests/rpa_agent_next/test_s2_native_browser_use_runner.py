from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from rpa_agent.host.native_browser_use_runner import NativeBrowserUseRunner
from rpa_agent.host.next_browser_use_runtime import build_next_openai_compatible_model
from rpa_agent.recording.ai_execution import BrowserUseExecutionRequest


class _Cdp:
    def __init__(self) -> None:
        self.detached = False

    async def send(self, command: str):
        assert command == "Target.getTargetInfo"
        return {"targetInfo": {"targetId": "target-1"}}

    async def detach(self) -> None:
        self.detached = True


class _Context:
    def __init__(self) -> None:
        self.cdp = _Cdp()

    async def new_cdp_session(self, page):
        return self.cdp


class _Page:
    def __init__(self) -> None:
        self.context = _Context()


class _BrowserSession:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.focused = None

    async def start(self) -> None:
        self.started = True

    async def get_or_create_cdp_session(self, *, target_id: str, focus: bool) -> None:
        self.focused = (target_id, focus)

    async def stop(self) -> None:
        self.stopped = True


class _History:
    def __init__(self, successful: bool) -> None:
        self.successful = successful

    def is_done(self) -> bool:
        return self.successful

    def is_successful(self) -> bool:
        return self.successful


class _Agent:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    async def run(self):
        return _History(successful=True)


def test_native_runner_attaches_to_exact_host_page_and_releases_session() -> None:
    async def scenario() -> None:
        browser_sessions = []

        def session_factory(**kwargs):
            session = _BrowserSession(**kwargs)
            browser_sessions.append(session)
            return session

        async def model_factory(owner_id: str, model_ref: str):
            assert (owner_id, model_ref) == ("owner-1", "model-1")
            return object()

        runner = NativeBrowserUseRunner(
            owner_id="owner-1",
            model_factory=model_factory,
            agent_factory=_Agent,
            browser_session_factory=session_factory,
        )
        page = _Page()
        result = await runner.execute(
            BrowserUseExecutionRequest(
                cdp_url="http://cdp.example.test",
                page=page,
                instruction="打开订单",
                model_ref="model-1",
            )
        )

        session = browser_sessions[0]
        assert result.result_summary == "Browser-use completed."
        assert session.kwargs == {"cdp_url": "http://cdp.example.test", "keep_alive": True}
        assert session.focused == ("target-1", True)
        assert page.context.cdp.detached is True
        assert session.stopped is True

    asyncio.run(scenario())


def test_native_runner_stops_browser_use_session_on_failed_history() -> None:
    async def scenario() -> None:
        session = _BrowserSession()

        class FailedAgent:
            def __init__(self, **kwargs) -> None:
                pass

            async def run(self):
                return _History(successful=False)

        async def model_factory(owner_id: str, model_ref: str):
            return object()

        runner = NativeBrowserUseRunner(
            owner_id="owner-1",
            model_factory=model_factory,
            agent_factory=FailedAgent,
            browser_session_factory=lambda **kwargs: session,
        )
        with pytest.raises(RuntimeError, match="instruction_failed"):
            await runner.execute(
                BrowserUseExecutionRequest(
                    cdp_url="http://cdp.example.test",
                    page=_Page(),
                    instruction="打开订单",
                    model_ref="model-1",
                )
            )
        assert session.stopped is True

    asyncio.run(scenario())


def test_next_model_adapter_accepts_openai_compatible_and_rejects_native_provider() -> None:
    model = build_next_openai_compatible_model(
        {
            "provider": "openai",
            "model_name": "gateway-model",
            "api_key": "test-key",
            "base_url": "https://gateway.example.test/v1",
        }
    )
    assert getattr(model, "model") == "gateway-model"

    with pytest.raises(RuntimeError, match="model_protocol_unsupported"):
        build_next_openai_compatible_model(
            {
                "provider": "anthropic",
                "model_name": "claude-test",
                "api_key": "test-key",
            }
        )


def test_next_native_runner_does_not_import_legacy_browser_use_host() -> None:
    runner_path = Path(__file__).resolve().parents[2] / "rpa_agent" / "host" / "native_browser_use_runner.py"
    assert "browser_use_agent" not in runner_path.read_text(encoding="utf-8")
