from __future__ import annotations

from rpa_agent.contracts.identity import (
    ArtifactKind,
    RPA_AGENT_NEXT_NAMESPACE,
    require_next_identity,
)
from rpa_agent.quality import FailureClass, QualityEvent, QualityStage


def test_quality_event_references_only_an_immutable_identity() -> None:
    event = QualityEvent(
        event_id="event-1",
        session_id="session-1",
        artifact=require_next_identity(
            {
                "schema_namespace": RPA_AGENT_NEXT_NAMESPACE,
                "artifact_kind": ArtifactKind.QUALITY_EVENT.value,
                "artifact_id": "quality-1",
                "producer": "quality-system",
            },
            entrypoint="quality",
            allowed_kinds=[ArtifactKind.QUALITY_EVENT],
        ),
        stage=QualityStage.QUALITY,
        failure_class=FailureClass.LEGACY_OR_UNKNOWN_ARTIFACT,
        correlation_id="correlation-1",
    )

    assert event.is_quality_artifact
    assert "CoreTrace" not in QualityEvent.model_fields
