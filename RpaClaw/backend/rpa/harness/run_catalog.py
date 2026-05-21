from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .catalog import build_harness_catalog
from .cli import emit_json_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an RPA Harness asset catalog")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    parser.add_argument("--output", help="Optional path to write the catalog JSON report")
    args = parser.parse_args(argv)

    report = build_harness_catalog(args.assets)
    emit_json_report(report, output_path=args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
