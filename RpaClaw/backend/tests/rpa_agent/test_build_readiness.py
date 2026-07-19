from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rpa_agent.contracts import (
    AcceptedSettlement,
    BrowserScope,
    CoreTrace,
    Diagnostic,
    RejectedSettlement,
    TraceCandidate,
)
from rpa_agent.creation import (
    ControlMode,
    InteractionKind,
    ManualEvent,
    ManualEventKind,
    ReadinessCode,
    SkillCreationSession,
)


NOW = datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc)


def _session() -> SkillCreationSession:
    return SkillCreationSession(
        session_id="session_readiness",
        main_runtime_ref="runtime_main",
        fact_buffer_capacity=20,
        fact_ttl=timedelta(minutes=1),
    )


def _candidate(
    candidate_id: str,
    ordinal: int,
    *,
    output_kind: str | None = None,
    output_ref: str | None = None,
    input_kind: str | None = None,
    input_ref: str | None = None,
    succeeded: bool = False,
    failed: bool = False,
) -> TraceCandidate:
    bindings = []
    if input_kind is not None:
        bindings.append(
            {
                "name": "source",
                "direction": "input",
                "kind_hint": input_kind,
                "ref_hint": input_ref,
                "sensitive": False,
            }
        )
    if output_kind is not None:
        bindings.append(
            {
                "name": "result",
                "direction": "output",
                "kind_hint": output_kind,
                "ref_hint": output_ref,
                "sensitive": False,
            }
        )
    return TraceCandidate.model_validate(
        {
            "candidate_id": candidate_id,
            "ordinal": ordinal,
            "origin": "agent",
            "scope_hint": {"page_ref": "main", "frame_path": []},
            "action_hint": {"kind": "agent", "instruction": "执行单个业务动作"},
            "binding_hints": bindings,
            "execution": (
                {
                    "status": "failed",
                    "started_at": NOW,
                    "ended_at": NOW + timedelta(milliseconds=1),
                    "output": None,
                    "error": {"code": "tool_failed", "message": "动作失败"},
                }
                if failed
                else
                {
                    "status": "succeeded",
                    "started_at": NOW,
                    "ended_at": NOW + timedelta(milliseconds=1),
                    "output": None,
                    "error": None,
                }
                if succeeded
                else {
                    "status": "running",
                    "started_at": NOW,
                    "ended_at": None,
                    "output": None,
                    "error": None,
                }
            ),
        }
    )


def _trace(
    trace_id: str,
    sequence: int,
    *,
    page_ref: str = "main",
    input_kind: str | None = None,
    input_ref: str | None = None,
    output_kind: str | None = None,
    output_ref: str | None = None,
    effects: list[dict[str, object]] | None = None,
) -> CoreTrace:
    bindings: list[dict[str, object]] = []
    if input_kind is not None:
        bindings.append(
            {
                "name": "source",
                "direction": "input",
                "kind": input_kind,
                "ref": input_ref,
                "sensitive": False,
            }
        )
    if output_kind is not None:
        bindings.append(
            {
                "name": "result",
                "direction": "output",
                "kind": output_kind,
                "ref": output_ref,
                "sensitive": False,
            }
        )
    return CoreTrace.model_validate(
        {
            "trace_id": trace_id,
            "sequence": sequence,
            "scope": {"page_ref": page_ref, "frame_path": []},
            "action": {"kind": "agent", "instruction": "执行单个业务动作"},
            "data_bindings": bindings,
            "effects": effects or [],
        }
    )


def _register(session: SkillCreationSession, candidate: TraceCandidate) -> None:
    reservation = _reserve(session, candidate.candidate_id)
    assert reservation.ordinal == candidate.ordinal
    session.register_candidate(
        reservation,
        candidate,
        completed_at=NOW + timedelta(milliseconds=2),
    )


def _reserve(session: SkillCreationSession, candidate_id: str):
    return session.reserve_agent(
        candidate_id,
        page_runtime_ref="runtime_main",
        frame_runtime_ref=f"frame_{candidate_id}",
    )


def _accept(
    session: SkillCreationSession,
    candidate_id: str,
    *,
    page_ref: str = "main",
) -> CoreTrace:
    outcome = session.settle_candidate(
        candidate_id,
        scope=BrowserScope(page_ref=page_ref, frame_path=[]),
    )
    assert outcome.status == "accepted"
    return outcome.core_trace


def _codes(readiness) -> set[ReadinessCode]:
    return {issue.code for issue in readiness.issues}


def test_pending_variable_producer_blocks_later_accepted_without_reverting_it() -> None:
    session = _session()
    session.switch_control(ControlMode.AGENT, at=NOW)
    producer = _candidate(
        "candidate_producer",
        1,
        output_kind="variable",
        output_ref="采购订单",
        succeeded=True,
    )
    consumer = _candidate(
        "candidate_consumer",
        2,
        input_kind="variable",
        input_ref="采购订单.订单号",
        succeeded=True,
    )
    _register(session, producer)
    _register(session, consumer)
    consumer_trace = _accept(session, consumer.candidate_id)

    blocked = session.build_readiness()

    assert _codes(blocked) == {
        ReadinessCode.CANDIDATE_PENDING,
        ReadinessCode.PENDING_VARIABLE,
    }
    dependency = next(
        issue for issue in blocked.issues if issue.code is ReadinessCode.PENDING_VARIABLE
    )
    assert (
        dependency.candidate_id,
        dependency.trace_id,
        dependency.ref,
        dependency.producer_candidate_id,
    ) == (
        "candidate_consumer",
        consumer_trace.trace_id,
        "采购订单.订单号",
        "candidate_producer",
    )
    assert session.accepted_traces["candidate_consumer"] == consumer_trace

    _accept(session, producer.candidate_id)
    ready = session.build_readiness()

    assert ready.ready is True
    assert [trace.sequence for trace in ready.timeline.traces] == [1, 2]
    assert session.accepted_traces["candidate_consumer"] == consumer_trace


def test_rejected_must_be_deleted_but_deleted_variable_producer_stays_unresolved() -> None:
    session = _session()
    session.switch_control(ControlMode.AGENT, at=NOW)
    producer = _candidate(
        "candidate_rejected",
        1,
        output_kind="variable",
        output_ref="采购订单",
        failed=True,
    )
    consumer = _candidate(
        "candidate_consumer",
        2,
        input_kind="variable",
        input_ref="采购订单.供应商",
        succeeded=True,
    )
    _register(session, producer)
    _register(session, consumer)
    rejected_outcome = session.settle_candidate(
        producer.candidate_id,
        scope=BrowserScope(page_ref="main", frame_path=[]),
    )
    assert rejected_outcome.status == "rejected"
    _accept(session, consumer.candidate_id)

    rejected = session.build_readiness()
    assert ReadinessCode.CANDIDATE_REJECTED in _codes(rejected)
    assert ReadinessCode.UNRESOLVED_VARIABLE in _codes(rejected)

    session.delete_candidate(producer.candidate_id)
    deleted = session.build_readiness()
    assert ReadinessCode.CANDIDATE_REJECTED not in _codes(deleted)
    assert ReadinessCode.UNRESOLVED_VARIABLE in _codes(deleted)


def test_pending_then_deleted_data_asset_producer_has_distinct_reasons() -> None:
    session = _session()
    session.switch_control(ControlMode.AGENT, at=NOW)
    producer = _candidate(
        "candidate_download",
        1,
        output_kind="data_asset",
        output_ref="acceptance_file",
        succeeded=True,
    )
    consumer = _candidate(
        "candidate_upload",
        2,
        input_kind="data_asset",
        input_ref="acceptance_file",
        succeeded=True,
    )
    _register(session, producer)
    _register(session, consumer)
    _accept(session, consumer.candidate_id)

    pending = session.build_readiness()
    assert ReadinessCode.PENDING_DATA_ASSET in _codes(pending)
    session.delete_candidate(producer.candidate_id)
    deleted = session.build_readiness()
    assert ReadinessCode.PENDING_DATA_ASSET not in _codes(deleted)
    assert ReadinessCode.UNRESOLVED_DATA_ASSET in _codes(deleted)


def test_deleted_new_page_producer_survives_fact_release_as_unresolved_provenance() -> None:
    session = _session()
    reservation = session.reserve_manual(
        candidate_id="candidate_popup",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
    )
    emitted = session.ingest_manual(
        reservation,
        ManualEvent(
            kind=ManualEventKind.CLICK,
            page_runtime_ref="runtime_main",
            frame_runtime_ref="frame_main",
            target_key="acceptance-button",
            target_name="发起验收",
            target_locators=({"strategy": "role", "role": "button", "name": "发起验收", "exact": True},),
            interaction_kind=InteractionKind.CLICK,
            observed_at=NOW,
        ),
    )
    trigger = session.observer.start_new_page("runtime_main", "frame_main")
    fact = session.observer.complete_new_page(
        trigger,
        observed_at=NOW + timedelta(seconds=1),
        new_page_runtime_ref="runtime_popup",
        initial_url="https://example.test/task/random-token",
    )
    page_ref = session.pages.apply(fact)
    producer_snapshot = session.pages.producer_snapshot()
    producer_snapshot[page_ref] = "mutated"
    assert session.pages.producer_snapshot()[page_ref] == "candidate_popup"
    session.switch_control(ControlMode.AGENT, at=NOW + timedelta(seconds=2))
    consumer = _candidate("candidate_popup_consumer", 2, succeeded=True)
    _register(session, consumer)
    _accept(session, consumer.candidate_id, page_ref=page_ref)

    pending = session.build_readiness()
    assert ReadinessCode.PENDING_PAGE in _codes(pending)
    session.delete_candidate(emitted[0].candidate_id)
    session.fact_buffer.clear()
    deleted = session.build_readiness()
    issue = next(issue for issue in deleted.issues if issue.code is ReadinessCode.UNRESOLVED_PAGE)
    assert (issue.ref, issue.producer_candidate_id) == (page_ref, "candidate_popup")


def test_later_producer_cannot_satisfy_earlier_consumer() -> None:
    session = _session()
    session.switch_control(ControlMode.AGENT, at=NOW)
    consumer = _candidate(
        "candidate_consumer",
        1,
        input_kind="variable",
        input_ref="采购订单.订单号",
        succeeded=True,
    )
    producer = _candidate(
        "candidate_late",
        2,
        output_kind="variable",
        output_ref="采购订单",
        succeeded=True,
    )
    consumer_reservation = _reserve(session, consumer.candidate_id)
    producer_reservation = _reserve(session, producer.candidate_id)
    session.register_candidate(
        producer_reservation,
        producer,
        completed_at=NOW + timedelta(milliseconds=2),
    )
    session.register_candidate(
        consumer_reservation,
        consumer,
        completed_at=NOW + timedelta(milliseconds=2),
    )
    _accept(session, consumer.candidate_id)
    _accept(session, producer.candidate_id)

    readiness = session.build_readiness()

    assert readiness.ready is False
    assert _codes(readiness) == {ReadinessCode.UNRESOLVED_VARIABLE}


def test_external_asset_ref_is_explicit_and_ready_snapshot_is_a_valid_deep_copy() -> None:
    session = _session()
    session.switch_control(ControlMode.AGENT, at=NOW)
    consumer = _candidate(
        "candidate_upload",
        1,
        input_kind="data_asset",
        input_ref="external_upload",
        succeeded=True,
    )
    _register(session, consumer)
    trace = _accept(session, consumer.candidate_id)

    blocked = session.build_readiness()
    ready = session.build_readiness(external_asset_refs={"external_upload"})

    assert _codes(blocked) == {ReadinessCode.UNRESOLVED_DATA_ASSET}
    assert ready.ready is True
    assert ready.issues == ()
    assert ready.timeline is not None
    assert ready.timeline.traces[0] is not trace
    exported = ready.timeline.model_dump(mode="python")
    exported["traces"][0]["data_bindings"][0]["ref"] = "mutated_copy"
    assert session.accepted_traces["candidate_upload"].data_bindings[0].ref == "external_upload"


def test_readiness_deduplicates_identical_dependency_issue_by_full_location_tuple() -> None:
    session = _session()
    session.switch_control(ControlMode.AGENT, at=NOW)
    producer = _candidate(
        "candidate_root",
        1,
        output_kind="variable",
        output_ref="采购订单",
        succeeded=True,
    )
    reservation = _reserve(session, producer.candidate_id)
    session.register_candidate(
        reservation,
        producer,
        completed_at=NOW + timedelta(milliseconds=2),
    )
    consumer_reservation = _reserve(session, "candidate_consumer")
    consumer = TraceCandidate.model_validate(
        {
            "candidate_id": consumer_reservation.candidate_id,
            "ordinal": consumer_reservation.ordinal,
            "origin": "agent",
            "scope_hint": {"page_ref": "main", "frame_path": []},
            "action_hint": {"kind": "agent", "instruction": "使用同一变量两次"},
            "binding_hints": [
                {
                    "name": name,
                    "direction": "input",
                    "kind_hint": "variable",
                    "ref_hint": "采购订单.订单号",
                    "sensitive": False,
                }
                for name in ("left", "right")
            ],
            "execution": {
                "status": "succeeded",
                "started_at": NOW,
                "ended_at": NOW + timedelta(milliseconds=1),
                "output": None,
                "error": None,
            },
        }
    )
    session.register_candidate(
        consumer_reservation,
        consumer,
        completed_at=NOW + timedelta(milliseconds=2),
    )
    _accept(session, consumer.candidate_id)

    readiness = session.build_readiness()

    assert sum(
        issue.code is ReadinessCode.PENDING_VARIABLE
        for issue in readiness.issues
    ) == 1
