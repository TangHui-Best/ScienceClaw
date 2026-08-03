from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from rpa_agent.contracts import CoreTrace
from rpa_agent.recording import AIInstructionStep, RecordingSession, RecordingTimeline


NOW = datetime(2026, 8, 2, tzinfo=timezone.utc)


def _navigation_trace(*, trace_id: str = "trace_1") -> CoreTrace:
    return CoreTrace.model_validate(
        {
            "trace_id": trace_id,
            "sequence": 1,
            "scope": {"page_ref": "page_1", "frame_path": []},
            "action": {"kind": "navigate", "mode": "url"},
            "data_bindings": [
                {
                    "name": "url",
                    "direction": "input",
                    "kind": "literal",
                    "value": "https://example.test",
                    "sensitive": False,
                }
            ],
            "effects": [],
        }
    )


def test_manual_draft_is_immediately_projected_but_never_serialized_as_timeline_item() -> None:
    session = RecordingSession(session_id="session_1")
    draft, ordinal = session.begin_manual_draft(draft_id="draft_1")

    assert ordinal == 1
    assert session.projection_items() == (draft,)
    assert session.timeline().items == []

    invalid = session.invalidate_manual_draft(
        draft_id="draft_1", diagnostic_code="target_unresolved"
    )
    assert invalid.capture_state == "invalid"
    assert invalid.diagnostic_codes == ["target_unresolved"]
    assert session.timeline().items == []


def test_only_a_valid_manual_fact_replaces_draft_with_core_trace() -> None:
    session = RecordingSession(session_id="session_1")
    session.begin_manual_draft(draft_id="draft_1")

    ordinal = session.freeze_manual_trace(
        draft_id="draft_1", trace=_navigation_trace()
    )

    assert ordinal == 1
    projection = session.projection_items()
    assert len(projection) == 1
    assert isinstance(projection[0], CoreTrace)
    assert session.timeline().schema_namespace == "rpa-agent-next/v1"


def test_ai_step_is_the_only_natural_language_timeline_item_and_rejects_f028_fields() -> None:
    session = RecordingSession(session_id="session_1")
    step, ordinal = session.queue_ai_instruction(
        step_id="step_1",
        instruction="打开设置页面",
        model_ref="model_1",
        context_snapshot_ref="context_1",
        created_at=NOW,
    )

    assert ordinal == 1
    assert session.timeline().items == [step]
    assert step.execution.status == "queued"
    payload = step.model_dump(mode="python")
    payload["expected_effects"] = []
    with pytest.raises(ValidationError):
        AIInstructionStep.model_validate(payload)
    payload.pop("expected_effects")
    payload["observation_trace_refs"] = []
    with pytest.raises(ValidationError):
        AIInstructionStep.model_validate(payload)


def test_ai_lifecycle_transitions_without_creating_core_trace_from_internal_history() -> None:
    session = RecordingSession(session_id="session_1")
    session.queue_ai_instruction(
        step_id="step_1",
        instruction="搜索订单",
        model_ref="model_1",
        context_snapshot_ref="context_1",
        created_at=NOW,
    )

    running = session.mark_ai_running(step_id="step_1", started_at=NOW)
    completed = session.finish_ai(
        step_id="step_1", finished_at=NOW, result_summary="已完成"
    )

    assert running.execution.status == "running"
    assert completed.execution.status == "succeeded"
    assert all(not isinstance(item, CoreTrace) for item in session.timeline().items)


def test_legacy_timeline_payload_is_rejected_before_it_can_enter_the_new_path() -> None:
    with pytest.raises(ValidationError):
        RecordingTimeline.model_validate(
            {
                "schema_version": "recording-timeline/v0.1",
                "session_id": "session_1",
                "items": [],
                "observed_traces": {},
            }
        )
