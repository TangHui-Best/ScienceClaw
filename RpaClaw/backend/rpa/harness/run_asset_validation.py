from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .asset_validation import validate_harness_assets
from .cli import emit_json_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate RPA Harness asset completeness")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    parser.add_argument("--output", help="Optional path to write the validation JSON report")
    args = parser.parse_args(argv)

    report = validate_harness_assets(args.assets)
    emit_json_report(report, output_path=args.output)
    return 1 if report["summary"]["blocking_issue_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
