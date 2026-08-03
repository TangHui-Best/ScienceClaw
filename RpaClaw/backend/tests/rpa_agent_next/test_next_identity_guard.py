from __future__ import annotations

import pytest

from rpa_agent.contracts.identity import (
    ArtifactIngressError,
    ArtifactKind,
    RPA_AGENT_NEXT_NAMESPACE,
    require_next_identity,
)


def _envelope(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_namespace": RPA_AGENT_NEXT_NAMESPACE,
        "artifact_kind": ArtifactKind.SKILL_ARTIFACT.value,
        "artifact_id": "skill-1",
        "producer": "rpa-core",
    }
    value.update(overrides)
    return value


def test_accepts_only_a_matching_vnext_identity() -> None:
    identity = require_next_identity(
        _envelope(),
        entrypoint="compile",
        allowed_kinds=[ArtifactKind.SKILL_ARTIFACT],
    )
    assert identity.schema_namespace == RPA_AGENT_NEXT_NAMESPACE
    assert identity.artifact_kind is ArtifactKind.SKILL_ARTIFACT


@pytest.mark.parametrize(
    "legacy_envelope",
    [
        {},
        {"schema_namespace": "rpa-agent/v0"},
        {"schema_namespace": "legacy", "artifact_kind": "skill_artifact"},
    ],
)
def test_rejects_legacy_or_unknown_artifacts_before_payload_handling(
    legacy_envelope: dict[str, object],
) -> None:
    legacy_envelope["payload"] = {"must_not_be_migrated": True}
    with pytest.raises(ArtifactIngressError) as error:
        require_next_identity(legacy_envelope, entrypoint="runtime")
    assert error.value.code == "rpa_agent_next.legacy_or_unknown_artifact"


def test_rejects_a_valid_namespace_with_the_wrong_entrypoint_kind() -> None:
    with pytest.raises(ArtifactIngressError):
        require_next_identity(
            _envelope(artifact_kind=ArtifactKind.QUALITY_EVENT.value),
            entrypoint="compile",
            allowed_kinds=[ArtifactKind.SKILL_ARTIFACT],
        )
