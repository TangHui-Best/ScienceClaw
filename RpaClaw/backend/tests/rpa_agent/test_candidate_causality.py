from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

from rpa_agent.creation.candidate_registry import ActiveCandidateRegistry


def test_reservation_is_explicit_and_fact_trigger_locks_candidate() -> None:
    registry = ActiveCandidateRegistry()
    reservation = registry.reserve(
        candidate_id="cand_click",
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )

    locked = registry.lock_fact(
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )

    assert locked is not None
    assert locked.candidate_id == "cand_click"
    assert registry.complete_fact(locked) == "cand_click"
    registry.close(reservation)


def test_fact_lock_is_consumed_exactly_once() -> None:
    registry = ActiveCandidateRegistry()
    registry.reserve(
        candidate_id="cand_click",
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )
    locked = registry.lock_fact(
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )

    assert locked is not None
    assert registry.complete_fact(locked) == "cand_click"
    assert registry.complete_fact(locked) is None


def test_forged_fact_lock_is_rejected_without_consuming_real_lock() -> None:
    registry = ActiveCandidateRegistry()
    registry.reserve(
        candidate_id="cand_download",
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )
    locked = registry.lock_fact(
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )
    assert locked is not None
    forged = replace(locked)

    assert registry.complete_fact(forged) is None
    assert registry.complete_fact(locked) == "cand_download"


def test_tail_accepts_only_tokens_locked_before_close() -> None:
    registry = ActiveCandidateRegistry()
    reservation = registry.reserve(
        candidate_id="cand_download",
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )
    locked_at_trigger = registry.lock_fact(
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )
    registry.close(reservation)

    assert registry.lock_fact(
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    ) is None
    assert locked_at_trigger is not None
    assert registry.complete_fact(locked_at_trigger) == "cand_download"


def test_null_lifecycle_fact_cannot_be_back_attached_after_reservation() -> None:
    registry = ActiveCandidateRegistry()
    unowned = registry.lock_fact(
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )
    assert unowned is None

    registry.reserve(
        candidate_id="cand_later",
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )

    assert registry.complete_fact(unowned) is None


def test_expire_invalidates_locked_async_completion() -> None:
    registry = ActiveCandidateRegistry()
    reservation = registry.reserve(
        candidate_id="cand_expired",
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )
    locked = registry.lock_fact(
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )
    registry.close(reservation)
    registry.expire(reservation)

    assert locked is not None
    assert registry.complete_fact(locked) is None


def test_page_and_frame_windows_are_isolated() -> None:
    registry = ActiveCandidateRegistry()
    registry.reserve(
        candidate_id="cand_main",
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )
    registry.reserve(
        candidate_id="cand_iframe",
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_child",
    )
    registry.reserve(
        candidate_id="cand_popup",
        page_runtime_ref="runtime_page_b",
        frame_runtime_ref="runtime_frame_main",
    )

    main = registry.lock_fact(
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )
    iframe = registry.lock_fact(
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_child",
    )
    popup = registry.lock_fact(
        page_runtime_ref="runtime_page_b",
        frame_runtime_ref="runtime_frame_main",
    )

    assert (main and main.candidate_id, iframe and iframe.candidate_id, popup and popup.candidate_id) == (
        "cand_main",
        "cand_iframe",
        "cand_popup",
    )


def test_scope_cannot_be_silently_replaced_and_ids_are_session_unique() -> None:
    registry = ActiveCandidateRegistry()
    registry.reserve(
        candidate_id="cand_one",
        page_runtime_ref="runtime_page_a",
        frame_runtime_ref="runtime_frame_main",
    )

    with pytest.raises(ValueError, match="candidate_window.scope_occupied"):
        registry.reserve(
            candidate_id="cand_two",
            page_runtime_ref="runtime_page_a",
            frame_runtime_ref="runtime_frame_main",
        )
    with pytest.raises(ValueError, match="candidate_window.id_duplicate"):
        registry.reserve(
            candidate_id="cand_one",
            page_runtime_ref="runtime_page_b",
            frame_runtime_ref="runtime_frame_main",
        )


def test_public_registry_api_has_no_recency_guessing_method() -> None:
    public_names = {
        name
        for name, _ in inspect.getmembers(ActiveCandidateRegistry)
        if not name.startswith("_")
    }
    forbidden_fragments = ("latest", "most_recent", "recent")

    assert not {
        name for name in public_names if any(fragment in name for fragment in forbidden_fragments)
    }
