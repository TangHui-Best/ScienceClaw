"""Candidate、CoreTrace 与 Diagnostic 的创建态统一只读投影。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Collection, Mapping

from ..contracts import CoreTrace, Diagnostic, TraceCandidate


_SAFE_DIAGNOSTIC_MESSAGES = {
    "execution_failed": "动作执行失败。",
    "execution_cancelled": "动作已取消。",
    "settlement_timeout": "动作结算超时。",
    "scope_unresolved": "页面作用域无法解析。",
    "action_not_replayable": "动作无法形成可回放步骤。",
    "target_unresolved": "操作目标无法解析。",
    "binding_unresolved": "输入输出绑定无法解析。",
    "browser_fact_unresolved": "浏览器副作用无法确认。",
    "asset_unavailable": "所需文件资产不可用。",
}


class ProjectionStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DELETED = "deleted"
    EFFECT = "effect"


@dataclass(frozen=True, slots=True)
class CreationStepRow:
    row_id: str
    candidate_id: str
    ordinal: int
    status: ProjectionStatus
    is_action: bool
    title: str
    action_kind: str | None = None
    effect_kind: str | None = None
    trace_id: str | None = None
    sequence: int | None = None
    parent_trace_id: str | None = None
    diagnostic_code: str | None = None
    diagnostic_message: str | None = None


def project_creation_steps(
    *,
    candidates: Mapping[str, TraceCandidate],
    accepted_traces: Mapping[str, CoreTrace],
    diagnostics: Mapping[str, Diagnostic],
    deleted_candidate_ids: Collection[str],
    include_deleted: bool = True,
) -> tuple[CreationStepRow, ...]:
    """生成稳定、不可变且不含录制值或运行时标识的步骤投影。"""

    deleted = set(deleted_candidate_ids)
    rows: list[CreationStepRow] = []
    for candidate in sorted(candidates.values(), key=lambda item: item.ordinal):
        candidate_id = candidate.candidate_id
        trace = accepted_traces.get(candidate_id)
        if trace is not None:
            rows.extend(_accepted_rows(candidate_id, trace))
            continue
        if candidate_id in deleted:
            if include_deleted:
                rows.append(
                    CreationStepRow(
                        row_id=f"{candidate_id}:action",
                        candidate_id=candidate_id,
                        ordinal=candidate.ordinal,
                        status=ProjectionStatus.DELETED,
                        is_action=True,
                        title="已删除步骤",
                        action_kind=candidate.action_hint.kind,
                    )
                )
            continue
        diagnostic = diagnostics.get(candidate_id)
        if diagnostic is not None:
            rows.append(
                CreationStepRow(
                    row_id=f"{candidate_id}:action",
                    candidate_id=candidate_id,
                    ordinal=candidate.ordinal,
                    status=ProjectionStatus.REJECTED,
                    is_action=True,
                    title="录制失败",
                    action_kind=candidate.action_hint.kind,
                    diagnostic_code=diagnostic.code,
                    diagnostic_message=_SAFE_DIAGNOSTIC_MESSAGES[diagnostic.code],
                )
            )
            continue
        rows.append(
            CreationStepRow(
                row_id=f"{candidate_id}:action",
                candidate_id=candidate_id,
                ordinal=candidate.ordinal,
                status=ProjectionStatus.PENDING,
                is_action=True,
                title=_candidate_title(candidate),
                action_kind=candidate.action_hint.kind,
            )
        )
    return tuple(rows)


def _accepted_rows(candidate_id: str, trace: CoreTrace) -> list[CreationStepRow]:
    rows = [
        CreationStepRow(
            row_id=f"{candidate_id}:action",
            candidate_id=candidate_id,
            ordinal=trace.sequence,
            status=ProjectionStatus.ACCEPTED,
            is_action=True,
            title=_trace_title(trace),
            action_kind=trace.action.kind,
            trace_id=trace.trace_id,
            sequence=trace.sequence,
        )
    ]
    effect_titles = {
        "navigation": "页面导航",
        "new_page": "打开新页面",
        "download": "下载文件",
        "dialog": "处理浏览器对话框",
    }
    for index, effect in enumerate(trace.effects):
        rows.append(
            CreationStepRow(
                row_id=f"{trace.trace_id}:effect:{index}",
                candidate_id=candidate_id,
                ordinal=trace.sequence,
                status=ProjectionStatus.EFFECT,
                is_action=False,
                title=effect_titles[effect.kind],
                effect_kind=effect.kind,
                parent_trace_id=trace.trace_id,
            )
        )
    return rows


def _candidate_title(candidate: TraceCandidate) -> str:
    target = getattr(candidate.action_hint, "target_hint", None)
    target_name = getattr(target, "name", None)
    title = (
        f"{candidate.action_hint.kind}: {target_name}"
        if target_name
        else candidate.action_hint.kind
    )
    return _bounded_title(title)


def _trace_title(trace: CoreTrace) -> str:
    target = getattr(trace.action, "target", None)
    target_name = getattr(target, "name", None)
    title = f"{trace.action.kind}: {target_name}" if target_name else trace.action.kind
    return _bounded_title(title)


def _bounded_title(title: str, limit: int = 120) -> str:
    return title if len(title) <= limit else title[: limit - 1] + "…"
