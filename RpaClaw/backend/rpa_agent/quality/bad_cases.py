"""Explicit review lifecycle for repeatable quality failures."""

from __future__ import annotations

from threading import RLock

from pydantic import Field, model_validator

from ..contracts.models import Identifier, StrictModel
from .harness import HarnessRunReport


class BadCase(StrictModel):
    bad_case_id: Identifier
    report_id: Identifier
    asset_id: Identifier
    correlation_id: Identifier
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    failure_stage: str = Field(min_length=1, max_length=64)
    failure_class: str = Field(min_length=1, max_length=128)
    status: str
    reviewed_by: Identifier | None = None

    @model_validator(mode="after")
    def _validate_state(self) -> "BadCase":
        if self.status not in {"proposed", "accepted", "rejected"}:
            raise ValueError("next_bad_case.status_invalid")
        if self.status == "proposed" and self.reviewed_by is not None:
            raise ValueError("next_bad_case.proposed_has_reviewer")
        if self.status != "proposed" and self.reviewed_by is None:
            raise ValueError("next_bad_case.review_required")
        return self


class BadCaseRegistry:
    def __init__(self) -> None:
        self._items: dict[str, BadCase] = {}
        self._mutex = RLock()

    def propose(self, *, bad_case_id: str, report: HarnessRunReport) -> BadCase:
        if report.status != "failed" or report.failure_class is None:
            raise ValueError("next_bad_case.failure_report_required")
        item = BadCase(
            bad_case_id=bad_case_id,
            report_id=report.report_id,
            asset_id=report.asset.artifact_id,
            correlation_id=report.correlation_id,
            input_fingerprint=report.input_fingerprint,
            failure_stage=report.stage.value,
            failure_class=report.failure_class.value,
            status="proposed",
        )
        with self._mutex:
            if bad_case_id in self._items:
                raise ValueError("next_bad_case.id_duplicate")
            self._items[bad_case_id] = item
        return item

    def accept(self, *, bad_case_id: str, reviewer_id: str) -> BadCase:
        with self._mutex:
            try:
                item = self._items[bad_case_id]
            except KeyError as error:
                raise ValueError("next_bad_case.not_found") from error
            if item.status != "proposed":
                raise ValueError("next_bad_case.not_proposed")
            accepted = item.model_copy(
                update={"status": "accepted", "reviewed_by": reviewer_id}, deep=True
            )
            self._items[bad_case_id] = accepted
            return accepted
