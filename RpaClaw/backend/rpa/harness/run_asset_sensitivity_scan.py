from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .cli import emit_json_report
from .sensitivity_scan import scan_harness_assets, write_sensitivity_scan_sidecars


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan RPA Harness assets for sensitive information")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    parser.add_argument("--asset-id", action="append", help="Optional asset id to scan; repeatable")
    parser.add_argument(
        "--output",
        help=(
            "Optional path to write an aggregate JSON scan report. "
            "When omitted, per-asset reports are written to <asset_dir>/sensitivity_scan.json."
        ),
    )
    args = parser.parse_args(argv)

    asset_ids = set(args.asset_id) if args.asset_id else None
    report = scan_harness_assets(args.assets, asset_ids=asset_ids)
    if args.output:
        emit_json_report(report, output_path=args.output)
    else:
        report = dict(report)
        report["sidecar_reports"] = write_sensitivity_scan_sidecars(args.assets, report)
        emit_json_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
