from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .cli import emit_json_report
from .governed_regression import run_governed_offline_regression
from .observability import render_chinese_summary, render_human_summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run governed RPA Harness offline regression")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    parser.add_argument("--output", help="Optional path to write the governed regression JSON report")
    parser.add_argument(
        "--format",
        choices=["json", "summary"],
        default="json",
        help="Output JSON report or concise human-readable summary",
    )
    parser.add_argument(
        "--lang",
        choices=["en", "zh"],
        default="en",
        help="Language for --format summary output",
    )
    args = parser.parse_args(argv)

    report = run_governed_offline_regression(args.assets)
    if args.format == "summary":
        rendered = render_chinese_summary(report) if args.lang == "zh" else render_human_summary(report)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
            sys.stdout.flush()
    else:
        emit_json_report(report, output_path=args.output)
    return 1 if report["summary"]["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
