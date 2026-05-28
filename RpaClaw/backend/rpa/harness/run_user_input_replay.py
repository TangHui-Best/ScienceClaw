from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .cli import emit_json_report
from .user_input_replay import render_user_input_replay_summary, run_user_input_replay


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run RPA Harness asset-driven user input replay")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    parser.add_argument(
        "--mode",
        default="deterministic",
        help="Replay mode. Phase 4 first slice supports only deterministic.",
    )
    parser.add_argument("--output", help="Optional path to write the replay report")
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
    parser.add_argument(
        "--machine-report",
        help="Optional machine-readable JSON report path referenced by summary output",
    )
    args = parser.parse_args(argv)

    try:
        report = run_user_input_replay(args.assets, mode=args.mode)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    if args.format == "summary":
        rendered = render_user_input_replay_summary(
            report,
            machine_report_path=args.machine_report,
            lang=args.lang,
        )
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
            sys.stdout.flush()
    else:
        emit_json_report(report, output_path=args.output)

    return 1 if report["summary"].get("status") == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
