from __future__ import annotations

import asyncio

from rpa_agent.contracts.identity import ArtifactIngressError, ArtifactKind, RPA_AGENT_NEXT_NAMESPACE, require_next_identity
from rpa_agent.platform import FakeRuntimeProvider
from rpa_agent.quality import FailureClass, QualityEvent, QualityStage


def test_s0_minimum_chain_releases_runtime_and_reports_legacy_rejection() -> None:
    async def scenario() -> QualityEvent:
        provider = FakeRuntimeProvider()
        lease = await provider.acquire("session-e2e", "user-e2e", "evaluation")
        try:
            require_next_identity(
                {"schema_namespace": "legacy-skill/v1"}, entrypoint="evaluation"
            )
        except ArtifactIngressError:
            return QualityEvent(
                event_id="event-e2e",
                session_id=lease.session_id,
                artifact=require_next_identity(
                    {
                        "schema_namespace": RPA_AGENT_NEXT_NAMESPACE,
                        "artifact_kind": ArtifactKind.QUALITY_EVENT.value,
                        "artifact_id": "event-e2e",
                        "producer": "quality-system",
                    },
                    entrypoint="quality",
                    allowed_kinds=[ArtifactKind.QUALITY_EVENT],
                ),
                stage=QualityStage.QUALITY,
                failure_class=FailureClass.LEGACY_OR_UNKNOWN_ARTIFACT,
                correlation_id="correlation-e2e",
            )
        finally:
            await provider.release(lease, "legacy_asset_rejected")

    event = asyncio.run(scenario())
    assert event.failure_class is FailureClass.LEGACY_OR_UNKNOWN_ARTIFACT
