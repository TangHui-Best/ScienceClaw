from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO


def render_json_report(report: Any) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def emit_json_report(
    report: Any,
    *,
    output_path: str | Path | None = None,
    stdout: TextIO | None = None,
) -> None:
    rendered = render_json_report(report)
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        return

    stream = stdout or sys.stdout
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write((rendered + "\n").encode("utf-8"))
        flush = getattr(buffer, "flush", None)
        if callable(flush):
            flush()
        return

    stream.write(rendered + "\n")
    stream.flush()
