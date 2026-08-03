"""Deterministic aggregation of quality reports without recording sensitive inputs."""

from __future__ import annotations

from collections import Counter

from pydantic import Field

from ..contracts.models import StrictModel
from .harness import HarnessRunReport


class QualityMetricsSnapshot(StrictModel):
    run_count: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    success_rate: float = Field(ge=0, le=1)
    average_duration_ms: int = Field(ge=0)
    p50_duration_ms: int = Field(ge=0)
    observed_cost_run_count: int = Field(ge=0)
    observed_cost_units: float = Field(ge=0)
    failures_by_stage: dict[str, int]
    failures_by_class: dict[str, int]


class QualityMetrics:
    def __init__(self) -> None:
        self._reports: list[HarnessRunReport] = []

    def record(self, report: HarnessRunReport) -> None:
        self._reports.append(report)

    def snapshot(self) -> QualityMetricsSnapshot:
        total = len(self._reports)
        succeeded = sum(report.status == "succeeded" for report in self._reports)
        failed = total - succeeded
        durations = sorted(report.duration_ms for report in self._reports)
        costs = [
            report.observed_cost_units
            for report in self._reports
            if report.observed_cost_units is not None
        ]
        stage_counts = Counter(
            report.stage.value for report in self._reports if report.status == "failed"
        )
        class_counts = Counter(
            report.failure_class.value
            for report in self._reports
            if report.failure_class is not None
        )
        return QualityMetricsSnapshot(
            run_count=total,
            succeeded_count=succeeded,
            failed_count=failed,
            success_rate=(succeeded / total) if total else 0,
            average_duration_ms=round(sum(durations) / total) if total else 0,
            p50_duration_ms=durations[(total - 1) // 2] if total else 0,
            observed_cost_run_count=len(costs),
            observed_cost_units=sum(costs),
            failures_by_stage=dict(sorted(stage_counts.items())),
            failures_by_class=dict(sorted(class_counts.items())),
        )
