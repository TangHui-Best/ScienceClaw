from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class HarnessAssetStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def capture_dir(self, capture_id: str) -> Path:
        return self._resolve_under_root(capture_id)

    def step_dir(self, capture_id: str, step_index: int) -> Path:
        return self._resolve_under_root(capture_id, "steps", f"{step_index:03d}")

    def write_text(self, path: Path, content: str) -> None:
        self._ensure_under_root(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_json(self, path: Path, payload: Any) -> None:
        self._ensure_under_root(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _resolve_under_root(self, *parts: str) -> Path:
        path = self.root.joinpath(*parts)
        self._ensure_under_root(path)
        return path

    def _ensure_under_root(self, path: Path) -> None:
        root = self.root.resolve()
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"Harness asset path escapes root: {path}")

