from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .catalog import (
    build_asset_lifecycle_summary,
    build_golden_eligibility_report,
    build_harness_catalog,
)
from .cli import emit_json_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an RPA Harness asset catalog")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    parser.add_argument("--output", help="Optional path to write the catalog JSON report")
    parser.add_argument(
        "--format",
        choices=["catalog", "lifecycle", "golden-eligibility"],
        default="catalog",
        help="Report shape to generate",
    )
    args = parser.parse_args(argv)

    if args.format == "lifecycle":
        report = build_asset_lifecycle_summary(args.assets)
    elif args.format == "golden-eligibility":
        report = build_golden_eligibility_report(args.assets)
    else:
        report = build_harness_catalog(args.assets)
    emit_json_report(report, output_path=args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
