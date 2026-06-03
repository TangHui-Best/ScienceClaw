from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from ..assistant_runtime import PLAYWRIGHT_RECORDER_RUNTIME_JS
from ..assistant_snapshot_runtime import SNAPSHOT_V2_JS
from ..snapshot_compression import compact_recording_snapshot

from .models import HarnessExpectedSignals, HarnessStepCheckpoint


SnapshotBuilder = Callable[[str, HarnessStepCheckpoint], dict[str, Any]]
SnapshotCompactor = Callable[[dict[str, Any], HarnessStepCheckpoint], dict[str, Any]]
_PRODUCTION_SNAPSHOT_SOURCE = "production-dom-snapshot-v1"


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


def _production_snapshot_compactor(
    raw_snapshot: dict[str, Any],
    checkpoint: HarnessStepCheckpoint,
) -> dict[str, Any]:
    compact = compact_recording_snapshot(raw_snapshot, checkpoint.step_intent)
    compact["_snapshot_source"] = _PRODUCTION_SNAPSHOT_SOURCE
    return compact


class ProductionSnapshotAdapter:
    """Build production raw snapshots from captured HTML without live navigation."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def build_raw_snapshot(
        self,
        html: str,
        checkpoint: HarnessStepCheckpoint,
    ) -> dict[str, Any]:
        page = self._new_page()
        try:
            page.set_content(html, wait_until="domcontentloaded")
            self._install_recorder_runtime(page)
            raw = page.evaluate(SNAPSHOT_V2_JS)
            data = json.loads(raw) if isinstance(raw, str) else raw
            snapshot = data if isinstance(data, dict) else {}
            title = page.title() or checkpoint.before.title
            return {
                "url": checkpoint.before.url,
                "title": title,
                "frames": [
                    {
                        "frame_path": [],
                        "url": checkpoint.before.url,
                        "frame_hint": "main document",
                        "elements": list(snapshot.get("actionable_nodes") or []),
                        "collections": [],
                    }
                ],
                "actionable_nodes": list(snapshot.get("actionable_nodes") or []),
                "content_nodes": list(snapshot.get("content_nodes") or []),
                "containers": list(snapshot.get("containers") or []),
                "table_views": list(snapshot.get("table_views") or []),
                "detail_views": list(snapshot.get("detail_views") or []),
                "_snapshot_source": _PRODUCTION_SNAPSHOT_SOURCE,
            }
        finally:
            page.close()

    def _new_page(self) -> Page:
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        if self._browser is None:
            self._browser = self._playwright.chromium.launch(headless=True)
        return self._browser.new_page()

    @staticmethod
    def _install_recorder_runtime(page: Page) -> None:
        ready = page.evaluate("() => !!globalThis.__rpaPlaywrightRecorder")
        if not ready:
            page.evaluate(PLAYWRIGHT_RECORDER_RUNTIME_JS)


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
    source_html: str,
    raw_snapshot: dict[str, Any],
    compact_snapshot: dict[str, Any],
    missing_text: list[str],
) -> str:
    if not missing_text:
        return ""
    source_missing = [
        text
        for text in missing_text
        if isinstance(text, str) and not _json_contains_text(source_html, text)
    ]
    if source_missing:
        return "source-html-missing-signal"
    raw_missing = [
        text
        for text in missing_text
        if isinstance(text, str) and not _json_contains_text(raw_snapshot, text)
    ]
    if raw_missing:
        return "raw-snapshot-missing-signal"
    return "compact-snapshot-lost-signal"


def _signal_status(payload: Any, required_text: list[str]) -> str:
    if not required_text:
        return "not_checked"
    missing = [
        text
        for text in required_text
        if isinstance(text, str) and not _json_contains_text(payload, text)
    ]
    return "missing" if missing else "present"


def _expected_region_scope(expected: HarnessExpectedSignals) -> dict[str, Any]:
    signal = expected.snapshot_signals.get("must_preserve_region_scope")
    return signal if isinstance(signal, dict) else {}


def _region_scope_status(payload: dict[str, Any], expected_scope: dict[str, Any]) -> str:
    if not expected_scope:
        return "not_checked"
    actual_scope = payload.get("region_scope")
    if not isinstance(actual_scope, dict):
        return "missing"
    expected_region_id = str(expected_scope.get("region_id") or "").strip()
    if expected_region_id and str(actual_scope.get("region_id") or "").strip() != expected_region_id:
        return "missing"
    expected_mode = str(expected_scope.get("mode") or "").strip()
    actual_mode = str(actual_scope.get("mode") or payload.get("mode") or "").strip()
    if expected_mode and actual_mode != expected_mode:
        return "missing"
    expected_frame_path = expected_scope.get("frame_path")
    if isinstance(expected_frame_path, list):
        actual_frame_path = actual_scope.get("frame_path")
        if not isinstance(actual_frame_path, list) or [str(item) for item in actual_frame_path] != [
            str(item) for item in expected_frame_path
        ]:
            return "missing"
    return "present"


def _snapshot_quality(raw_snapshot: dict[str, Any], compact_snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": str(raw_snapshot.get("_snapshot_source") or compact_snapshot.get("_snapshot_source") or "custom"),
        "raw": {
            "frame_count": len(raw_snapshot.get("frames") or []),
            "actionable_node_count": len(raw_snapshot.get("actionable_nodes") or []),
            "content_node_count": len(raw_snapshot.get("content_nodes") or []),
            "container_count": len(raw_snapshot.get("containers") or []),
            "table_view_count": len(raw_snapshot.get("table_views") or []),
            "detail_view_count": len(raw_snapshot.get("detail_views") or []),
        },
        "compact": {
            "mode": str(compact_snapshot.get("mode") or ""),
            "expanded_region_count": len(compact_snapshot.get("expanded_regions") or []),
            "sampled_region_count": len(compact_snapshot.get("sampled_regions") or []),
            "region_catalogue_count": len(compact_snapshot.get("region_catalogue") or []),
            "table_view_count": len(compact_snapshot.get("table_views") or []),
            "detail_view_count": len(compact_snapshot.get("detail_views") or []),
            "form_view_count": len(compact_snapshot.get("form_views") or []),
        },
    }


def run_snapshot_regression(
    assets_root: str | Path,
    *,
    snapshot_builder: SnapshotBuilder | None = None,
    snapshot_compactor: SnapshotCompactor | None = None,
    asset_ids: set[str] | None = None,
) -> dict[str, Any]:
    root = Path(assets_root)
    items: list[dict[str, Any]] = []
    adapter: ProductionSnapshotAdapter | None = None
    if snapshot_builder is None:
        adapter = ProductionSnapshotAdapter()
        snapshot_builder = adapter.build_raw_snapshot
        if snapshot_compactor is None:
            snapshot_compactor = _production_snapshot_compactor
    elif snapshot_compactor is None:
        snapshot_compactor = _default_snapshot_compactor

    try:
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
            expected_scope = _expected_region_scope(expected)
            if expected_scope and "region_scope" not in raw_snapshot:
                raw_snapshot["region_scope"] = dict(expected_scope)
            compact_snapshot = snapshot_compactor(raw_snapshot, checkpoint)
            required_text = list(expected.snapshot_signals.get("must_contain_text") or [])
            missing_text = [
                text
                for text in required_text
                if isinstance(text, str) and not _json_contains_text(compact_snapshot, text)
            ]
            raw_region_scope_status = _region_scope_status(raw_snapshot, expected_scope)
            region_scope_status = _region_scope_status(compact_snapshot, expected_scope)
            missing_region_scope = region_scope_status == "missing"
            source_html_size = len(html)
            raw_snapshot_size = len(json.dumps(raw_snapshot, ensure_ascii=False))
            compact_snapshot_size = len(json.dumps(compact_snapshot, ensure_ascii=False))
            status = "failed" if missing_text or missing_region_scope else "passed"
            failure_category = _snapshot_failure_category(
                html,
                raw_snapshot,
                compact_snapshot,
                missing_text,
            )
            if missing_region_scope:
                failure_category = (
                    "raw-snapshot-missing-region-scope"
                    if raw_region_scope_status == "missing"
                    else "compact-snapshot-lost-region-scope"
                )
            item = {
                "asset_id": _asset_id_for_checkpoint(root, checkpoint_path),
                "step_id": checkpoint.step_id,
                "step_index": checkpoint.step_index,
                "step_intent": checkpoint.step_intent,
                "page_patterns": checkpoint.page_patterns,
                "status": status,
                "failure_category": failure_category,
                "missing_text": missing_text,
                "snapshot_source": str(
                    raw_snapshot.get("_snapshot_source")
                    or compact_snapshot.get("_snapshot_source")
                    or "custom"
                ),
                "source_html_size": source_html_size,
                "raw_snapshot_size": raw_snapshot_size,
                "compact_snapshot_size": compact_snapshot_size,
                "compression_ratio": round(
                    compact_snapshot_size / raw_snapshot_size,
                    4,
                )
                if raw_snapshot_size
                else 0,
                "source_signal_status": _signal_status(html, required_text),
                "raw_signal_status": _signal_status(raw_snapshot, required_text),
                "compact_signal_status": _signal_status(compact_snapshot, required_text),
                "region_scope_status": region_scope_status,
                "snapshot_quality": _snapshot_quality(raw_snapshot, compact_snapshot),
            }
            items.append(item)
    finally:
        if adapter is not None:
            adapter.close()

    failed = len([item for item in items if item["status"] == "failed"])
    return {
        "summary": {
            "total": len(items),
            "passed": len(items) - failed,
            "failed": failed,
        },
        "assets": items,
    }

