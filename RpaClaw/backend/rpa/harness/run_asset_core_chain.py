from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .asset_core_chain import run_asset_core_chain_export
from .cli import emit_json_report


def _load_model_config(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.model_config_json:
        return json.loads(args.model_config_json)
    if args.model_config_file:
        return json.loads(Path(args.model_config_file).read_text(encoding="utf-8"))
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export asset-local RPA Harness core-chain reports and generated Skills"
    )
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    parser.add_argument("--asset-id", action="append", help="Optional asset id; repeatable")
    parser.add_argument(
        "--model-config-json",
        help="Optional JSON object injected into generated Skill runtime AI replay",
    )
    parser.add_argument(
        "--model-config-file",
        help="Optional JSON file injected into generated Skill runtime AI replay",
    )
    parser.add_argument("--output", help="Optional aggregate JSON report path")
    args = parser.parse_args(argv)

    report = run_asset_core_chain_export(
        args.assets,
        asset_ids=set(args.asset_id) if args.asset_id else None,
        model_config=_load_model_config(args),
    )
    emit_json_report(report, output_path=args.output)
    return 1 if report["summary"]["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
