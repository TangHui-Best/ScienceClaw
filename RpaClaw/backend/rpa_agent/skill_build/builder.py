"""Compile a vNext timeline without invoking any legacy compiler or asset store."""

from __future__ import annotations

import hashlib
import json

from ..contracts.identity import RPA_AGENT_NEXT_NAMESPACE
from ..contracts.models import CoreTrace
from ..recording.contracts import AIInstructionStep, RecordingTimeline
from .contracts import (
    CompiledBrowserUseStep,
    CompiledPlaywrightStep,
    CompiledSkill,
    CompileDecision,
    SkillBuildConfig,
)
from .decisions import decide_core_trace


COMPILER_VERSION = "rpa-agent-next-s3/0.1"


class CompileRejectedError(ValueError):
    def __init__(self, decisions: list[CompileDecision]) -> None:
        self.decisions = decisions
        super().__init__("next_skill_build.compile_review_required")


def compile_skill(
    timeline: RecordingTimeline, config: SkillBuildConfig
) -> CompiledSkill:
    """Create a new skill artifact from only vNext facts and user configuration."""

    if timeline.schema_namespace != RPA_AGENT_NEXT_NAMESPACE:
        raise ValueError("next_skill_build.timeline_namespace_invalid")
    if config.schema_namespace != RPA_AGENT_NEXT_NAMESPACE:
        raise ValueError("next_skill_build.config_namespace_invalid")

    decisions = _timeline_decisions(timeline)
    if any(decision.mode != "playwright" for decision in decisions):
        raise CompileRejectedError(decisions)

    steps: list[CompiledPlaywrightStep | CompiledBrowserUseStep] = []
    for ordinal, item in enumerate(timeline.items, start=1):
        if isinstance(item, CoreTrace):
            steps.append(
                CompiledPlaywrightStep(
                    mode="playwright",
                    step_id=item.trace_id,
                    ordinal=ordinal,
                    trace=item,
                )
            )
            continue
        if not isinstance(item, AIInstructionStep):
            raise ValueError("next_skill_build.timeline_item_invalid")
        steps.append(
            CompiledBrowserUseStep(
                mode="browser_use",
                step_id=item.step_id,
                ordinal=ordinal,
                instruction=item.instruction,
                model_ref=config.browser_use_model_ref,
            )
        )

    return CompiledSkill(
        schema_namespace=RPA_AGENT_NEXT_NAMESPACE,
        skill_id=config.skill_id,
        config_id=config.config_id,
        source_hash=_source_hash(timeline, config),
        compiler_version=COMPILER_VERSION,
        steps=steps,
        config=config,
    )


def _timeline_decisions(timeline: RecordingTimeline) -> list[CompileDecision]:
    """Add only chronology/dependency facts that are visible in the new timeline."""

    decisions: list[CompileDecision] = []
    previous_sequence = 0
    produced_variables: set[str] = set()
    produced_assets: set[str] = set()
    for item in timeline.items:
        if not isinstance(item, CoreTrace):
            continue
        baseline = decide_core_trace(item)
        reason_codes = list(baseline.reason_codes)
        if item.sequence <= previous_sequence:
            reason_codes.append("manual_trace.sequence_not_ascending")
        for binding in item.data_bindings:
            if binding.direction != "input":
                continue
            if binding.kind == "variable" and not any(
                binding.ref == ref or binding.ref.startswith(ref + ".")
                for ref in produced_variables
            ):
                reason_codes.append("manual_trace.variable_input_unproven")
            if binding.kind == "data_asset" and binding.ref not in produced_assets:
                reason_codes.append("manual_trace.asset_input_unproven")
        decisions.append(
            CompileDecision(
                trace_id=item.trace_id,
                mode="playwright" if not reason_codes else "review_required",
                reason_codes=reason_codes,
            )
        )
        previous_sequence = item.sequence
        for binding in item.data_bindings:
            if binding.direction == "output" and binding.kind == "variable":
                produced_variables.add(binding.ref)
            if binding.direction == "output" and binding.kind == "data_asset":
                produced_assets.add(binding.ref)
    return decisions


def _source_hash(timeline: RecordingTimeline, config: SkillBuildConfig) -> str:
    """Exclude AI execution diagnostics; source is facts, intent, and user config."""

    items: list[dict[str, object]] = []
    for item in timeline.items:
        if isinstance(item, CoreTrace):
            items.append({"kind": "core_trace", "trace": item.model_dump(mode="json")})
        else:
            items.append(
                {
                    "kind": "ai_instruction",
                    "step_id": item.step_id,
                    "instruction": item.instruction,
                    "declared_outputs": [
                        output.model_dump(mode="json")
                        for output in item.declared_outputs
                    ],
                }
            )
    payload = {
        "schema_namespace": RPA_AGENT_NEXT_NAMESPACE,
        "timeline_session_id": timeline.session_id,
        "items": items,
        "config": config.model_dump(mode="json"),
        "compiler_version": COMPILER_VERSION,
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
