from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from rpa_agent.creation.browser_facts import BrowserFactObserver, FactBuffer
from rpa_agent.creation.candidate_registry import ActiveCandidateRegistry
from rpa_agent.creation.page_registry import PageRegistry


NOW = datetime(2026, 7, 18, 1, 2, 3, tzinfo=timezone.utc)


def _observer(*, capacity: int = 20, ttl_seconds: int = 30):
    candidates = ActiveCandidateRegistry()
    buffer = FactBuffer(capacity=capacity, ttl=timedelta(seconds=ttl_seconds))
    return candidates, buffer, BrowserFactObserver(candidates, buffer)


class _CountingRegistry(ActiveCandidateRegistry):
    def __init__(self) -> None:
        super().__init__()
        self.lock_calls = 0

    def lock_fact(self, *, page_runtime_ref: str, frame_runtime_ref: str):
        self.lock_calls += 1
        return super().lock_fact(
            page_runtime_ref=page_runtime_ref,
            frame_runtime_ref=frame_runtime_ref,
        )


def test_six_fact_kinds_receive_one_atomic_monotonic_order() -> None:
    _, buffer, observer = _observer()

    navigation = observer.complete_navigation(
        observer.start_navigation("runtime_main", "frame_main"),
        observed_at=NOW,
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
        is_main_frame=True,
        url="https://example.test/orders",
    )
    new_page = observer.complete_new_page(
        observer.start_new_page("runtime_main", "frame_main"),
        observed_at=NOW + timedelta(milliseconds=1),
        new_page_runtime_ref="runtime_popup",
        initial_url="about:blank",
    )
    download = observer.complete_download(
        observer.start_download("runtime_main", "frame_main"),
        observed_at=NOW + timedelta(milliseconds=2),
        page_runtime_ref="runtime_main",
        download_ref="download_1",
        status="completed",
        suggested_filename="orders.xlsx",
    )
    dialog = observer.complete_dialog(
        observer.start_dialog("runtime_main", "frame_main"),
        observed_at=NOW + timedelta(milliseconds=3),
        page_runtime_ref="runtime_main",
        dialog_type="confirm",
        response="accept",
    )
    activated = observer.complete_page_activated(
        observer.start_page_activated("runtime_popup", "frame_main"),
        observed_at=NOW + timedelta(milliseconds=4),
        page_runtime_ref="runtime_popup",
    )
    closed = observer.complete_page_closed(
        observer.start_page_closed("runtime_popup", "frame_main"),
        observed_at=NOW + timedelta(milliseconds=5),
        page_runtime_ref="runtime_popup",
    )

    facts = (navigation, new_page, download, dialog, activated, closed)
    assert [fact.kind for fact in facts] == [
        "navigation", "new_page", "download", "dialog",
        "page_activated", "page_closed",
    ]
    assert [fact.observed_order for fact in facts] == list(range(1, 7))
    assert buffer.facts() == facts


def test_candidate_is_locked_at_trigger_not_async_completion() -> None:
    candidates, _, observer = _observer()
    reservation = candidates.reserve(
        candidate_id="cand_download",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
    )
    trigger = observer.start_download("runtime_main", "frame_main")
    candidates.close(reservation)

    fact = observer.complete_download(
        trigger,
        observed_at=NOW,
        page_runtime_ref="runtime_main",
        download_ref="download_1",
        status="completed",
        suggested_filename=None,
    )

    assert fact.candidate_id == "cand_download"


def test_null_trigger_never_back_attaches_to_a_later_candidate() -> None:
    candidates, _, observer = _observer()
    trigger = observer.start_new_page("runtime_main", "frame_main")
    candidates.reserve(
        candidate_id="cand_later",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
    )

    fact = observer.complete_new_page(
        trigger,
        observed_at=NOW,
        new_page_runtime_ref="runtime_popup",
        initial_url="https://example.test/random?token=secret",
    )

    assert fact.candidate_id is None


def test_new_page_lock_uses_opener_but_runtime_scope_is_new_page() -> None:
    candidates, _, observer = _observer()
    candidates.reserve(
        candidate_id="cand_popup",
        page_runtime_ref="runtime_opener",
        frame_runtime_ref="frame_iframe",
    )

    fact = observer.complete_new_page(
        observer.start_new_page("runtime_opener", "frame_iframe"),
        observed_at=NOW,
        new_page_runtime_ref="runtime_random_9c39",
        initial_url="https://example.test/task/9c39?token=opaque",
    )

    assert fact.candidate_id == "cand_popup"
    assert fact.runtime_scope.page_runtime_ref == "runtime_random_9c39"


def test_page_activation_locks_source_scope_not_activated_page() -> None:
    candidates, _, observer = _observer()
    candidates.reserve(
        candidate_id="cand_switch",
        page_runtime_ref="runtime_opener",
        frame_runtime_ref="frame_main",
    )

    fact = observer.complete_page_activated(
        observer.start_page_activated("runtime_opener", "frame_main"),
        observed_at=NOW,
        page_runtime_ref="runtime_popup",
    )

    assert fact.candidate_id == "cand_switch"
    assert fact.runtime_scope.page_runtime_ref == "runtime_popup"


def test_capacity_failure_does_not_consume_trigger_or_candidate_lock() -> None:
    candidates, buffer, observer = _observer(capacity=1, ttl_seconds=2)
    candidates.reserve(
        candidate_id="cand_download",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
    )
    filler = observer.complete_page_activated(
        observer.start_page_activated("runtime_unowned", "frame_main"),
        observed_at=NOW,
        page_runtime_ref="runtime_unowned",
    )
    trigger = observer.start_download("runtime_main", "frame_main")
    with pytest.raises(ValueError, match="browser_fact_buffer.capacity_exceeded"):
        observer.complete_download(
            trigger,
            observed_at=NOW + timedelta(seconds=1),
            page_runtime_ref="runtime_main",
            download_ref="download_1",
            status="completed",
            suggested_filename="orders.xlsx",
        )

    assert buffer.expire(NOW + timedelta(seconds=3)) == 1
    replacement = observer.complete_download(
        trigger,
        observed_at=NOW + timedelta(seconds=3),
        page_runtime_ref="runtime_main",
        download_ref="download_1",
        status="completed",
        suggested_filename="orders.xlsx",
    )
    assert filler.candidate_id is None
    assert replacement.candidate_id == "cand_download"
    assert replacement.observed_order == 2


def test_shape_failure_does_not_consume_trigger_or_candidate_lock() -> None:
    candidates, _, observer = _observer()
    candidates.reserve(
        candidate_id="cand_download",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
    )
    trigger = observer.start_download("runtime_main", "frame_main")

    with pytest.raises(ValueError, match="download.completed_has_failure_reason"):
        observer.complete_download(
            trigger,
            observed_at=NOW,
            page_runtime_ref="runtime_main",
            download_ref="download_1",
            status="completed",
            suggested_filename=None,
            failure_reason="invalid",
        )

    fact = observer.complete_download(
        trigger,
        observed_at=NOW,
        page_runtime_ref="runtime_main",
        download_ref="download_1",
        status="completed",
        suggested_filename=None,
    )
    assert fact.candidate_id == "cand_download"


def test_page_lifecycle_capacity_failure_is_retryable_with_original_lock() -> None:
    candidates, buffer, observer = _observer(capacity=1, ttl_seconds=1)
    candidates.reserve(
        candidate_id="cand_close",
        page_runtime_ref="runtime_popup",
        frame_runtime_ref="frame_main",
    )
    observer.complete_page_activated(
        observer.start_page_activated("runtime_unowned", "frame_main"),
        observed_at=NOW,
        page_runtime_ref="runtime_unowned",
    )
    trigger = observer.start_page_closed("runtime_popup", "frame_main")
    with pytest.raises(ValueError, match="browser_fact_buffer.capacity_exceeded"):
        observer.complete_page_closed(
            trigger, observed_at=NOW, page_runtime_ref="runtime_popup"
        )

    buffer.expire(NOW + timedelta(seconds=2))
    fact = observer.complete_page_closed(
        trigger,
        observed_at=NOW + timedelta(seconds=2),
        page_runtime_ref="runtime_popup",
    )
    assert fact.candidate_id == "cand_close"


def test_pending_limit_is_checked_before_lock_and_cancel_is_one_shot() -> None:
    candidates = _CountingRegistry()
    buffer = FactBuffer(capacity=4, ttl=timedelta(seconds=30))
    observer = BrowserFactObserver(candidates, buffer, max_pending=1)
    reservation = candidates.reserve(
        candidate_id="cand_pending",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
    )
    trigger = observer.start_download("runtime_main", "frame_main")

    with pytest.raises(ValueError, match="browser_fact.pending_limit_exceeded"):
        observer.start_dialog("runtime_main", "frame_main")
    assert candidates.lock_calls == 1
    assert observer.pending_count == 1
    assert observer.cancel_trigger(trigger) is True
    assert observer.cancel_trigger(trigger) is False
    assert candidates.discard_fact_lock(trigger.locked_candidate) is False
    with pytest.raises(ValueError, match="browser_fact.trigger_invalid_or_completed"):
        observer.complete_download(
            trigger,
            observed_at=NOW,
            page_runtime_ref="runtime_main",
            download_ref="download_1",
            status="completed",
            suggested_filename=None,
        )
    candidates.close(reservation)
    candidates.expire(reservation)


def test_expire_and_clear_pending_release_registry_fact_locks() -> None:
    candidates, buffer, observer = _observer(capacity=4)
    reservation = candidates.reserve(
        candidate_id="cand_pending",
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
    )
    expired = observer.start_download("runtime_main", "frame_main")
    assert observer.expire_trigger(expired) is True
    assert observer.expire_trigger(expired) is False
    assert candidates.discard_fact_lock(expired.locked_candidate) is False

    first = observer.start_navigation("runtime_main", "frame_main")
    second = observer.start_dialog("runtime_main", "frame_main")
    assert observer.clear_pending() == 2
    assert observer.pending_count == 0
    assert candidates.discard_fact_lock(first.locked_candidate) is False
    assert candidates.discard_fact_lock(second.locked_candidate) is False
    candidates.close(reservation)
    candidates.expire(reservation)
    assert buffer.capacity == 4


def test_page_registry_allocates_stable_ref_without_url_or_runtime_id() -> None:
    _, _, observer = _observer()
    pages = PageRegistry(main_runtime_ref="runtime_main")
    fact = observer.complete_new_page(
        observer.start_new_page("runtime_main", "frame_main"),
        observed_at=NOW,
        new_page_runtime_ref="runtime_token_abc",
        initial_url="https://example.test/random/abc?token=sensitive",
    )

    assert pages.apply(fact) == "page_001"
    assert pages.resolve("runtime_token_abc") == "page_001"
    assert "token" not in pages.resolve("runtime_token_abc")
    assert pages.apply(fact) == "page_001"  # exact fact retry is idempotent


def test_page_registry_applies_order_activation_close_and_rejects_conflicts() -> None:
    _, _, observer = _observer()
    pages = PageRegistry(main_runtime_ref="runtime_main")
    created = observer.complete_new_page(
        observer.start_new_page("runtime_main", "frame_main"),
        observed_at=NOW,
        new_page_runtime_ref="runtime_popup",
        initial_url="about:blank",
    )
    activated = observer.complete_page_activated(
        observer.start_page_activated("runtime_popup", "frame_main"),
        observed_at=NOW + timedelta(milliseconds=1),
        page_runtime_ref="runtime_popup",
    )
    closed = observer.complete_page_closed(
        observer.start_page_closed("runtime_popup", "frame_main"),
        observed_at=NOW + timedelta(milliseconds=2),
        page_runtime_ref="runtime_popup",
    )
    pages.apply(created)
    pages.apply(activated)
    assert pages.active_page_ref == "page_001"
    pages.apply(closed)
    assert pages.active_page_ref == "main"
    assert pages.is_closed("page_001")

    with pytest.raises(ValueError, match="page_registry.observed_order_regressed"):
        pages.apply(activated.model_copy(update={"fact_id": "fact_late_retry"}))
    with pytest.raises(ValueError, match="page_registry.fact_id_conflict"):
        pages.apply(activated.model_copy(update={
            "fact_id": created.fact_id,
            "observed_order": closed.observed_order + 1,
        }))


def test_page_registry_revalidates_fact_before_any_state_change() -> None:
    _, _, observer = _observer()
    pages = PageRegistry(main_runtime_ref="runtime_main")
    valid = observer.complete_new_page(
        observer.start_new_page("runtime_main", "frame_main"),
        observed_at=NOW,
        new_page_runtime_ref="runtime_popup",
        initial_url="about:blank",
    )
    forged = valid.model_copy(update={"observed_order": 0})

    with pytest.raises(ValueError):
        pages.apply(forged)
    with pytest.raises(ValueError, match="page_registry.runtime_page_unknown"):
        pages.resolve("runtime_popup")
