import json
from pathlib import Path

from backend.rpa.harness.asset_sanitization import sanitize_harness_asset
from backend.rpa.harness.run_asset_sanitize import main as run_asset_sanitize_main
from backend.rpa.harness.sensitivity_scan import scan_harness_assets


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_sensitive_asset(root: Path, asset_id: str = "raw-asset") -> Path:
    capture_dir = root / asset_id
    _write_json(
        capture_dir / "scenario.json",
        {
            "schema_version": "rpa-harness-scenario-v0",
            "asset_id": asset_id,
            "capture_scope": "full_sop",
            "sop_intent": "Review sensitive transaction",
            "source": {
                "recording_id": "session-raw",
                "captured_at": "2026-05-30T12:00:00",
                "capture_mode": "harness",
                "capture_trigger": "full_sop",
            },
            "asset_status": "draft",
            "sensitivity": "local-only",
            "environment": {},
            "governance": {
                "promotion_status": "candidate-lite",
                "runner_modes": ["offline_core_chain"],
                "core_chain_coverage": [],
                "expected_signals_reviewed": False,
                "sensitivity_reviewed": False,
                "review_notes": "",
            },
            "step_checkpoints": [{"step_index": 1, "checkpoint_path": "steps/001/checkpoint.json"}],
        },
    )
    step_dir = capture_dir / "steps" / "001"
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / "before.html").write_text(
        '<html><body><input type="password" value="hunter2"> alice@example.com</body></html>',
        encoding="utf-8",
    )
    (step_dir / "after.html").write_text(
        "<html><body>Amount $99.00 path C:\\Users\\alice\\Downloads\\statement.pdf</body></html>",
        encoding="utf-8",
    )
    _write_json(
        step_dir / "trace_events.json",
        [
            {
                "trace_id": "trace-1",
                "action": "ai_operation",
                "input": {"password": "hunter2"},
                "session_id": "8ded3be8-475b-44d0-8662-4f3ded111e86",
                "output_key": "amount",
                "output": {
                    "email": "alice@example.com",
                    "amount": "$99.00",
                    "path": "C:\\Users\\alice\\Downloads\\statement.pdf",
                },
                "accepted": True,
            }
        ],
    )
    _write_json(
        step_dir / "expected.json",
        {
            "state_signals": {
                "output_key": "amount",
                "observed_output_shape": {"type": "object", "keys": ["email", "amount", "path"]},
            }
        },
    )
    _write_json(
        step_dir / "checkpoint.json",
        {
            "step_index": 1,
            "step_id": "step-1",
            "step_intent": "Extract transaction",
            "recording_mode": "natural_language",
            "before": {
                "url": "https://bank.example/transaction",
                "title": "Transaction",
                "html_path": "steps/001/before.html",
                "html_sha256": "before",
            },
            "action": {"trace_events_path": "steps/001/trace_events.json"},
            "after": {
                "url": "https://bank.example/transaction",
                "title": "Transaction",
                "html_path": "steps/001/after.html",
                "html_sha256": "after",
            },
            "runtime_result": {"status": "success"},
            "captured_at": "2026-05-30T12:00:00",
            "expected_path": "steps/001/expected.json",
        },
    )
    return capture_dir


def test_sanitize_harness_asset_creates_derived_copy_without_mutating_raw_asset(tmp_path: Path):
    raw_dir = _write_sensitive_asset(tmp_path)
    (raw_dir / "sensitivity_scan.json").write_text('{"stale": "alice@example.com"}', encoding="utf-8")
    (raw_dir / "review.md").write_text("stale review alice@example.com", encoding="utf-8")

    report = sanitize_harness_asset(tmp_path, "raw-asset", target_asset_id="raw-asset-sanitized")

    sanitized_dir = tmp_path / "raw-asset-sanitized"
    assert report["source_asset_id"] == "raw-asset"
    assert report["target_asset_id"] == "raw-asset-sanitized"
    assert sanitized_dir.exists()
    assert "alice@example.com" in (raw_dir / "steps" / "001" / "trace_events.json").read_text(encoding="utf-8")
    assert "alice@example.com" not in (sanitized_dir / "steps" / "001" / "trace_events.json").read_text(encoding="utf-8")
    assert "<EMAIL_1>" in (sanitized_dir / "steps" / "001" / "trace_events.json").read_text(encoding="utf-8")
    assert "<AMOUNT_1>" in (sanitized_dir / "steps" / "001" / "after.html").read_text(encoding="utf-8")
    assert (sanitized_dir / "sanitization_report.json").exists()
    assert not (sanitized_dir / "sensitivity_scan.json").exists()
    assert not (sanitized_dir / "review.md").exists()

    scenario = json.loads((sanitized_dir / "scenario.json").read_text(encoding="utf-8"))
    assert scenario["asset_id"] == "raw-asset-sanitized"
    assert scenario["sensitivity"] == "sanitized"
    assert scenario["environment"]["sanitized_from_asset_id"] == "raw-asset"
    assert scenario["governance"]["promotion_status"] == "candidate-lite"
    assert scenario["governance"]["sensitivity_reviewed"] is False

    expected = json.loads((sanitized_dir / "steps" / "001" / "expected.json").read_text(encoding="utf-8"))
    contract = expected["state_signals"]["sanitization_contract"]
    assert contract["runtime_secret_refs"] == []
    assert "sanitized asset preserves output shape and SOP replay evidence" in contract["replay_assertions"]
    tokens = {item["token"]: item["semantic_type"] for item in contract["placeholders"]}
    assert tokens["<EMAIL_1>"] == "email"
    assert tokens["<AMOUNT_1>"] == "currency_amount"
    assert tokens["<LOCAL_PATH_1>"] == "local_path"
    assert tokens["<SESSION_ID_1>"] == "session_identifier"

    scan = scan_harness_assets(tmp_path, asset_ids={"raw-asset-sanitized"})
    asset = scan["assets"][0]
    assert asset["repo_safe_blocked"] is False
    assert asset["sanitized_replay_contract"]["status"] == "preserved"


def test_sanitize_harness_asset_replaces_html_rendered_windows_paths(tmp_path: Path):
    raw_dir = _write_sensitive_asset(tmp_path)
    html_path = raw_dir / "steps" / "001" / "after.html"
    html_path.write_text(
        '<div data-snippet-clipboard-copy-content="ffmpeg_path = &quot;C:\\\\Users\\\\harry\\\\Downloads\\\\ffmpeg.exe&quot;">'
        '<span class="pl-smi">ffmpeg_path</span> = '
        '<span class="pl-s">C:<span class="pl-cce">\\\\</span>Users'
        '<span class="pl-cce">\\\\</span>harry'
        '<span class="pl-cce">\\\\</span>Downloads'
        '<span class="pl-cce">\\\\</span>ffmpeg.exe</span>'
        "</div>",
        encoding="utf-8",
    )

    sanitize_harness_asset(tmp_path, "raw-asset", target_asset_id="raw-asset-sanitized")

    sanitized_html = (tmp_path / "raw-asset-sanitized" / "steps" / "001" / "after.html").read_text(encoding="utf-8")
    assert "C:\\\\Users" not in sanitized_html
    assert 'C:<span class="pl-cce">' not in sanitized_html
    assert "<LOCAL_PATH_" in sanitized_html
    scan = scan_harness_assets(tmp_path, asset_ids={"raw-asset-sanitized"})
    assert scan["assets"][0]["repo_safe_blocked"] is False


def test_asset_sanitize_cli_writes_sanitized_asset_report(tmp_path: Path):
    _write_sensitive_asset(tmp_path, asset_id="cli-raw")

    exit_code = run_asset_sanitize_main(
        [
            "--assets",
            str(tmp_path),
            "--asset-id",
            "cli-raw",
            "--target-asset-id",
            "cli-raw-sanitized",
        ]
    )

    assert exit_code == 0
    report_path = tmp_path / "cli-raw-sanitized" / "sanitization_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["source_asset_id"] == "cli-raw"
    assert report["target_asset_id"] == "cli-raw-sanitized"
