from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .asset_promotion import PromotionError, promote_harness_asset
from .cli import emit_json_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Promote an RPA Harness scenario asset")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    parser.add_argument("--asset-id", required=True, help="Scenario asset id to promote")
    parser.add_argument(
        "--level",
        required=True,
        choices=["candidate-lite", "candidate", "golden"],
        help="Promotion level to apply",
    )
    parser.add_argument(
        "--confirm-expected",
        action="store_true",
        help="Confirm expected signals were reviewed for candidate/golden promotion",
    )
    parser.add_argument(
        "--confirm-sensitivity",
        action="store_true",
        help="Confirm sensitivity was reviewed for candidate/golden promotion",
    )
    parser.add_argument("--output", help="Optional path to write the promotion JSON report")
    args = parser.parse_args(argv)

    try:
        report = promote_harness_asset(
            args.assets,
            args.asset_id,
            args.level,
            confirm_expected=args.confirm_expected,
            confirm_sensitivity=args.confirm_sensitivity,
        )
    except PromotionError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    emit_json_report(report, output_path=args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
