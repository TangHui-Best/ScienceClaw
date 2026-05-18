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


def test_snapshot_regression_default_uses_production_snapshot_chain(tmp_path: Path):
    assets = _write_checkpoint_asset(tmp_path)
    before_html = """
    <html>
      <head><title>Search</title></head>
      <body>
        <main data-section="results">
          <h2><a href="/scienceclaw">ScienceClaw</a></h2>
        </main>
      </body>
    </html>
    """
    (tmp_path / "asset-1" / "steps" / "001" / "before.html").write_text(
        before_html,
        encoding="utf-8",
    )

    report = run_snapshot_regression(assets)

    item = report["assets"][0]
    assert report["summary"]["failed"] == 0
    assert item["snapshot_source"] == "production-dom-snapshot-v1"
    assert item["source_html_size"] > 0
    assert item["raw_snapshot_size"] > 0
    assert item["compact_snapshot_size"] > 0
    assert item["compression_ratio"] > 0
    assert item["raw_signal_status"] == "present"
    assert item["compact_signal_status"] == "present"
    assert item["snapshot_quality"]["raw"]["content_node_count"] >= 1
    assert item["snapshot_quality"]["compact"]["mode"] in {"clean_snapshot", "tiered_snapshot"}


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
    assert item["failure_category"] == "source-html-missing-signal"
    assert item["missing_text"] == ["Missing Project"]


def test_snapshot_regression_distinguishes_source_html_missing_signal(tmp_path: Path):
    assets = _write_checkpoint_asset(tmp_path, compact_text="Missing Project")

    report = run_snapshot_regression(
        assets,
        snapshot_builder=lambda html, checkpoint: {"html": html},
        snapshot_compactor=lambda raw, checkpoint: dict(raw),
    )

    item = report["assets"][0]
    assert report["summary"]["failed"] == 1
    assert item["failure_category"] == "source-html-missing-signal"
    assert item["raw_signal_status"] == "missing"
    assert item["compact_signal_status"] == "missing"
    assert item["missing_text"] == ["Missing Project"]


def test_snapshot_regression_distinguishes_raw_snapshot_missing_signal(tmp_path: Path):
    assets = _write_checkpoint_asset(tmp_path, compact_text="ScienceClaw")

    report = run_snapshot_regression(
        assets,
        snapshot_builder=lambda html, checkpoint: {"visible_text": "Other Project"},
        snapshot_compactor=lambda raw, checkpoint: dict(raw),
    )

    item = report["assets"][0]
    assert report["summary"]["failed"] == 1
    assert item["failure_category"] == "raw-snapshot-missing-signal"
    assert item["raw_signal_status"] == "missing"
    assert item["compact_signal_status"] == "missing"
    assert item["missing_text"] == ["ScienceClaw"]


def test_snapshot_regression_distinguishes_compact_signal_loss(tmp_path: Path):
    assets = _write_checkpoint_asset(tmp_path, compact_text="ScienceClaw")

    report = run_snapshot_regression(
        assets,
        snapshot_builder=lambda html, checkpoint: {"html": html},
        snapshot_compactor=lambda raw, checkpoint: {"visible_text": "Other Project"},
    )

    item = report["assets"][0]
    assert report["summary"]["failed"] == 1
    assert item["failure_category"] == "compact-snapshot-lost-signal"
    assert item["raw_signal_status"] == "present"
    assert item["compact_signal_status"] == "missing"
    assert item["missing_text"] == ["ScienceClaw"]


def test_snapshot_regression_matches_normalized_split_text(tmp_path: Path):
    assets = _write_checkpoint_asset(tmp_path, compact_text="tinyhumansai / openhuman")
    before_html = (
        "<html><body><h2><span>tinyhumansai /</span>\n"
        "      <strong>openhuman</strong></h2></body></html>"
    )
    (tmp_path / "asset-1" / "steps" / "001" / "before.html").write_text(before_html, encoding="utf-8")

    report = run_snapshot_regression(
        assets,
        snapshot_builder=lambda html, checkpoint: {"html": html},
        snapshot_compactor=lambda raw, checkpoint: dict(raw),
    )

    assert report["summary"]["failed"] == 0
    assert report["assets"][0]["missing_text"] == []

