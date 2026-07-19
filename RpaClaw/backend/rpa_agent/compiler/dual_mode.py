"""F028 top-level timeline compiler: one item, exactly one execution mode."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from ..contracts import (
    AIInstructionStep,
    AgentSegment,
    BrowserScopeHint,
    CompilationConfiguration,
    CompiledSkillPlan,
    CoreTrace,
    CoreTraceTimeline,
    PlaywrightSegment,
    RecordingTimeline,
    ReplayAssessment,
)


def compile_dual_mode_plan(
    timeline: RecordingTimeline,
    assessments: Sequence[ReplayAssessment],
    configuration: CompilationConfiguration,
    *,
    compiler_version: str = "rpa-agent-compiler/0.1",
) -> CompiledSkillPlan:
    """Compile immutable decisions without re-assessing evidence or execution success."""

    item_ids = [
        item.trace_id if isinstance(item, CoreTrace) else item.step_id
        for item in timeline.items
    ]
    by_id = {assessment.item_id: assessment for assessment in assessments}
    if len(by_id) != len(assessments):
        raise ValueError("dual_compiler.assessment_duplicate")
    if set(by_id) != set(item_ids):
        raise ValueError("dual_compiler.assessment_coverage_mismatch")

    steps: list[PlaywrightSegment | AgentSegment] = []
    for ordinal, item in enumerate(timeline.items, start=1):
        item_id = item.trace_id if isinstance(item, CoreTrace) else item.step_id
        assessment = by_id[item_id]
        if assessment.status == "needs_confirmation":
            raise ValueError(f"dual_compiler.needs_confirmation:{item_id}")
        if isinstance(item, CoreTrace):
            if assessment.status == "deterministic_ready":
                steps.append(
                    PlaywrightSegment(
                        mode="playwright",
                        step_id=item.trace_id,
                        ordinal=ordinal,
                        trace_refs=[item.trace_id],
                        operations=[item],
                        expected_outputs=_outputs_for_traces(configuration, [item]),
                        expected_effects=[],
                    )
                )
                continue
            fallback = configuration.manual_fallbacks.get(item.trace_id)
            if fallback is None:
                raise ValueError(f"dual_compiler.manual_fallback_required:{item.trace_id}")
            step_config = _agent_configuration(configuration, item.trace_id)
            steps.append(
                _agent_segment(
                    step_id=item.trace_id,
                    ordinal=ordinal,
                    instruction=fallback.instruction,
                    scope_hint=fallback.scope_hint,
                    configuration=step_config,
                )
            )
            continue

        if assessment.status == "deterministic_ready":
            traces = [timeline.observed_traces[ref] for ref in item.observation_trace_refs]
            if not traces:
                raise ValueError(f"dual_compiler.ai_evidence_required:{item.step_id}")
            steps.append(
                PlaywrightSegment(
                    mode="playwright",
                    step_id=item.step_id,
                    ordinal=ordinal,
                    trace_refs=[trace.trace_id for trace in traces],
                    operations=traces,
                    expected_outputs=item.declared_outputs,
                    expected_effects=item.expected_effects,
                )
            )
            continue
        step_config = _agent_configuration(configuration, item.step_id)
        steps.append(
            _agent_segment(
                step_id=item.step_id,
                ordinal=ordinal,
                instruction=item.instruction,
                scope_hint=_scope_hint(item, timeline, step_config.page_aliases),
                configuration=step_config,
            )
        )

    source_hash = _source_hash(
        timeline, assessments, configuration, compiler_version=compiler_version
    )
    return CompiledSkillPlan(
        schema_version="compiled-skill/v0.1",
        skill_id=configuration.skill_definition.skill.id,
        source_hash=source_hash,
        steps=steps,
    )


def _agent_configuration(configuration: CompilationConfiguration, step_id: str):
    try:
        return configuration.agent_steps[step_id]
    except KeyError as exc:
        raise ValueError(f"dual_compiler.agent_configuration_required:{step_id}") from exc


def _agent_segment(*, step_id: str, ordinal: int, instruction: str, scope_hint, configuration):
    return AgentSegment(
        mode="agent",
        step_id=step_id,
        ordinal=ordinal,
        instruction=instruction,
        scope_hint=scope_hint,
        output_refs=configuration.output_refs,
        expected_effects=configuration.expected_effects,
        allowed_input_refs=configuration.allowed_input_refs,
        allowed_secret_refs=configuration.allowed_secret_refs,
        allowed_asset_refs=configuration.allowed_asset_refs,
        page_aliases=configuration.page_aliases,
        business_terms=configuration.business_terms,
        model_policy=configuration.model_policy,
        timeout_seconds=configuration.timeout_seconds,
    )


def _scope_hint(item: AIInstructionStep, timeline: RecordingTimeline, page_aliases):
    if item.observation_trace_refs:
        trace = timeline.observed_traces[item.observation_trace_refs[0]]
        return BrowserScopeHint(
            page_ref=trace.scope.page_ref,
            frame_path=trace.scope.frame_path,
        )
    if page_aliases:
        page = next(iter(page_aliases.values()))
        return BrowserScopeHint(page_ref=page.page_ref, url=page.url, title=page.title)
    return BrowserScopeHint(page_ref="main")


def _outputs_for_traces(configuration: CompilationConfiguration, traces: Sequence[CoreTrace]):
    produced = {
        binding.ref
        for trace in traces
        for binding in trace.data_bindings
        if binding.kind == "variable" and binding.direction == "output"
    }
    return [
        output
        for output in configuration.skill_definition.outputs
        if output.variable_ref in produced
        or any(output.variable_ref.startswith(ref + ".") for ref in produced)
    ]


def _source_hash(
    timeline: RecordingTimeline,
    assessments: Sequence[ReplayAssessment],
    configuration: CompilationConfiguration,
    *,
    compiler_version: str,
) -> str:
    payload = {
        "timeline": timeline.model_dump(mode="json", exclude_none=True),
        "assessments": [
            item.model_dump(mode="json", exclude_none=True, exclude={"assessed_at"})
            for item in sorted(assessments, key=lambda value: value.item_id)
        ],
        "configuration": configuration.model_dump(mode="json", exclude_none=True),
        "compiler_version": compiler_version,
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def materialize_core_trace_timeline(
    plan: CompiledSkillPlan,
    configuration: CompilationConfiguration,
) -> CoreTraceTimeline:
    """Lower the dual-mode plan into the existing deterministic renderer IR."""

    traces: list[CoreTrace] = []
    sequence = 1
    for step in plan.steps:
        if isinstance(step, PlaywrightSegment):
            for operation in step.operations:
                traces.append(operation.model_copy(update={"sequence": sequence}, deep=True))
                sequence += 1
            continue
        bindings: list[dict[str, object]] = []
        definition = configuration.skill_definition
        inputs_by_ref = {item.ref: item for item in definition.inputs}
        secrets_by_ref = {item.ref: item for item in definition.secrets}
        assets_by_ref = {item.ref: item for item in definition.asset_inputs}
        outputs_by_name = {item.name: item for item in definition.outputs}
        for ref in step.allowed_input_refs:
            if ref not in inputs_by_ref:
                raise ValueError(f"dual_compiler.input_ref_unresolved:{ref}")
            bindings.append(
                {"name": ref, "direction": "input", "kind": "skill_input", "ref": ref, "sensitive": False}
            )
        for ref in step.allowed_secret_refs:
            if ref not in secrets_by_ref:
                raise ValueError(f"dual_compiler.secret_ref_unresolved:{ref}")
            bindings.append(
                {"name": ref, "direction": "input", "kind": "secret", "ref": ref, "sensitive": True}
            )
        for ref in step.allowed_asset_refs:
            if ref not in assets_by_ref:
                raise ValueError(f"dual_compiler.asset_ref_unresolved:{ref}")
            bindings.append(
                {"name": ref, "direction": "input", "kind": "data_asset", "ref": ref, "sensitive": False}
            )
        for name in step.output_refs:
            output = outputs_by_name.get(name)
            if output is None:
                raise ValueError(f"dual_compiler.output_ref_unresolved:{name}")
            bindings.append(
                {
                    "name": output.name,
                    "direction": "output",
                    "kind": "variable",
                    "ref": output.variable_ref,
                    "sensitive": False,
                }
            )
        asset_outputs_by_ref = {
            item.asset_ref: item for item in definition.asset_outputs
        }
        for effect in step.expected_effects:
            if effect.kind != "download":
                continue
            output = asset_outputs_by_ref.get(effect.asset_output_ref)
            if output is None:
                raise ValueError(
                    f"dual_compiler.asset_output_ref_unresolved:{effect.asset_output_ref}"
                )
            bindings.append(
                {
                    "name": output.name,
                    "direction": "output",
                    "kind": "data_asset",
                    "ref": output.asset_ref,
                    "sensitive": False,
                }
            )
        traces.append(
            CoreTrace.model_validate(
                {
                    "trace_id": step.step_id,
                    "sequence": sequence,
                    "scope": {
                        "page_ref": step.scope_hint.page_ref,
                        "frame_path": [
                            frame.model_dump(mode="python")
                            for frame in step.scope_hint.frame_path
                        ],
                    },
                    "action": {"kind": "agent", "instruction": step.instruction},
                    "data_bindings": bindings,
                    "effects": [],
                }
            )
        )
        sequence += 1
    return CoreTraceTimeline(
        schema_version="core-trace/v0.1",
        traces=traces,
    )
