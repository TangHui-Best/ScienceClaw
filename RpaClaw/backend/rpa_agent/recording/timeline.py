"""Creation-state store for the vNext two-item recording timeline."""

from __future__ import annotations

from threading import RLock

from ..contracts.identity import RPA_AGENT_NEXT_NAMESPACE
from ..contracts.models import CoreTrace, CoreTraceDraft, ObservedEffectEnvelope
from ..contracts.validators import validate_trace

from .contracts import AIInstructionStep, RecordingTimeline


class RecordingTimelineStore:
    def __init__(self, *, session_id: str) -> None:
        self._session_id = session_id
        self._items: list[CoreTrace | AIInstructionStep] = []
        self._drafts: dict[str, CoreTraceDraft] = {}
        self._orphan_effects: dict[str, ObservedEffectEnvelope] = {}
        self._mutex = RLock()

    def begin_draft(self, draft: CoreTraceDraft) -> int:
        with self._mutex:
            self._assert_id_available(draft.draft_id)
            self._drafts[draft.draft_id] = draft.model_copy(deep=True)
            return len(self._items) + 1

    def invalidate_draft(self, *, draft_id: str, diagnostic_code: str) -> CoreTraceDraft:
        with self._mutex:
            draft = self._drafts.get(draft_id)
            if draft is None:
                raise ValueError("next_timeline.draft_unknown")
            updated = draft.model_copy(
                update={
                    "capture_state": "invalid",
                    "diagnostic_codes": [*draft.diagnostic_codes, diagnostic_code],
                },
                deep=True,
            )
            self._drafts[draft_id] = updated
            return updated.model_copy(deep=True)

    def mark_draft_enriching(self, *, draft_id: str, diagnostic_code: str) -> CoreTraceDraft:
        with self._mutex:
            draft = self._drafts.get(draft_id)
            if draft is None:
                raise ValueError("next_timeline.draft_unknown")
            updated = draft.model_copy(
                update={
                    "capture_state": "enriching",
                    "diagnostic_codes": [*draft.diagnostic_codes, diagnostic_code],
                },
                deep=True,
            )
            self._drafts[draft_id] = updated
            return updated.model_copy(deep=True)

    def finalize_draft(self, *, draft_id: str, trace: CoreTrace) -> int:
        validate_trace(trace)
        with self._mutex:
            if draft_id not in self._drafts:
                raise ValueError("next_timeline.draft_unknown")
            self._assert_id_available(trace.trace_id)
            self._drafts.pop(draft_id)
            self._items.append(trace.model_copy(deep=True))
            return len(self._items)

    def append_ai(self, step: AIInstructionStep) -> int:
        with self._mutex:
            self._assert_id_available(step.step_id)
            self._items.append(step.model_copy(deep=True))
            return len(self._items)

    def replace_ai(self, step: AIInstructionStep) -> None:
        with self._mutex:
            for index, item in enumerate(self._items):
                if isinstance(item, AIInstructionStep) and item.step_id == step.step_id:
                    self._items[index] = step.model_copy(deep=True)
                    return
        raise ValueError("next_timeline.ai_step_unknown")

    def add_orphan_effect(self, effect: ObservedEffectEnvelope) -> None:
        with self._mutex:
            if effect.session_id != self._session_id:
                raise ValueError("next_timeline.orphan_effect_session_mismatch")
            if effect.effect_id in self._orphan_effects:
                raise ValueError("next_timeline.orphan_effect_duplicate")
            self._orphan_effects[effect.effect_id] = effect.model_copy(deep=True)

    def projection_items(self) -> tuple[CoreTraceDraft | CoreTrace | AIInstructionStep, ...]:
        with self._mutex:
            return (
                *(draft.model_copy(deep=True) for draft in self._drafts.values()),
                *(item.model_copy(deep=True) for item in self._items),
            )

    def item(self, step_id: str) -> AIInstructionStep:
        with self._mutex:
            for item in self._items:
                if isinstance(item, AIInstructionStep) and item.step_id == step_id:
                    return item.model_copy(deep=True)
        raise ValueError("next_timeline.ai_step_unknown")

    def snapshot(self) -> RecordingTimeline:
        with self._mutex:
            return RecordingTimeline(
                schema_namespace=RPA_AGENT_NEXT_NAMESPACE,
                session_id=self._session_id,
                items=[item.model_copy(deep=True) for item in self._items],
                orphan_effects={
                    key: effect.model_copy(deep=True)
                    for key, effect in self._orphan_effects.items()
                },
            )

    def _assert_id_available(self, item_id: str) -> None:
        if item_id in self._drafts or any(
            getattr(item, "trace_id", None) == item_id
            or getattr(item, "step_id", None) == item_id
            for item in self._items
        ):
            raise ValueError("next_timeline.item_id_duplicate")
