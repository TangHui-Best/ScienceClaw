from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from rpa_agent.contracts import CoreTrace
from rpa_agent.application import (
    RpaAgentNextSessionOrchestrator,
    RpaAgentNextSkillBuildService,
)
from rpa_agent.host import BrowserHostSession
from rpa_agent.platform import FakeRuntimeProvider, RuntimeLease
from rpa_agent.recording import RecordingSession
from rpa_agent.recording.ai_execution import BrowserUseExecutionResult
from rpa_agent.skill_build import (
    CompileRejectedError,
    IndependentSkillReplayer,
    OutcomeAssertion,
    RuntimeLimits,
    SkillBuildConfig,
    SkillBuildOutput,
    compile_skill,
    decide_core_trace,
)

from test_s2_recording_contracts import NOW, _navigation_trace


def _config(*, assertions=()) -> SkillBuildConfig:
    return SkillBuildConfig(
        schema_namespace="rpa-agent-next/v1",
        config_id="config_1",
        skill_id="skill_1",
        name="Purchase order lookup",
        description="Open the order page and collect its status.",
        browser_use_model_ref="model_1",
        runtime_limits=RuntimeLimits(timeout_seconds=120),
        outputs=[SkillBuildOutput(ref="result", title="Result")],
        outcome_assertions=list(assertions),
    )


def _timeline_with_manual_and_ai():
    session = RecordingSession(session_id="recording_session_1")
    session.begin_manual_draft(draft_id="draft_1")
    session.freeze_manual_trace(draft_id="draft_1", trace=_navigation_trace())
    session.queue_ai_instruction(
        step_id="ai_1",
        instruction="Find the order status.",
        model_ref="recording_model_must_not_be_compiled",
        context_snapshot_ref="context_1",
        created_at=NOW,
    )
    return session


def test_compile_decision_and_skill_build_use_only_next_facts_intent_and_config() -> None:
    session = _timeline_with_manual_and_ai()
    skill = compile_skill(session.timeline(), _config())

    assert decide_core_trace(_navigation_trace()).mode == "playwright"
    assert [step.mode for step in skill.steps] == ["playwright", "browser_use"]
    assert skill.steps[0].step_id == "trace_1"
    assert skill.steps[1].model_ref == "model_1"
    assert skill.steps[1].instruction == "Find the order status."
    assert "recording_model" not in skill.model_dump_json()

    source_hash_before = skill.source_hash
    session.mark_ai_running(step_id="ai_1", started_at=NOW)
    session.finish_ai(step_id="ai_1", finished_at=NOW, result_summary="done")
    assert compile_skill(session.timeline(), _config()).source_hash == source_hash_before


def test_agent_core_trace_requires_review_and_is_never_auto_converted_to_browser_use() -> None:
    trace = CoreTrace.model_validate(
        {
            "trace_id": "trace_agent_1",
            "sequence": 1,
            "scope": {"page_ref": "main", "frame_path": []},
            "action": {"kind": "agent", "instruction": "Do the task"},
            "data_bindings": [],
            "effects": [],
        }
    )
    session = RecordingSession(session_id="recording_session_2")
    session.begin_manual_draft(draft_id="draft_1")
    session.freeze_manual_trace(draft_id="draft_1", trace=trace)

    decision = decide_core_trace(trace)
    assert decision.mode == "review_required"
    assert decision.reason_codes == ["manual_trace.agent_action_not_playwright"]
    with pytest.raises(CompileRejectedError) as rejected:
        compile_skill(session.timeline(), _config())
    assert rejected.value.decisions == [decision]


class _ReplayPort:
    browser_use_cdp_url = "http://new-replay-cdp.example.test"

    def __init__(self) -> None:
        self.page = object()
        self.closed = 0

    async def active_page_object(self) -> object:
        return self.page

    def subscribe(self, kind, callback):
        del kind, callback
        return lambda: None

    async def aclose(self) -> None:
        self.closed += 1


class _ReplayHostFactory:
    def __init__(self) -> None:
        self.port = _ReplayPort()
        self.leases: list[RuntimeLease] = []

    async def create_replay(self, *, owner_id: str, lease: RuntimeLease, skill_id: str):
        assert owner_id == "user_1"
        assert skill_id == "skill_1"
        self.leases.append(lease)
        return BrowserHostSession(
            browser_session_ref="replay_host_1",
            page_ref="replay_page_1",
            target_id="replay_target_1",
            generation="replay_generation_1",
            port=self.port,
        )

    async def create_recording(self, *, owner_id: str, lease: RuntimeLease):
        assert owner_id == "user_1"
        self.leases.append(lease)
        return BrowserHostSession(
            browser_session_ref="recording_host_1",
            page_ref="recording_page_1",
            target_id="recording_target_1",
            generation="recording_generation_1",
            port=_ReplayPort(),
        )


class _Playwright:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.traces = []
        self.hosts = []

    async def execute(self, trace, *, host, inputs) -> None:
        self.traces.append(trace)
        self.hosts.append(host)
        assert inputs == {"order_id": "PO-1"}
        if self.fail:
            raise RuntimeError("page body must not reach error response")


class _BrowserUse:
    def __init__(self) -> None:
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        return BrowserUseExecutionResult(result_summary="done")


class _Assertions:
    def __init__(self) -> None:
        self.received = []

    async def evaluate(self, assertions, *, host, inputs) -> None:
        self.received.append((assertions, host, inputs))


def test_independent_replay_uses_new_lease_and_host_and_only_explicit_assertions() -> None:
    async def scenario() -> None:
        assertion = OutcomeAssertion(
            assertion_id="assert_1", kind="url_matches", expected="/orders/"
        )
        skill = compile_skill(_timeline_with_manual_and_ai().timeline(), _config(assertions=(assertion,)))
        runtime = FakeRuntimeProvider()
        hosts = _ReplayHostFactory()
        playwright = _Playwright()
        browser_use = _BrowserUse()
        assertions = _Assertions()
        result = await IndependentSkillReplayer(
            runtime_provider=runtime,
            host_factory=hosts,
            playwright=playwright,
            browser_use_runner_factory=lambda _owner: browser_use,
            assertion_evaluator=assertions,
        ).replay(
            skill=skill,
            owner_id="user_1",
            inputs={"order_id": "PO-1"},
            replay_id="replay_session_1",
        )

        assert result.status == "succeeded"
        assert hosts.leases[0].session_id == "replay_session_1"
        assert hosts.leases[0].purpose == "replay"
        assert playwright.hosts == [
            playwright.hosts[0]
        ] and playwright.hosts[0].browser_session_ref == "replay_host_1"
        assert browser_use.requests[0].cdp_url == "http://new-replay-cdp.example.test"
        assert browser_use.requests[0].page is hosts.port.page
        assert assertions.received[0][0] == [assertion]
        assert hosts.port.closed == 1
        assert runtime.release_reasons == [
            ("lease:replay_session_1", "rpa_agent_next.skill_replay_closed")
        ]

    asyncio.run(scenario())


def test_independent_replay_releases_fresh_resources_when_a_step_fails() -> None:
    async def scenario() -> None:
        runtime = FakeRuntimeProvider()
        hosts = _ReplayHostFactory()
        result = await IndependentSkillReplayer(
            runtime_provider=runtime,
            host_factory=hosts,
            playwright=_Playwright(fail=True),
            browser_use_runner_factory=lambda _owner: _BrowserUse(),
            assertion_evaluator=_Assertions(),
        ).replay(
            skill=compile_skill(_timeline_with_manual_and_ai().timeline(), _config()),
            owner_id="user_1",
            inputs={"order_id": "PO-1"},
            replay_id="replay_session_2",
        )

        assert result.status == "failed"
        assert result.error_code == "next_skill_replay.execution_failed"
        assert hosts.port.closed == 1
        assert runtime.release_reasons == [
            ("lease:replay_session_2", "rpa_agent_next.skill_replay_closed")
        ]

    asyncio.run(scenario())


def test_skill_build_service_receives_source_only_from_next_session_orchestrator() -> None:
    async def scenario() -> None:
        runtime = FakeRuntimeProvider()
        hosts = _ReplayHostFactory()
        browser_use = _BrowserUse()
        replayer = IndependentSkillReplayer(
            runtime_provider=runtime,
            host_factory=hosts,
            playwright=_Playwright(),
            browser_use_runner_factory=lambda _owner: browser_use,
            assertion_evaluator=_Assertions(),
        )
        sessions = RpaAgentNextSessionOrchestrator(
            runtime_provider=runtime,
            host_factory=hosts,
            runner_factory=lambda _owner: browser_use,
        )
        recording = await sessions.start(
            session_id="recording_session_3", owner_id="user_1"
        )
        recording.begin_manual_draft(draft_id="draft_1")
        recording.freeze_manual_trace(draft_id="draft_1", trace=_navigation_trace())
        artifact = await RpaAgentNextSkillBuildService(
            sessions=sessions, replayer=replayer
        ).build(
            session_id="recording_session_3", owner_id="user_1", config=_config()
        )

        assert artifact.steps[0].step_id == "trace_1"
        assert artifact.schema_namespace == "rpa-agent-next/v1"
        assert hosts.leases[0].purpose == "recording"
        await sessions.close(session_id="recording_session_3", owner_id="user_1")

    asyncio.run(scenario())
