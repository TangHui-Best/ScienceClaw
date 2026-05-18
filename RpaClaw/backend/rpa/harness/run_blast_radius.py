from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .blast_radius import build_blast_radius_report
from .cli import emit_json_report


def _load_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an RPA Harness blast-radius report")
    parser.add_argument("--snapshot-report", required=True, help="Path to snapshot regression JSON report")
    parser.add_argument("--compiler-report", required=True, help="Path to compiler regression JSON report")
    parser.add_argument("--catalog", help="Optional path to Harness catalog JSON report")
    parser.add_argument("--output", help="Optional path to write the blast-radius JSON report")
    args = parser.parse_args(argv)

    report = build_blast_radius_report(
        snapshot_report=_load_json(args.snapshot_report),
        compiler_report=_load_json(args.compiler_report),
        catalog=_load_json(args.catalog),
    )
    emit_json_report(report, output_path=args.output)
    return 1 if report["summary"]["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
