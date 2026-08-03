"""Execute accepted harness assets through S3's independent replay boundary."""

from __future__ import annotations

from time import perf_counter
import secrets
from typing import Mapping

from pydantic import Field, model_validator

from ..contracts.identity import ArtifactIdentity
from ..contracts.models import Identifier, StrictModel
from ..skill_build import CompiledSkill, IndependentSkillReplayer
from .contracts import FailureClass, QualityStage
from .harness_assets import HarnessAsset, input_fingerprint


class HarnessRunReport(StrictModel):
    report_id: Identifier
    correlation_id: Identifier
    asset: ArtifactIdentity
    skill_artifact: ArtifactIdentity
    skill_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: str
    stage: QualityStage
    failure_class: FailureClass | None = None
    replay_id: Identifier | None = None
    duration_ms: int = Field(ge=0)
    observed_cost_units: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_result(self) -> "HarnessRunReport":
        if self.status == "succeeded":
            if self.failure_class is not None:
                raise ValueError("next_harness.success_has_failure")
        elif self.status == "failed":
            if self.failure_class is None:
                raise ValueError("next_harness.failure_class_required")
        else:
            raise ValueError("next_harness.status_invalid")
        return self


class QualityHarness:
    def __init__(self, *, replayer: IndependentSkillReplayer) -> None:
        self._replayer = replayer

    async def run(
        self,
        *,
        asset: HarnessAsset,
        skill_artifact: ArtifactIdentity,
        skill: CompiledSkill,
        owner_id: str,
        inputs: Mapping[str, object],
        correlation_id: str,
        observed_cost_units: float | None = None,
    ) -> HarnessRunReport:
        started = perf_counter()
        validation_failure = _validate_run_input(asset, skill_artifact, skill, inputs)
        if validation_failure is not None:
            return _report(
                asset=asset,
                correlation_id=correlation_id,
                duration_ms=_duration_ms(started),
                stage=QualityStage.QUALITY,
                failure_class=validation_failure,
                observed_cost_units=observed_cost_units,
            )

        result = await self._replayer.replay(
            skill=skill, owner_id=owner_id, inputs=inputs
        )
        duration_ms = _duration_ms(started)
        if result.status == asset.expected_replay_status:
            return HarnessRunReport(
                report_id="qrr_" + secrets.token_hex(12),
                correlation_id=correlation_id,
                asset=asset.identity,
                skill_artifact=skill_artifact,
                skill_source_hash=skill.source_hash,
                input_fingerprint=asset.input_fingerprint,
                status="succeeded",
                stage=QualityStage.REPLAY,
                replay_id=result.replay_id,
                duration_ms=duration_ms,
                observed_cost_units=observed_cost_units,
            )
        failure_class = (
            FailureClass.REPLAY_CLEANUP_FAILED
            if result.error_code == "next_skill_replay.cleanup_failed"
            else FailureClass.OUTCOME_ASSERTION_FAILED
            if result.error_code == "next_skill_replay.outcome_assertion_failed"
            else FailureClass.REPLAY_EXECUTION_FAILED
        )
        return HarnessRunReport(
            report_id="qrr_" + secrets.token_hex(12),
            correlation_id=correlation_id,
            asset=asset.identity,
            skill_artifact=skill_artifact,
            skill_source_hash=skill.source_hash,
            input_fingerprint=asset.input_fingerprint,
            status="failed",
            stage=QualityStage.REPLAY,
            failure_class=failure_class,
            replay_id=result.replay_id,
            duration_ms=duration_ms,
            observed_cost_units=observed_cost_units,
        )


def _validate_run_input(
    asset: HarnessAsset,
    skill_artifact: ArtifactIdentity,
    skill: CompiledSkill,
    inputs: Mapping[str, object],
) -> FailureClass | None:
    if asset.state != "accepted":
        return FailureClass.QUALITY_CONTRACT_VIOLATION
    if asset.skill_artifact != skill_artifact:
        return FailureClass.QUALITY_CONTRACT_VIOLATION
    if skill_artifact.artifact_id != skill.skill_id:
        return FailureClass.QUALITY_CONTRACT_VIOLATION
    if asset.skill_source_hash != skill.source_hash:
        return FailureClass.QUALITY_CONTRACT_VIOLATION
    if asset.input_fingerprint != input_fingerprint(inputs):
        return FailureClass.QUALITY_CONTRACT_VIOLATION
    return None


def _report(
    *,
    asset: HarnessAsset,
    correlation_id: str,
    duration_ms: int,
    stage: QualityStage,
    failure_class: FailureClass,
    observed_cost_units: float | None,
) -> HarnessRunReport:
    return HarnessRunReport(
        report_id="qrr_" + secrets.token_hex(12),
        correlation_id=correlation_id,
        asset=asset.identity,
        skill_artifact=asset.skill_artifact,
        skill_source_hash=asset.skill_source_hash,
        input_fingerprint=asset.input_fingerprint,
        status="failed",
        stage=stage,
        failure_class=failure_class,
        duration_ms=duration_ms,
        observed_cost_units=observed_cost_units,
    )


def _duration_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1_000))
