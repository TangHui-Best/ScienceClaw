from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from tests.rpa_harness.evaluators.dom_morphology import DomMorphologyEvaluator
from tests.rpa_harness.evaluators.snapshot_diff import SnapshotDiffEvaluator


CASE_ROOT = Path(__file__).parent / "cases" / "dom_morphology"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    command = args[0] if args else "dom"
    if command == "dom":
        return _run_dom()
    if command == "snapshot":
        return _run_snapshot()

    if command not in {"dom", "snapshot"}:
        print(f"Unsupported RPA harness command: {command}")
        return 2


def _run_dom() -> int:
    summary = DomMorphologyEvaluator.from_directory(CASE_ROOT).summarize()
    print(f"DOM morphology cases: {summary.case_count}")
    print(f"pass: {summary.passed_count}")
    print(f"fail: {summary.failed_count}")
    for result in summary.results:
        if result.passed:
            continue
        missing = ", ".join([*result.missing_facts, *result.missing_locators])
        print(f"- {result.case_id}: {result.attribution_layer}: {missing}")
    return 0 if summary.passed else 1


def _run_snapshot() -> int:
    summary = SnapshotDiffEvaluator.from_directory(CASE_ROOT).summarize()
    print(f"Snapshot diff cases: {summary.case_count}")
    print(f"pass: {summary.passed_count}")
    print(f"fail: {summary.failed_count}")
    for result in summary.results:
        if result.passed:
            continue
        missing = ", ".join(fact.key for fact in result.missing_facts)
        print(f"- {result.case_id}: {result.attribution_layer}: {missing}")
    return 0 if summary.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
