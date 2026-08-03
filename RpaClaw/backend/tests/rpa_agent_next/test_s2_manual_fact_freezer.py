from __future__ import annotations

from datetime import datetime, timezone

from rpa_agent.contracts.models import AcceptedSettlement, RejectedSettlement
from rpa_agent.creation.page_registry import PageRegistry
from rpa_agent.creation.settlement import SettlementEngine
from rpa_agent.creation.settlement import SettlementAttempt, SettlementAttemptStatus
from rpa_agent.recording import ManualFactFreezer, RecordingSession

from test_s2_recording_contracts import _navigation_trace


class _Settlement:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.calls = 0

    def settle(self, candidate, *, facts, scope, resolved_assets=None):
        self.calls += 1
        return self.outcome


def test_only_accepted_causal_settlement_freezes_manual_draft() -> None:
    session = RecordingSession(session_id="session_1")
    session.begin_manual_draft(draft_id="draft_1")
    trace = _navigation_trace()
    settlement = _Settlement(
        AcceptedSettlement(candidate_id="candidate_1", status="accepted", core_trace=trace)
    )

    result = ManualFactFreezer(settlement).settle_draft(
        session=session,
        draft_id="draft_1",
        candidate=object(),
        facts=(),
        scope=None,
    )

    assert result.state == "frozen"
    assert result.trace_id == "trace_1"
    assert session.timeline().items == [trace]


def test_rejected_manual_draft_never_becomes_an_ai_instruction_automatically() -> None:
    session = RecordingSession(session_id="session_1")
    session.begin_manual_draft(draft_id="draft_1")
    settlement = _Settlement(
        RejectedSettlement.model_validate(
            {
                "candidate_id": "candidate_1",
                "status": "rejected",
                "diagnostic": {
                    "code": "target_unresolved",
                    "message": "Target is not stable.",
                },
            }
        )
    )

    result = ManualFactFreezer(settlement).settle_draft(
        session=session,
        draft_id="draft_1",
        candidate=object(),
        facts=(),
        scope=None,
    )

    assert result.state == "invalid"
    assert session.timeline().items == []
    assert session.projection_items()[0].capture_state == "invalid"

    step, _ = session.queue_ai_instruction(
        step_id="step_1",
        instruction="请完成目标操作",
        model_ref="model_1",
        context_snapshot_ref="context_1",
        created_at=datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    assert session.timeline().items == [step]


def test_unclosed_facts_keep_draft_in_enriching_state() -> None:
    session = RecordingSession(session_id="session_1")
    session.begin_manual_draft(draft_id="draft_1")
    settlement = _Settlement(
        SettlementAttempt(
            candidate_id="candidate_1",
            status=SettlementAttemptStatus.WAITING,
            reason="execution_running",
        )
    )

    result = ManualFactFreezer(settlement).settle_draft(
        session=session,
        draft_id="draft_1",
        candidate=object(),
        facts=(),
        scope=None,
    )

    assert result.state == "enriching"
    draft = session.projection_items()[0]
    assert draft.capture_state == "enriching"
    assert draft.diagnostic_codes == ["execution_running"]


def test_real_causal_settlement_can_freeze_a_navigation_without_reading_old_timeline() -> None:
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    fact = {
        "fact_id": "fact_1",
        "observed_order": 1,
        "candidate_id": "candidate_1",
        "observed_at": now,
        "runtime_scope": {"page_runtime_ref": "runtime_page_1"},
        "kind": "navigation",
        "detail": {
            "frame_runtime_ref": "runtime_frame_1",
            "is_main_frame": True,
            "url": "https://example.test",
        },
    }
    candidate = {
        "candidate_id": "candidate_1",
        "ordinal": 1,
        "origin": "human",
        "scope_hint": {"page_ref": "main", "frame_path": []},
        "action_hint": {"kind": "navigate", "mode": "url"},
        "binding_hints": [
            {
                "name": "url",
                "direction": "input",
                "kind_hint": "literal",
                "value": "https://example.test",
                "sensitive": False,
            }
        ],
        "execution": {
            "status": "succeeded",
            "started_at": now,
            "ended_at": now,
            "output": None,
            "error": None,
        },
    }
    pages = PageRegistry(main_runtime_ref="runtime_page_1")
    from pydantic import TypeAdapter
    from rpa_agent.contracts.models import BrowserFact, BrowserScope, TraceCandidate

    browser_fact = TypeAdapter(BrowserFact).validate_python(fact)
    pages.apply(browser_fact)
    session = RecordingSession(session_id="session_1")
    session.begin_manual_draft(draft_id="draft_1")

    result = ManualFactFreezer(SettlementEngine(pages)).settle_draft(
        session=session,
        draft_id="draft_1",
        candidate=TraceCandidate.model_validate(candidate),
        facts=[browser_fact],
        scope=BrowserScope.model_validate({"page_ref": "main", "frame_path": []}),
    )

    assert result.state == "frozen"
    trace = session.timeline().items[0]
    assert trace.action.kind == "navigate"
