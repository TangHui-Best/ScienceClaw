from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from rpa_agent.contracts import TraceCandidate
from rpa_agent.creation.candidate_registry import (
    ActiveCandidateRegistry,
    CandidateReservation,
)
from rpa_agent.creation.manual_aggregator import (
    InteractionKind,
    ManualEvent,
    ManualEventKind,
    ManualInteractionAggregator,
)


NOW = datetime(2026, 7, 17, 10, 0, tzinfo=timezone.utc)


def _event(
    kind: ManualEventKind,
    *,
    page_runtime_ref: str = "runtime_page_a",
    frame_runtime_ref: str = "runtime_frame_main",
    target_key: str = "order-number",
    target_name: str = "订单号",
    target_locators: tuple[dict[str, object], ...] | None = None,
    target_path: tuple[dict[str, object], ...] = (),
    binding_hints: tuple[dict[str, object], ...] = (),
    interaction_kind: InteractionKind = InteractionKind.FILL,
    offset_ms: int = 0,
    value: str | None = None,
    checked: bool | None = None,
) -> ManualEvent:
    return ManualEvent(
        kind=kind,
        page_runtime_ref=page_runtime_ref,
        frame_runtime_ref=frame_runtime_ref,
        target_key=target_key,
        target_name=target_name,
        target_locators=target_locators
        or ({"strategy": "label", "value": target_name, "exact": True},),
        target_path=target_path,
        binding_hints=binding_hints,
        interaction_kind=interaction_kind,
        observed_at=NOW + timedelta(milliseconds=offset_ms),
        value=value,
        checked=checked,
    )


def _harness(
    candidate_id: str = "cand_input",
    *,
    page_runtime_ref: str = "runtime_page_a",
    frame_runtime_ref: str = "runtime_frame_main",
    allocate_ordinal=None,
) -> tuple[ActiveCandidateRegistry, CandidateReservation, ManualInteractionAggregator]:
    registry = ActiveCandidateRegistry()
    reservation = registry.reserve(
        candidate_id=candidate_id,
        page_runtime_ref=page_runtime_ref,
        frame_runtime_ref=frame_runtime_ref,
    )
    return (
        registry,
        reservation,
        ManualInteractionAggregator(
            registry=registry,
            allocate_ordinal=allocate_ordinal,
        ),
    )


def test_continuous_input_events_form_one_fill_candidate() -> None:
    assigned: list[int] = []

    def allocate_ordinal() -> int:
        ordinal = len(assigned) + 1
        assigned.append(ordinal)
        return ordinal

    registry, reservation, aggregator = _harness(allocate_ordinal=allocate_ordinal)
    streams = [
        _event(ManualEventKind.FOCUS),
        _event(ManualEventKind.BEFORE_INPUT, offset_ms=1),
        _event(ManualEventKind.INPUT, offset_ms=2, value="P"),
        _event(ManualEventKind.INPUT, offset_ms=3, value="PO-"),
        _event(ManualEventKind.CHANGE, offset_ms=4, value="PO-1001"),
        _event(ManualEventKind.BLUR, offset_ms=5),
    ]

    emitted = [
        candidate
        for event in streams
        for candidate in aggregator.ingest(reservation, event)
    ]

    assert assigned == [1]
    assert len(emitted) == 1
    candidate = emitted[0]
    assert isinstance(candidate, TraceCandidate)
    assert candidate.candidate_id == "cand_input"
    assert candidate.ordinal == 1
    assert candidate.origin == "human"
    assert candidate.action_hint.kind == "fill"
    assert candidate.binding_hints[0].value == "PO-1001"
    assert candidate.execution.status == "succeeded"
    registry.close(reservation)


def test_manual_same_name_row_click_preserves_explicit_path_and_binding() -> None:
    _, reservation, aggregator = _harness(candidate_id="cand_row")
    path_step = {
        "name": "Matching order row",
        "locators": [{"strategy": "role", "role": "row"}],
        "filter_binding": "row_key",
    }
    binding = {
        "name": "row_key",
        "direction": "input",
        "kind_hint": "skill_input",
        "ref_hint": "query.order_no",
        "sensitive": False,
    }
    event = _event(
        ManualEventKind.CLICK,
        target_name="Start acceptance",
        target_locators=(
            {"strategy": "role", "role": "button", "name": "Start acceptance", "exact": True},
        ),
        target_path=(path_step,),
        binding_hints=(binding,),
        interaction_kind=InteractionKind.CLICK,
    )
    path_step["filter_binding"] = "tampered"
    binding["ref_hint"] = "query.tampered"

    candidate = aggregator.ingest(reservation, event)[0]

    assert candidate.action_hint.target_hint.path[0].filter_binding == "row_key"
    assert candidate.binding_hints[0].name == "row_key"
    assert candidate.binding_hints[0].ref_hint == "query.order_no"


def test_manual_explicit_target_metadata_is_validated_by_candidate_contract() -> None:
    _, reservation, aggregator = _harness(candidate_id="cand_bad_row")
    event = _event(
        ManualEventKind.CLICK,
        target_path=(
            {
                "name": "Invalid row",
                "locators": [{"strategy": "role", "role": "row"}],
                "filter_binding": "missing_binding",
            },
        ),
        binding_hints=(
            {
                "name": "missing_binding",
                "direction": "sideways",
                "kind_hint": "skill_input",
                "ref_hint": "query.order_no",
                "sensitive": False,
            },
        ),
        interaction_kind=InteractionKind.CLICK,
    )

    with pytest.raises(ValueError):
        aggregator.ingest(reservation, event)


def test_ordinal_is_reserved_on_first_semantic_event_not_close_order() -> None:
    registry = ActiveCandidateRegistry()
    first_reservation = registry.reserve(
        candidate_id="cand_a",
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )
    second_reservation = registry.reserve(
        candidate_id="cand_b",
        page_runtime_ref="runtime_page_b",
        frame_runtime_ref="runtime_frame_main",
    )
    next_ordinal = iter((11, 12))
    aggregator = ManualInteractionAggregator(
        registry=registry, allocate_ordinal=lambda: next(next_ordinal)
    )

    event_a = _event(ManualEventKind.BEFORE_INPUT, offset_ms=1)
    event_b = _event(
        ManualEventKind.BEFORE_INPUT,
        page_runtime_ref="runtime_page_b",
        target_key="supplier",
        offset_ms=2,
    )
    aggregator.ingest(first_reservation, event_a)
    aggregator.ingest(second_reservation, event_b)
    aggregator.ingest(
        second_reservation,
        replace(
            event_b,
            kind=ManualEventKind.INPUT,
            value="乙方",
            observed_at=NOW + timedelta(milliseconds=3),
        ),
    )
    second = aggregator.ingest(
        second_reservation,
        replace(
            event_b,
            kind=ManualEventKind.BLUR,
            observed_at=NOW + timedelta(milliseconds=4),
        ),
    )
    aggregator.ingest(
        first_reservation,
        replace(
            event_a,
            kind=ManualEventKind.INPUT,
            value="PO-A",
            observed_at=NOW + timedelta(milliseconds=5),
        ),
    )
    first = aggregator.ingest(
        first_reservation,
        replace(
            event_a,
            kind=ManualEventKind.BLUR,
            observed_at=NOW + timedelta(milliseconds=6),
        ),
    )

    assert [candidate.ordinal for candidate in second + first] == [12, 11]


def test_ime_intermediate_values_are_not_committed() -> None:
    _, reservation, aggregator = _harness()
    events = [
        _event(ManualEventKind.FOCUS),
        _event(ManualEventKind.COMPOSITION_START, offset_ms=1),
        _event(ManualEventKind.BEFORE_INPUT, offset_ms=2),
        _event(ManualEventKind.INPUT, offset_ms=3, value="g"),
        _event(ManualEventKind.INPUT, offset_ms=4, value="gong"),
    ]
    assert [
        candidate
        for event in events
        for candidate in aggregator.ingest(reservation, event)
    ] == []

    aggregator.ingest(
        reservation,
        _event(ManualEventKind.COMPOSITION_END, offset_ms=5, value="供应商"),
    )
    aggregator.ingest(
        reservation,
        _event(ManualEventKind.CHANGE, offset_ms=6, value="供应商甲"),
    )
    emitted = aggregator.ingest(
        reservation, _event(ManualEventKind.BLUR, offset_ms=7)
    )

    assert len(emitted) == 1
    assert emitted[0].binding_hints[0].value == "供应商甲"


def test_label_click_and_checkbox_change_form_one_set_checked_candidate() -> None:
    _, reservation, aggregator = _harness(candidate_id="cand_checkbox")
    click = _event(
        ManualEventKind.CLICK,
        target_key="urgent",
        interaction_kind=InteractionKind.SET_CHECKED,
    )
    change = replace(click, kind=ManualEventKind.CHANGE, checked=True)

    assert aggregator.ingest(reservation, click) == ()
    emitted = aggregator.ingest(reservation, change)

    assert len(emitted) == 1
    assert emitted[0].action_hint.kind == "set_checked"
    assert emitted[0].action_hint.checked is True
    assert emitted[0].binding_hints == []
    assert aggregator.flush_all(NOW + timedelta(seconds=1)) == ()


def test_plain_icon_click_emits_one_candidate_and_keeps_fact_window_active() -> None:
    registry, reservation, aggregator = _harness(candidate_id="cand_search")
    icon_click = _event(
        ManualEventKind.CLICK,
        target_key="search-icon",
        target_name="查询",
        target_locators=({"strategy": "title", "value": "查询", "exact": True},),
        interaction_kind=InteractionKind.CLICK,
    )

    emitted = aggregator.ingest(reservation, icon_click)

    assert len(emitted) == 1
    assert emitted[0].candidate_id == "cand_search"
    assert emitted[0].action_hint.kind == "click"
    assert emitted[0].action_hint.target_hint.locators[0].strategy == "title"
    assert emitted[0].binding_hints == []
    locked = registry.lock_fact(
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )
    assert locked is not None
    registry.close(reservation)
    assert registry.complete_fact(locked) == "cand_search"


def test_same_reservation_cannot_emit_a_second_candidate() -> None:
    _, reservation, aggregator = _harness(candidate_id="cand_search")
    icon_click = _event(
        ManualEventKind.CLICK,
        interaction_kind=InteractionKind.CLICK,
    )
    assert len(aggregator.ingest(reservation, icon_click)) == 1

    with pytest.raises(ValueError, match="manual_window.already_emitted"):
        aggregator.ingest(reservation, icon_click)


@pytest.mark.parametrize("open_window", ["fill", "checkbox"])
def test_open_window_rejects_plain_click_for_same_reservation(open_window: str) -> None:
    _, reservation, aggregator = _harness(candidate_id="cand_one_action")
    if open_window == "fill":
        first = _event(ManualEventKind.BEFORE_INPUT)
    else:
        first = _event(
            ManualEventKind.CLICK,
            interaction_kind=InteractionKind.SET_CHECKED,
        )
    aggregator.ingest(reservation, first)

    with pytest.raises(ValueError, match="manual_window.reservation_has_open_window"):
        aggregator.ingest(
            reservation,
            _event(
                ManualEventKind.CLICK,
                target_key="other-target",
                interaction_kind=InteractionKind.CLICK,
                offset_ms=1,
            ),
        )

    if open_window == "fill":
        aggregator.ingest(
            reservation,
            _event(ManualEventKind.INPUT, value="one", offset_ms=2),
        )
        emitted = aggregator.ingest(
            reservation, _event(ManualEventKind.BLUR, offset_ms=3)
        )
    else:
        emitted = aggregator.ingest(
            reservation,
            _event(
                ManualEventKind.CHANGE,
                interaction_kind=InteractionKind.SET_CHECKED,
                checked=True,
                offset_ms=2,
            ),
        )
    assert len(emitted) == 1
    assert emitted[0].candidate_id == "cand_one_action"


def test_window_rejects_regressed_event_time_and_keeps_prior_state() -> None:
    _, reservation, aggregator = _harness()
    aggregator.ingest(
        reservation, _event(ManualEventKind.BEFORE_INPUT, offset_ms=2)
    )
    aggregator.ingest(
        reservation, _event(ManualEventKind.INPUT, value="kept", offset_ms=3)
    )

    with pytest.raises(ValueError, match="manual_event.observed_at_regressed"):
        aggregator.ingest(
            reservation, _event(ManualEventKind.INPUT, value="stale", offset_ms=1)
        )

    emitted = aggregator.ingest(
        reservation, _event(ManualEventKind.BLUR, offset_ms=4)
    )
    assert emitted[0].binding_hints[0].value == "kept"


def test_focus_event_cannot_move_an_existing_window_clock_backwards() -> None:
    _, reservation, aggregator = _harness()
    aggregator.ingest(
        reservation, _event(ManualEventKind.BEFORE_INPUT, offset_ms=2)
    )

    with pytest.raises(ValueError, match="manual_event.observed_at_regressed"):
        aggregator.ingest(
            reservation, _event(ManualEventKind.FOCUS, offset_ms=1)
        )


def test_flush_rejects_regressed_end_time_and_keeps_window() -> None:
    _, reservation, aggregator = _harness()
    aggregator.ingest(
        reservation, _event(ManualEventKind.BEFORE_INPUT, offset_ms=2)
    )
    aggregator.ingest(
        reservation, _event(ManualEventKind.INPUT, value="kept", offset_ms=3)
    )

    with pytest.raises(ValueError, match="manual_event.ended_at_regressed"):
        aggregator.flush_all(NOW + timedelta(milliseconds=1))

    emitted = aggregator.flush_all(NOW + timedelta(milliseconds=4))
    assert emitted[0].binding_hints[0].value == "kept"


def test_cancel_rejects_regressed_end_time_and_keeps_window_active() -> None:
    registry, reservation, aggregator = _harness()
    aggregator.ingest(
        reservation, _event(ManualEventKind.BEFORE_INPUT, offset_ms=2)
    )

    with pytest.raises(ValueError, match="manual_event.ended_at_regressed"):
        aggregator.cancel(reservation, NOW + timedelta(milliseconds=1))
    assert registry.validate_active(
        reservation,
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    ) == "cand_input"

    cancelled = aggregator.cancel(
        reservation, NOW + timedelta(milliseconds=3)
    )
    assert cancelled.execution.status == "cancelled"


def test_target_locators_are_snapshotted_when_window_starts() -> None:
    _, reservation, aggregator = _harness()
    mutable_locator: dict[str, object] = {
        "strategy": "label",
        "value": "订单号",
        "exact": True,
    }
    before_input = _event(
        ManualEventKind.BEFORE_INPUT,
        target_locators=(mutable_locator,),
    )
    aggregator.ingest(reservation, before_input)
    mutable_locator["value"] = "已被外部修改"
    aggregator.ingest(
        reservation,
        _event(ManualEventKind.INPUT, value="PO-1", offset_ms=1),
    )

    emitted = aggregator.ingest(
        reservation, _event(ManualEventKind.BLUR, offset_ms=2)
    )
    assert emitted[0].action_hint.target_hint.locators[0].value == "订单号"


@pytest.mark.parametrize("state", ["forged", "wrong_scope", "closed", "expired"])
def test_every_event_requires_matching_active_reservation(state: str) -> None:
    registry, reservation, aggregator = _harness()
    event = _event(ManualEventKind.BEFORE_INPUT)

    if state == "forged":
        invalid = CandidateReservation(
            candidate_id=reservation.candidate_id,
            page_runtime_ref=reservation.page_runtime_ref,
            frame_runtime_ref=reservation.frame_runtime_ref,
            window_id=reservation.window_id,
        )
    elif state == "wrong_scope":
        invalid = reservation
        event = replace(event, page_runtime_ref="runtime_page_b")
    elif state == "closed":
        registry.close(reservation)
        invalid = reservation
    else:
        registry.expire(reservation)
        invalid = reservation

    with pytest.raises(ValueError, match="candidate_window"):
        aggregator.ingest(invalid, event)


@pytest.mark.parametrize("incomplete", ["ime", "fill", "checkbox"])
def test_flush_all_is_atomic_and_keeps_incomplete_windows(incomplete: str) -> None:
    registry, reservation, aggregator = _harness()
    if incomplete == "ime":
        aggregator.ingest(reservation, _event(ManualEventKind.COMPOSITION_START))
    elif incomplete == "fill":
        aggregator.ingest(reservation, _event(ManualEventKind.BEFORE_INPUT))
    else:
        aggregator.ingest(
            reservation,
            _event(
                ManualEventKind.CLICK,
                interaction_kind=InteractionKind.SET_CHECKED,
            ),
        )

    with pytest.raises(ValueError, match="manual_window.incomplete"):
        aggregator.flush_all(NOW + timedelta(seconds=1))
    cancelled = aggregator.cancel(reservation, NOW + timedelta(seconds=2))

    assert cancelled.candidate_id == "cand_input"
    assert cancelled.execution.status == "cancelled"
    with pytest.raises(ValueError, match="candidate_window.not_active"):
        registry.validate_active(
            reservation,
            page_runtime_ref="runtime_page_a",
            frame_runtime_ref="runtime_frame_main",
        )
    assert aggregator.flush_all(NOW + timedelta(seconds=3)) == ()


def test_flush_all_keeps_complete_windows_when_another_window_is_incomplete() -> None:
    registry = ActiveCandidateRegistry()
    complete = registry.reserve(
        candidate_id="cand_complete",
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )
    incomplete = registry.reserve(
        candidate_id="cand_incomplete",
        page_runtime_ref="runtime_page_b",
        frame_runtime_ref="runtime_frame_main",
    )
    aggregator = ManualInteractionAggregator(registry=registry)
    aggregator.ingest(complete, _event(ManualEventKind.BEFORE_INPUT))
    aggregator.ingest(
        complete, _event(ManualEventKind.INPUT, value="kept", offset_ms=1)
    )
    aggregator.ingest(
        incomplete,
        _event(
            ManualEventKind.BEFORE_INPUT,
            page_runtime_ref="runtime_page_b",
            offset_ms=2,
        ),
    )

    with pytest.raises(ValueError, match="manual_window.incomplete:cand_incomplete"):
        aggregator.flush_all(NOW + timedelta(seconds=1))
    aggregator.cancel(incomplete, NOW + timedelta(seconds=2))

    emitted = aggregator.flush_all(NOW + timedelta(seconds=3))
    assert len(emitted) == 1
    assert emitted[0].candidate_id == "cand_complete"
    assert emitted[0].binding_hints[0].value == "kept"


def test_flush_all_closes_complete_aggregation_window_without_expiring_fact_tail() -> None:
    registry, reservation, aggregator = _harness()
    aggregator.ingest(reservation, _event(ManualEventKind.BEFORE_INPUT))
    aggregator.ingest(
        reservation, _event(ManualEventKind.INPUT, value="draft", offset_ms=1)
    )
    locked = registry.lock_fact(
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )

    emitted = aggregator.flush_all(NOW + timedelta(milliseconds=2))

    assert len(emitted) == 1
    assert emitted[0].binding_hints[0].value == "draft"
    registry.close(reservation)
    assert locked is not None
    assert registry.complete_fact(locked) == "cand_input"
