from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from backend.rpa.snapshot_compression import compact_recording_snapshot


@dataclass(frozen=True)
class DomMorphologyCase:
    case_id: str
    title: str
    task_shape: str
    instruction: str
    raw_snapshot: dict[str, Any]
    expected_raw_facts: list[str]
    expected_compact_facts: list[str]
    expected_semantic_view: dict[str, Any]
    expected_locator_preservation: list[str]
    guarded_failure_mode: str
    case_type: str = "dom_morphology"
    source: str = "curated_structural_fixture"
    char_budget: int = 1

    @classmethod
    def from_path(cls, path: Path) -> "DomMorphologyCase":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            case_id=str(payload["case_id"]),
            title=str(payload["title"]),
            task_shape=str(payload["task_shape"]),
            instruction=str(payload["instruction"]),
            raw_snapshot=dict(payload["raw_snapshot"]),
            expected_raw_facts=[str(item) for item in payload.get("expected_raw_facts", [])],
            expected_compact_facts=[str(item) for item in payload.get("expected_compact_facts", [])],
            expected_semantic_view=dict(payload.get("expected_semantic_view") or {}),
            expected_locator_preservation=[
                str(item) for item in payload.get("expected_locator_preservation", [])
            ],
            guarded_failure_mode=str(payload["guarded_failure_mode"]),
            case_type=str(payload.get("case_type") or "dom_morphology"),
            source=str(payload.get("source") or "curated_structural_fixture"),
            char_budget=int(payload.get("char_budget", 1)),
        )


@dataclass(frozen=True)
class DomMorphologyResult:
    case_id: str
    title: str
    task_shape: str
    passed: bool
    attribution_layer: str
    missing_facts: list[str] = field(default_factory=list)
    missing_locators: list[str] = field(default_factory=list)
    compact_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DomMorphologySummary:
    case_count: int
    passed_count: int
    failed_count: int
    results: list[DomMorphologyResult]

    @property
    def passed(self) -> bool:
        return self.failed_count == 0


class DomMorphologyEvaluator:
    def __init__(self, cases: Iterable[DomMorphologyCase]) -> None:
        self.cases = list(cases)

    @classmethod
    def from_directory(cls, case_root: Path) -> "DomMorphologyEvaluator":
        cases = [
            DomMorphologyCase.from_path(path)
            for path in sorted(case_root.glob("*/case.json"))
        ]
        return cls(cases)

    def evaluate(self) -> list[DomMorphologyResult]:
        return [self._evaluate_case(case) for case in self.cases]

    def summarize(self) -> DomMorphologySummary:
        results = self.evaluate()
        passed_count = sum(1 for result in results if result.passed)
        return DomMorphologySummary(
            case_count=len(results),
            passed_count=passed_count,
            failed_count=len(results) - passed_count,
            results=results,
        )

    def _evaluate_case(self, case: DomMorphologyCase) -> DomMorphologyResult:
        raw_text = _flatten_text(case.raw_snapshot)
        raw_missing = [fact for fact in case.expected_raw_facts if fact not in raw_text]
        compact = compact_recording_snapshot(
            case.raw_snapshot,
            case.instruction,
            char_budget=case.char_budget,
        )
        compact_text = _flatten_text(compact)

        if raw_missing:
            return DomMorphologyResult(
                case_id=case.case_id,
                title=case.title,
                task_shape=case.task_shape,
                passed=False,
                attribution_layer="raw_missing",
                missing_facts=raw_missing,
                compact_snapshot=compact,
            )

        expected_compact = [
            *case.expected_compact_facts,
            *[
                str(value)
                for value in case.expected_semantic_view.values()
                if isinstance(value, str) and value
            ],
        ]
        compact_missing = [fact for fact in expected_compact if fact not in compact_text]
        missing_locators = [
            locator
            for locator in case.expected_locator_preservation
            if locator not in compact_text
        ]
        if compact_missing or missing_locators:
            return DomMorphologyResult(
                case_id=case.case_id,
                title=case.title,
                task_shape=case.task_shape,
                passed=False,
                attribution_layer="compact_loss",
                missing_facts=compact_missing,
                missing_locators=missing_locators,
                compact_snapshot=compact,
            )

        return DomMorphologyResult(
            case_id=case.case_id,
            title=case.title,
            task_shape=case.task_shape,
            passed=True,
            attribution_layer="passed",
            compact_snapshot=compact,
        )


def _flatten_text(payload: Any) -> str:
    if isinstance(payload, dict):
        return " ".join(_flatten_text(value) for value in payload.values())
    if isinstance(payload, list):
        return " ".join(_flatten_text(item) for item in payload)
    return str(payload)
