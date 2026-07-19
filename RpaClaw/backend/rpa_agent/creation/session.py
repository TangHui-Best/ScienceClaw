"""新版 RPA Agent 创建态会话边界与录制值隔离。"""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import json
from pathlib import Path, PureWindowsPath
import re
from threading import RLock
from typing import Any

from ..contracts import (
    AIInstructionStep,
    AcceptedSettlement,
    BrowserScope,
    CoreTrace,
    CoreTraceDraft,
    Diagnostic,
    RecordingTimeline,
    RejectedSettlement,
    TraceCandidate,
)
from .browser_facts import BrowserFactObserver, FactBuffer
from .candidate_registry import ActiveCandidateRegistry, CandidateReservation
from .manual_aggregator import ManualEvent, ManualInteractionAggregator
from .page_registry import PageRegistry
from .projection import CreationStepRow, project_creation_steps
from .readiness import BuildReadiness, derive_build_readiness
from .settlement import SettlementAttempt, SettlementEngine, SettlementOutcome
from .timeline import RecordingTimelineStore, TimelineStore


_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,127}$")


class ControlMode(Enum):
    HUMAN = "human"
    AGENT = "agent"


@dataclass(frozen=True, slots=True, eq=False)
class AgentCandidateReservation:
    candidate_id: str
    ordinal: int
    reservation_id: int


class SessionVariableStore:
    """一次创建会话内的 JSON 工作值；不承担 Secret/DataAsset 存储。"""

    def __init__(self, *, session_id: str) -> None:
        if _IDENTIFIER.fullmatch(session_id) is None:
            raise ValueError("session_variable_store.session_id_invalid")
        self._session_id = session_id
        self._values: dict[str, Any] = {}
        self._producers: dict[str, str] = {}
        self._mutex = RLock()

    @property
    def session_id(self) -> str:
        return self._session_id

    def write(self, ref: str, value: Any, *, producer_candidate_id: str) -> None:
        with self._mutex:
            values, producers = self._prepare_writes_locked(
                {ref: value},
                producer_candidate_id=producer_candidate_id,
            )
            self._values = values
            self._producers = producers

    def write_many(
        self, writes: Mapping[str, Any], *, producer_candidate_id: str
    ) -> None:
        with self._mutex:
            values, producers = self._prepare_writes_locked(
                writes, producer_candidate_id=producer_candidate_id
            )
            self._values = values
            self._producers = producers

    def _prepare_writes_locked(
        self,
        writes: Mapping[str, Any],
        *,
        producer_candidate_id: str,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """在持有 Store 锁时构造批量写副本；失败绝不改变现有值。"""

        self._validate_producer(producer_candidate_id)
        values = deepcopy(self._values)
        producers = dict(self._producers)
        for ref, value in writes.items():
            parts = self._validate_ref(ref)
            copied = self._copy_json(value)
            if len(parts) == 1:
                values[parts[0]] = copied
            else:
                root = values.setdefault(parts[0], {})
                if not isinstance(root, dict):
                    raise ValueError("session_variable_store.path_conflict")
                cursor = root
                for part in parts[1:-1]:
                    child = cursor.setdefault(part, {})
                    if not isinstance(child, dict):
                        raise ValueError("session_variable_store.path_conflict")
                    cursor = child
                cursor[parts[-1]] = copied
            for known_ref in tuple(producers):
                if known_ref == ref or known_ref.startswith(ref + "."):
                    del producers[known_ref]
            producers[ref] = producer_candidate_id
        return values, producers

    def read(self, ref: str) -> Any:
        parts = self._validate_ref(ref)
        with self._mutex:
            try:
                value: Any = self._values[parts[0]]
                for part in parts[1:]:
                    if not isinstance(value, dict):
                        raise KeyError(part)
                    value = value[part]
            except KeyError as exc:
                raise KeyError(f"session_variable_store.ref_missing:{ref}") from exc
            return deepcopy(value)

    def producer_for(self, ref: str) -> str:
        parts = self._validate_ref(ref)
        with self._mutex:
            try:
                value: Any = self._values[parts[0]]
                for part in parts[1:]:
                    if not isinstance(value, dict):
                        raise KeyError(part)
                    value = value[part]
            except KeyError as exc:
                raise KeyError(
                    f"session_variable_store.producer_missing:{ref}"
                ) from exc
            matches = [
                (known_ref, producer)
                for known_ref, producer in self._producers.items()
                if ref == known_ref or ref.startswith(known_ref + ".")
            ]
            if not matches:
                raise KeyError(f"session_variable_store.producer_missing:{ref}")
            return max(matches, key=lambda item: len(item[0]))[1]

    def snapshot(self) -> dict[str, Any]:
        with self._mutex:
            return deepcopy(self._values)

    def write_secret(
        self, ref: str, plaintext: str, *, producer_candidate_id: str
    ) -> None:
        del ref, plaintext, producer_candidate_id
        raise ValueError("session_variable_store.secret_plaintext_forbidden")

    def write_data_asset(
        self, ref: str, location: str, *, producer_candidate_id: str
    ) -> None:
        del ref, producer_candidate_id
        if Path(location).is_absolute() or PureWindowsPath(location).is_absolute():
            raise ValueError("session_variable_store.local_asset_path_forbidden")
        raise ValueError("session_variable_store.data_asset_namespace_forbidden")

    def clear(self) -> None:
        with self._mutex:
            self._values.clear()
            self._producers.clear()

    @staticmethod
    def _validate_ref(ref: str) -> tuple[str, ...]:
        if not isinstance(ref, str):
            raise ValueError("session_variable_store.ref_invalid")
        parts = tuple(ref.split("."))
        if (
            not parts
            or any(not part or part.isspace() or any(char.isspace() for char in part) for part in parts)
            or any(part.isdigit() for part in parts)
        ):
            raise ValueError("session_variable_store.ref_invalid")
        return parts

    @staticmethod
    def _validate_producer(candidate_id: str) -> None:
        if not isinstance(candidate_id, str) or _IDENTIFIER.fullmatch(candidate_id) is None:
            raise ValueError("session_variable_store.producer_invalid")

    @staticmethod
    def _copy_json(value: Any) -> Any:
        try:
            payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
            return json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("session_variable_store.value_not_json") from exc


class SkillCreationSession:
    """串行协调人工聚合与事实观察的单次 Skill 创建会话。"""

    def __init__(
        self,
        *,
        session_id: str,
        main_runtime_ref: str,
        fact_buffer_capacity: int,
        fact_ttl: timedelta,
    ) -> None:
        if _IDENTIFIER.fullmatch(session_id) is None:
            raise ValueError("creation_session.session_id_invalid")
        self.session_id = session_id
        self.registry = ActiveCandidateRegistry()
        self.fact_buffer = FactBuffer(capacity=fact_buffer_capacity, ttl=fact_ttl)
        self.observer = BrowserFactObserver(self.registry, self.fact_buffer)
        self.pages = PageRegistry(main_runtime_ref=main_runtime_ref)
        self._settlement_engine = SettlementEngine(self.pages)
        self.timeline_store = TimelineStore()
        self.recording_timeline_store = RecordingTimelineStore(session_id=session_id)
        self.variables = SessionVariableStore(session_id=session_id)
        self._tail_ttl = fact_ttl
        self._next_ordinal = 1
        self._allocated_ordinals: set[int] = set()
        self._aggregator = ManualInteractionAggregator(
            registry=self.registry,
            allocate_ordinal=self._allocate_ordinal,
        )
        self._control_mode = ControlMode.HUMAN
        self._closed = False
        self._candidates: dict[str, TraceCandidate] = {}
        self._attempts: dict[str, SettlementAttempt] = {}
        self._accepted_traces: dict[str, CoreTrace] = {}
        self._diagnostics: dict[str, Diagnostic] = {}
        self._deleted_candidate_ids: set[str] = set()
        self._reservations: dict[int, CandidateReservation] = {}
        self._finished_manual_window_ids: set[int] = set()
        self._agent_reservations: dict[int, AgentCandidateReservation] = {}
        self._agent_causal_windows: dict[int, CandidateReservation] = {}
        self._consumed_agent_reservation_ids: set[int] = set()
        self._next_agent_reservation_id = 1
        self._mutex = RLock()

    @property
    def control_mode(self) -> ControlMode:
        with self._mutex:
            return self._control_mode

    @property
    def closed(self) -> bool:
        with self._mutex:
            return self._closed

    @property
    def candidates(self) -> dict[str, TraceCandidate]:
        with self._mutex:
            return {
                candidate_id: candidate.model_copy(deep=True)
                for candidate_id, candidate in self._candidates.items()
            }

    @property
    def accepted_traces(self) -> dict[str, CoreTrace]:
        with self._mutex:
            return {
                candidate_id: trace.model_copy(deep=True)
                for candidate_id, trace in self._accepted_traces.items()
            }

    @property
    def diagnostics(self) -> dict[str, Diagnostic]:
        with self._mutex:
            return {
                candidate_id: diagnostic.model_copy(deep=True)
                for candidate_id, diagnostic in self._diagnostics.items()
            }

    @property
    def settlement_attempts(self) -> dict[str, SettlementAttempt]:
        with self._mutex:
            return dict(self._attempts)

    def queue_ai_instruction(
        self,
        *,
        step_id: str,
        instruction: str,
        model_ref: str,
        context_snapshot_ref: str,
        created_at: datetime,
        declared_outputs: tuple[object, ...] = (),
        expected_effects: tuple[object, ...] = (),
    ) -> tuple[AIInstructionStep, int]:
        """原子写入 Intent；Browser-use 尚未启动时步骤已经可见。"""

        attempt_id = "attempt_" + step_id
        step = AIInstructionStep.model_validate(
            {
                "step_id": step_id,
                "instruction": instruction,
                "created_at": created_at,
                "execution": {
                    "status": "queued",
                    "selected_attempt_id": attempt_id,
                    "attempts": [
                        {
                            "attempt_id": attempt_id,
                            "model_ref": model_ref,
                            "status": "queued",
                        }
                    ],
                },
                "context_snapshot_ref": context_snapshot_ref,
                "declared_outputs": list(declared_outputs),
                "expected_effects": list(expected_effects),
            }
        )
        with self._mutex:
            self._require_open()
            ordinal = self.recording_timeline_store.append_ai(step)
        return step.model_copy(deep=True), ordinal

    def mark_ai_instruction_running(
        self, step_id: str, *, started_at: datetime
    ) -> AIInstructionStep:
        with self._mutex:
            self._require_open()
            step = self.recording_timeline_store.item(step_id)
            if not isinstance(step, AIInstructionStep):
                raise ValueError(f"creation_session.ai_step_unknown:{step_id}")
            if step.execution.status != "queued":
                raise ValueError(f"creation_session.ai_step_not_queued:{step_id}")
            attempts = [
                attempt.model_dump(mode="python", exclude_none=True)
                for attempt in step.execution.attempts
            ]
            for attempt in attempts:
                if attempt["attempt_id"] == step.execution.selected_attempt_id:
                    attempt.update({"status": "running", "started_at": started_at})
            payload = step.model_dump(mode="python", exclude_none=True)
            payload["execution"] = {
                "status": "running",
                "started_at": started_at,
                "selected_attempt_id": step.execution.selected_attempt_id,
                "attempts": attempts,
            }
            updated = AIInstructionStep.model_validate(payload)
            self.recording_timeline_store.replace_ai(updated)
            return updated.model_copy(deep=True)

    def finish_ai_instruction(
        self,
        step_id: str,
        *,
        finished_at: datetime,
        succeeded: bool,
        result_summary: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> AIInstructionStep:
        with self._mutex:
            self._require_open()
            step = self.recording_timeline_store.item(step_id)
            if not isinstance(step, AIInstructionStep):
                raise ValueError(f"creation_session.ai_step_unknown:{step_id}")
            if step.execution.status != "running":
                raise ValueError(f"creation_session.ai_step_not_running:{step_id}")
            status = "succeeded" if succeeded else "failed"
            attempts = [
                attempt.model_dump(mode="python", exclude_none=True)
                for attempt in step.execution.attempts
            ]
            for attempt in attempts:
                if attempt["attempt_id"] == step.execution.selected_attempt_id:
                    attempt.update({"status": status, "finished_at": finished_at})
                    if not succeeded:
                        attempt["error_code"] = error_code or "agent_execution_failed"
            payload = step.model_dump(mode="python", exclude_none=True)
            execution: dict[str, object] = {
                "status": status,
                "started_at": step.execution.started_at,
                "finished_at": finished_at,
                "selected_attempt_id": step.execution.selected_attempt_id,
                "attempts": attempts,
            }
            if succeeded:
                execution["result_summary"] = result_summary
            else:
                execution["error_code"] = error_code or "agent_execution_failed"
                execution["error_message"] = error_message or "Agent execution failed."
            payload["execution"] = execution
            updated = AIInstructionStep.model_validate(payload)
            self.recording_timeline_store.replace_ai(updated)
            return updated.model_copy(deep=True)

    def cancel_ai_instruction(
        self, step_id: str, *, finished_at: datetime
    ) -> AIInstructionStep:
        with self._mutex:
            self._require_open()
            step = self.recording_timeline_store.item(step_id)
            if not isinstance(step, AIInstructionStep):
                raise ValueError(f"creation_session.ai_step_unknown:{step_id}")
            if step.execution.status not in {"queued", "running"}:
                raise ValueError(f"creation_session.ai_step_not_cancellable:{step_id}")
            started_at = step.execution.started_at or finished_at
            attempts = [
                attempt.model_dump(mode="python", exclude_none=True)
                for attempt in step.execution.attempts
            ]
            for attempt in attempts:
                if attempt["attempt_id"] == step.execution.selected_attempt_id:
                    attempt.update(
                        {
                            "status": "cancelled",
                            "started_at": attempt.get("started_at", started_at),
                            "finished_at": finished_at,
                            "error_code": "agent_execution_cancelled",
                        }
                    )
            payload = step.model_dump(mode="python", exclude_none=True)
            payload["execution"] = {
                "status": "cancelled",
                "started_at": started_at,
                "finished_at": finished_at,
                "error_code": "agent_execution_cancelled",
                "error_message": "Agent execution was cancelled.",
                "selected_attempt_id": step.execution.selected_attempt_id,
                "attempts": attempts,
            }
            updated = AIInstructionStep.model_validate(payload)
            self.recording_timeline_store.replace_ai(updated)
            return updated.model_copy(deep=True)

    def recording_timeline(self) -> RecordingTimeline:
        with self._mutex:
            self._require_open()
            return self.recording_timeline_store.snapshot()

    def begin_manual_draft(self, *, draft_id: str) -> tuple[CoreTraceDraft, int]:
        draft = CoreTraceDraft(
            draft_id=draft_id,
            capture_state="capturing",
        )
        with self._mutex:
            self._require_open()
            ordinal = self.recording_timeline_store.append_draft(draft)
        return draft.model_copy(deep=True), ordinal

    def fail_manual_draft(self, *, draft_id: str, diagnostic_code: str) -> None:
        with self._mutex:
            self._require_open()
            self.recording_timeline_store.invalidate_draft(
                draft_id=draft_id, diagnostic_code=diagnostic_code
            )

    def complete_manual_navigation(
        self,
        *,
        draft_id: str,
        trace_id: str,
        ordinal: int,
        page_ref: str,
        url: str,
    ) -> CoreTrace:
        trace = CoreTrace.model_validate(
            {
                "trace_id": trace_id,
                "sequence": ordinal,
                "scope": {"page_ref": page_ref, "frame_path": []},
                "action": {"kind": "navigate", "mode": "url"},
                "data_bindings": [
                    {
                        "name": "url",
                        "direction": "input",
                        "kind": "literal",
                        "value": url,
                        "sensitive": False,
                    }
                ],
                # Navigation is intrinsic to a navigate action.  Emitting a
                # second navigation effect violates the formal CoreTrace
                # invariant and makes an otherwise valid recording impossible
                # to compile.
                "effects": [],
            }
        )
        with self._mutex:
            self._require_open()
            self.recording_timeline_store.finalize_draft(
                draft_id=draft_id, trace=trace
            )
        return trace

    def discard_manual_draft(self, *, draft_id: str) -> None:
        with self._mutex:
            self._require_open()
            self.recording_timeline_store.discard_draft(draft_id=draft_id)

    def recording_projection_items(
        self,
    ) -> tuple[CoreTraceDraft | CoreTrace | AIInstructionStep, ...]:
        with self._mutex:
            self._require_open()
            return self.recording_timeline_store.projection_items()

    def recording_projection_state(self):
        with self._mutex:
            self._require_open()
            return self.recording_timeline_store.projection_state()

    def attach_ai_observation(self, *, step_id: str, trace: CoreTrace) -> None:
        with self._mutex:
            self._require_open()
            self.recording_timeline_store.attach_observation(
                step_id=step_id, trace=trace
            )

    @property
    def reservation_count(self) -> int:
        with self._mutex:
            return len(self._reservations)

    @property
    def outstanding_agent_reservation_count(self) -> int:
        with self._mutex:
            return len(self._agent_reservations)

    def reserve_manual(
        self,
        *,
        candidate_id: str,
        page_runtime_ref: str,
        frame_runtime_ref: str,
    ) -> CandidateReservation:
        with self._mutex:
            self._require_open()
            if self._control_mode is not ControlMode.HUMAN:
                raise ValueError("creation_session.manual_control_inactive")
            if candidate_id in self._candidates:
                raise ValueError(
                    f"creation_session.candidate_id_duplicate:{candidate_id}"
                )
            reservation = self.registry.reserve(
                candidate_id=candidate_id,
                page_runtime_ref=page_runtime_ref,
                frame_runtime_ref=frame_runtime_ref,
            )
            self._reservations[reservation.window_id] = reservation
            return reservation

    def ingest_manual(
        self, reservation: CandidateReservation, event: ManualEvent
    ) -> tuple[TraceCandidate, ...]:
        with self._mutex:
            self._require_open()
            if self._control_mode is ControlMode.AGENT:
                return ()
            emitted = self._aggregator.ingest(reservation, event)
            self._record_candidates(emitted)
            return emitted

    def finish_manual_candidate(
        self,
        reservation: CandidateReservation,
        *,
        at: datetime,
    ) -> None:
        """Close one emitted human Candidate while retaining prelocked fact tails.

        This is the normal lifecycle boundary between consecutive human
        interactions. It does not finalize other windows and does not change
        control mode.
        """
        with self._mutex:
            self._require_open()
            if self._control_mode is not ControlMode.HUMAN:
                raise ValueError("manual_candidate.human_control_required")
            stored = self._reservations.get(getattr(reservation, "window_id", -1))
            if stored is not reservation:
                raise ValueError("manual_candidate.reservation_not_owned")
            if reservation.window_id in self._finished_manual_window_ids:
                raise ValueError("manual_candidate.already_finished")
            candidate = self._candidates.get(reservation.candidate_id)
            if (
                candidate is None
                or candidate.origin != "human"
                or candidate.execution.status != "succeeded"
            ):
                raise ValueError("manual_candidate.not_emitted")
            ended_at = candidate.execution.ended_at
            try:
                if ended_at is None or at < ended_at:
                    raise ValueError("manual_candidate.finish_time_regressed")
                expires_at = at + self._tail_ttl
            except TypeError as exc:
                raise ValueError("manual_candidate.finish_time_incomparable") from exc
            self.registry.close(reservation, expires_at=expires_at)
            self._finished_manual_window_ids.add(reservation.window_id)

    def fail_manual_candidate(
        self,
        reservation: CandidateReservation,
        event: ManualEvent,
        *,
        at: datetime,
        error_code: str,
        error_message: str,
    ) -> TraceCandidate:
        """Record a failed browser dispatch without losing its causal facts."""

        with self._mutex:
            self._require_open()
            if self._control_mode is not ControlMode.HUMAN:
                raise ValueError("manual_candidate.human_control_required")
            stored = self._reservations.get(getattr(reservation, "window_id", -1))
            if stored is not reservation:
                raise ValueError("manual_candidate.reservation_not_owned")
            if reservation.window_id in self._finished_manual_window_ids:
                raise ValueError("manual_candidate.already_finished")
            candidate = self._aggregator.fail(
                reservation,
                event,
                ended_at=at,
                error_code=error_code,
                error_message=error_message,
            )
            self._record_candidates((candidate,))
            self.registry.close(reservation, expires_at=at + self._tail_ttl)
            self._finished_manual_window_ids.add(reservation.window_id)
            return candidate

    def cancel_manual_candidate(
        self,
        reservation: CandidateReservation,
        *,
        at: datetime,
    ) -> TraceCandidate:
        """Explicitly cancel an opened manual window before another target starts."""

        with self._mutex:
            self._require_open()
            if self._control_mode is not ControlMode.HUMAN:
                raise ValueError("manual_candidate.human_control_required")
            stored = self._reservations.get(getattr(reservation, "window_id", -1))
            if stored is not reservation:
                raise ValueError("manual_candidate.reservation_not_owned")
            if reservation.window_id in self._finished_manual_window_ids:
                raise ValueError("manual_candidate.already_finished")
            candidate = self._aggregator.cancel(
                reservation,
                at,
                tail_expires_at=at + self._tail_ttl,
            )
            self._record_candidates((candidate,))
            self._finished_manual_window_ids.add(reservation.window_id)
            return candidate

    def reserve_agent(
        self,
        candidate_id: str,
        *,
        page_runtime_ref: str,
        frame_runtime_ref: str,
    ) -> AgentCandidateReservation:
        with self._mutex:
            self._require_open()
            if self._control_mode is not ControlMode.AGENT:
                raise ValueError("creation_session.agent_control_inactive")
            if _IDENTIFIER.fullmatch(candidate_id) is None:
                raise ValueError("creation_session.candidate_id_invalid")
            if candidate_id in self._candidates or any(
                reservation.candidate_id == candidate_id
                for reservation in self._reservations.values()
            ) or any(
                reservation.candidate_id == candidate_id
                for reservation in self._agent_reservations.values()
            ):
                raise ValueError(
                    f"creation_session.candidate_reservation_conflict:{candidate_id}"
                )
            causal_window = self.registry.reserve(
                candidate_id=candidate_id,
                page_runtime_ref=page_runtime_ref,
                frame_runtime_ref=frame_runtime_ref,
            )
            reservation = AgentCandidateReservation(
                candidate_id=candidate_id,
                ordinal=self._allocate_ordinal(),
                reservation_id=self._next_agent_reservation_id,
            )
            self._next_agent_reservation_id += 1
            self._agent_reservations[reservation.reservation_id] = reservation
            self._agent_causal_windows[reservation.reservation_id] = causal_window
            self._reservations[causal_window.window_id] = causal_window
            return reservation

    def register_candidate(
        self,
        reservation: AgentCandidateReservation,
        candidate: TraceCandidate,
        *,
        completed_at: datetime,
        variable_outputs: Mapping[str, Any] | None = None,
    ) -> None:
        """登记人工通道之外已经规范化的 Candidate。"""

        if not isinstance(candidate, TraceCandidate):
            candidate = TraceCandidate.model_validate(candidate)
        with self._mutex:
            self._require_open()
            if self._control_mode is not ControlMode.AGENT:
                raise ValueError("creation_session.agent_control_inactive")
            stored = self._agent_reservations.get(reservation.reservation_id)
            if stored is None:
                if reservation.reservation_id in self._consumed_agent_reservation_ids:
                    raise ValueError("creation_session.agent_reservation_consumed")
                raise ValueError("creation_session.agent_reservation_mismatch")
            if stored is not reservation:
                raise ValueError("creation_session.agent_reservation_mismatch")
            if candidate.origin != "agent":
                raise ValueError("creation_session.agent_origin_required")
            if (
                candidate.candidate_id != reservation.candidate_id
                or candidate.ordinal != reservation.ordinal
            ):
                raise ValueError("creation_session.agent_reservation_mismatch")
            causal_window = self._agent_causal_windows.get(reservation.reservation_id)
            if causal_window is None:
                raise ValueError("creation_session.agent_reservation_mismatch")
            lower_bounds = [candidate.execution.started_at]
            ended_at = getattr(candidate.execution, "ended_at", None)
            if ended_at is not None:
                lower_bounds.append(ended_at)
            try:
                if any(completed_at < bound for bound in lower_bounds):
                    raise ValueError("creation_session.agent_completion_time_regressed")
            except TypeError as exc:
                raise ValueError("creation_session.agent_completion_time_incomparable") from exc
            copied = candidate.model_copy(deep=True)
            with self.variables._mutex:
                prepared_values, prepared_producers = self.variables._prepare_writes_locked(
                    dict(variable_outputs or {}),
                    producer_candidate_id=candidate.candidate_id,
                )
                self._validate_candidate_batch((copied,))
                self.registry.validate_active(
                    causal_window,
                    page_runtime_ref=causal_window.page_runtime_ref,
                    frame_runtime_ref=causal_window.frame_runtime_ref,
                )
                self.registry.close(
                    causal_window,
                    expires_at=completed_at + self._tail_ttl,
                )
                self._record_candidates((copied,), prevalidated=True)
                self.variables._values = prepared_values
                self.variables._producers = prepared_producers
                del self._agent_reservations[reservation.reservation_id]
                del self._agent_causal_windows[reservation.reservation_id]
                self._consumed_agent_reservation_ids.add(reservation.reservation_id)

    def record_outcome(
        self,
        outcome: AcceptedSettlement | RejectedSettlement | SettlementAttempt,
    ) -> None:
        del outcome
        raise ValueError("creation_session.direct_outcome_forbidden")

    def settle_candidate(
        self,
        candidate_id: str,
        *,
        scope: BrowserScope | None,
        resolved_assets: Mapping[str, str] | None = None,
    ) -> SettlementOutcome:
        with self._mutex:
            self._require_open()
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                raise ValueError(f"creation_session.candidate_unknown:{candidate_id}")
            facts = tuple(
                fact
                for fact in self.fact_buffer.facts()
                if fact.candidate_id in {None, candidate_id}
            )
            outcome = self._settlement_engine.settle(
                candidate,
                facts=facts,
                scope=scope,
                resolved_assets=resolved_assets,
            )
            self._commit_outcome(outcome)
            return outcome

    def confirm_agent_fallback(
        self,
        candidate_id: str,
        *,
        scope: BrowserScope | None,
        instruction: str,
        confirmed_at: datetime,
        resolved_assets: Mapping[str, str] | None = None,
    ) -> SettlementOutcome:
        with self._mutex:
            self._require_open()
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                raise ValueError(f"creation_session.candidate_unknown:{candidate_id}")
            facts = tuple(
                fact
                for fact in self.fact_buffer.facts()
                if fact.candidate_id in {None, candidate_id}
            )
            normalized = self._settlement_engine.confirm_agent_fallback(
                candidate,
                facts=facts,
                scope=scope,
                instruction=instruction,
                confirmed_at=confirmed_at,
            )
            self._candidates[candidate_id] = normalized
            outcome = self._settlement_engine.settle(
                normalized,
                facts=facts,
                scope=scope,
                resolved_assets=resolved_assets,
            )
            self._commit_outcome(outcome)
            return outcome

    def _commit_outcome(self, outcome: SettlementOutcome) -> None:
        """只消费本 Session SettlementEngine 生成的瞬时结果。"""

        candidate_id = outcome.candidate_id
        candidate = self._candidates.get(candidate_id)
        if candidate is None:
            raise ValueError(f"creation_session.candidate_unknown:{candidate_id}")
        if candidate_id in self._deleted_candidate_ids:
            raise ValueError(f"creation_session.candidate_deleted:{candidate_id}")
        if isinstance(outcome, SettlementAttempt):
            if candidate_id in self._accepted_traces or candidate_id in self._diagnostics:
                raise ValueError(f"creation_session.outcome_terminal:{candidate_id}")
            self._attempts[candidate_id] = outcome
            return
        if candidate_id in self._accepted_traces or candidate_id in self._diagnostics:
            raise ValueError(f"creation_session.outcome_terminal:{candidate_id}")
        if isinstance(outcome, AcceptedSettlement):
            if outcome.core_trace.sequence != candidate.ordinal:
                raise ValueError(f"creation_session.sequence_mismatch:{candidate_id}")
            self.timeline_store.append(outcome)
            self._accepted_traces[candidate_id] = outcome.core_trace.model_copy(deep=True)
            try:
                self.recording_timeline_store.finalize_draft(
                    draft_id=candidate_id,
                    trace=outcome.core_trace,
                )
            except ValueError as exc:
                if not str(exc).startswith("recording_timeline.draft_unknown:"):
                    raise
                self.recording_timeline_store.append_manual(outcome.core_trace)
        elif isinstance(outcome, RejectedSettlement):
            self._diagnostics[candidate_id] = outcome.diagnostic.model_copy(deep=True)
        else:
            raise ValueError("creation_session.outcome_invalid")
        self._attempts.pop(candidate_id, None)

    def delete_candidate(self, candidate_id: str) -> None:
        with self._mutex:
            self._require_open()
            if candidate_id not in self._candidates:
                raise ValueError(f"creation_session.candidate_unknown:{candidate_id}")
            if candidate_id in self._accepted_traces:
                raise ValueError(f"creation_session.accepted_delete_forbidden:{candidate_id}")
            self._deleted_candidate_ids.add(candidate_id)
            self._diagnostics.pop(candidate_id, None)
            self._attempts.pop(candidate_id, None)
            self.fact_buffer.release_candidate(candidate_id)

    def build_readiness(
        self, *, external_asset_refs: set[str] | None = None
    ) -> BuildReadiness:
        with self._mutex:
            self._require_open()
            return derive_build_readiness(
                candidates=self._candidates,
                accepted_traces=self._accepted_traces,
                diagnostics=self._diagnostics,
                deleted_candidate_ids=self._deleted_candidate_ids,
                page_registry=self.pages,
                external_asset_refs=set(external_asset_refs or set()),
            )

    def creation_projection(
        self, *, include_deleted: bool = True
    ) -> tuple[CreationStepRow, ...]:
        with self._mutex:
            self._require_open()
            return project_creation_steps(
                candidates=self._candidates,
                accepted_traces=self._accepted_traces,
                diagnostics=self._diagnostics,
                deleted_candidate_ids=self._deleted_candidate_ids,
                include_deleted=include_deleted,
            )

    def candidate_has_side_effect(self, candidate_id: str) -> bool:
        """只暴露副作用存在性，不把 BrowserFact 内容交给 Adapter。"""

        with self._mutex:
            self._require_open()
            return any(
                fact.candidate_id == candidate_id
                and (
                    fact.kind in {
                        "navigation", "new_page", "dialog",
                        "page_activated", "page_closed",
                    }
                    or fact.kind == "download"
                    and fact.detail.status == "completed"
                )
                for fact in self.fact_buffer.facts()
            )

    def candidate_has_fact(self, candidate_id: str, kind: str) -> bool:
        with self._mutex:
            self._require_open()
            return any(
                fact.candidate_id == candidate_id and fact.kind == kind
                for fact in self.fact_buffer.facts()
            )

    def switch_control(
        self, mode: ControlMode, *, at: datetime
    ) -> tuple[TraceCandidate, ...]:
        if not isinstance(mode, ControlMode):
            raise ValueError("creation_session.control_mode_invalid")
        with self._mutex:
            self._require_open()
            if mode is self._control_mode:
                return ()
            if mode is ControlMode.HUMAN and self._agent_reservations:
                raise ValueError("creation_session.agent_reservation_outstanding")
            emitted: tuple[TraceCandidate, ...] = ()
            if mode is ControlMode.AGENT:
                owned = tuple(self._reservations.values())
                self.registry.validate_reservations(owned)
                emitted = self._aggregator.finalize_all(
                    at,
                    reservations_to_close=owned,
                    tail_expires_at=at + self._tail_ttl,
                )
                self._record_candidates(emitted)
            self._control_mode = mode
            return emitted

    def close(self, *, at: datetime) -> tuple[TraceCandidate, ...]:
        with self._mutex:
            if self._closed:
                return ()
            if self._agent_reservations:
                raise ValueError("creation_session.agent_reservation_outstanding")
            emitted: tuple[TraceCandidate, ...] = ()
            owned = tuple(self._reservations.values())
            self.registry.validate_reservations(owned)
            if self._control_mode is ControlMode.HUMAN:
                emitted = self._aggregator.finalize_all(
                    at,
                    reservations_to_close=owned,
                    tail_expires_at=at + self._tail_ttl,
                )
                self._record_candidates(emitted)
            self.registry.expire_many(owned)
            self.observer.clear_pending()
            self._reservations.clear()
            self._finished_manual_window_ids.clear()
            self.fact_buffer.clear()
            self._attempts.clear()
            self._agent_reservations.clear()
            self.variables.clear()
            self.pages.clear()
            self._closed = True
            return emitted

    def expire_tail_windows(self, now: datetime) -> int:
        with self._mutex:
            self._require_open()
            expired_ids = set(self.registry.expire_closed(now))
            if not expired_ids:
                return 0
            self.observer.expire_windows(expired_ids)
            for window_id in expired_ids:
                self._reservations.pop(window_id, None)
            return len(expired_ids)

    def _allocate_ordinal(self) -> int:
        ordinal = self._next_ordinal
        self._next_ordinal += 1
        self._allocated_ordinals.add(ordinal)
        return ordinal

    def _validate_candidate_batch(
        self, candidates: tuple[TraceCandidate, ...]
    ) -> None:
        incoming_ids = [candidate.candidate_id for candidate in candidates]
        incoming_ordinals = [candidate.ordinal for candidate in candidates]
        if len(incoming_ids) != len(set(incoming_ids)):
            raise ValueError("creation_session.candidate_batch_id_duplicate")
        if len(incoming_ordinals) != len(set(incoming_ordinals)):
            raise ValueError("creation_session.candidate_batch_ordinal_duplicate")
        existing_ordinals = {
            candidate.ordinal for candidate in self._candidates.values()
        }
        for candidate in candidates:
            if candidate.candidate_id in self._candidates:
                raise ValueError(
                    f"creation_session.candidate_id_duplicate:{candidate.candidate_id}"
                )
            if candidate.ordinal in existing_ordinals:
                raise ValueError(
                    f"creation_session.ordinal_duplicate:{candidate.ordinal}"
                )

    def _record_candidates(
        self,
        candidates: tuple[TraceCandidate, ...],
        *,
        prevalidated: bool = False,
    ) -> None:
        if not prevalidated:
            self._validate_candidate_batch(candidates)
        for candidate in candidates:
            self._candidates[candidate.candidate_id] = candidate
            self._allocated_ordinals.add(candidate.ordinal)

    def _require_open(self) -> None:
        if self._closed:
            raise ValueError("creation_session.closed")
