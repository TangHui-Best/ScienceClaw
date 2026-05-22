from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .cli import emit_json_report
from .live_agent_eval import run_live_agent_eval


def _load_model_config(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.model_config_json:
        return json.loads(args.model_config_json)
    if args.model_config_file:
        return json.loads(Path(args.model_config_file).read_text(encoding="utf-8"))
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run live RPA Agent Harness scenarios against controlled HTML")
    parser.add_argument("--scenarios", required=True, help="Directory containing live-agent scenario JSON files")
    parser.add_argument("--assets", required=True, help="Directory where generated Harness assets should be written")
    parser.add_argument("--output", help="Optional path to write the live-agent evaluation JSON report")
    parser.add_argument("--model-config-json", help="Optional JSON object passed to RecordingRuntimeAgent model_config")
    parser.add_argument("--model-config-file", help="Optional JSON file passed to RecordingRuntimeAgent model_config")
    args = parser.parse_args(argv)

    try:
        model_config = _load_model_config(args)
        report = asyncio.run(
            run_live_agent_eval(
                scenarios_root=args.scenarios,
                assets_root=args.assets,
                model_config=model_config,
            )
        )
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 1

    emit_json_report(report, output_path=args.output)
    return 1 if report["summary"]["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
