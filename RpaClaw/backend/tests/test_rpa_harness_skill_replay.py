import json
import hashlib
from pathlib import Path

from backend.rpa.harness.skill_replay import run_skill_replay_e2e


_REPO_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP_ASSET_ROOT = _REPO_ROOT / "data" / "rpa_harness_assets_bootstrap"
_REAL_CANDIDATE_ASSET_ID = "hcap-4be6265f43eb42dfa259182207aa64cc"


def _write_replay_asset(root: Path, *, expected_text: str = "Fork 1.3k") -> Path:
    asset_dir = root / "asset-replay"
    step_dir = asset_dir / "steps" / "001"
    step_dir.mkdir(parents=True)
    (asset_dir / "scenario.json").write_text(
        json.dumps(
            {
                "schema_version": "rpa-harness-scenario-v0",
                "asset_id": "asset-replay",
                "capture_scope": "full_sop",
                "sop_intent": "Extract fork count from a controlled repository page",
                "source": {
                    "recording_id": "rec-replay",
                    "captured_at": "2026-05-18T10:00:00",
                    "capture_mode": "harness",
                    "capture_trigger": "full_sop",
                },
                "asset_status": "active",
                "sensitivity": "local-only",
                "page_patterns": ["detail-page", "data-extraction"],
                "governance": {
                    "promotion_status": "candidate",
                    "runner_modes": ["offline_core_chain", "skill_replay_e2e"],
                    "core_chain_coverage": [
                        "html_to_raw_snapshot",
                        "raw_to_compact_snapshot",
                        "trace_to_skill",
                        "skill_replay",
                    ],
                    "expected_signals_reviewed": True,
                    "sensitivity_reviewed": True,
                    "review_notes": "Controlled fixture for Skill Replay E2E runner contract.",
                },
                "step_checkpoints": [
                    {"step_index": 1, "checkpoint_path": "steps/001/checkpoint.json"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (step_dir / "before.html").write_text(
        "<html><body><main><a href='/forks'>Fork 1.3k</a></main></body></html>",
        encoding="utf-8",
    )
    (step_dir / "after.html").write_text(
        "<html><body><main><a href='/forks'>Fork 1.3k</a></main></body></html>",
        encoding="utf-8",
    )
    (step_dir / "trace_events.json").write_text(
        json.dumps(
            [
                {
                    "trace_id": "trace-replay",
                    "trace_type": "ai_operation",
                    "source": "ai",
                    "user_instruction": "Extract the fork count from the current page",
                    "description": "Extract fork count",
                    "before_page": {"url": "https://example.test/repo", "title": "Repo"},
                    "after_page": {"url": "https://example.test/repo", "title": "Repo"},
                    "output_key": "fork_count",
                    "output": "Fork 1.3k",
                    "ai_execution": {
                        "language": "python",
                        "code": (
                            "async def run(page, results):\n"
                            "    fork_locator = page.get_by_role('link', name=re.compile(r'^Fork\\s'))\n"
                            "    await fork_locator.wait_for(state='visible', timeout=5000)\n"
                            "    return await fork_locator.inner_text()\n"
                        ),
                        "output": "Fork 1.3k",
                    },
                    "accepted": True,
                    "started_at": "2026-05-18T10:00:00",
                    "ended_at": "2026-05-18T10:00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    (step_dir / "expected.json").write_text(
        json.dumps(
            {
                "state_signals": {
                    "output_key": "fork_count",
                    "must_contain_text": [expected_text],
                    "observed_output_shape": {"type": "str"},
                }
            }
        ),
        encoding="utf-8",
    )
    (step_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "step_index": 1,
                "step_id": "step-replay",
                "step_intent": "Extract fork count",
                "recording_mode": "natural_language",
                "page_patterns": ["detail-page", "data-extraction"],
                "before": {
                    "url": "https://example.test/repo",
                    "title": "Repo",
                    "html_path": "steps/001/before.html",
                    "html_sha256": "before",
                },
                "action": {"trace_events_path": "steps/001/trace_events.json"},
                "after": {
                    "url": "https://example.test/repo",
                    "title": "Repo",
                    "html_path": "steps/001/after.html",
                    "html_sha256": "after",
                },
                "runtime_result": {"status": "success"},
                "captured_at": "2026-05-18T10:00:00",
                "expected_path": "steps/001/expected.json",
            }
        ),
        encoding="utf-8",
    )
    return root


def _write_download_replay_asset(root: Path) -> Path:
    asset_dir = root / "asset-download-replay"
    step_dir = asset_dir / "steps" / "001"
    download_dir = step_dir / "downloads"
    download_body = b"controlled report bytes\n"
    download_sha256 = hashlib.sha256(download_body).hexdigest()
    step_dir.mkdir(parents=True)
    download_dir.mkdir()
    (download_dir / "report.xlsx").write_bytes(download_body)
    (asset_dir / "scenario.json").write_text(
        json.dumps(
            {
                "schema_version": "rpa-harness-scenario-v0",
                "asset_id": "asset-download-replay",
                "capture_scope": "full_sop",
                "sop_intent": "Click the first file name and download it from a controlled list page",
                "source": {
                    "recording_id": "rec-download-replay",
                    "captured_at": "2026-05-29T10:00:00",
                    "capture_mode": "harness",
                    "capture_trigger": "full_sop",
                },
                "asset_status": "active",
                "sensitivity": "local-only",
                "page_patterns": ["list-page", "download"],
                "governance": {
                    "promotion_status": "candidate",
                    "runner_modes": ["offline_core_chain", "skill_replay_e2e"],
                    "core_chain_coverage": [
                        "html_to_raw_snapshot",
                        "raw_to_compact_snapshot",
                        "trace_to_skill",
                        "skill_replay",
                    ],
                    "expected_signals_reviewed": True,
                    "sensitivity_reviewed": True,
                    "review_notes": "Controlled fixture for download side-effect replay.",
                },
                "step_checkpoints": [
                    {"step_index": 1, "checkpoint_path": "steps/001/checkpoint.json"}
                ],
            }
        ),
        encoding="utf-8",
    )
    html = """
        <html>
          <body>
            <table>
              <tbody>
                <tr>
                  <td>
                    <a id="first-file" href="https://example.test/files/report.xlsx">
                      report.xlsx
                    </a>
                  </td>
                </tr>
              </tbody>
            </table>
          </body>
        </html>
    """
    (step_dir / "before.html").write_text(html, encoding="utf-8")
    (step_dir / "after.html").write_text(html, encoding="utf-8")
    (step_dir / "trace_events.json").write_text(
        json.dumps(
            [
                {
                    "trace_id": "trace-download-replay",
                    "trace_type": "manual_action",
                    "source": "record",
                    "action": "click",
                    "description": "Click the first file name",
                    "before_page": {"url": "https://example.test/files", "title": "Files"},
                    "after_page": {"url": "https://example.test/files", "title": "Files"},
                    "locator_candidates": [
                        {"locator": {"method": "css", "value": "#first-file"}, "selected": True}
                    ],
                    "signals": {
                        "download": {
                            "filename": "report.xlsx",
                            "url": "https://example.test/files/report.xlsx",
                        }
                    },
                    "accepted": True,
                    "started_at": "2026-05-29T10:00:00",
                    "ended_at": "2026-05-29T10:00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    (step_dir / "expected.json").write_text(
        json.dumps(
            {
                "state_signals": {
                    "controlled_download": {
                        "output_key": "download_report",
                        "url": "https://example.test/files/report.xlsx",
                        "filename": "report.xlsx",
                        "content_type": (
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        ),
                        "body_path": "steps/001/downloads/report.xlsx",
                        "sha256": download_sha256,
                        "min_size_bytes": len(download_body),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (step_dir / "checkpoint.json").write_text(
        json.dumps(
            {
                "step_index": 1,
                "step_id": "step-download-replay",
                "step_intent": "Click the first file name",
                "recording_mode": "natural_language",
                "page_patterns": ["list-page", "download"],
                "before": {
                    "url": "https://example.test/files",
                    "title": "Files",
                    "html_path": "steps/001/before.html",
                    "html_sha256": "before",
                },
                "action": {"trace_events_path": "steps/001/trace_events.json"},
                "after": {
                    "url": "https://example.test/files",
                    "title": "Files",
                    "html_path": "steps/001/after.html",
                    "html_sha256": "after",
                },
                "runtime_result": {"status": "success"},
                "captured_at": "2026-05-29T10:00:00",
                "expected_path": "steps/001/expected.json",
            }
        ),
        encoding="utf-8",
    )
    return root


def test_skill_replay_executes_compiled_skill_against_controlled_fixture(tmp_path: Path):
    assets = _write_replay_asset(tmp_path)

    report = run_skill_replay_e2e(assets)

    assert report["schema_version"] == "rpa-harness-skill-replay-e2e-v0"
    assert report["summary"]["status"] == "passed"
    assert report["summary"]["total"] == 1
    assert report["summary"]["passed"] == 1
    item = report["assets"][0]
    assert item["asset_id"] == "asset-replay"
    assert item["step_id"] == "step-replay"
    assert item["status"] == "passed"
    assert item["output_key"] == "fork_count"
    assert item["actual_output"] == "Fork 1.3k"
    assert item["generated_skill_size"] > 0


def test_skill_replay_reports_expected_signal_mismatch(tmp_path: Path):
    assets = _write_replay_asset(tmp_path, expected_text="Fork 9.9k")

    report = run_skill_replay_e2e(assets)

    assert report["summary"]["status"] == "failed"
    assert report["summary"]["failed"] == 1
    item = report["assets"][0]
    assert item["status"] == "failed"
    assert item["failure_category"] == "replay-output-missing-signal"
    assert item["missing_text"] == ["Fork 9.9k"]


def test_skill_replay_replays_real_governed_candidate_asset_with_controlled_provider():
    report = run_skill_replay_e2e(
        _BOOTSTRAP_ASSET_ROOT,
        asset_ids={_REAL_CANDIDATE_ASSET_ID},
    )

    assert report["summary"]["status"] == "passed"
    assert report["summary"]["eligible_capture_count"] == 1
    assert report["summary"]["total"] == 3
    assert report["summary"]["failed"] == 0
    by_step = {item["step_index"]: item for item in report["assets"]}
    assert by_step[1]["status"] == "passed"
    assert by_step[2]["status"] == "passed"
    assert by_step[3]["output_key"] == "fork_count"
    assert by_step[3]["actual_output"] == "Fork 1.3k"


def test_skill_replay_serves_controlled_download_and_validates_saved_file(tmp_path: Path):
    assets = _write_download_replay_asset(tmp_path)

    report = run_skill_replay_e2e(assets)

    assert report["summary"]["status"] == "passed", report
    item = report["assets"][0]
    assert item["status"] == "passed"
    assert item["output_key"] == "download_report"
    assert item["actual_output"]["filename"] == "report.xlsx"
    assert item["controlled_download"]["filename"] == "report.xlsx"
    assert item["controlled_download"]["url"] == "https://example.test/files/report.xlsx"
    assert item["controlled_download"]["saved_file_exists"] is True
    assert item["controlled_download"]["sha256_verified"] is True


def test_skill_replay_injects_explicit_model_config_into_generated_skill(
    tmp_path: Path,
    monkeypatch,
):
    assets = _write_replay_asset(tmp_path)
    received: dict[str, object] = {}

    async def fake_execute_skill(_page, **kwargs):
        received.update(kwargs)
        return {"fork_count": "Fork 1.3k"}

    monkeypatch.setattr(
        "backend.rpa.harness.skill_replay._load_execute_skill",
        lambda _script: fake_execute_skill,
    )

    report = run_skill_replay_e2e(
        assets,
        model_config={"model_name": "test-model", "api_key": "sk-test"},
    )

    assert report["summary"]["status"] == "passed"
    assert report["summary"]["runtime_ai_model_config_source"] == "harness_explicit_model_config"
    assert received["_model_config"]["api_key"] == "sk-test"
    runtime_context = received["_runtime_context"]
    assert runtime_context["runtime_ai"]["model_config"]["model_name"] == "test-model"
    assert runtime_context["runtime_ai"]["source"] == "harness_explicit_model_config"
