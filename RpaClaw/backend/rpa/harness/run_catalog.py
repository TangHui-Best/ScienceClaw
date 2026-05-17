from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .catalog import build_harness_catalog


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an RPA Harness asset catalog")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    parser.add_argument("--output", help="Optional path to write the catalog JSON report")
    args = parser.parse_args(argv)

    report = build_harness_catalog(args.assets)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
