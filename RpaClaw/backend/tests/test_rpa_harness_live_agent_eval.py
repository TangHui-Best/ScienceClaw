import json
import hashlib
from pathlib import Path

import pytest

from backend.rpa.harness.live_agent_eval import run_live_agent_eval
from backend.rpa.harness.run_live_agent_eval import main as run_live_agent_eval_main


def _write_live_scenario(root: Path) -> Path:
    scenarios = root / "scenarios"
    scenarios.mkdir()
    (scenarios / "invoice-total.json").write_text(
        json.dumps(
            {
                "scenario_id": "invoice-total",
                "instruction": "Extract the invoice total",
                "url": "https://fixture.local/invoice",
                "html": """
                    <html>
                      <head><title>Invoice</title></head>
                      <body>
                        <main>
                          <h1>Invoice #42</h1>
                          <dl>
                            <dt>Invoice Total</dt>
                            <dd id="invoice-total">$42.00</dd>
                          </dl>
                        </main>
                      </body>
                    </html>
                """,
                "expected": {
                    "output_key": "invoice_total",
                    "must_contain_text": ["$42.00"],
                },
                "page_patterns": ["detail-page", "data-extraction"],
            }
        ),
        encoding="utf-8",
    )
    return scenarios


def _write_live_download_scenario(root: Path) -> Path:
    scenarios = root / "scenarios"
    downloads = scenarios / "downloads"
    scenarios.mkdir()
    downloads.mkdir()
    download_body = b"controlled live download bytes\n"
    download_sha256 = hashlib.sha256(download_body).hexdigest()
    (downloads / "report.xlsx").write_bytes(download_body)
    (scenarios / "file-download.json").write_text(
        json.dumps(
            {
                "scenario_id": "file-download",
                "instruction": "点击列表第一行的文件名称",
                "url": "https://fixture.local/files",
                "html": """
                    <html>
                      <head><title>File Center</title></head>
                      <body>
                        <main>
                        <h1>File Center</h1>
                        <p>Downloadable project files are listed below for controlled replay validation.</p>
                        <table>
                          <caption>Project Files</caption>
                          <tbody>
                            <tr>
                              <td>
                                <a id="first-file" href="https://fixture.local/downloads/report.xlsx">
                                  report.xlsx
                                </a>
                              </td>
                            </tr>
                          </tbody>
                        </table>
                        </main>
                      </body>
                    </html>
                """,
                "expected": {
                    "controlled_download": {
                        "url": "https://fixture.local/downloads/report.xlsx",
                        "filename": "report.xlsx",
                        "content_type": (
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        ),
                        "body_path": "downloads/report.xlsx",
                        "sha256": download_sha256,
                    }
                },
                "page_patterns": ["list-page", "download"],
            }
        ),
        encoding="utf-8",
    )
    return scenarios


@pytest.mark.asyncio
async def test_live_agent_eval_invokes_planner_and_writes_replayable_candidate_lite_asset(tmp_path: Path):
    scenarios = _write_live_scenario(tmp_path)
    assets = tmp_path / "assets"
    planner_calls = []

    async def planner(payload):
        planner_calls.append(payload)
        assert payload["instruction"] == "Extract the invoice total"
        return {
            "description": "Extract invoice total from the invoice page",
            "output_key": "invoice_total",
            "code": """
async def run(page, results):
    return (await page.locator('#invoice-total').inner_text()).strip()
""",
        }

    report = await run_live_agent_eval(
        scenarios_root=scenarios,
        assets_root=assets,
        planner=planner,
    )

    assert report["summary"]["status"] == "passed", report
    assert report["summary"]["scenario_count"] == 1
    assert report["summary"]["passed"] == 1
    assert report["summary"]["planner_invocation_count"] == 1
    assert len(planner_calls) == 1

    item = report["scenarios"][0]
    assert item["status"] == "passed"
    assert item["asset_id"] == "hcap-live-invoice-total"
    assert item["output_key"] == "invoice_total"
    assert item["actual_output"] == "$42.00"
    assert item["post_capture"]["warning_count"] == 0
    assert item["post_capture"]["skill_replay"]["summary"]["failed"] == 0
    assert item["post_capture"]["stateful_sop"]["summary"]["failed"] == 0

    scenario_payload = json.loads((assets / "hcap-live-invoice-total" / "scenario.json").read_text(encoding="utf-8"))
    assert scenario_payload["asset_status"] == "active"
    assert scenario_payload["governance"]["promotion_status"] == "candidate-lite"
    assert "skill_replay_e2e" in scenario_payload["governance"]["runner_modes"]

    trace_events = json.loads(
        (assets / "hcap-live-invoice-total" / "steps" / "001" / "trace_events.json").read_text(encoding="utf-8")
    )
    assert trace_events[0]["trace_type"] == "ai_operation"
    assert trace_events[0]["output_key"] == "invoice_total"
    assert "page.locator('#invoice-total')" in trace_events[0]["ai_execution"]["code"]


@pytest.mark.asyncio
async def test_live_agent_eval_controlled_download_is_captured_as_trace_signal(tmp_path: Path):
    scenarios = _write_live_download_scenario(tmp_path)
    assets = tmp_path / "assets"

    async def planner(payload):
        assert payload["instruction"] == "点击列表第一行的文件名称"
        return {
            "description": "Click first file name",
            "output_key": "download_action",
            "code": """
async def run(page, results):
    await page.locator('#first-file').click()
    return {'action_performed': True, 'action_type': 'click'}
""",
        }

    report = await run_live_agent_eval(
        scenarios_root=scenarios,
        assets_root=assets,
        planner=planner,
    )

    assert report["summary"]["status"] == "passed", report
    item = report["scenarios"][0]
    assert item["status"] == "passed"
    assert item["controlled_download"]["filename"] == "report.xlsx"
    assert item["controlled_download"]["sha256_verified"] is True

    trace_events = json.loads(
        (assets / "hcap-live-file-download" / "steps" / "001" / "trace_events.json").read_text(encoding="utf-8")
    )
    assert trace_events[0]["signals"]["download"]["filename"] == "report.xlsx"
    assert trace_events[0]["signals"]["download"]["count"] == 1


def test_live_agent_eval_cli_writes_report_for_invalid_scenario_without_calling_llm(tmp_path: Path):
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    (scenarios / "invalid.json").write_text(
        json.dumps(
            {
                "scenario_id": "invalid",
                "instruction": "Extract the invoice total",
                "url": "https://fixture.local/invoice",
                "expected": {"output_key": "invoice_total"},
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "report.json"

    exit_code = run_live_agent_eval_main(
        [
            "--scenarios",
            str(scenarios),
            "--assets",
            str(tmp_path / "assets"),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["schema_version"] == "rpa-harness-live-agent-eval-v0"
    assert report["summary"]["status"] == "failed"
    assert report["scenarios"][0]["failure_category"] == "live-agent-scenario-error"


def test_live_agent_eval_cli_fails_when_no_scenarios_are_present(tmp_path: Path):
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    output = tmp_path / "report.json"

    exit_code = run_live_agent_eval_main(
        [
            "--scenarios",
            str(scenarios),
            "--assets",
            str(tmp_path / "assets"),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["status"] == "failed"
    assert report["scenarios"][0]["failure_category"] == "no-live-agent-scenarios"
