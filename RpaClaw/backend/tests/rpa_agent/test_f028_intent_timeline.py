from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rpa_agent.creation.session import SkillCreationSession
from rpa_agent.contracts import validate_timeline_payload


NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


def _session() -> SkillCreationSession:
    return SkillCreationSession(
        session_id="creation_f028",
        main_runtime_ref="runtime_main",
        fact_buffer_capacity=32,
        fact_ttl=timedelta(seconds=30),
    )


def test_ai_instruction_is_top_level_before_browser_use_starts() -> None:
    session = _session()

    step, ordinal = session.queue_ai_instruction(
        step_id="ais_open_skill_repo",
        instruction="打开和 skill 最相关的项目",
        model_ref="model-config-uuid",
        context_snapshot_ref="ctx_open_skill_repo",
        created_at=NOW,
    )

    timeline = session.recording_timeline()
    assert ordinal == 1
    assert step.execution.status == "queued"
    assert len(timeline.items) == 1
    assert timeline.items[0].step_id == step.step_id
    assert timeline.items[0].instruction == "打开和 skill 最相关的项目"


def test_manual_navigate_is_formal_trace_without_redundant_navigation_effect() -> None:
    session = _session()
    session.begin_manual_draft(draft_id="draft_open_trending")

    trace = session.complete_manual_navigation(
        draft_id="draft_open_trending",
        trace_id="trace_open_trending",
        ordinal=1,
        page_ref="main",
        url="https://github.com/trending",
    )

    assert trace.effects == []
    validate_timeline_payload(
        {
            "schema_version": "core-trace/v0.1",
            "traces": [trace.model_dump(mode="python", exclude_unset=True)],
        }
    )


def test_browser_use_execution_updates_same_ai_item_without_duplicate_top_level_rows() -> None:
    session = _session()
    session.queue_ai_instruction(
        step_id="ais_open_skill_repo",
        instruction="打开和 skill 最相关的项目",
        model_ref="model-config-uuid",
        context_snapshot_ref="ctx_open_skill_repo",
        created_at=NOW,
    )

    session.mark_ai_instruction_running(
        "ais_open_skill_repo", started_at=NOW + timedelta(milliseconds=1)
    )
    session.finish_ai_instruction(
        "ais_open_skill_repo",
        finished_at=NOW + timedelta(seconds=2),
        succeeded=True,
        result_summary="已打开项目",
    )

    timeline = session.recording_timeline()
    assert len(timeline.items) == 1
    assert timeline.items[0].execution.status == "succeeded"
    assert timeline.items[0].execution.result_summary == "已打开项目"


def test_failed_browser_use_keeps_original_ai_instruction() -> None:
    session = _session()
    session.queue_ai_instruction(
        step_id="ais_star",
        instruction="获取 star 数",
        model_ref="model-config-uuid",
        context_snapshot_ref="ctx_star",
        created_at=NOW,
    )
    session.mark_ai_instruction_running("ais_star", started_at=NOW)
    session.finish_ai_instruction(
        "ais_star",
        finished_at=NOW + timedelta(seconds=1),
        succeeded=False,
        error_code="provider_quota_exhausted",
        error_message="provider quota exhausted",
    )

    step = session.recording_timeline().items[0]
    assert step.instruction == "获取 star 数"
    assert step.execution.status == "failed"
    assert step.execution.error_code == "provider_quota_exhausted"
