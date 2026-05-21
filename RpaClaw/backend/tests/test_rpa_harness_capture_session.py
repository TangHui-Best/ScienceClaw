from backend.rpa.harness.capture import HarnessCaptureSessionState
from backend.rpa.manager import RPASession, RPASessionManager


def _manager_with_session() -> RPASessionManager:
    manager = RPASessionManager()
    manager.sessions["session-1"] = RPASession(
        id="session-1",
        user_id="user-1",
        sandbox_session_id="sandbox-1",
    )
    return manager


def test_capture_session_is_absent_by_default_when_gate_disabled():
    manager = _manager_with_session()

    result = manager.start_harness_capture(
        "session-1",
        capture_scope="full_sop",
        enabled=False,
    )

    assert result is None
    assert manager.get_harness_capture_session("session-1") is None


def test_capture_session_stores_full_sop_scope_when_enabled():
    manager = _manager_with_session()

    result = manager.start_harness_capture(
        "session-1",
        capture_scope="full_sop",
        enabled=True,
    )

    assert isinstance(result, HarnessCaptureSessionState)
    assert result.session_id == "session-1"
    assert result.capture_scope == "full_sop"
    assert result.selected_step_indexes == []


def test_capture_session_stores_selected_step_scope_and_marked_steps():
    manager = _manager_with_session()

    manager.start_harness_capture(
        "session-1",
        capture_scope="selected_steps",
        enabled=True,
    )
    state = manager.mark_harness_step_selected("session-1", step_index=3)

    assert state is not None
    assert state.capture_scope == "selected_steps"
    assert state.selected_step_indexes == [3]


def test_capture_session_deduplicates_selected_steps():
    manager = _manager_with_session()

    manager.start_harness_capture(
        "session-1",
        capture_scope="selected_steps",
        enabled=True,
    )
    manager.mark_harness_step_selected("session-1", step_index=2)
    state = manager.mark_harness_step_selected("session-1", step_index=2)

    assert state is not None
    assert state.selected_step_indexes == [2]


def test_selected_capture_can_mark_next_natural_language_step_without_fixed_index():
    manager = _manager_with_session()

    manager.start_harness_capture(
        "session-1",
        capture_scope="selected_steps",
        enabled=True,
    )
    state = manager.mark_harness_next_natural_language_step_selected("session-1")

    assert state is not None
    assert state.pending_natural_language_step_captures == 1
    assert state.should_capture_step(9) is True


def test_selected_next_natural_language_mark_is_idempotent():
    manager = _manager_with_session()

    manager.start_harness_capture(
        "session-1",
        capture_scope="selected_steps",
        enabled=True,
    )
    manager.mark_harness_next_natural_language_step_selected("session-1")
    state = manager.mark_harness_next_natural_language_step_selected("session-1")

    assert state is not None
    assert state.pending_natural_language_step_captures == 1


def test_full_sop_capture_does_not_store_selected_step_marks():
    manager = _manager_with_session()

    manager.start_harness_capture(
        "session-1",
        capture_scope="full_sop",
        enabled=True,
    )
    state = manager.mark_harness_step_selected("session-1", step_index=1)

    assert state is not None
    assert state.selected_step_indexes == []
