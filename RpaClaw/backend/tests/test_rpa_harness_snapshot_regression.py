import json
from pathlib import Path

from backend.rpa.harness.snapshot_regression import run_snapshot_regression


def _write_checkpoint_asset(root: Path, *, compact_text: str = "ScienceClaw") -> Path:
    step_dir = root / "asset-1" / "steps" / "001"
    step_dir.mkdir(parents=True)
    (step_dir / "before.html").write_text(
        "<html><body><a>ScienceClaw</a></body></html>",
        encoding="utf-8",
    )
    (step_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "step_index": 1,
                "step_id": "step-1",
                "step_intent": "Click ScienceClaw",
                "recording_mode": "natural_language",
                "page_patterns": ["search-result"],
                "before": {
                    "url": "https://example.test/search",
                    "title": "Search",
                    "html_path": "steps/001/before.html",
                    "html_sha256": "abc",
                },
                "action": {
                    "trace_events_path": "steps/001/trace_events.json",
                    "expected_action_type": "click",
                },
                "after": {
                    "url": "https://example.test/project",
                    "title": "Project",
                    "html_path": "steps/001/after.html",
                    "html_sha256": "def",
                },
                "runtime_result": {"status": "success"},
                "captured_at": "2026-05-17T10:00:00",
                "expected_path": "steps/001/expected.json",
            }
        ),
        encoding="utf-8",
    )
    (step_dir / "expected.json").write_text(
        json.dumps({"snapshot_signals": {"must_contain_text": [compact_text]}}),
        encoding="utf-8",
    )
    return root


def test_snapshot_regression_passes_when_expected_text_is_preserved(tmp_path: Path):
    assets = _write_checkpoint_asset(tmp_path)

    report = run_snapshot_regression(
        assets,
        snapshot_builder=lambda html, checkpoint: {"html": html, "url": checkpoint.before.url},
        snapshot_compactor=lambda raw, checkpoint: {"visible_text": raw["html"]},
    )

    assert report["summary"]["total"] == 1
    assert report["summary"]["failed"] == 0
    assert report["assets"][0]["asset_id"] == "asset-1"
    assert report["assets"][0]["step_id"] == "step-1"
    assert report["assets"][0]["page_patterns"] == ["search-result"]


def test_snapshot_regression_reports_missing_expected_text(tmp_path: Path):
    assets = _write_checkpoint_asset(tmp_path, compact_text="Missing Project")

    report = run_snapshot_regression(
        assets,
        snapshot_builder=lambda html, checkpoint: {"html": html},
        snapshot_compactor=lambda raw, checkpoint: {"visible_text": "ScienceClaw"},
    )

    item = report["assets"][0]
    assert report["summary"]["failed"] == 1
    assert item["status"] == "failed"
    assert item["failure_category"] == "compact-snapshot-lost-signal"
    assert item["missing_text"] == ["Missing Project"]

