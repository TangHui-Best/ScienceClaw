"""创建期用户时间线与旧 CoreTrace 兼容存储。"""

from __future__ import annotations

from threading import RLock

from pydantic import BaseModel

from ..contracts.models import (
    AIInstructionStep,
    AcceptedSettlement,
    CoreTrace,
    CoreTraceDraft,
    CoreTraceTimeline,
    RecordingTimeline,
)
from ..contracts.validators import validate_trace


class TimelineStore:
    def __init__(self) -> None:
        self._traces: dict[str, CoreTrace] = {}
        self._sequence_ids: dict[int, str] = {}
        self._mutex = RLock()

    def append(self, settlement: AcceptedSettlement) -> bool:
        if not isinstance(settlement, AcceptedSettlement):
            raise ValueError("timeline_store.accepted_required")
        source_trace = settlement.core_trace
        payload = (
            source_trace.model_dump(
                mode="python", exclude_unset=True, warnings=False
            )
            if isinstance(source_trace, BaseModel)
            else source_trace
        )
        trace = CoreTrace.model_validate(payload)
        validate_trace(trace)
        trace = CoreTrace.model_validate(
            trace.model_dump(mode="python", exclude_unset=True)
        )
        with self._mutex:
            existing = self._traces.get(trace.trace_id)
            if existing is not None:
                if existing != trace:
                    raise ValueError(f"timeline_store.trace_id_conflict:{trace.trace_id}")
                return False
            existing_id = self._sequence_ids.get(trace.sequence)
            if existing_id is not None:
                raise ValueError(
                    f"timeline_store.sequence_conflict:{trace.sequence}:{existing_id}:{trace.trace_id}"
                )
            self._traces[trace.trace_id] = trace
            self._sequence_ids[trace.sequence] = trace.trace_id
            return True

    def timeline(self) -> CoreTraceTimeline:
        with self._mutex:
            traces = [
                trace.model_dump(mode="python", exclude_unset=True)
                for trace in sorted(
                    self._traces.values(), key=lambda item: item.sequence
                )
            ]
        return CoreTraceTimeline.model_validate({
            "schema_version": "core-trace/v0.1",
            "traces": traces,
        })


class RecordingTimelineStore:
    """F028 唯一顶层顺序存储；观察 Trace 永不提升为顶层步骤。"""

    def __init__(self, *, session_id: str) -> None:
        self._session_id = session_id
        self._items: list[CoreTraceDraft | CoreTrace | AIInstructionStep] = []
        self._observed_traces: dict[str, CoreTrace] = {}
        self._orphan_effects: dict[str, object] = {}
        self._mutex = RLock()

    def append_ai(self, step: AIInstructionStep) -> int:
        with self._mutex:
            if any(
                getattr(item, "step_id", None) == step.step_id
                or getattr(item, "trace_id", None) == step.step_id
                for item in self._items
            ):
                raise ValueError(f"recording_timeline.item_id_duplicate:{step.step_id}")
            self._items.append(step.model_copy(deep=True))
            return len(self._items)

    def replace_ai(self, step: AIInstructionStep) -> None:
        with self._mutex:
            matches = [
                index
                for index, item in enumerate(self._items)
                if isinstance(item, AIInstructionStep) and item.step_id == step.step_id
            ]
            if len(matches) != 1:
                raise ValueError(f"recording_timeline.ai_step_unknown:{step.step_id}")
            self._items[matches[0]] = step.model_copy(deep=True)

    def append_manual(self, trace: CoreTrace) -> int:
        with self._mutex:
            if trace.trace_id in self._observed_traces or any(
                getattr(item, "trace_id", None) == trace.trace_id
                or getattr(item, "step_id", None) == trace.trace_id
                for item in self._items
            ):
                raise ValueError(f"recording_timeline.trace_id_duplicate:{trace.trace_id}")
            self._items.append(trace.model_copy(deep=True))
            return len(self._items)

    def append_draft(self, draft: CoreTraceDraft) -> int:
        with self._mutex:
            if any(
                getattr(item, "draft_id", None) == draft.draft_id
                or getattr(item, "trace_id", None) == draft.draft_id
                or getattr(item, "step_id", None) == draft.draft_id
                for item in self._items
            ):
                raise ValueError(f"recording_timeline.item_id_duplicate:{draft.draft_id}")
            self._items.append(draft.model_copy(deep=True))
            return len(self._items)

    def finalize_draft(self, *, draft_id: str, trace: CoreTrace) -> int:
        with self._mutex:
            matches = [
                index
                for index, item in enumerate(self._items)
                if isinstance(item, CoreTraceDraft) and item.draft_id == draft_id
            ]
            if len(matches) != 1:
                raise ValueError(f"recording_timeline.draft_unknown:{draft_id}")
            if trace.trace_id in self._observed_traces or any(
                getattr(item, "trace_id", None) == trace.trace_id
                for item in self._items
            ):
                raise ValueError(f"recording_timeline.trace_id_duplicate:{trace.trace_id}")
            self._items[matches[0]] = trace.model_copy(deep=True)
            return matches[0] + 1

    def invalidate_draft(self, *, draft_id: str, diagnostic_code: str) -> None:
        with self._mutex:
            draft = next(
                (
                    item
                    for item in self._items
                    if isinstance(item, CoreTraceDraft) and item.draft_id == draft_id
                ),
                None,
            )
            if draft is None:
                return
            index = self._items.index(draft)
            self._items[index] = draft.model_copy(
                update={
                    "capture_state": "invalid",
                    "diagnostic_codes": [*draft.diagnostic_codes, diagnostic_code],
                },
                deep=True,
            )

    def discard_draft(self, *, draft_id: str) -> None:
        with self._mutex:
            self._items = [
                item
                for item in self._items
                if not (isinstance(item, CoreTraceDraft) and item.draft_id == draft_id)
            ]

    def projection_items(self) -> tuple[CoreTraceDraft | CoreTrace | AIInstructionStep, ...]:
        with self._mutex:
            return tuple(item.model_copy(deep=True) for item in self._items)

    def projection_state(
        self,
    ) -> tuple[
        tuple[CoreTraceDraft | CoreTrace | AIInstructionStep, ...],
        dict[str, CoreTrace],
    ]:
        with self._mutex:
            return (
                tuple(item.model_copy(deep=True) for item in self._items),
                {
                    key: trace.model_copy(deep=True)
                    for key, trace in self._observed_traces.items()
                },
            )

    def attach_observation(self, *, step_id: str, trace: CoreTrace) -> None:
        with self._mutex:
            if trace.trace_id in self._observed_traces or any(
                getattr(item, "trace_id", None) == trace.trace_id
                for item in self._items
            ):
                raise ValueError(
                    f"recording_timeline.observation_trace_duplicate:{trace.trace_id}"
                )
            step = next(
                (
                    item
                    for item in self._items
                    if isinstance(item, AIInstructionStep) and item.step_id == step_id
                ),
                None,
            )
            if step is None:
                raise ValueError(f"recording_timeline.ai_step_unknown:{step_id}")
            self._observed_traces[trace.trace_id] = trace.model_copy(deep=True)
            refs = [*step.observation_trace_refs, trace.trace_id]
            attempts = [attempt.model_copy(deep=True) for attempt in step.execution.attempts]
            if step.execution.selected_attempt_id is not None:
                attempts = [
                    attempt.model_copy(
                        update={"observation_trace_refs": refs}, deep=True
                    )
                    if attempt.attempt_id == step.execution.selected_attempt_id
                    else attempt
                    for attempt in attempts
                ]
            execution = step.execution.model_copy(update={"attempts": attempts}, deep=True)
            self._items[self._items.index(step)] = step.model_copy(
                update={"observation_trace_refs": refs, "execution": execution},
                deep=True,
            )

    def item(self, item_id: str) -> CoreTrace | AIInstructionStep:
        with self._mutex:
            for item in self._items:
                if getattr(item, "trace_id", None) == item_id or getattr(
                    item, "step_id", None
                ) == item_id:
                    return item.model_copy(deep=True)
        raise KeyError(f"recording_timeline.item_unknown:{item_id}")

    def snapshot(self) -> RecordingTimeline:
        with self._mutex:
            incomplete = [
                item.draft_id for item in self._items if isinstance(item, CoreTraceDraft)
            ]
            if incomplete:
                raise ValueError(
                    "recording_timeline.drafts_incomplete:" + ",".join(incomplete)
                )
            items = [
                item.model_dump(mode="python", exclude_none=True)
                for item in self._items
            ]
            observed = {
                key: trace.model_dump(mode="python", exclude_none=True)
                for key, trace in self._observed_traces.items()
            }
            orphan_effects = dict(self._orphan_effects)
        return RecordingTimeline.model_validate(
            {
                "schema_version": "recording-timeline/v0.1",
                "session_id": self._session_id,
                "items": items,
                "observed_traces": observed,
                "orphan_effects": orphan_effects,
            }
        )
