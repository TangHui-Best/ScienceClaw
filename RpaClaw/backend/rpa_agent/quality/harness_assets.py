"""Governed vNext harness assets; they reference Skills but never own recording facts."""

from __future__ import annotations

import hashlib
import json
from threading import RLock
from typing import Literal, Mapping

from pydantic import Field, model_validator

from ..contracts.identity import ArtifactIdentity, ArtifactKind, ArtifactProducer
from ..contracts.models import Identifier, StrictModel


HarnessAssetState = Literal["proposed", "accepted", "rejected"]


class HarnessAsset(StrictModel):
    identity: ArtifactIdentity
    skill_artifact: ArtifactIdentity
    skill_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_replay_status: Literal["succeeded"] = "succeeded"
    state: HarnessAssetState = "proposed"
    reviewed_by: Identifier | None = None

    @model_validator(mode="after")
    def _validate_ownership(self) -> "HarnessAsset":
        if (
            self.identity.artifact_kind is not ArtifactKind.HARNESS_ASSET
            or self.identity.producer is not ArtifactProducer.QUALITY_SYSTEM
        ):
            raise ValueError("next_harness.asset_identity_invalid")
        if (
            self.skill_artifact.artifact_kind is not ArtifactKind.SKILL_ARTIFACT
            or self.skill_artifact.producer is not ArtifactProducer.RPA_CORE
        ):
            raise ValueError("next_harness.skill_identity_invalid")
        if self.state == "accepted" and self.reviewed_by is None:
            raise ValueError("next_harness.accepted_requires_reviewer")
        if self.state != "accepted" and self.reviewed_by is not None:
            raise ValueError("next_harness.unaccepted_has_reviewer")
        return self


class HarnessAssetRegistry:
    """Process-local governance registry for the S4 harness boundary."""

    def __init__(self) -> None:
        self._assets: dict[str, HarnessAsset] = {}
        self._mutex = RLock()

    def propose(self, asset: HarnessAsset, *, inputs: Mapping[str, object]) -> HarnessAsset:
        if asset.input_fingerprint != input_fingerprint(inputs):
            raise ValueError("next_harness.input_fingerprint_mismatch")
        if asset.state != "proposed":
            raise ValueError("next_harness.proposal_state_invalid")
        with self._mutex:
            if asset.identity.artifact_id in self._assets:
                raise ValueError("next_harness.asset_id_duplicate")
            self._assets[asset.identity.artifact_id] = asset
        return asset

    def accept(self, *, asset_id: str, reviewer_id: str) -> HarnessAsset:
        with self._mutex:
            asset = self._require(asset_id)
            if asset.state != "proposed":
                raise ValueError("next_harness.asset_not_proposed")
            accepted = asset.model_copy(
                update={"state": "accepted", "reviewed_by": reviewer_id}, deep=True
            )
            self._assets[asset_id] = accepted
            return accepted

    def get(self, asset_id: str) -> HarnessAsset:
        with self._mutex:
            return self._require(asset_id).model_copy(deep=True)

    def _require(self, asset_id: str) -> HarnessAsset:
        try:
            return self._assets[asset_id]
        except KeyError as error:
            raise ValueError("next_harness.asset_not_found") from error


def input_fingerprint(inputs: Mapping[str, object]) -> str:
    """Use only scalar test inputs and retain only a one-way fingerprint in assets/reports."""

    canonical_inputs: dict[str, str | int | float | bool] = {}
    for key, value in inputs.items():
        if not isinstance(key, str) or not key:
            raise ValueError("next_harness.input_key_invalid")
        if not isinstance(value, (str, int, float, bool)):
            raise ValueError("next_harness.input_value_unsupported")
        canonical_inputs[key] = value
    payload = json.dumps(
        canonical_inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
