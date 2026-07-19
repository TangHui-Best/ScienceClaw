"""确定性 Compiler 的短生命周期计划与诊断对象。"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import CoreTraceTimeline, SkillDefinition, SkillManifest


@dataclass(frozen=True, slots=True)
class CompileIssue:
    code: str
    message: str
    trace_id: str | None
    sequence: int | None
    path: str


@dataclass(frozen=True, slots=True)
class BrowserCompilePlan:
    timeline: CoreTraceTimeline
    definition: SkillDefinition
    manifest: SkillManifest
    agent_required_paths: dict[str, dict[str, tuple[str, ...]]]


def sort_issues(issues: list[CompileIssue]) -> tuple[CompileIssue, ...]:
    return tuple(
        sorted(
            issues,
            key=lambda item: (
                item.sequence is None,
                item.sequence if item.sequence is not None else 0,
                item.path,
                item.code,
            ),
        )
    )
