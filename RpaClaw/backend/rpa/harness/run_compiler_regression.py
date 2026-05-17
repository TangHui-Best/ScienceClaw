from __future__ import annotations

import argparse
import json
import sys

from .compiler_regression import run_compiler_regression


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RPA Harness compiler regression")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    args = parser.parse_args()

    report = run_compiler_regression(args.assets)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())

