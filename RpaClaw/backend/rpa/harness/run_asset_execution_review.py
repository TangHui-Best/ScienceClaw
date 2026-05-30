from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .asset_execution_review import write_asset_execution_review_packets
from .cli import emit_json_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate RPA Harness asset execution review packets")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    parser.add_argument("--asset-id", action="append", help="Optional asset id to review; repeatable")
    parser.add_argument("--output", help="Optional path to write the JSON generation report")
    args = parser.parse_args(argv)

    asset_ids = set(args.asset_id) if args.asset_id else None
    report = write_asset_execution_review_packets(args.assets, asset_ids=asset_ids)
    emit_json_report(report, output_path=args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
