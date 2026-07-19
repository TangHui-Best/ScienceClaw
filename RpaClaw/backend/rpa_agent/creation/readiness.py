"""创建态 Build Readiness 的纯派生计算。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Collection, Mapping

from ..contracts import (
    CoreTrace,
    CoreTraceTimeline,
    Diagnostic,
    TraceCandidate,
    validate_timeline_payload,
)
from .page_registry import PageRegistry


class ReadinessCode(str, Enum):
    CANDIDATE_PENDING = "candidate_pending"
    CANDIDATE_REJECTED = "candidate_rejected"
    PENDING_PAGE = "pending_page"
    PENDING_VARIABLE = "pending_variable"
    PENDING_DATA_ASSET = "pending_data_asset"
    UNRESOLVED_PAGE = "unresolved_page"
    UNRESOLVED_VARIABLE = "unresolved_variable"
    UNRESOLVED_DATA_ASSET = "unresolved_data_asset"
    TIMELINE_INVALID = "timeline_invalid"


@dataclass(frozen=True, slots=True)
class ReadinessIssue:
    code: ReadinessCode
    candidate_id: str | None = None
    trace_id: str | None = None
    ref: str | None = None
    producer_candidate_id: str | None = None


@dataclass(frozen=True, slots=True)
class BuildReadiness:
    ready: bool
    issues: tuple[ReadinessIssue, ...]
    timeline: CoreTraceTimeline | None


class _ProducerState(Enum):
    ACCEPTED = "accepted"
    PENDING = "pending"
    REJECTED = "rejected"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class _Producer:
    ref: str
    ordinal: int
    candidate_id: str
    state: _ProducerState


def derive_build_readiness(
    *,
    candidates: Mapping[str, TraceCandidate],
    accepted_traces: Mapping[str, CoreTrace],
    diagnostics: Mapping[str, Diagnostic],
    deleted_candidate_ids: Collection[str],
    page_registry: PageRegistry,
    external_asset_refs: Collection[str] = (),
) -> BuildReadiness:
    """从创建态事实索引派生构建门禁，不修改任何输入状态。"""

    accepted_ids = set(accepted_traces)
    rejected_ids = set(diagnostics)
    deleted_ids = set(deleted_candidate_ids)
    pending_ids = set(candidates) - accepted_ids - rejected_ids - deleted_ids
    issues: list[ReadinessIssue] = []

    for candidate in sorted(candidates.values(), key=lambda item: item.ordinal):
        if candidate.candidate_id in pending_ids:
            issues.append(
                ReadinessIssue(
                    code=ReadinessCode.CANDIDATE_PENDING,
                    candidate_id=candidate.candidate_id,
                )
            )
        elif (
            candidate.candidate_id in rejected_ids
            and candidate.candidate_id not in deleted_ids
        ):
            issues.append(
                ReadinessIssue(
                    code=ReadinessCode.CANDIDATE_REJECTED,
                    candidate_id=candidate.candidate_id,
                )
            )

    variable_producers: list[_Producer] = []
    asset_producers: list[_Producer] = []
    page_producers: list[_Producer] = []
    for candidate in candidates.values():
        state = _candidate_state(
            candidate.candidate_id,
            accepted_ids=accepted_ids,
            rejected_ids=rejected_ids,
            deleted_ids=deleted_ids,
        )
        if state is _ProducerState.ACCEPTED:
            trace = accepted_traces[candidate.candidate_id]
            for binding in trace.data_bindings:
                if binding.direction != "output":
                    continue
                producer = _Producer(
                    ref=binding.ref,
                    ordinal=trace.sequence,
                    candidate_id=candidate.candidate_id,
                    state=state,
                )
                if binding.kind == "variable":
                    variable_producers.append(producer)
                elif binding.kind == "data_asset":
                    asset_producers.append(producer)
            for effect in trace.effects:
                if effect.kind == "new_page":
                    page_producers.append(
                        _Producer(
                            ref=effect.page_ref,
                            ordinal=trace.sequence,
                            candidate_id=candidate.candidate_id,
                            state=state,
                        )
                    )
            continue

        for binding in candidate.binding_hints:
            if binding.direction != "output" or binding.ref_hint is None:
                continue
            producer = _Producer(
                ref=binding.ref_hint,
                ordinal=candidate.ordinal,
                candidate_id=candidate.candidate_id,
                state=state,
            )
            if binding.kind_hint == "variable":
                variable_producers.append(producer)
            elif binding.kind_hint == "data_asset":
                asset_producers.append(producer)

    for page_ref, candidate_id in page_registry.producer_snapshot().items():
        if candidate_id not in candidates or candidate_id in accepted_ids:
            continue
        candidate = candidates[candidate_id]
        page_producers.append(
            _Producer(
                ref=page_ref,
                ordinal=candidate.ordinal,
                candidate_id=candidate.candidate_id,
                state=_candidate_state(
                    candidate.candidate_id,
                    accepted_ids=accepted_ids,
                    rejected_ids=rejected_ids,
                    deleted_ids=deleted_ids,
                ),
            )
        )

    external_assets = set(external_asset_refs)
    for candidate_id, trace in sorted(
        accepted_traces.items(), key=lambda item: item[1].sequence
    ):
        page_refs = [trace.scope.page_ref]
        if trace.action.kind == "switch_page":
            page_refs.append(trace.action.page_ref)
        for ref in dict.fromkeys(page_refs):
            if ref != "main":
                issue = _dependency_issue(
                    kind="page",
                    ref=ref,
                    consumer_candidate_id=candidate_id,
                    consumer_trace=trace,
                    producers=page_producers,
                )
                if issue is not None:
                    issues.append(issue)

        for binding in trace.data_bindings:
            if binding.direction != "input":
                continue
            if binding.kind == "variable":
                issue = _dependency_issue(
                    kind="variable",
                    ref=binding.ref,
                    consumer_candidate_id=candidate_id,
                    consumer_trace=trace,
                    producers=variable_producers,
                )
                if issue is not None:
                    issues.append(issue)
            elif binding.kind == "data_asset" and binding.ref not in external_assets:
                issue = _dependency_issue(
                    kind="data_asset",
                    ref=binding.ref,
                    consumer_candidate_id=candidate_id,
                    consumer_trace=trace,
                    producers=asset_producers,
                )
                if issue is not None:
                    issues.append(issue)

    if issues:
        return BuildReadiness(
            ready=False,
            issues=_deduplicate_issues(issues),
            timeline=None,
        )

    payload = {
        "schema_version": "core-trace/v0.1",
        "traces": [
            trace.model_dump(mode="python", exclude_unset=True)
            for trace in sorted(accepted_traces.values(), key=lambda item: item.sequence)
        ],
    }
    try:
        timeline = validate_timeline_payload(
            payload,
            external_asset_refs=external_assets,
        )
    except (ValueError, TypeError):
        return BuildReadiness(
            ready=False,
            issues=(ReadinessIssue(code=ReadinessCode.TIMELINE_INVALID),),
            timeline=None,
        )
    return BuildReadiness(ready=True, issues=(), timeline=timeline)


def _candidate_state(
    candidate_id: str,
    *,
    accepted_ids: set[str],
    rejected_ids: set[str],
    deleted_ids: set[str],
) -> _ProducerState:
    if candidate_id in accepted_ids:
        return _ProducerState.ACCEPTED
    if candidate_id in deleted_ids:
        return _ProducerState.DELETED
    if candidate_id in rejected_ids:
        return _ProducerState.REJECTED
    return _ProducerState.PENDING


def _dependency_issue(
    *,
    kind: str,
    ref: str,
    consumer_candidate_id: str,
    consumer_trace: CoreTrace,
    producers: list[_Producer],
) -> ReadinessIssue | None:
    matching = [
        producer
        for producer in producers
        if _ref_matches(kind, producer.ref, ref)
    ]
    prior = [
        producer for producer in matching if producer.ordinal < consumer_trace.sequence
    ]
    if any(producer.state is _ProducerState.ACCEPTED for producer in prior):
        return None
    pending = sorted(
        (producer for producer in prior if producer.state is _ProducerState.PENDING),
        key=lambda item: item.ordinal,
    )
    if pending:
        producer = pending[-1]
        code = {
            "page": ReadinessCode.PENDING_PAGE,
            "variable": ReadinessCode.PENDING_VARIABLE,
            "data_asset": ReadinessCode.PENDING_DATA_ASSET,
        }[kind]
    else:
        candidates = prior or matching
        producer = max(candidates, key=lambda item: item.ordinal) if candidates else None
        code = {
            "page": ReadinessCode.UNRESOLVED_PAGE,
            "variable": ReadinessCode.UNRESOLVED_VARIABLE,
            "data_asset": ReadinessCode.UNRESOLVED_DATA_ASSET,
        }[kind]
    return ReadinessIssue(
        code=code,
        candidate_id=consumer_candidate_id,
        trace_id=consumer_trace.trace_id,
        ref=ref,
        producer_candidate_id=(producer.candidate_id if producer is not None else None),
    )


def _ref_matches(kind: str, produced_ref: str, consumed_ref: str) -> bool:
    if kind == "variable":
        return consumed_ref == produced_ref or consumed_ref.startswith(produced_ref + ".")
    return consumed_ref == produced_ref


def _deduplicate_issues(
    issues: list[ReadinessIssue],
) -> tuple[ReadinessIssue, ...]:
    seen: set[tuple[object, ...]] = set()
    result: list[ReadinessIssue] = []
    for issue in issues:
        key = (
            issue.code,
            issue.candidate_id,
            issue.trace_id,
            issue.ref,
            issue.producer_candidate_id,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return tuple(result)
