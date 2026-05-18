from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from typing import Any, Callable

from .models import HarnessExpectedSignals, HarnessStepCheckpoint


SnapshotBuilder = Callable[[str, HarnessStepCheckpoint], dict[str, Any]]
SnapshotCompactor = Callable[[dict[str, Any], HarnessStepCheckpoint], dict[str, Any]]


def _default_snapshot_builder(html: str, checkpoint: HarnessStepCheckpoint) -> dict[str, Any]:
    return {
        "url": checkpoint.before.url,
        "title": checkpoint.before.title,
        "html": html,
    }


def _default_snapshot_compactor(
    raw_snapshot: dict[str, Any],
    _checkpoint: HarnessStepCheckpoint,
) -> dict[str, Any]:
    return dict(raw_snapshot)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _asset_id_for_checkpoint(assets_root: Path, checkpoint_path: Path) -> str:
    try:
        return checkpoint_path.relative_to(assets_root).parts[0]
    except Exception:
        return checkpoint_path.parent.parent.parent.name


def _json_contains_text(payload: Any, text: str) -> bool:
    serialized = json.dumps(payload, ensure_ascii=False)
    if text in serialized:
        return True
    return _normalize_match_text(text) in _normalize_match_text(serialized)


def _normalize_match_text(value: str) -> str:
    decoded = unescape(str(value)).replace("\\n", " ").replace("\\t", " ").replace("\\r", " ")
    without_tags = re.sub(r"<[^>]+>", " ", decoded)
    return re.sub(r"\s+", " ", without_tags).strip()


def _snapshot_failure_category(
    raw_snapshot: dict[str, Any],
    compact_snapshot: dict[str, Any],
    missing_text: list[str],
) -> str:
    if not missing_text:
        return ""
    raw_missing = [
        text
        for text in missing_text
        if isinstance(text, str) and not _json_contains_text(raw_snapshot, text)
    ]
    if raw_missing:
        return "raw-html-missing-signal"
    return "compact-snapshot-lost-signal"


def run_snapshot_regression(
    assets_root: str | Path,
    *,
    snapshot_builder: SnapshotBuilder = _default_snapshot_builder,
    snapshot_compactor: SnapshotCompactor = _default_snapshot_compactor,
    asset_ids: set[str] | None = None,
) -> dict[str, Any]:
    root = Path(assets_root)
    items: list[dict[str, Any]] = []

    for checkpoint_path in sorted(root.glob("*/steps/*/checkpoint.json")):
        asset_id = _asset_id_for_checkpoint(root, checkpoint_path)
        if asset_ids is not None and asset_id not in asset_ids:
            continue
        checkpoint = HarnessStepCheckpoint.model_validate(_load_json(checkpoint_path))
        capture_dir = checkpoint_path.parents[2]
        before_html_path = capture_dir / checkpoint.before.html_path
        html = before_html_path.read_text(encoding="utf-8")
        expected_payload = _load_json(capture_dir / checkpoint.expected_path)
        expected = HarnessExpectedSignals.model_validate(expected_payload)

        raw_snapshot = snapshot_builder(html, checkpoint)
        compact_snapshot = snapshot_compactor(raw_snapshot, checkpoint)
        required_text = list(expected.snapshot_signals.get("must_contain_text") or [])
        missing_text = [
            text
            for text in required_text
            if isinstance(text, str) and not _json_contains_text(compact_snapshot, text)
        ]
        status = "failed" if missing_text else "passed"
        failure_category = _snapshot_failure_category(raw_snapshot, compact_snapshot, missing_text)
        item = {
            "asset_id": _asset_id_for_checkpoint(root, checkpoint_path),
            "step_id": checkpoint.step_id,
            "step_index": checkpoint.step_index,
            "step_intent": checkpoint.step_intent,
            "page_patterns": checkpoint.page_patterns,
            "status": status,
            "failure_category": failure_category,
            "missing_text": missing_text,
            "raw_snapshot_size": len(json.dumps(raw_snapshot, ensure_ascii=False)),
            "compact_snapshot_size": len(json.dumps(compact_snapshot, ensure_ascii=False)),
        }
        items.append(item)

    failed = len([item for item in items if item["status"] == "failed"])
    return {
        "summary": {
            "total": len(items),
            "passed": len(items) - failed,
            "failed": failed,
        },
        "assets": items,
    }

