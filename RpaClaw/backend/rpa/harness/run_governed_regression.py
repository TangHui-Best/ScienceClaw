from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .cli import emit_json_report
from .governed_regression import run_governed_offline_regression


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run governed RPA Harness offline regression")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    parser.add_argument("--output", help="Optional path to write the governed regression JSON report")
    args = parser.parse_args(argv)

    report = run_governed_offline_regression(args.assets)
    emit_json_report(report, output_path=args.output)
    return 1 if report["summary"]["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
