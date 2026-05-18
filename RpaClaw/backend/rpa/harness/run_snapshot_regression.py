from __future__ import annotations

import argparse
import sys

from .cli import emit_json_report
from .snapshot_regression import run_snapshot_regression


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RPA Harness snapshot regression")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    args = parser.parse_args()

    report = run_snapshot_regression(args.assets)
    emit_json_report(report)
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())

