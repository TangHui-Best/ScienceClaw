from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .asset_pool_doctor import build_asset_pool_doctor_report, render_asset_pool_doctor_summary
from .cli import emit_json_report


def _emit_text(text: str, *, output_path: str | None = None) -> None:
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
        return
    sys.stdout.write(text)
    sys.stdout.flush()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect RPA Harness asset pool readiness")
    parser.add_argument("--assets", required=True, help="Path to RPA Harness assets root")
    parser.add_argument("--output", help="Optional path to write the report")
    parser.add_argument(
        "--format",
        choices=["json", "summary"],
        default="json",
        help="Report shape to generate",
    )
    parser.add_argument(
        "--lang",
        choices=["zh", "en"],
        default="zh",
        help="Summary language",
    )
    args = parser.parse_args(argv)

    report = build_asset_pool_doctor_report(args.assets)
    if args.format == "summary":
        _emit_text(
            render_asset_pool_doctor_summary(report, lang=args.lang),
            output_path=args.output,
        )
    else:
        emit_json_report(report, output_path=args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
