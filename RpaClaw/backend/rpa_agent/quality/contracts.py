"""Quality events reference immutable artifact identities, never CoreTrace objects."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from rpa_agent.contracts.identity import ArtifactIdentity, ArtifactKind


class QualityStage(str, Enum):
    RUNTIME = "runtime"
    RECORDING = "recording"
    COMPILE = "compile"
    REPLAY = "replay"
    QUALITY = "quality"


class FailureClass(str, Enum):
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    LEGACY_OR_UNKNOWN_ARTIFACT = "legacy_or_unknown_artifact"
    QUALITY_CONTRACT_VIOLATION = "quality_contract_violation"
    REPLAY_EXECUTION_FAILED = "replay_execution_failed"
    REPLAY_CLEANUP_FAILED = "replay_cleanup_failed"
    OUTCOME_ASSERTION_FAILED = "outcome_assertion_failed"


class QualityEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    event_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    artifact: ArtifactIdentity
    stage: QualityStage
    failure_class: FailureClass
    correlation_id: str = Field(min_length=1, max_length=128)

    @property
    def is_quality_artifact(self) -> bool:
        return self.artifact.artifact_kind is ArtifactKind.QUALITY_EVENT
