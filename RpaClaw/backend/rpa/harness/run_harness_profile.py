from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .cli import emit_json_report
from .profile_runner import render_profile_summary, run_harness_profile


def _load_model_config(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.model_config_json:
        return json.loads(args.model_config_json)
    if args.model_config_file:
        return json.loads(Path(args.model_config_file).read_text(encoding="utf-8"))
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an RPA Harness execution profile")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    parser.add_argument(
        "--profile",
        default="deterministic",
        help="Profile to run: deterministic or full-live.",
    )
    parser.add_argument(
        "--generated-assets",
        help=(
            "Output directory for full-live generated candidate-lite/profile "
            "artifacts. Deterministic profile ignores this option."
        ),
    )
    parser.add_argument("--model-config-json", help="Optional JSON object passed to full-live RecordingRuntimeAgent")
    parser.add_argument("--model-config-file", help="Optional JSON file passed to full-live RecordingRuntimeAgent")
    parser.add_argument("--output", help="Optional path to write the profile report")
    parser.add_argument(
        "--machine-report",
        help=(
            "Optional machine-readable JSON report path referenced by summary "
            "output. Use this when generating human summaries after or beside a "
            "JSON profile run."
        ),
    )
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

    try:
        if args.format == "summary" and args.machine_report and Path(args.machine_report).exists():
            report = json.loads(Path(args.machine_report).read_text(encoding="utf-8"))
        else:
            model_config = _load_model_config(args) if args.profile == "full-live" else None
            report = run_harness_profile(
                args.assets,
                profile=args.profile,
                generated_assets_root=args.generated_assets,
                model_config=model_config,
            )
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2

    if args.format == "summary":
        rendered = render_profile_summary(
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
    return 1 if report["summary"]["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
