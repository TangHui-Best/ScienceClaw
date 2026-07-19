"""Finite, deterministic replay assessment rules for F028."""

from __future__ import annotations

from datetime import datetime, timezone
import re

from ..contracts import AIInstructionStep, CoreTrace, RecordingTimeline, ReplayAssessment


ASSESSOR_VERSION = "f028-replay-assessor/0.1"


def assess_recording_timeline(
    timeline: RecordingTimeline,
) -> tuple[ReplayAssessment, ...]:
    assessments: list[ReplayAssessment] = []
    for item in timeline.items:
        if isinstance(item, CoreTrace):
            assessments.append(
                _assessment(
                    item.trace_id,
                    "deterministic_ready",
                    [item.trace_id],
                    [],
                    [],
                    "手工 CoreTrace 已通过稳定 Scope、Action、Binding 与 Effect 校验。",
                )
            )
            continue
        traces = [timeline.observed_traces[ref] for ref in item.observation_trace_refs]
        issue_codes: list[str] = []
        deterministic = bool(traces) and _covers_instruction(item, traces)
        if not traces:
            issue_codes.append("ai.observation_missing")
        elif not deterministic:
            issue_codes.append("ai.semantic_coverage_incomplete")
        if item.orphan_effect_refs:
            deterministic = False
            issue_codes.append("ai.orphan_effect_present")
        assessments.append(
            _assessment(
                item.step_id,
                "deterministic_ready" if deterministic else "insufficient_evidence",
                [trace.trace_id for trace in traces],
                list(item.orphan_effect_refs),
                issue_codes,
                (
                    "观察动作满足有限语义覆盖规则。"
                    if deterministic
                    else "证据不足，保留原始意图并编译为 AgentSegment。"
                ),
            )
        )
    return tuple(assessments)


def _covers_instruction(item: AIInstructionStep, traces: list[CoreTrace]) -> bool:
    instruction = item.instruction.casefold()
    action_kinds = {trace.action.kind for trace in traces}
    if any(marker in instruction for marker in ("获取", "提取", "读取", "get ", "extract", "read ")):
        return "extract" in action_kinds and any(
            binding.direction == "output"
            for trace in traces
            for binding in trace.data_bindings
        )
    if any(marker in instruction for marker in ("打开", "进入", "open ", "navigate")):
        if action_kinds & {"click", "switch_page"}:
            return True
        # A bare observed navigation does not prove an AI selection was
        # captured: Browser-use performs an initial navigation to the current
        # page before making its semantic decision. It is replay-complete only
        # when the instruction itself supplied the exact URL and the trace
        # bound that same URL.
        explicit_urls = set(re.findall(r"https?://[^\s]+", item.instruction))
        return any(
            trace.action.kind == "navigate"
            and any(
                binding.kind == "literal"
                and binding.name == "url"
                and binding.value in explicit_urls
                for binding in trace.data_bindings
            )
            for trace in traces
        )
    return bool(traces)


def _assessment(item_id, status, trace_refs, effect_refs, issue_codes, explanation):
    return ReplayAssessment(
        item_id=item_id,
        status=status,
        trace_refs=trace_refs,
        effect_refs=effect_refs,
        issue_codes=issue_codes,
        explanation=explanation,
        assessed_at=datetime.now(timezone.utc),
        assessor_version=ASSESSOR_VERSION,
    )


__all__ = ["ASSESSOR_VERSION", "assess_recording_timeline"]
