"""vNext recording contracts: only proven manual facts and AI intent are timeline items."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from ..contracts.identity import RPA_AGENT_NEXT_NAMESPACE
from ..contracts.models import (
    CoreTrace,
    Identifier,
    ObservedEffectEnvelope,
    OutputDefinition,
    StrictModel,
)


class AIExecutionAttempt(StrictModel):
    attempt_id: Identifier
    model_ref: str = Field(min_length=1, max_length=256)
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _validate_shape(self) -> "AIExecutionAttempt":
        if self.status == "queued":
            if self.started_at is not None or self.finished_at is not None:
                raise ValueError("next_ai.attempt_queued_shape")
        elif self.status == "running":
            if self.started_at is None or self.finished_at is not None:
                raise ValueError("next_ai.attempt_running_shape")
        elif self.status == "succeeded":
            if self.started_at is None or self.finished_at is None or self.error_code is not None:
                raise ValueError("next_ai.attempt_succeeded_shape")
        elif self.started_at is None or self.finished_at is None or self.error_code is None:
            raise ValueError("next_ai.attempt_terminal_shape")
        return self


class AIExecutionState(StrictModel):
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_summary: str | None = Field(default=None, max_length=2_000)
    error_code: str | None = Field(default=None, min_length=1, max_length=128)
    error_message: str | None = Field(default=None, min_length=1, max_length=2_000)
    selected_attempt_id: Identifier
    attempts: list[AIExecutionAttempt] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_shape(self) -> "AIExecutionState":
        attempts = {attempt.attempt_id: attempt for attempt in self.attempts}
        if len(attempts) != len(self.attempts):
            raise ValueError("next_ai.attempt_ids_unique")
        selected = attempts.get(self.selected_attempt_id)
        if selected is None or selected.status != self.status:
            raise ValueError("next_ai.selected_attempt_invalid")
        if self.status == "queued":
            if self.started_at is not None or self.finished_at is not None:
                raise ValueError("next_ai.execution_queued_shape")
        elif self.status == "running":
            if self.started_at is None or self.finished_at is not None:
                raise ValueError("next_ai.execution_running_shape")
        elif self.status == "succeeded":
            if self.started_at is None or self.finished_at is None or self.error_code is not None:
                raise ValueError("next_ai.execution_succeeded_shape")
        elif (
            self.started_at is None
            or self.finished_at is None
            or self.error_code is None
            or self.error_message is None
        ):
            raise ValueError("next_ai.execution_terminal_shape")
        return self


class AIInstructionStep(StrictModel):
    """A user-visible intent; internal tool history is never a CoreTrace."""

    step_id: Identifier
    instruction: str = Field(min_length=1, max_length=20_000)
    created_at: datetime
    context_snapshot_ref: Identifier
    execution: AIExecutionState
    declared_outputs: list[OutputDefinition] = Field(default_factory=list)
    diagnostic_evidence_refs: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_evidence_refs(self) -> "AIInstructionStep":
        if len(self.diagnostic_evidence_refs) != len(set(self.diagnostic_evidence_refs)):
            raise ValueError("next_ai.diagnostic_evidence_refs_unique")
        return self


RecordingTimelineItem = CoreTrace | AIInstructionStep


class RecordingTimeline(StrictModel):
    """Serializable vNext timeline; CoreTraceDraft is intentionally absent."""

    schema_namespace: Literal[RPA_AGENT_NEXT_NAMESPACE]
    session_id: Identifier
    items: list[RecordingTimelineItem]
    orphan_effects: dict[Identifier, ObservedEffectEnvelope] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_ownership(self) -> "RecordingTimeline":
        item_ids = [
            item.trace_id if isinstance(item, CoreTrace) else item.step_id
            for item in self.items
        ]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("next_timeline.item_ids_unique")
        for effect_id, effect in self.orphan_effects.items():
            if effect_id != effect.effect_id:
                raise ValueError("next_timeline.orphan_effect_key_mismatch")
            if effect.session_id != self.session_id:
                raise ValueError("next_timeline.orphan_effect_session_mismatch")
        return self
