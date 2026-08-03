"""RPA Agent Next artifact identity and fail-closed ingress validation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


RPA_AGENT_NEXT_NAMESPACE = "rpa-agent-next/v1"


class ArtifactKind(str, Enum):
    RECORDING_TIMELINE = "recording_timeline"
    SKILL_BUILD_CONFIG = "skill_build_config"
    SKILL_ARTIFACT = "skill_artifact"
    HARNESS_ASSET = "harness_asset"
    QUALITY_EVENT = "quality_event"


class ArtifactProducer(str, Enum):
    RPA_CORE = "rpa-core"
    RUNTIME_PLATFORM = "runtime-platform"
    QUALITY_SYSTEM = "quality-system"


class ArtifactIdentity(BaseModel):
    """The small, versioned envelope every vNext ingress validates first."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_namespace: str = Field(min_length=1)
    artifact_kind: ArtifactKind
    artifact_id: str = Field(min_length=1, max_length=128)
    producer: ArtifactProducer


class ArtifactIngressError(ValueError):
    """A stable, payload-free error for unsupported artifact generations."""

    code = "rpa_agent_next.legacy_or_unknown_artifact"

    def __init__(self, entrypoint: str) -> None:
        self.entrypoint = entrypoint
        super().__init__(f"{self.code}:{entrypoint}")


def require_next_identity(
    envelope: Mapping[str, object],
    *,
    entrypoint: str,
    allowed_kinds: Iterable[ArtifactKind] | None = None,
) -> ArtifactIdentity:
    """Accept only the vNext identity without inspecting a business payload.

    The function intentionally reads only the four identity fields.  A caller can
    therefore reject legacy artifacts before deserializing a possibly sensitive or
    incompatible payload.
    """

    namespace = envelope.get("schema_namespace")
    if namespace != RPA_AGENT_NEXT_NAMESPACE:
        raise ArtifactIngressError(entrypoint)

    try:
        kind = ArtifactKind(envelope.get("artifact_kind"))
        producer = ArtifactProducer(envelope.get("producer"))
        artifact_id = envelope.get("artifact_id")
    except (TypeError, ValueError) as error:
        raise ArtifactIngressError(entrypoint) from error

    if not isinstance(artifact_id, str) or not artifact_id:
        raise ArtifactIngressError(entrypoint)

    accepted_kinds = set(allowed_kinds) if allowed_kinds is not None else None
    if accepted_kinds is not None and kind not in accepted_kinds:
        raise ArtifactIngressError(entrypoint)

    return ArtifactIdentity(
        schema_namespace=RPA_AGENT_NEXT_NAMESPACE,
        artifact_kind=kind,
        artifact_id=artifact_id,
        producer=producer,
    )
