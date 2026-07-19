from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from rpa_agent.contracts import (
    AIInstructionStep,
    CompiledStep,
    CompilationConfiguration,
    CoreTraceDraft,
    RecordingTimeline,
    ReplayAssessment,
)
from rpa_agent.compiler import (
    assess_recording_timeline,
    compile_dual_mode_plan,
    materialize_core_trace_timeline,
)


NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
TARGET = {
    "name": "目标",
    "locators": [{"strategy": "test_id", "value": "target"}],
}


def _trace(trace_id: str = "trace_manual", sequence: int = 1) -> dict:
    return {
        "trace_id": trace_id,
        "sequence": sequence,
        "scope": {"page_ref": "main", "frame_path": []},
        "action": {"kind": "click", "target": TARGET},
        "data_bindings": [],
        "effects": [],
    }


def _ai_step(*, trace_refs: list[str] | None = None) -> dict:
    refs = trace_refs or []
    return {
        "step_id": "ais_open_skill_repo",
        "instruction": "打开和 skill 最相关的项目",
        "created_at": NOW,
        "execution": {
            "status": "succeeded",
            "started_at": NOW,
            "finished_at": NOW,
            "result_summary": "已打开项目",
            "error_code": None,
            "error_message": None,
            "selected_attempt_id": "attempt_1",
            "attempts": [
                {
                    "attempt_id": "attempt_1",
                    "model_ref": "model-config-uuid",
                    "status": "succeeded",
                    "started_at": NOW,
                    "finished_at": NOW,
                    "error_code": None,
                    "observation_trace_refs": refs,
                }
            ],
        },
        "context_snapshot_ref": "ctx_open_skill_repo",
        "observation_trace_refs": refs,
        "orphan_effect_refs": [],
        "declared_outputs": [],
        "expected_effects": [],
    }


def _timeline(*, ai_trace_refs: list[str] | None = None) -> dict:
    refs = ai_trace_refs or []
    observed = {
        trace_id: _trace(trace_id, sequence=index + 2)
        for index, trace_id in enumerate(refs)
    }
    return {
        "schema_version": "recording-timeline/v0.1",
        "session_id": "rca_f028",
        "items": [_trace(), _ai_step(trace_refs=refs)],
        "observed_traces": observed,
        "orphan_effects": {},
    }


def _configuration() -> CompilationConfiguration:
    return CompilationConfiguration.model_validate(
        {
            "skill_definition": {
                "schema_version": "skill-definition/v0.1",
                "skill": {
                    "id": "skill_f028",
                    "name": "F028",
                    "version": "0.1.0",
                    "description": "F028 contract",
                },
                "inputs": [],
                "secrets": [],
                "asset_inputs": [],
                "outputs": [],
                "asset_outputs": [],
                "stage_2_rules": None,
            },
            "manual_fallbacks": {},
            "agent_steps": {
                "ais_open_skill_repo": {
                    "step_id": "ais_open_skill_repo",
                    "output_refs": [],
                    "expected_effects": [],
                    "allowed_input_refs": [],
                    "allowed_secret_refs": [],
                    "allowed_asset_refs": [],
                    "page_aliases": {},
                    "business_terms": [],
                    "model_policy": {"mode": "runtime_default", "model_ref": None},
                    "timeout_seconds": 180,
                }
            },
        }
    )


def _assessment(item_id: str, status: str, *, refs: list[str] | None = None):
    return ReplayAssessment.model_validate(
        {
            "item_id": item_id,
            "status": status,
            "trace_refs": refs or [],
            "effect_refs": [],
            "issue_codes": [],
            "explanation": "有限硬条件评估结果",
            "assessed_at": NOW,
            "assessor_version": "f028-v1",
        }
    )


def test_recording_timeline_round_trips_manual_and_ai_items_without_wrapper() -> None:
    timeline = RecordingTimeline.model_validate(
        _timeline(ai_trace_refs=["trace_observed_click", "trace_observed_navigation"])
    )

    assert timeline.items[0].trace_id == "trace_manual"
    assert timeline.items[1].step_id == "ais_open_skill_repo"
    assert [item.trace_id for item in timeline.observed_traces.values()] == [
        "trace_observed_click",
        "trace_observed_navigation",
    ]
    assert RecordingTimeline.model_validate_json(
        timeline.model_dump_json(exclude_none=True)
    ) == timeline


def test_ai_open_with_only_initial_navigation_keeps_runtime_agent_mode() -> None:
    payload = _timeline(ai_trace_refs=["trace_observed_navigation"])
    payload["items"][1]["instruction"] = "Open the project most relevant to skill"
    payload["observed_traces"]["trace_observed_navigation"] = {
        "trace_id": "trace_observed_navigation",
        "sequence": 2,
        "scope": {"page_ref": "main", "frame_path": []},
        "action": {"kind": "navigate", "mode": "url"},
        "data_bindings": [
            {
                "name": "url",
                "direction": "input",
                "kind": "literal",
                "value": "https://github.com/trending",
                "sensitive": False,
            }
        ],
        "effects": [],
    }
    timeline = RecordingTimeline.model_validate(payload)

    assessments = assess_recording_timeline(timeline)

    assert assessments[1].status == "insufficient_evidence"
    assert assessments[1].issue_codes == ["ai.semantic_coverage_incomplete"]


def test_ai_open_exact_url_can_compile_from_matching_navigation() -> None:
    payload = _timeline(ai_trace_refs=["trace_observed_navigation"])
    payload["items"][1]["instruction"] = "Open https://github.com/openai/codex"
    payload["observed_traces"]["trace_observed_navigation"] = {
        "trace_id": "trace_observed_navigation",
        "sequence": 2,
        "scope": {"page_ref": "main", "frame_path": []},
        "action": {"kind": "navigate", "mode": "url"},
        "data_bindings": [
            {
                "name": "url",
                "direction": "input",
                "kind": "literal",
                "value": "https://github.com/openai/codex",
                "sensitive": False,
            }
        ],
        "effects": [],
    }
    timeline = RecordingTimeline.model_validate(payload)

    assessments = assess_recording_timeline(timeline)

    assert assessments[1].status == "deterministic_ready"


def test_recording_timeline_rejects_unresolved_or_duplicate_trace_ownership() -> None:
    unresolved = _timeline(ai_trace_refs=["trace_missing"])
    unresolved["observed_traces"] = {}
    with pytest.raises(ValidationError, match="timeline.observation_trace_unresolved"):
        RecordingTimeline.model_validate(unresolved)

    duplicated = _timeline(ai_trace_refs=["trace_manual"])
    with pytest.raises(ValidationError, match="timeline.trace_ownership_conflict"):
        RecordingTimeline.model_validate(duplicated)


def test_ai_selected_attempt_must_match_top_level_observation_refs() -> None:
    payload = _timeline(ai_trace_refs=["trace_observed_click"])
    payload["items"][1]["execution"]["attempts"][0]["observation_trace_refs"] = []

    with pytest.raises(ValidationError, match="ai.execution_selected_attempt_refs_mismatch"):
        RecordingTimeline.model_validate(payload)


def test_draft_is_creation_only_and_can_preserve_stable_identity() -> None:
    draft = CoreTraceDraft.model_validate(
        {
            "draft_id": "trace_manual",
            "capture_state": "capturing",
            "partial_scope": {"page_ref": "main", "frame_path": []},
            "partial_action": None,
            "data_bindings": [],
            "effects": [],
            "diagnostic_codes": [],
        }
    )
    assert draft.draft_id == "trace_manual"

    timeline = _timeline()
    timeline["items"].append(draft.model_dump())
    with pytest.raises(ValidationError):
        RecordingTimeline.model_validate(timeline)


@pytest.mark.parametrize(
    ("execution", "assessment", "mode"),
    [
        ("succeeded", "deterministic_ready", "playwright"),
        ("succeeded", "insufficient_evidence", "agent"),
        ("failed", "insufficient_evidence", "agent"),
    ],
)
def test_execution_evidence_and_compile_mode_are_independent(
    execution: str, assessment: str, mode: str
) -> None:
    step = _ai_step()
    step["execution"]["status"] = execution
    if execution == "failed":
        step["execution"]["result_summary"] = None
        step["execution"]["error_code"] = "agent_execution_failed"
        step["execution"]["error_message"] = "provider failed"
        step["execution"]["attempts"][0]["status"] = "failed"
        step["execution"]["attempts"][0]["error_code"] = "agent_execution_failed"
    AIInstructionStep.model_validate(step)
    ReplayAssessment.model_validate(
        {
            "item_id": "ais_open_skill_repo",
            "status": assessment,
            "trace_refs": [],
            "effect_refs": [],
            "issue_codes": [],
            "explanation": "有限硬条件评估结果",
            "assessed_at": NOW,
            "assessor_version": "f028-v1",
        }
    )
    compiled = TypeAdapter(CompiledStep).validate_python(
        {
            "mode": mode,
            "step_id": "ais_open_skill_repo",
            "ordinal": 1,
            **(
                {
                    "trace_refs": ["trace_observed_click"],
                    "operations": [_trace("trace_observed_click")],
                    "expected_outputs": [],
                    "expected_effects": [],
                }
                if mode == "playwright"
                else {
                    "instruction": "打开和 skill 最相关的项目",
                    "scope_hint": {"page_ref": "main", "url": None, "title": None, "frame_path": []},
                    "output_refs": [],
                    "expected_effects": [],
                    "allowed_input_refs": [],
                    "allowed_secret_refs": [],
                    "allowed_asset_refs": [],
                    "page_aliases": {},
                    "business_terms": [],
                    "model_policy": {"mode": "runtime_default", "model_ref": None},
                    "timeout_seconds": 180,
                }
            ),
        }
    )
    assert compiled.mode == mode


def test_compilation_configuration_requires_explicit_per_agent_step_policy() -> None:
    configuration = CompilationConfiguration.model_validate(
        {
            "skill_definition": {
                "schema_version": "skill-definition/v0.1",
                "skill": {
                    "id": "skill_f028",
                    "name": "F028",
                    "version": "0.1.0",
                    "description": "F028 contract",
                },
                "inputs": [],
                "secrets": [],
                "asset_inputs": [],
                "outputs": [],
                "asset_outputs": [],
                "stage_2_rules": None,
            },
            "manual_fallbacks": {},
            "agent_steps": {
                "ais_open_skill_repo": {
                    "step_id": "ais_open_skill_repo",
                    "output_refs": [],
                    "expected_effects": [],
                    "allowed_input_refs": [],
                    "allowed_secret_refs": [],
                    "allowed_asset_refs": [],
                    "page_aliases": {},
                    "business_terms": [],
                    "model_policy": {"mode": "runtime_default", "model_ref": None},
                    "timeout_seconds": 180,
                }
            },
        }
    )
    assert configuration.agent_steps["ais_open_skill_repo"].step_id == "ais_open_skill_repo"

    invalid = configuration.model_dump()
    invalid["agent_steps"]["wrong_key"] = invalid["agent_steps"].pop(
        "ais_open_skill_repo"
    )
    with pytest.raises(ValidationError, match="configuration.agent_step_key_mismatch"):
        CompilationConfiguration.model_validate(invalid)


def test_dual_compiler_selects_exactly_one_mode_per_top_level_item() -> None:
    timeline = RecordingTimeline.model_validate(
        _timeline(ai_trace_refs=["trace_observed_click"])
    )
    plan = compile_dual_mode_plan(
        timeline,
        [
            _assessment("trace_manual", "deterministic_ready", refs=["trace_manual"]),
            _assessment("ais_open_skill_repo", "insufficient_evidence"),
        ],
        _configuration(),
    )

    assert [step.mode for step in plan.steps] == ["playwright", "agent"]
    assert [step.step_id for step in plan.steps] == [
        "trace_manual",
        "ais_open_skill_repo",
    ]
    assert plan.steps[1].instruction == "打开和 skill 最相关的项目"


def test_dual_compiler_uses_all_selected_ai_observations_as_one_playwright_step() -> None:
    refs = ["trace_observed_click", "trace_observed_navigation"]
    timeline = RecordingTimeline.model_validate(_timeline(ai_trace_refs=refs))
    plan = compile_dual_mode_plan(
        timeline,
        [
            _assessment("trace_manual", "deterministic_ready"),
            _assessment("ais_open_skill_repo", "deterministic_ready", refs=refs),
        ],
        _configuration(),
    )

    assert len(plan.steps) == 2
    assert plan.steps[1].mode == "playwright"
    assert plan.steps[1].trace_refs == refs


def test_dual_compiler_rejects_missing_assessment_and_confirmation() -> None:
    timeline = RecordingTimeline.model_validate(_timeline())
    with pytest.raises(ValueError, match="assessment_coverage_mismatch"):
        compile_dual_mode_plan(
            timeline,
            [_assessment("trace_manual", "deterministic_ready")],
            _configuration(),
        )
    with pytest.raises(ValueError, match="needs_confirmation"):
        compile_dual_mode_plan(
            timeline,
            [
                _assessment("trace_manual", "deterministic_ready"),
                _assessment("ais_open_skill_repo", "needs_confirmation"),
            ],
            _configuration(),
        )


def test_dual_compiler_source_hash_excludes_assessment_wall_clock() -> None:
    timeline = RecordingTimeline.model_validate(_timeline())
    first = [
        _assessment("trace_manual", "deterministic_ready"),
        _assessment("ais_open_skill_repo", "insufficient_evidence"),
    ]
    second = [
        item.model_copy(update={"assessed_at": item.assessed_at.replace(year=2030)})
        for item in first
    ]

    first_plan = compile_dual_mode_plan(timeline, first, _configuration())
    second_plan = compile_dual_mode_plan(timeline, second, _configuration())
    assert first_plan.source_hash == second_plan.source_hash

    changed_payload = _configuration().model_dump(mode="python")
    changed_payload["agent_steps"]["ais_open_skill_repo"]["business_terms"] = [
        "GitHub skill"
    ]
    changed = CompilationConfiguration.model_validate(changed_payload)
    changed_plan = compile_dual_mode_plan(timeline, first, changed)
    assert changed_plan.source_hash != first_plan.source_hash


def test_agent_download_effect_materializes_as_data_asset_output() -> None:
    timeline = RecordingTimeline.model_validate(_timeline())
    payload = _configuration().model_dump(mode="python")
    payload["skill_definition"]["asset_outputs"] = [
        {"name": "downloaded_file", "title": "下载文件", "asset_ref": "download_asset"}
    ]
    payload["agent_steps"]["ais_open_skill_repo"]["expected_effects"] = [
        {"kind": "download", "asset_output_ref": "download_asset"}
    ]
    configuration = CompilationConfiguration.model_validate(payload)
    assessments = [
        _assessment("trace_manual", "deterministic_ready"),
        _assessment("ais_open_skill_repo", "insufficient_evidence"),
    ]
    plan = compile_dual_mode_plan(timeline, assessments, configuration)
    lowered = materialize_core_trace_timeline(plan, configuration)
    agent_trace = lowered.traces[1]
    assert [
        (binding.name, binding.kind, binding.ref)
        for binding in agent_trace.data_bindings
        if binding.direction == "output"
    ] == [("downloaded_file", "data_asset", "download_asset")]


def test_agent_scalar_output_materializes_from_named_skill_output() -> None:
    timeline = RecordingTimeline.model_validate(_timeline())
    payload = _configuration().model_dump(mode="python")
    payload["skill_definition"]["outputs"] = [
        {
            "name": "star_count",
            "title": "Star 数",
            "variable_ref": "result.star_count",
            "value_type": "number",
        }
    ]
    payload["agent_steps"]["ais_open_skill_repo"]["output_refs"] = ["star_count"]
    configuration = CompilationConfiguration.model_validate(payload)
    assessments = [
        _assessment("trace_manual", "deterministic_ready"),
        _assessment("ais_open_skill_repo", "insufficient_evidence"),
    ]

    plan = compile_dual_mode_plan(timeline, assessments, configuration)
    lowered = materialize_core_trace_timeline(plan, configuration)

    agent_trace = lowered.traces[1]
    assert [
        (binding.name, binding.kind, binding.ref)
        for binding in agent_trace.data_bindings
        if binding.direction == "output"
    ] == [("star_count", "variable", "result.star_count")]
