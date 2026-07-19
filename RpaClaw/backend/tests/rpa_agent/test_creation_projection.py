from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict
from datetime import datetime, timedelta, timezone
import json

import pytest

from rpa_agent.contracts import (
    AcceptedSettlement,
    CoreTrace,
    Diagnostic,
    RejectedSettlement,
    TraceCandidate,
)
from rpa_agent.creation import (
    ControlMode,
    ProjectionStatus,
    SkillCreationSession,
    project_creation_steps,
)


NOW = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)


def _session() -> SkillCreationSession:
    return SkillCreationSession(
        session_id="session_projection",
        main_runtime_ref="runtime_main",
        fact_buffer_capacity=10,
        fact_ttl=timedelta(minutes=1),
    )


def _reserve(session: SkillCreationSession, candidate_id: str):
    return session.reserve_agent(
        candidate_id,
        page_runtime_ref="runtime_main",
        frame_runtime_ref=f"frame_{candidate_id}",
    )


def _candidate(
    candidate_id: str,
    ordinal: int,
    *,
    action_kind: str = "agent",
    literal: str | None = None,
) -> TraceCandidate:
    if action_kind == "fill":
        action_hint = {
            "kind": "fill",
            "target_hint": {
                "name": "密码",
                "locators": [
                    {"strategy": "label", "value": "密码", "exact": True}
                ],
            },
        }
        bindings = [
            {
                "name": "value",
                "direction": "input",
                "kind_hint": "literal",
                "value": literal,
                "sensitive": True,
            }
        ]
    else:
        action_hint = {"kind": "agent", "instruction": "执行单个业务动作"}
        bindings = []
    return TraceCandidate.model_validate(
        {
            "candidate_id": candidate_id,
            "ordinal": ordinal,
            "origin": "agent",
            "scope_hint": {"page_ref": "main", "frame_path": []},
            "action_hint": action_hint,
            "binding_hints": bindings,
            "execution": {
                "status": "running",
                "started_at": NOW,
                "ended_at": None,
                "output": None,
                "error": None,
            },
        }
    )


def _accepted_trace() -> CoreTrace:
    return CoreTrace.model_validate(
        {
            "trace_id": "trace_accepted",
            "sequence": 2,
            "scope": {"page_ref": "main", "frame_path": []},
            "action": {
                "kind": "click",
                "target": {
                    "name": "导出",
                    "locators": [
                        {
                            "strategy": "role",
                            "role": "button",
                            "name": "导出",
                            "exact": True,
                        }
                    ],
                },
                "button": "left",
                "count": 1,
            },
            "data_bindings": [
                {
                    "name": "downloaded_file",
                    "direction": "output",
                    "kind": "data_asset",
                    "ref": "orders_export",
                    "sensitive": False,
                }
            ],
            "effects": [
                {"kind": "new_page", "page_ref": "page_001"},
                {"kind": "download", "binding": "downloaded_file"},
            ],
        }
    )


def test_projection_unifies_four_candidate_states_and_effect_children_without_duplicates() -> None:
    pending = _candidate("candidate_pending", 1)
    accepted = _candidate("candidate_accepted", 2)
    rejected = _candidate("candidate_rejected", 3)
    deleted = _candidate("candidate_deleted", 4)
    trace = _accepted_trace()
    rows = project_creation_steps(
        candidates={
            candidate.candidate_id: candidate
            for candidate in (deleted, rejected, accepted, pending)
        },
        accepted_traces={accepted.candidate_id: trace},
        diagnostics={
            rejected.candidate_id: Diagnostic(
                code="action_not_replayable",
                message="该动作无法形成回放步骤",
            )
        },
        deleted_candidate_ids={deleted.candidate_id},
        include_deleted=True,
    )

    assert [(row.candidate_id, row.status, row.is_action) for row in rows] == [
        ("candidate_pending", ProjectionStatus.PENDING, True),
        ("candidate_accepted", ProjectionStatus.ACCEPTED, True),
        ("candidate_accepted", ProjectionStatus.EFFECT, False),
        ("candidate_accepted", ProjectionStatus.EFFECT, False),
        ("candidate_rejected", ProjectionStatus.REJECTED, True),
        ("candidate_deleted", ProjectionStatus.DELETED, True),
    ]
    accepted_rows = [row for row in rows if row.candidate_id == "candidate_accepted"]
    assert sum(row.is_action for row in accepted_rows) == 1
    assert [row.effect_kind for row in accepted_rows[1:]] == ["new_page", "download"]
    assert all(
        row.parent_trace_id == "trace_accepted"
        and row.trace_id is None
        and row.sequence is None
        for row in accepted_rows[1:]
    )
    assert len({trace.trace_id}) == 1


def test_projection_is_immutable_fresh_and_omits_sensitive_or_runtime_payloads() -> None:
    session = _session()
    session.switch_control(ControlMode.AGENT, at=NOW)
    pending = _candidate(
        "candidate_sensitive",
        1,
        action_kind="fill",
        literal="RECORDED-SECRET-VALUE",
    )
    reservation = _reserve(session, pending.candidate_id)
    session.register_candidate(
        reservation,
        pending,
        completed_at=NOW + timedelta(milliseconds=1),
    )

    first = session.creation_projection()
    second = session.creation_projection()
    serialized = json.dumps([asdict(row) for row in first], ensure_ascii=False)

    assert first == second
    assert first[0] is not second[0]
    assert "RECORDED-SECRET-VALUE" not in serialized
    assert "runtime_main" not in serialized
    assert "BrowserFact" not in serialized
    assert "History" not in serialized
    with pytest.raises(FrozenInstanceError):
        first[0].title = "mutated"


def test_deleted_rows_are_optional_without_changing_other_order() -> None:
    session = _session()
    session.switch_control(ControlMode.AGENT, at=NOW)
    pending = _candidate("candidate_pending", 1)
    deleted = _candidate("candidate_deleted", 2)
    pending_reservation = _reserve(session, pending.candidate_id)
    deleted_reservation = _reserve(session, deleted.candidate_id)
    session.register_candidate(
        deleted_reservation,
        deleted,
        completed_at=NOW + timedelta(milliseconds=1),
    )
    session.register_candidate(
        pending_reservation,
        pending,
        completed_at=NOW + timedelta(milliseconds=1),
    )
    session.delete_candidate(deleted.candidate_id)

    visible = session.creation_projection(include_deleted=True)
    hidden = session.creation_projection(include_deleted=False)

    assert [row.candidate_id for row in visible] == [
        "candidate_pending",
        "candidate_deleted",
    ]
    assert [row.candidate_id for row in hidden] == ["candidate_pending"]


def test_rejected_projection_uses_safe_code_message_not_untrusted_diagnostic_text() -> None:
    rejected = _candidate("candidate_rejected", 1)
    rows = project_creation_steps(
        candidates={rejected.candidate_id: rejected},
        accepted_traces={},
        diagnostics={
            rejected.candidate_id: Diagnostic(
                code="scope_unresolved",
                message=(
                    "PO-SECRET https://example.test/task/random-token "
                    "runtime_page_99 token=super-secret"
                ),
            )
        },
        deleted_candidate_ids=set(),
    )

    serialized = json.dumps(
        [asdict(row) for row in rows], ensure_ascii=False
    )

    assert "页面作用域无法解析" in serialized
    assert "PO-SECRET" not in serialized
    assert "random-token" not in serialized
    assert "runtime_page_99" not in serialized
    assert "super-secret" not in serialized


def test_projection_titles_are_bounded_without_changing_step_identity() -> None:
    candidate = _candidate("candidate_long_title", 1, action_kind="fill", literal="x")
    long_target = candidate.model_dump(mode="python")
    long_target["action_hint"]["target_hint"].pop("path")
    long_target["action_hint"]["target_hint"].pop("index")
    long_target["binding_hints"][0].pop("ref_hint")
    long_target["action_hint"]["target_hint"]["name"] = "目标" * 100
    candidate = TraceCandidate.model_validate(long_target)

    row = project_creation_steps(
        candidates={candidate.candidate_id: candidate},
        accepted_traces={},
        diagnostics={},
        deleted_candidate_ids=set(),
    )[0]

    assert len(row.title) <= 120
    assert row.candidate_id == "candidate_long_title"
