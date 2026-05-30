import json
from pathlib import Path

from backend.rpa.harness.run_asset_sensitivity_scan import main as run_scan_main
from backend.rpa.harness.sensitivity_scan import scan_harness_assets


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_asset(
    root: Path,
    *,
    asset_id: str,
    trace_events: list[dict],
    expected: dict | None = None,
    before_html: str = "<html><body>before</body></html>",
    after_html: str = "<html><body>after</body></html>",
) -> Path:
    capture_dir = root / asset_id
    _write_json(
        capture_dir / "scenario.json",
        {
            "schema_version": "rpa-harness-scenario-v0",
            "asset_id": asset_id,
            "capture_scope": "full_sop",
            "sop_intent": "Scan sensitive asset",
            "source": {
                "recording_id": "session-1",
                "captured_at": "2026-05-30T10:00:00",
                "capture_mode": "harness",
                "capture_trigger": "full_sop",
            },
            "asset_status": "draft",
            "sensitivity": "local-only",
            "governance": {
                "promotion_status": "captured",
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
    (step_dir / "before.html").write_text(before_html, encoding="utf-8")
    (step_dir / "after.html").write_text(after_html, encoding="utf-8")
    _write_json(step_dir / "trace_events.json", trace_events)
    _write_json(step_dir / "expected.json", expected or {})
    _write_json(
        step_dir / "checkpoint.json",
        {
            "step_index": 1,
            "step_id": "step-1",
            "step_intent": "Submit login and read transaction amount",
            "recording_mode": "natural_language",
            "before": {
                "url": "https://bank.example/login",
                "title": "Login",
                "html_path": "steps/001/before.html",
                "html_sha256": "before",
            },
            "action": {"trace_events_path": "steps/001/trace_events.json"},
            "after": {
                "url": "https://bank.example/transactions",
                "title": "Transactions",
                "html_path": "steps/001/after.html",
                "html_sha256": "after",
            },
            "runtime_result": {"status": "success"},
            "captured_at": "2026-05-30T10:00:00",
            "expected_path": "steps/001/expected.json",
        },
    )
    return capture_dir


def test_sensitivity_scan_detects_credentials_financial_values_and_repo_safe_blockers(tmp_path: Path):
    _write_asset(
        tmp_path,
        asset_id="sensitive-asset",
        before_html='<form><input type="password" value="hunter2"></form>',
        after_html="<html><body>Transaction amount: $12,345.67</body></html>",
        trace_events=[
            {
                "trace_id": "trace-1",
                "action": "ai_operation",
                "input": {"username": "alice@example.com", "password": "hunter2"},
                "output": {"amount": "$12,345.67", "account": "6222021234567890123"},
                "ai_execution": {"code": "headers = {'Authorization': 'Bearer sk-test-1234567890abcdef'}"},
                "accepted": True,
            }
        ],
    )

    report = scan_harness_assets(tmp_path, asset_ids={"sensitive-asset"})

    asset = report["assets"][0]
    categories = {finding["category"] for finding in asset["findings"]}
    assert report["summary"]["asset_count"] == 1
    assert asset["asset_id"] == "sensitive-asset"
    assert asset["risk_level"] == "critical"
    assert asset["repo_safe_blocked"] is True
    assert asset["recommended_sensitivity"] == "sensitive"
    assert {"credential/password", "secret/token", "financial", "PII"}.issubset(categories)
    assert asset["sanitized_replay_contract"]["status"] == "needs-contract"
    assert "sensitive-asset" in report["summary"]["repo_safe_blocked_asset_ids"]


def test_sensitivity_scan_accepts_sanitized_replay_contract_without_real_secret_values(tmp_path: Path):
    _write_asset(
        tmp_path,
        asset_id="sanitized-asset",
        before_html='<form><input type="password" value="<LOGIN_PASSWORD>"></form>',
        after_html="<html><body>Transaction amount: <AMOUNT_1></body></html>",
        trace_events=[
            {
                "trace_id": "trace-1",
                "action": "ai_operation",
                "input": {"username": "<LOGIN_USERNAME>", "password": "<LOGIN_PASSWORD>"},
                "output": {"amount": "<AMOUNT_1>"},
                "accepted": True,
            }
        ],
        expected={
            "state_signals": {
                "output_key": "amount",
                "sanitization_contract": {
                    "placeholders": [
                        {
                            "token": "<AMOUNT_1>",
                            "semantic_type": "currency_amount",
                            "shape": "money",
                        }
                    ],
                    "runtime_secret_refs": ["LOGIN_USERNAME", "LOGIN_PASSWORD"],
                    "controlled_fixtures": ["login-page"],
                    "replay_assertions": ["amount field is present", "amount shape is money"],
                },
            }
        },
    )

    report = scan_harness_assets(tmp_path, asset_ids={"sanitized-asset"})

    asset = report["assets"][0]
    assert asset["risk_level"] == "low"
    assert asset["repo_safe_blocked"] is False
    assert asset["recommended_sensitivity"] == "sanitized"
    assert asset["sanitized_replay_contract"]["status"] == "preserved"
    assert asset["sanitized_replay_contract"]["runtime_secret_refs"] == ["LOGIN_USERNAME", "LOGIN_PASSWORD"]
    assert asset["sanitized_replay_contract"]["controlled_fixtures"] == ["login-page"]
    assert any(finding["category"] == "sanitized-placeholder" for finding in asset["findings"])


def test_sensitivity_scan_detects_html_rendered_windows_paths(tmp_path: Path):
    _write_asset(
        tmp_path,
        asset_id="html-path-asset",
        trace_events=[{"trace_id": "trace-1", "output": {}, "accepted": True}],
        after_html=(
            '<div data-snippet-clipboard-copy-content="ffmpeg_path = &quot;C:\\\\Users\\\\harry\\\\Downloads\\\\ffmpeg.exe&quot;">'
            '<span class="pl-smi">ffmpeg_path</span> = '
            '<span class="pl-s">C:<span class="pl-cce">\\\\</span>Users'
            '<span class="pl-cce">\\\\</span>harry'
            '<span class="pl-cce">\\\\</span>Downloads'
            '<span class="pl-cce">\\\\</span>ffmpeg.exe</span>'
            "</div>"
        ),
    )

    report = scan_harness_assets(tmp_path, asset_ids={"html-path-asset"})

    asset = report["assets"][0]
    assert asset["repo_safe_blocked"] is True
    assert asset["category_counts"]["local-path"] >= 2


def test_sensitivity_scan_cli_writes_json_report(tmp_path: Path):
    _write_asset(
        tmp_path,
        asset_id="cli-asset",
        trace_events=[{"trace_id": "trace-1", "output": {"amount": "$99.00"}, "accepted": True}],
    )
    output_path = tmp_path / "scan-report.json"

    exit_code = run_scan_main(
        [
            "--assets",
            str(tmp_path),
            "--asset-id",
            "cli-asset",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "rpa-harness-sensitivity-scan-v0"
    assert report["summary"]["asset_count"] == 1
    assert report["assets"][0]["asset_id"] == "cli-asset"


def test_sensitivity_scan_cli_writes_sidecar_report_by_default(tmp_path: Path):
    capture_dir = _write_asset(
        tmp_path,
        asset_id="sidecar-asset",
        trace_events=[{"trace_id": "trace-1", "output": {"amount": "$99.00"}, "accepted": True}],
    )
    sidecar_path = capture_dir / "sensitivity_scan.json"

    exit_code = run_scan_main(["--assets", str(tmp_path), "--asset-id", "sidecar-asset"])

    assert exit_code == 0
    report = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == "rpa-harness-sensitivity-scan-v0"
    assert report["summary"]["asset_count"] == 1
    assert report["assets"][0]["asset_id"] == "sidecar-asset"


def test_sensitivity_scan_ignores_existing_generated_sidecar_report(tmp_path: Path):
    capture_dir = _write_asset(
        tmp_path,
        asset_id="sidecar-input-asset",
        trace_events=[{"trace_id": "trace-1", "output": {"amount": "$99.00"}, "accepted": True}],
    )
    (capture_dir / "sensitivity_scan.json").write_text(
        json.dumps(
            {
                "schema_version": "rpa-harness-sensitivity-scan-v0",
                "assets": [
                    {
                        "findings": [
                            {
                                "category": "public-web-noise",
                                "excerpt": "authenticity_token from prior generated report",
                            }
                        ]
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = scan_harness_assets(tmp_path, asset_ids={"sidecar-input-asset"})

    asset = report["assets"][0]
    assert asset["finding_count"] == 1
    assert asset["category_counts"] == {"financial": 1}
    assert all(finding["file"] != "sensitivity_scan.json" for finding in asset["findings"])
