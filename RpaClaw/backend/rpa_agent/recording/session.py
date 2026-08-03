"""Small vNext creation-session state machine, independent from F028 storage."""

from __future__ import annotations

from datetime import datetime

from ..contracts.models import CoreTrace, CoreTraceDraft

from .contracts import AIExecutionAttempt, AIExecutionState, AIInstructionStep, RecordingTimeline
from .timeline import RecordingTimelineStore


class RecordingSession:
    def __init__(self, *, session_id: str) -> None:
        self._timeline = RecordingTimelineStore(session_id=session_id)

    def begin_manual_draft(self, *, draft_id: str) -> tuple[CoreTraceDraft, int]:
        draft = CoreTraceDraft(draft_id=draft_id, capture_state="capturing")
        ordinal = self._timeline.begin_draft(draft)
        return draft, ordinal

    def invalidate_manual_draft(self, *, draft_id: str, diagnostic_code: str) -> CoreTraceDraft:
        return self._timeline.invalidate_draft(
            draft_id=draft_id, diagnostic_code=diagnostic_code
        )

    def mark_manual_draft_enriching(
        self, *, draft_id: str, diagnostic_code: str
    ) -> CoreTraceDraft:
        return self._timeline.mark_draft_enriching(
            draft_id=draft_id, diagnostic_code=diagnostic_code
        )

    def freeze_manual_trace(self, *, draft_id: str, trace: CoreTrace) -> int:
        return self._timeline.finalize_draft(draft_id=draft_id, trace=trace)

    def queue_ai_instruction(
        self,
        *,
        step_id: str,
        instruction: str,
        model_ref: str,
        context_snapshot_ref: str,
        created_at: datetime,
    ) -> tuple[AIInstructionStep, int]:
        attempt = AIExecutionAttempt(
            attempt_id=f"attempt_{step_id}", model_ref=model_ref, status="queued"
        )
        step = AIInstructionStep(
            step_id=step_id,
            instruction=instruction,
            created_at=created_at,
            context_snapshot_ref=context_snapshot_ref,
            execution=AIExecutionState(
                status="queued",
                selected_attempt_id=attempt.attempt_id,
                attempts=[attempt],
            ),
        )
        return step, self._timeline.append_ai(step)

    def mark_ai_running(self, *, step_id: str, started_at: datetime) -> AIInstructionStep:
        step = self._timeline.item(step_id)
        if step.execution.status != "queued":
            raise ValueError("next_recording.ai_step_not_queued")
        updated = self._replace_execution(step, status="running", started_at=started_at)
        self._timeline.replace_ai(updated)
        return updated

    def finish_ai(
        self,
        *,
        step_id: str,
        finished_at: datetime,
        result_summary: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> AIInstructionStep:
        step = self._timeline.item(step_id)
        if step.execution.status != "running":
            raise ValueError("next_recording.ai_step_not_running")
        status = "succeeded" if error_code is None else "failed"
        updated = self._replace_execution(
            step,
            status=status,
            started_at=step.execution.started_at,
            finished_at=finished_at,
            result_summary=result_summary if status == "succeeded" else None,
            error_code=error_code,
            error_message=error_message,
        )
        self._timeline.replace_ai(updated)
        return updated

    def cancel_ai(self, *, step_id: str, finished_at: datetime) -> AIInstructionStep:
        step = self._timeline.item(step_id)
        if step.execution.status not in {"queued", "running"}:
            raise ValueError("next_recording.ai_step_not_cancellable")
        started_at = step.execution.started_at or finished_at
        updated = self._replace_execution(
            step,
            status="cancelled",
            started_at=started_at,
            finished_at=finished_at,
            error_code="ai_execution_cancelled",
            error_message="AI execution was cancelled.",
        )
        self._timeline.replace_ai(updated)
        return updated

    def projection_items(self):
        return self._timeline.projection_items()

    def timeline(self) -> RecordingTimeline:
        return self._timeline.snapshot()

    @staticmethod
    def _replace_execution(
        step: AIInstructionStep,
        *,
        status: str,
        started_at: datetime,
        finished_at: datetime | None = None,
        result_summary: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> AIInstructionStep:
        attempt = step.execution.attempts[0].model_copy(
            update={
                "status": status,
                "started_at": started_at,
                "finished_at": finished_at,
                "error_code": error_code,
            }
        )
        execution = AIExecutionState(
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            result_summary=result_summary,
            error_code=error_code,
            error_message=error_message,
            selected_attempt_id=attempt.attempt_id,
            attempts=[attempt],
        )
        return step.model_copy(update={"execution": execution}, deep=True)
