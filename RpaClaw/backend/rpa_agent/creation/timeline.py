"""只长期保留 CoreTrace 的幂等 Timeline Store。"""

from __future__ import annotations

from threading import RLock

from pydantic import BaseModel

from ..contracts.models import AcceptedSettlement, CoreTrace, CoreTraceTimeline
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
