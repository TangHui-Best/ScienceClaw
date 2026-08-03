from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from rpa_agent.contracts.identity import (
    RPA_AGENT_NEXT_NAMESPACE,
    ArtifactIdentity,
    ArtifactKind,
    ArtifactProducer,
)
from rpa_agent.host import BrowserHostSession
from rpa_agent.platform import FakeRuntimeProvider, RuntimeLease
from rpa_agent.quality import (
    BadCaseRegistry,
    FailureClass,
    HarnessAsset,
    HarnessAssetRegistry,
    QualityHarness,
    QualityMetrics,
    input_fingerprint,
)
from rpa_agent.recording import RecordingSession
from rpa_agent.skill_build import (
    IndependentSkillReplayer,
    OutcomeAssertion,
    RuntimeLimits,
    SkillBuildConfig,
    SkillBuildOutput,
    compile_skill,
)

from test_s2_recording_contracts import _navigation_trace


INPUTS = {"order_id": "PO-secret-1"}


def _config(*, assertions: tuple[OutcomeAssertion, ...] = ()) -> SkillBuildConfig:
    return SkillBuildConfig(
        schema_namespace=RPA_AGENT_NEXT_NAMESPACE,
        config_id="config_s4_1",
        skill_id="skill_s4_1",
        name="S4 quality skill",
        description="A minimal new-generation skill used by the quality harness.",
        browser_use_model_ref="model_s4_1",
        runtime_limits=RuntimeLimits(timeout_seconds=30),
        outputs=[SkillBuildOutput(ref="result", title="Result")],
        outcome_assertions=list(assertions),
    )


def _skill(*, assertions: tuple[OutcomeAssertion, ...] = ()):
    session = RecordingSession(session_id="recording_s4_1")
    session.begin_manual_draft(draft_id="draft_s4_1")
    session.freeze_manual_trace(draft_id="draft_s4_1", trace=_navigation_trace())
    return compile_skill(session.timeline(), _config(assertions=assertions))


def _skill_identity() -> ArtifactIdentity:
    return ArtifactIdentity(
        schema_namespace=RPA_AGENT_NEXT_NAMESPACE,
        artifact_kind=ArtifactKind.SKILL_ARTIFACT,
        artifact_id="skill_s4_1",
        producer=ArtifactProducer.RPA_CORE,
    )


def _asset(skill, *, asset_id: str = "harness_s4_1") -> HarnessAsset:
    return HarnessAsset(
        identity=ArtifactIdentity(
            schema_namespace=RPA_AGENT_NEXT_NAMESPACE,
            artifact_kind=ArtifactKind.HARNESS_ASSET,
            artifact_id=asset_id,
            producer=ArtifactProducer.QUALITY_SYSTEM,
        ),
        skill_artifact=_skill_identity(),
        skill_source_hash=skill.source_hash,
        input_fingerprint=input_fingerprint(INPUTS),
    )


class _ReplayPort:
    browser_use_cdp_url = "http://s4-replay-cdp.example.test"

    def __init__(self) -> None:
        self.closed = 0

    async def active_page_object(self) -> object:
        return object()

    def subscribe(self, kind, callback):
        del kind, callback
        return lambda: None

    async def aclose(self) -> None:
        self.closed += 1


class _HostFactory:
    def __init__(self) -> None:
        self.port = _ReplayPort()
        self.created = 0

    async def create_replay(
        self, *, owner_id: str, lease: RuntimeLease, skill_id: str
    ) -> BrowserHostSession:
        assert owner_id == "user_s4_1"
        assert lease.purpose == "replay"
        assert skill_id == "skill_s4_1"
        self.created += 1
        return BrowserHostSession(
            browser_session_ref="replay_host_s4_1",
            page_ref="replay_page_s4_1",
            target_id="replay_target_s4_1",
            generation="replay_generation_s4_1",
            port=self.port,
        )


class _Playwright:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def execute(self, trace, *, host, inputs) -> None:
        del trace, host
        assert inputs == INPUTS
        if self.fail:
            raise RuntimeError("simulated playwright failure")


class _BrowserUse:
    async def execute(self, request):
        del request


class _Assertions:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def evaluate(self, assertions, *, host, inputs) -> None:
        del assertions, host
        assert inputs == INPUTS
        if self.fail:
            raise RuntimeError("simulated outcome assertion failure")


def _harness(*, playwright_fail: bool = False, assertion_fail: bool = False):
    runtime = FakeRuntimeProvider()
    hosts = _HostFactory()
    return (
        QualityHarness(
            replayer=IndependentSkillReplayer(
                runtime_provider=runtime,
                host_factory=hosts,
                playwright=_Playwright(fail=playwright_fail),
                browser_use_runner_factory=lambda _owner: _BrowserUse(),
                assertion_evaluator=_Assertions(fail=assertion_fail),
            )
        ),
        runtime,
        hosts,
    )


def test_harness_requires_reviewed_asset_and_never_persists_raw_input() -> None:
    async def scenario() -> None:
        skill = _skill()
        registry = HarnessAssetRegistry()
        proposed = registry.propose(_asset(skill), inputs=INPUTS)
        harness, _runtime, hosts = _harness()

        unapproved = await harness.run(
            asset=proposed,
            skill_artifact=_skill_identity(),
            skill=skill,
            owner_id="user_s4_1",
            inputs=INPUTS,
            correlation_id="correlation_s4_1",
        )
        assert unapproved.status == "failed"
        assert unapproved.failure_class is FailureClass.QUALITY_CONTRACT_VIOLATION
        assert hosts.created == 0

        accepted = registry.accept(asset_id="harness_s4_1", reviewer_id="reviewer_s4_1")
        passed = await harness.run(
            asset=accepted,
            skill_artifact=_skill_identity(),
            skill=skill,
            owner_id="user_s4_1",
            inputs=INPUTS,
            correlation_id="correlation_s4_2",
            observed_cost_units=1.25,
        )
        assert passed.status == "succeeded"
        assert "PO-secret-1" not in passed.model_dump_json()

        metrics = QualityMetrics()
        metrics.record(unapproved)
        metrics.record(passed)
        snapshot = metrics.snapshot()
        assert snapshot.run_count == 2
        assert snapshot.success_rate == 0.5
        assert snapshot.observed_cost_units == 1.25
        assert snapshot.failures_by_class == {
            "quality_contract_violation": 1
        }

    asyncio.run(scenario())


def test_replay_failure_becomes_reviewable_bad_case() -> None:
    async def scenario() -> None:
        skill = _skill()
        assets = HarnessAssetRegistry()
        assets.propose(_asset(skill), inputs=INPUTS)
        accepted = assets.accept(asset_id="harness_s4_1", reviewer_id="reviewer_s4_1")
        harness, runtime, hosts = _harness(playwright_fail=True)

        report = await harness.run(
            asset=accepted,
            skill_artifact=_skill_identity(),
            skill=skill,
            owner_id="user_s4_1",
            inputs=INPUTS,
            correlation_id="correlation_s4_3",
        )
        assert report.status == "failed"
        assert report.failure_class is FailureClass.REPLAY_EXECUTION_FAILED
        assert hosts.port.closed == 1
        assert runtime.release_reasons == [
            ("lease:" + report.replay_id, "rpa_agent_next.skill_replay_closed")
        ]

        bad_cases = BadCaseRegistry()
        proposed = bad_cases.propose(bad_case_id="bad_case_s4_1", report=report)
        assert proposed.status == "proposed"
        accepted_bad_case = bad_cases.accept(
            bad_case_id="bad_case_s4_1", reviewer_id="reviewer_s4_1"
        )
        assert accepted_bad_case.status == "accepted"
        assert accepted_bad_case.reviewed_by == "reviewer_s4_1"

    asyncio.run(scenario())


def test_outcome_assertion_has_its_own_failure_class() -> None:
    async def scenario() -> None:
        assertion = OutcomeAssertion(
            assertion_id="assertion_s4_1", kind="url_matches", expected="/done"
        )
        skill = _skill(assertions=(assertion,))
        assets = HarnessAssetRegistry()
        assets.propose(_asset(skill), inputs=INPUTS)
        accepted = assets.accept(asset_id="harness_s4_1", reviewer_id="reviewer_s4_1")
        harness, _runtime, _hosts = _harness(assertion_fail=True)

        report = await harness.run(
            asset=accepted,
            skill_artifact=_skill_identity(),
            skill=skill,
            owner_id="user_s4_1",
            inputs=INPUTS,
            correlation_id="correlation_s4_4",
        )
        assert report.failure_class is FailureClass.OUTCOME_ASSERTION_FAILED

    asyncio.run(scenario())


def test_harness_rejects_legacy_or_wrongly_owned_asset_identity() -> None:
    skill = _skill()
    with pytest.raises(ValidationError, match="next_harness.asset_identity_invalid"):
        HarnessAsset(
            identity=ArtifactIdentity(
                schema_namespace=RPA_AGENT_NEXT_NAMESPACE,
                artifact_kind=ArtifactKind.RECORDING_TIMELINE,
                artifact_id="legacy_trace_s4_1",
                producer=ArtifactProducer.RPA_CORE,
            ),
            skill_artifact=_skill_identity(),
            skill_source_hash=skill.source_hash,
            input_fingerprint=input_fingerprint(INPUTS),
        )
