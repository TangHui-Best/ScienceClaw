from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from rpa_agent.contracts import TraceCandidate
from rpa_agent.creation import (
    ControlMode,
    InteractionKind,
    ManualEvent,
    ManualEventKind,
    SessionVariableStore,
    SkillCreationSession,
)


BASE_TIME = datetime(2026, 7, 18, 8, 0, tzinfo=timezone.utc)


def _event(
    kind: ManualEventKind,
    *,
    frame: str,
    interaction: InteractionKind = InteractionKind.FILL,
    value: str | None = None,
    offset: int = 0,
) -> ManualEvent:
    return ManualEvent(
        kind=kind,
        page_runtime_ref="runtime_main",
        frame_runtime_ref=frame,
        target_key=f"field-{frame}",
        target_name="订单号",
        target_locators=({"strategy": "label", "value": f"input-{frame}", "exact": True},),
        interaction_kind=interaction,
        observed_at=BASE_TIME + timedelta(seconds=offset),
        value=value,
    )


def _session(session_id: str = "session_a") -> SkillCreationSession:
    return SkillCreationSession(
        session_id=session_id,
        main_runtime_ref="runtime_main",
        fact_buffer_capacity=8,
        fact_ttl=timedelta(minutes=1),
    )


def test_finish_manual_candidate_releases_scope_without_changing_human_control() -> None:
    session = _session()
    first = session.reserve_manual(
        candidate_id="candidate_first",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
    )
    emitted = session.ingest_manual(
        first,
        _event(ManualEventKind.CLICK, frame="frame_main", interaction=InteractionKind.CLICK),
    )

    session.finish_manual_candidate(first, at=BASE_TIME + timedelta(seconds=1))
    second = session.reserve_manual(
        candidate_id="candidate_second",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
    )

    assert [candidate.candidate_id for candidate in emitted] == ["candidate_first"]
    assert second.candidate_id == "candidate_second"
    assert session.control_mode is ControlMode.HUMAN


def test_finish_manual_candidate_preserves_prelocked_fact_until_tail_deadline() -> None:
    session = _session()
    reservation = session.reserve_manual(
        candidate_id="candidate_popup",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_popup",
    )
    session.ingest_manual(
        reservation,
        _event(ManualEventKind.CLICK, frame="frame_popup", interaction=InteractionKind.CLICK),
    )
    trigger = session.observer.start_new_page("runtime_main", "frame_popup")

    session.finish_manual_candidate(reservation, at=BASE_TIME + timedelta(seconds=1))
    fact = session.observer.complete_new_page(
        trigger,
        observed_at=BASE_TIME + timedelta(seconds=30),
        new_page_runtime_ref="runtime_popup",
        initial_url="https://example.invalid/random",
    )

    assert fact.candidate_id == "candidate_popup"
    assert session.control_mode is ControlMode.HUMAN


def test_finish_manual_candidate_rejects_unemitted_foreign_and_agent_mode() -> None:
    session = _session()
    open_reservation = session.reserve_manual(
        candidate_id="candidate_open",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_open",
    )
    with pytest.raises(ValueError, match="manual_candidate.not_emitted"):
        session.finish_manual_candidate(open_reservation, at=BASE_TIME)

    foreign = _session("session_foreign").reserve_manual(
        candidate_id="candidate_foreign",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_foreign",
    )
    with pytest.raises(ValueError, match="manual_candidate.reservation_not_owned"):
        session.finish_manual_candidate(foreign, at=BASE_TIME)

    emitted = session.reserve_manual(
        candidate_id="candidate_emitted",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_emitted",
    )
    session.ingest_manual(
        emitted,
        _event(ManualEventKind.CLICK, frame="frame_emitted", interaction=InteractionKind.CLICK),
    )
    session.switch_control(ControlMode.AGENT, at=BASE_TIME + timedelta(seconds=1))
    with pytest.raises(ValueError, match="manual_candidate.human_control_required"):
        session.finish_manual_candidate(emitted, at=BASE_TIME + timedelta(seconds=2))


def test_switch_to_agent_atomically_finalizes_complete_and_incomplete_manual_windows() -> None:
    session = _session()
    complete = session.reserve_manual(
        candidate_id="candidate_complete",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_complete",
    )
    incomplete = session.reserve_manual(
        candidate_id="candidate_incomplete",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_incomplete",
    )

    session.ingest_manual(complete, _event(ManualEventKind.BEFORE_INPUT, frame="frame_complete"))
    session.ingest_manual(
        complete,
        _event(ManualEventKind.INPUT, frame="frame_complete", value="PO-001", offset=1),
    )
    session.ingest_manual(
        incomplete,
        _event(ManualEventKind.COMPOSITION_START, frame="frame_incomplete", offset=2),
    )

    finalized = session.switch_control(ControlMode.AGENT, at=BASE_TIME + timedelta(seconds=3))

    assert session.control_mode is ControlMode.AGENT
    assert [(item.candidate_id, item.execution.status) for item in finalized] == [
        ("candidate_complete", "succeeded"),
        ("candidate_incomplete", "cancelled"),
    ]
    assert [item.ordinal for item in finalized] == [1, 2]
    assert tuple(session.candidates) == ("candidate_complete", "candidate_incomplete")
    with pytest.raises(ValueError, match="candidate_window.not_active"):
        session.registry.validate_active(
            complete,
            page_runtime_ref="runtime_main",
            frame_runtime_ref="frame_complete",
        )


def test_agent_mode_drops_manual_promotion_but_browser_fact_observer_keeps_running() -> None:
    session = _session()
    reservation = session.reserve_manual(
        candidate_id="candidate_manual",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
    )
    session.ingest_manual(
        reservation,
        _event(ManualEventKind.COMPOSITION_START, frame="frame_main"),
    )
    completed_click = session.reserve_manual(
        candidate_id="candidate_click",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_click",
    )
    session.ingest_manual(
        completed_click,
        _event(
            ManualEventKind.CLICK,
            frame="frame_click",
            interaction=InteractionKind.CLICK,
        ),
    )
    session.switch_control(ControlMode.AGENT, at=BASE_TIME + timedelta(seconds=1))

    assert session.ingest_manual(
        reservation,
        _event(ManualEventKind.INPUT, frame="frame_main", value="ignored", offset=2),
    ) == ()
    trigger = session.observer.start_page_activated("runtime_main", "frame_click")
    fact = session.observer.complete_page_activated(
        trigger,
        observed_at=BASE_TIME + timedelta(seconds=2),
        page_runtime_ref="runtime_main",
    )

    assert fact.candidate_id is None
    assert session.fact_buffer.facts() == (fact,)
    session.switch_control(ControlMode.HUMAN, at=BASE_TIME + timedelta(seconds=3))
    restored = session.reserve_manual(
        candidate_id="candidate_restored",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
    )
    emitted = session.ingest_manual(
        restored,
        _event(
            ManualEventKind.CLICK,
            frame="frame_main",
            interaction=InteractionKind.CLICK,
            offset=4,
        ),
    )
    assert emitted[0].candidate_id == "candidate_restored"


def test_sessions_isolate_candidate_ids_ordinals_and_cleanup_all_short_lived_state() -> None:
    first = _session("session_first")
    second = _session("session_second")
    first_reservation = first.reserve_manual(
        candidate_id="candidate_same",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
    )
    second_reservation = second.reserve_manual(
        candidate_id="candidate_same",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
    )
    first_candidate = first.ingest_manual(
        first_reservation,
        _event(ManualEventKind.CLICK, frame="frame_main", interaction=InteractionKind.CLICK),
    )[0]
    second_candidate = second.ingest_manual(
        second_reservation,
        _event(ManualEventKind.CLICK, frame="frame_main", interaction=InteractionKind.CLICK),
    )[0]
    assert first_candidate.ordinal == second_candidate.ordinal == 1

    pending = first.observer.start_navigation("runtime_main", "frame_main")
    first.observer.complete_navigation(
        pending,
        observed_at=BASE_TIME + timedelta(seconds=1),
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
        is_main_frame=True,
        url="https://example.test/next",
    )
    dangling = first.observer.start_download("runtime_main", "frame_main")
    assert first.observer.pending_count == 1
    assert first.fact_buffer.facts()

    first.close(at=BASE_TIME + timedelta(seconds=2))

    assert first.closed is True
    assert first.observer.pending_count == 0
    assert first.fact_buffer.facts() == ()
    assert first.observer.cancel_trigger(dangling) is False
    with pytest.raises(ValueError, match="creation_session.closed"):
        first.reserve_manual(
            candidate_id="candidate_late",
            page_runtime_ref="runtime_main",
            frame_runtime_ref="frame_main",
        )
    assert second.closed is False


def test_session_variable_store_copies_json_values_and_refuses_secret_or_local_asset_storage() -> None:
    store = SessionVariableStore(session_id="session_values")
    source = {"订单号": "PO-001", "items": [{"amount": 10}]}

    store.write("采购订单", source, producer_candidate_id="candidate_extract")
    source["items"][0]["amount"] = 99
    read_back = store.read("采购订单")
    read_back["items"][0]["amount"] = 88

    assert store.read("采购订单") == {"订单号": "PO-001", "items": [{"amount": 10}]}
    assert store.producer_for("采购订单") == "candidate_extract"
    with pytest.raises(ValueError, match="session_variable_store.secret_plaintext_forbidden"):
        store.write_secret("erp_password", "plaintext", producer_candidate_id="candidate_1")
    with pytest.raises(ValueError, match="session_variable_store.local_asset_path_forbidden"):
        store.write_data_asset(
            "acceptance_file",
            r"C:\\Users\\tester\\Downloads\\acceptance.xlsx",
            producer_candidate_id="candidate_2",
        )
    with pytest.raises(ValueError, match="session_variable_store.value_not_json"):
        store.write("非法值", {"when": BASE_TIME}, producer_candidate_id="candidate_bad")


def _agent_candidate(candidate_id: str, ordinal: int, *, origin: str = "agent") -> TraceCandidate:
    return TraceCandidate.model_validate(
        {
            "candidate_id": candidate_id,
            "ordinal": ordinal,
            "origin": origin,
            "scope_hint": {"page_ref": "main", "frame_path": []},
            "action_hint": {"kind": "agent", "instruction": "执行单个动作"},
            "binding_hints": [],
            "execution": {
                "status": "running",
                "started_at": BASE_TIME,
                "ended_at": None,
                "output": None,
                "error": None,
            },
        }
    )


def _succeeded_agent_candidate(candidate_id: str, ordinal: int) -> TraceCandidate:
    payload = _agent_candidate(candidate_id, ordinal).model_dump(mode="python")
    payload["execution"] = {
        "status": "succeeded",
        "started_at": BASE_TIME,
        "ended_at": BASE_TIME + timedelta(milliseconds=1),
        "output": None,
        "error": None,
    }
    return TraceCandidate.model_validate(payload)


def test_public_candidate_registration_is_agent_only_and_uses_one_contract_identity() -> None:
    session = _session()
    with pytest.raises(ValueError, match="creation_session.agent_control_inactive"):
        session.reserve_agent(
            "candidate_agent",
            page_runtime_ref="runtime_main",
            frame_runtime_ref="frame_agent",
        )

    session.switch_control(ControlMode.AGENT, at=BASE_TIME)
    reservation = session.reserve_agent(
        "candidate_agent",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_agent",
    )
    with pytest.raises(ValueError, match="creation_session.agent_origin_required"):
        session.register_candidate(
            reservation,
            _agent_candidate(
                reservation.candidate_id,
                reservation.ordinal,
                origin="human",
            ),
            completed_at=BASE_TIME + timedelta(seconds=1),
        )
    candidate = _agent_candidate(reservation.candidate_id, reservation.ordinal)
    session.register_candidate(
        reservation,
        candidate,
        completed_at=BASE_TIME + timedelta(seconds=1),
    )

    stored = session.candidates[candidate.candidate_id]
    assert type(stored) is TraceCandidate
    assert type(stored).__module__ == "rpa_agent.contracts.models"


def test_agent_registration_rejects_reserved_candidate_id_and_allocated_ordinal() -> None:
    session = _session()
    reservation = session.reserve_manual(
        candidate_id="candidate_reserved",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_reserved",
    )
    emitted = session.ingest_manual(
        reservation,
        _event(
            ManualEventKind.CLICK,
            frame="frame_reserved",
            interaction=InteractionKind.CLICK,
        ),
    )
    session.switch_control(ControlMode.AGENT, at=BASE_TIME + timedelta(seconds=1))

    with pytest.raises(ValueError, match="creation_session.candidate_reservation_conflict"):
        session.reserve_agent(
            "candidate_reserved",
            page_runtime_ref="runtime_main",
            frame_runtime_ref="frame_reserved",
        )
    other = session.reserve_agent(
        "candidate_other",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_other",
    )
    with pytest.raises(ValueError, match="creation_session.agent_reservation_mismatch"):
        session.register_candidate(
            other,
            _agent_candidate("candidate_other", emitted[0].ordinal),
            completed_at=BASE_TIME + timedelta(seconds=2),
        )


def test_failed_switch_preflight_keeps_mode_candidates_and_manual_window_unchanged() -> None:
    session = _session()
    valid = session.reserve_manual(
        candidate_id="candidate_valid",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_valid",
    )
    invalid = session.reserve_manual(
        candidate_id="candidate_invalid",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_invalid",
    )
    session.ingest_manual(valid, _event(ManualEventKind.BEFORE_INPUT, frame="frame_valid"))
    session.ingest_manual(
        valid,
        _event(ManualEventKind.INPUT, frame="frame_valid", value="before", offset=1),
    )
    session.registry.expire(invalid)

    with pytest.raises(ValueError, match="candidate_window.reservation_mismatch"):
        session.switch_control(ControlMode.AGENT, at=BASE_TIME + timedelta(seconds=2))

    assert session.control_mode is ControlMode.HUMAN
    assert session.candidates == {}
    assert session.ingest_manual(
        valid,
        _event(ManualEventKind.INPUT, frame="frame_valid", value="after", offset=3),
    ) == ()


def test_close_clears_attempts_and_session_variable_values() -> None:
    from rpa_agent.creation import SettlementAttempt, SettlementAttemptStatus

    session = _session()
    session.switch_control(ControlMode.AGENT, at=BASE_TIME)
    reservation = session.reserve_agent(
        "candidate_pending",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_pending",
    )
    candidate = _agent_candidate(reservation.candidate_id, reservation.ordinal)
    session.register_candidate(
        reservation,
        candidate,
        completed_at=BASE_TIME + timedelta(seconds=1),
    )
    from rpa_agent.contracts import BrowserScope
    outcome = session.settle_candidate(
        candidate.candidate_id,
        scope=BrowserScope(page_ref="main", frame_path=[]),
    )
    assert isinstance(outcome, SettlementAttempt)
    assert outcome.status is SettlementAttemptStatus.WAITING
    session.variables.write(
        "采购订单",
        {"订单号": "PO-CLOSE"},
        producer_candidate_id=candidate.candidate_id,
    )

    session.close(at=BASE_TIME + timedelta(seconds=1))

    assert session.settlement_attempts == {}
    with pytest.raises(KeyError, match="session_variable_store.ref_missing"):
        session.variables.read("采购订单")


def test_variable_store_parent_and_subtree_overwrite_keep_producer_index_consistent() -> None:
    store = SessionVariableStore(session_id="session_overwrite")
    store.write(
        "采购订单",
        {"订单号": "PO-ROOT", "供应商": {"名称": "旧供应商"}},
        producer_candidate_id="candidate_root",
    )
    store.write(
        "采购订单.供应商.名称",
        "新供应商",
        producer_candidate_id="candidate_leaf",
    )
    assert store.producer_for("采购订单.供应商.名称") == "candidate_leaf"

    store.write(
        "采购订单.供应商",
        {"名称": "整体替换"},
        producer_candidate_id="candidate_subtree",
    )
    assert store.producer_for("采购订单.供应商.名称") == "candidate_subtree"
    assert store.producer_for("采购订单.订单号") == "candidate_root"

    store.write(
        "采购订单",
        {"订单号": "PO-REPLACED"},
        producer_candidate_id="candidate_parent",
    )
    assert store.producer_for("采购订单.订单号") == "candidate_parent"
    with pytest.raises(KeyError, match="session_variable_store.ref_missing"):
        store.read("采购订单.供应商")


def test_variable_store_path_conflict_is_atomic() -> None:
    store = SessionVariableStore(session_id="session_atomic")
    store.write("采购订单", "scalar", producer_candidate_id="candidate_root")
    before = store.snapshot()

    with pytest.raises(ValueError, match="session_variable_store.path_conflict"):
        store.write(
            "采购订单.订单号",
            "PO-FAIL",
            producer_candidate_id="candidate_child",
        )

    assert store.snapshot() == before
    assert store.producer_for("采购订单") == "candidate_root"
    with pytest.raises(KeyError, match="session_variable_store.producer_missing"):
        store.producer_for("采购订单.订单号")


def test_agent_candidate_reservation_owns_id_and_ordinal_and_is_one_shot() -> None:
    session = _session()
    session.switch_control(ControlMode.AGENT, at=BASE_TIME)

    reservation = session.reserve_agent(
        "candidate_agent",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_agent",
    )
    assert reservation.ordinal == 1
    wrong = _agent_candidate("candidate_agent", 2)
    with pytest.raises(ValueError, match="creation_session.agent_reservation_mismatch"):
        session.register_candidate(
            reservation,
            wrong,
            completed_at=BASE_TIME + timedelta(seconds=1),
        )

    candidate = _agent_candidate("candidate_agent", reservation.ordinal)
    session.register_candidate(
        reservation,
        candidate,
        completed_at=BASE_TIME + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="creation_session.agent_reservation_consumed"):
        session.register_candidate(
            reservation,
            candidate,
            completed_at=BASE_TIME + timedelta(seconds=1),
        )


def test_agent_reservation_opens_opaque_causal_window_and_registration_closes_it() -> None:
    session = _session()
    session.switch_control(ControlMode.AGENT, at=BASE_TIME)
    reservation = session.reserve_agent(
        "candidate_agent_scope",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_agent",
    )
    trigger = session.observer.start_navigation("runtime_main", "frame_agent")
    candidate = _agent_candidate(reservation.candidate_id, reservation.ordinal)
    session.register_candidate(
        reservation,
        candidate,
        completed_at=BASE_TIME + timedelta(seconds=1),
    )
    fact = session.observer.complete_navigation(
        trigger,
        observed_at=BASE_TIME + timedelta(seconds=2),
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_agent",
        is_main_frame=True,
        url="https://example.test/orders",
    )

    assert fact.candidate_id == "candidate_agent_scope"
    late = session.observer.start_navigation("runtime_main", "frame_agent")
    late_fact = session.observer.complete_navigation(
        late,
        observed_at=BASE_TIME + timedelta(seconds=3),
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_agent",
        is_main_frame=True,
        url="https://example.test/late",
    )
    assert late_fact.candidate_id is None


def test_failed_agent_registration_is_atomic_and_reservation_window_remains_usable() -> None:
    session = _session()
    session.switch_control(ControlMode.AGENT, at=BASE_TIME)
    reservation = session.reserve_agent(
        "candidate_agent_retry",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_agent_retry",
    )
    wrong = _agent_candidate(reservation.candidate_id, reservation.ordinal + 1)
    with pytest.raises(ValueError, match="creation_session.agent_reservation_mismatch"):
        session.register_candidate(
            reservation,
            wrong,
            completed_at=BASE_TIME + timedelta(seconds=1),
        )

    assert session.outstanding_agent_reservation_count == 1
    trigger = session.observer.start_download("runtime_main", "frame_agent_retry")
    fact = session.observer.complete_download(
        trigger,
        observed_at=BASE_TIME + timedelta(seconds=2),
        page_runtime_ref="runtime_main",
        download_ref="download_retry",
        status="completed",
        suggested_filename="result.csv",
    )
    assert fact.candidate_id == reservation.candidate_id

    correct = _agent_candidate(reservation.candidate_id, reservation.ordinal)
    session.register_candidate(
        reservation,
        correct,
        completed_at=BASE_TIME + timedelta(seconds=3),
    )
    assert session.outstanding_agent_reservation_count == 0


def test_session_accepts_only_outcome_from_its_settlement_engine() -> None:
    from rpa_agent.contracts import AcceptedSettlement, BrowserScope, CoreTrace

    session = _session()
    session.switch_control(ControlMode.AGENT, at=BASE_TIME)
    reservation = session.reserve_agent(
        "candidate_settle",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_settle",
    )
    candidate = _succeeded_agent_candidate(
        reservation.candidate_id, reservation.ordinal
    )
    session.register_candidate(
        reservation,
        candidate,
        completed_at=BASE_TIME + timedelta(seconds=1),
    )
    forged = AcceptedSettlement(
        candidate_id=candidate.candidate_id,
        status="accepted",
        core_trace=CoreTrace.model_validate(
            {
                "trace_id": "trace_forged",
                "sequence": candidate.ordinal,
                "scope": {"page_ref": "main", "frame_path": []},
                "action": {"kind": "agent", "instruction": "伪造步骤"},
                "data_bindings": [],
                "effects": [],
            }
        ),
    )
    with pytest.raises(ValueError, match="creation_session.direct_outcome_forbidden"):
        session.record_outcome(forged)

    outcome = session.settle_candidate(
        candidate.candidate_id,
        scope=BrowserScope(page_ref="main", frame_path=[]),
    )
    assert outcome.status == "accepted"
    assert session.accepted_traces[candidate.candidate_id].trace_id != "trace_forged"


def test_tail_deadline_controls_locked_fact_completion_and_expiry_cleanup() -> None:
    session = _session()
    reservation = session.reserve_manual(
        candidate_id="candidate_tail",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_tail",
    )
    session.ingest_manual(
        reservation,
        _event(
            ManualEventKind.CLICK,
            frame="frame_tail",
            interaction=InteractionKind.CLICK,
        ),
    )
    before = session.observer.start_navigation("runtime_main", "frame_tail")
    after = session.observer.start_dialog("runtime_main", "frame_tail")
    pending = session.observer.start_download("runtime_main", "frame_tail")
    session.switch_control(ControlMode.AGENT, at=BASE_TIME)

    before_fact = session.observer.complete_navigation(
        before,
        observed_at=BASE_TIME + timedelta(seconds=30),
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_tail",
        is_main_frame=True,
        url="https://example.test/before",
    )
    after_fact = session.observer.complete_dialog(
        after,
        observed_at=BASE_TIME + timedelta(seconds=61),
        page_runtime_ref="runtime_main",
        dialog_type="alert",
        response="accept",
    )
    assert before_fact.candidate_id == "candidate_tail"
    assert after_fact.candidate_id is None

    expired = session.expire_tail_windows(BASE_TIME + timedelta(seconds=61))
    assert expired == 1
    assert session.observer.pending_count == 0
    assert session.reservation_count == 0
    assert session.observer.cancel_trigger(pending) is False
    with pytest.raises(ValueError, match="candidate_window.reservation_mismatch"):
        session.registry.validate_reservations((reservation,))


def test_close_preflight_failure_preserves_all_short_lived_state() -> None:
    session = _session()
    valid = session.reserve_manual(
        candidate_id="candidate_close_valid",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_close_valid",
    )
    invalid = session.reserve_manual(
        candidate_id="candidate_close_invalid",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_close_invalid",
    )
    session.ingest_manual(valid, _event(ManualEventKind.BEFORE_INPUT, frame="frame_close_valid"))
    session.variables.write(
        "关闭测试",
        {"保留": True},
        producer_candidate_id="candidate_close_valid",
    )
    session.registry.expire(invalid)

    with pytest.raises(ValueError, match="candidate_window.reservation_mismatch"):
        session.close(at=BASE_TIME + timedelta(seconds=1))

    assert session.closed is False
    assert session.control_mode is ControlMode.HUMAN
    assert session.variables.read("关闭测试") == {"保留": True}
    assert session.reservation_count == 2


def test_normal_close_clears_page_registry_runtime_and_producer_state() -> None:
    session = _session()
    reservation = session.reserve_manual(
        candidate_id="candidate_page_cleanup",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
    )
    session.ingest_manual(
        reservation,
        _event(
            ManualEventKind.CLICK,
            frame="frame_main",
            interaction=InteractionKind.CLICK,
        ),
    )
    trigger = session.observer.start_new_page("runtime_main", "frame_main")
    fact = session.observer.complete_new_page(
        trigger,
        observed_at=BASE_TIME + timedelta(milliseconds=1),
        new_page_runtime_ref="runtime_random_token",
        initial_url="https://example.test/task/random-token",
    )
    session.pages.apply(fact)
    assert session.pages.runtime_state_count == 2

    session.close(at=BASE_TIME + timedelta(seconds=1))

    assert session.pages.runtime_state_count == 0
    assert session.pages.producer_snapshot() == {}
    with pytest.raises(ValueError, match="page_registry.runtime_page_unknown"):
        session.pages.resolve("runtime_random_token")


def _session_with_locked_tail(candidate_id: str):
    session = _session(candidate_id.replace("candidate", "session"))
    reservation = session.reserve_manual(
        candidate_id=candidate_id,
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_tail_boundary",
    )
    session.ingest_manual(
        reservation,
        _event(
            ManualEventKind.CLICK,
            frame="frame_tail_boundary",
            interaction=InteractionKind.CLICK,
        ),
    )
    trigger = session.observer.start_navigation(
        "runtime_main", "frame_tail_boundary"
    )
    session.switch_control(ControlMode.AGENT, at=BASE_TIME)
    return session, trigger


@pytest.mark.parametrize(
    ("offset_seconds", "expected_candidate_id"),
    [
        (59, "candidate_tail_before"),
        (60, None),
        (61, None),
    ],
)
def test_tail_deadline_is_half_open(
    offset_seconds: int, expected_candidate_id: str | None
) -> None:
    candidate_id = f"candidate_tail_{'before' if offset_seconds == 59 else offset_seconds}"
    session, trigger = _session_with_locked_tail(candidate_id)

    fact = session.observer.complete_navigation(
        trigger,
        observed_at=BASE_TIME + timedelta(seconds=offset_seconds),
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_tail_boundary",
        is_main_frame=True,
        url="https://example.test/boundary",
    )

    assert fact.candidate_id == expected_candidate_id


def test_tail_cleanup_before_or_after_deadline_has_same_no_association_result() -> None:
    completed, completed_trigger = _session_with_locked_tail(
        "candidate_tail_complete_first"
    )
    fact = completed.observer.complete_navigation(
        completed_trigger,
        observed_at=BASE_TIME + timedelta(seconds=60),
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_tail_boundary",
        is_main_frame=True,
        url="https://example.test/deadline",
    )
    assert fact.candidate_id is None
    assert completed.expire_tail_windows(BASE_TIME + timedelta(seconds=60)) == 1

    cleaned, pending_trigger = _session_with_locked_tail(
        "candidate_tail_cleanup_first"
    )
    assert cleaned.expire_tail_windows(BASE_TIME + timedelta(seconds=60)) == 1
    assert cleaned.observer.pending_count == 0
    with pytest.raises(ValueError, match="browser_fact.trigger_invalid_or_completed"):
        cleaned.observer.complete_navigation(
            pending_trigger,
            observed_at=BASE_TIME + timedelta(seconds=60),
            page_runtime_ref="runtime_main",
            frame_runtime_ref="frame_tail_boundary",
            is_main_frame=True,
            url="https://example.test/deadline",
        )
    assert all(
        item.candidate_id != "candidate_tail_cleanup_first"
        for item in cleaned.fact_buffer.facts()
    )


def test_outstanding_agent_reservation_blocks_switch_to_human_atomically() -> None:
    session = _session("session_agent_switch_guard")
    session.switch_control(ControlMode.AGENT, at=BASE_TIME)
    reservation = session.reserve_agent(
        "candidate_agent_outstanding",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_agent_outstanding",
    )
    session.variables.write(
        "守卫值", {"保留": True}, producer_candidate_id=reservation.candidate_id
    )
    before_pages = session.pages.runtime_state_count

    with pytest.raises(ValueError, match="creation_session.agent_reservation_outstanding"):
        session.switch_control(ControlMode.HUMAN, at=BASE_TIME + timedelta(seconds=1))

    assert session.control_mode is ControlMode.AGENT
    assert session.closed is False
    assert session.candidates == {}
    assert session.outstanding_agent_reservation_count == 1
    assert session.variables.read("守卫值") == {"保留": True}
    assert session.pages.runtime_state_count == before_pages
    candidate = _agent_candidate(reservation.candidate_id, reservation.ordinal)
    session.register_candidate(
        reservation,
        candidate,
        completed_at=BASE_TIME + timedelta(seconds=1),
    )
    session.switch_control(ControlMode.HUMAN, at=BASE_TIME + timedelta(seconds=2))
    assert session.control_mode is ControlMode.HUMAN


def test_outstanding_agent_reservation_blocks_close_without_cleanup() -> None:
    session = _session("session_agent_close_guard")
    session.switch_control(ControlMode.AGENT, at=BASE_TIME)
    reservation = session.reserve_agent(
        "candidate_agent_close_outstanding",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_agent_close",
    )
    session.variables.write(
        "关闭守卫", "仍存在", producer_candidate_id=reservation.candidate_id
    )
    before_facts = session.fact_buffer.facts()
    before_pages = session.pages.runtime_state_count

    with pytest.raises(ValueError, match="creation_session.agent_reservation_outstanding"):
        session.close(at=BASE_TIME + timedelta(seconds=1))

    assert session.control_mode is ControlMode.AGENT
    assert session.closed is False
    assert session.candidates == {}
    assert session.outstanding_agent_reservation_count == 1
    assert session.fact_buffer.facts() == before_facts
    assert session.variables.read("关闭守卫") == "仍存在"
    assert session.pages.runtime_state_count == before_pages
