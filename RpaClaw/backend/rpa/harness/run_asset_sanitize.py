from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .asset_sanitization import sanitize_harness_asset
from .cli import emit_json_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a sanitized copy of an RPA Harness asset")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    parser.add_argument("--asset-id", required=True, help="Source asset id")
    parser.add_argument("--target-asset-id", help="Target sanitized asset id; defaults to <asset-id>-sanitized")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing sanitized target asset")
    parser.add_argument("--output", help="Optional path to write the sanitization JSON report")
    args = parser.parse_args(argv)

    report = sanitize_harness_asset(
        args.assets,
        args.asset_id,
        target_asset_id=args.target_asset_id,
        overwrite=args.overwrite,
    )
    emit_json_report(report, output_path=args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
