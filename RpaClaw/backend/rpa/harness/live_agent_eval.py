from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright
from pydantic import BaseModel, Field

from backend.rpa.recording_runtime_agent import Planner, RecordingRuntimeAgent

from .asset_validation import validate_harness_assets
from .capture import (
    HarnessCaptureSessionState,
    capture_current_page_state,
    capture_step_checkpoint,
)
from .compiler_regression import run_compiler_regression
from .models import HarnessScenarioAsset
from .skill_replay import _install_controlled_replay_routes, run_skill_replay_e2e
from .skill_replay import _install_controlled_download_routes
from .snapshot_regression import run_snapshot_regression
from .stateful_sop import run_stateful_sop_capture_to_skill
from .store import HarnessAssetStore


_RUNNER_MODES = [
    "offline_core_chain",
    "skill_replay_e2e",
    "stateful_sop_capture_to_skill",
]
_CORE_CHAIN_COVERAGE = [
    "html_to_raw_snapshot",
    "raw_to_compact_snapshot",
    "planner_action_selection",
    "trace_to_skill",
    "skill_replay",
    "stateful_capture_to_skill",
]


class LiveAgentExpected(BaseModel):
    output_key: str = ""
    must_contain_text: list[str] = Field(default_factory=list)
    controlled_download: dict[str, Any] = Field(default_factory=dict)


class LiveAgentScenario(BaseModel):
    schema_version: str = "rpa-harness-live-agent-scenario-v0"
    scenario_id: str
    instruction: str
    url: str
    html: str = ""
    html_path: str = ""
    title: str = ""
    expected: LiveAgentExpected = Field(default_factory=LiveAgentExpected)
    page_patterns: list[str] = Field(default_factory=list)
    asset_id: str = ""
    region_context: dict[str, Any] = Field(default_factory=dict)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug or "scenario"


def _asset_id_for_scenario(scenario: LiveAgentScenario) -> str:
    if scenario.asset_id.strip():
        return _safe_slug(scenario.asset_id)
    return f"hcap-live-{_safe_slug(scenario.scenario_id)}"


def _load_scenario_html(path: Path, scenario: LiveAgentScenario) -> str:
    if scenario.html:
        return scenario.html
    if not scenario.html_path:
        raise ValueError("live-agent scenario requires html or html_path")
    html_path = (path.parent / scenario.html_path).resolve()
    return html_path.read_text(encoding="utf-8")


def _json_contains_text(payload: Any, text: str) -> bool:
    return text in json.dumps(payload, ensure_ascii=False, default=str)


def _validate_expected_output(result_output: Any, expected: LiveAgentExpected) -> tuple[str, str, list[str]]:
    missing = [
        text
        for text in expected.must_contain_text
        if isinstance(text, str) and not _json_contains_text(result_output, text)
    ]
    if missing:
        return "failed", "live-agent-output-missing-signal", missing
    return "passed", "", []


def _download_output_key(filename: str) -> str:
    stem = str(filename or "file").split(".")[0]
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", stem) or "file"
    return f"download_{safe}"


def _controlled_download_spec(path: Path, scenario: LiveAgentScenario) -> dict[str, Any]:
    signal = scenario.expected.controlled_download
    if not isinstance(signal, dict) or not signal:
        return {}
    url = str(signal.get("url") or "").strip()
    body_path = str(signal.get("body_path") or "").strip()
    if not url or not body_path:
        return {}
    relative_body = Path(body_path)
    if relative_body.is_absolute():
        raise ValueError("controlled_download.body_path must be relative to scenario directory")
    scenario_dir = path.parent.resolve()
    body_file = (scenario_dir / relative_body).resolve()
    try:
        body_file.relative_to(scenario_dir)
    except ValueError as exc:
        raise ValueError("controlled_download.body_path must stay inside scenario directory") from exc
    filename = str(signal.get("filename") or body_file.name)
    return {
        **signal,
        "url": url,
        "body_file": body_file,
        "filename": filename,
        "content_type": str(signal.get("content_type") or "application/octet-stream"),
        "output_key": str(signal.get("output_key") or _download_output_key(filename)),
    }


def _validate_controlled_download_trace(
    trace: Any,
    download_spec: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    if not download_spec:
        return "passed", "", {}
    expected_sha = str(download_spec.get("sha256") or "").strip()
    body_file = download_spec.get("body_file")
    actual_sha = ""
    sha_verified = False
    size_bytes = 0
    if isinstance(body_file, Path) and body_file.exists():
        body = body_file.read_bytes()
        size_bytes = len(body)
        actual_sha = hashlib.sha256(body).hexdigest()
        sha_verified = not expected_sha or actual_sha == expected_sha
    signal = {}
    if trace is not None:
        signal = dict(getattr(trace, "signals", {}) or {}).get("download") or {}
    evidence = {
        "url": str(download_spec.get("url") or ""),
        "filename": str(signal.get("filename") or ""),
        "expected_filename": str(download_spec.get("filename") or ""),
        "count": int(signal.get("count") or 0),
        "fixture_sha256": actual_sha,
        "sha256_verified": sha_verified,
        "fixture_size_bytes": size_bytes,
    }
    if not isinstance(signal, dict) or not signal:
        return "failed", "live-agent-download-missing-signal", evidence
    expected_filename = str(download_spec.get("filename") or "").strip()
    if expected_filename and str(signal.get("filename") or "") != expected_filename:
        return "failed", "live-agent-download-filename-mismatch", evidence
    if not sha_verified:
        return "failed", "live-agent-download-fixture-sha256-mismatch", evidence
    return "passed", "", evidence


def _attach_controlled_download_to_generated_asset(
    *,
    assets_root: Path,
    asset_id: str,
    checkpoint: Any,
    download_spec: dict[str, Any],
) -> dict[str, Any]:
    if not download_spec or checkpoint is None:
        return {}
    body_file = download_spec.get("body_file")
    if not isinstance(body_file, Path) or not body_file.exists():
        return {}
    step_dir = assets_root / asset_id / f"steps/{int(checkpoint.step_index):03d}"
    downloads_dir = step_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    filename = str(download_spec.get("filename") or body_file.name)
    dest = downloads_dir / filename
    shutil.copyfile(body_file, dest)

    expected_path = assets_root / asset_id / checkpoint.expected_path
    expected_payload = _load_json(expected_path)
    state_signals = dict(expected_payload.get("state_signals") or {})
    body = dest.read_bytes()
    state_signals["controlled_download"] = {
        "output_key": str(download_spec.get("output_key") or _download_output_key(filename)),
        "url": str(download_spec.get("url") or ""),
        "filename": filename,
        "content_type": str(download_spec.get("content_type") or "application/octet-stream"),
        "body_path": f"steps/{int(checkpoint.step_index):03d}/downloads/{filename}",
        "sha256": hashlib.sha256(body).hexdigest(),
        "min_size_bytes": len(body),
    }
    expected_payload["state_signals"] = state_signals
    expected_path.write_text(json.dumps(expected_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return dict(state_signals["controlled_download"])


def _post_capture_checks(assets_root: Path, asset_id: str) -> dict[str, Any]:
    asset_ids = {asset_id}
    validation = validate_harness_assets(assets_root, asset_ids=asset_ids)
    snapshot = run_snapshot_regression(assets_root, asset_ids=asset_ids)
    compiler = run_compiler_regression(assets_root, asset_ids=asset_ids)
    skill_replay = run_skill_replay_e2e(assets_root, asset_ids=asset_ids)
    stateful_sop = run_stateful_sop_capture_to_skill(
        assets_root,
        asset_ids=asset_ids,
        include_candidate_lite=True,
    )
    warning_count = (
        int(validation["summary"]["issue_count"])
        + int(snapshot["summary"]["failed"])
        + int(compiler["summary"]["failed"])
        + int(skill_replay["summary"]["failed"])
        + int(stateful_sop["summary"]["failed"])
    )
    return {
        "warning_count": warning_count,
        "validation": validation,
        "snapshot": snapshot,
        "compiler": compiler,
        "skill_replay": skill_replay,
        "stateful_sop": stateful_sop,
    }


def _activate_candidate_lite_asset(
    *,
    assets_root: Path,
    asset_id: str,
    scenario: LiveAgentScenario,
) -> None:
    scenario_path = assets_root / asset_id / "scenario.json"
    payload = _load_json(scenario_path)
    asset = HarnessScenarioAsset.model_validate(payload)
    asset.sop_intent = scenario.instruction
    asset.asset_status = "active"
    asset.sensitivity = "local-only"
    asset.page_patterns = sorted({*asset.page_patterns, *scenario.page_patterns})
    asset.environment = {
        **dict(asset.environment or {}),
        "runner": "live_agent_eval",
        "controlled_fixture": True,
        "start_url": scenario.url,
    }
    asset.governance.promotion_status = "candidate-lite"
    asset.governance.runner_modes = list(_RUNNER_MODES)
    asset.governance.core_chain_coverage = list(_CORE_CHAIN_COVERAGE)
    asset.governance.expected_signals_reviewed = False
    asset.governance.sensitivity_reviewed = False
    asset.governance.review_notes = (
        "Generated by live_agent_eval. Candidate-lite assets exercise live "
        "RecordingRuntimeAgent planning against controlled HTML and must be reviewed "
        "before candidate/golden promotion."
    )
    scenario_path.write_text(
        json.dumps(asset.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def _run_one_scenario(
    *,
    path: Path,
    scenario: LiveAgentScenario,
    assets_root: Path,
    planner: Planner | None,
    model_config: dict[str, Any] | None,
) -> dict[str, Any]:
    html = _load_scenario_html(path, scenario)
    asset_id = _asset_id_for_scenario(scenario)
    planner_invocation_count = 0
    download_spec = _controlled_download_spec(path, scenario)

    async def counting_planner(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal planner_invocation_count
        planner_invocation_count += 1
        if planner is None:
            raise RuntimeError("internal planner wrapper should not be used without planner")
        return await planner(payload)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(10000)
        page.set_default_navigation_timeout(10000)
        try:
            await _install_controlled_replay_routes(page, {scenario.url: html})
            await _install_controlled_download_routes(page, download_spec)
            await page.goto(scenario.url, wait_until="domcontentloaded")
            before_state = await capture_current_page_state(page)
            agent = RecordingRuntimeAgent(
                planner=counting_planner if planner is not None else None,
                model_config=model_config,
            )
            result = await agent.run(
                page=page,
                instruction=scenario.instruction,
                runtime_results={},
                region_context=scenario.region_context or None,
            )
            if planner is None:
                planner_invocation_count = len(getattr(agent, "_planner_llm_calls", []) or [])
            after_state = await capture_current_page_state(page)
        finally:
            await page.close()
            await browser.close()

    expected_status, expected_failure, missing_text = _validate_expected_output(
        result.output,
        scenario.expected,
    )
    download_status, download_failure, controlled_download = _validate_controlled_download_trace(
        result.trace,
        download_spec,
    )
    if expected_status == "passed" and download_status != "passed":
        expected_status = download_status
        expected_failure = download_failure
    status = "passed" if result.success and expected_status == "passed" else "failed"
    failure_category = "" if status == "passed" else expected_failure or "live-agent-run-failed"
    error = "" if result.success else result.message
    trace_events = [result.trace.model_dump(mode="json")] if result.trace is not None else []

    state = HarnessCaptureSessionState(
        capture_id=asset_id,
        session_id=f"live-agent-{scenario.scenario_id}",
        capture_scope="full_sop",
    )
    store = HarnessAssetStore(assets_root)
    checkpoint = await capture_step_checkpoint(
        state,
        store,
        step_index=1,
        step_id=result.trace.trace_id if result.trace is not None else f"live-agent-{scenario.scenario_id}",
        step_intent=scenario.instruction,
        recording_mode="natural_language",
        before_state=before_state,
        after_state=after_state,
        trace_events=trace_events,
        runtime_status="success" if result.success else "failed",
        error=error or failure_category,
    )

    post_capture: dict[str, Any] = {"warning_count": 0}
    if status == "passed" and checkpoint is not None:
        _activate_candidate_lite_asset(
            assets_root=assets_root,
            asset_id=asset_id,
            scenario=scenario,
        )
        generated_download = _attach_controlled_download_to_generated_asset(
            assets_root=assets_root,
            asset_id=asset_id,
            checkpoint=checkpoint,
            download_spec=download_spec,
        )
        if generated_download:
            controlled_download["generated_expected_signal"] = generated_download
        post_capture = await asyncio.to_thread(_post_capture_checks, assets_root, asset_id)
        if post_capture["warning_count"]:
            status = "failed"
            failure_category = "post-capture-regression-warning"

    return {
        "scenario_id": scenario.scenario_id,
        "asset_id": asset_id,
        "instruction": scenario.instruction,
        "status": status,
        "failure_category": failure_category,
        "planner_invocation_count": planner_invocation_count,
        "region_context": scenario.region_context,
        "output_key": result.output_key or scenario.expected.output_key,
        "actual_output": result.output,
        "missing_text": missing_text,
        "error": error,
        "controlled_download": controlled_download,
        "post_capture": post_capture,
    }


async def run_live_agent_eval(
    *,
    scenarios_root: str | Path,
    assets_root: str | Path,
    planner: Planner | None = None,
    model_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scenarios_path = Path(scenarios_root)
    output_assets = Path(assets_root)
    output_assets.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = []
    scenario_files = sorted(scenarios_path.glob("*.json"))
    if not scenario_files:
        return {
            "schema_version": "rpa-harness-live-agent-eval-v0",
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "status": "failed",
                "scenario_count": 0,
                "passed": 0,
                "failed": 1,
                "planner_invocation_count": 0,
            },
            "scenarios": [
                {
                    "scenario_id": "",
                    "asset_id": "",
                    "instruction": "",
                    "status": "failed",
                    "failure_category": "no-live-agent-scenarios",
                    "planner_invocation_count": 0,
                    "output_key": "",
                    "actual_output": None,
                    "missing_text": [],
                    "error": f"no scenario JSON files found under {scenarios_path}",
                    "post_capture": {"warning_count": 0},
                }
            ],
        }

    for path in scenario_files:
        try:
            scenario = LiveAgentScenario.model_validate(_load_json(path))
            item = await _run_one_scenario(
                path=path,
                scenario=scenario,
                assets_root=output_assets,
                planner=planner,
                model_config=model_config,
            )
        except Exception as exc:
            item = {
                "scenario_id": path.stem,
                "asset_id": "",
                "instruction": "",
                "status": "failed",
                "failure_category": "live-agent-scenario-error",
                "planner_invocation_count": 0,
                "output_key": "",
                "actual_output": None,
                "missing_text": [],
                "error": f"{type(exc).__name__}: {exc}",
                "post_capture": {"warning_count": 0},
            }
        items.append(item)

    failed = len([item for item in items if item["status"] == "failed"])
    return {
        "schema_version": "rpa-harness-live-agent-eval-v0",
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "status": "failed" if failed else "passed",
            "scenario_count": len(items),
            "passed": len(items) - failed,
            "failed": failed,
            "planner_invocation_count": sum(int(item.get("planner_invocation_count") or 0) for item in items),
        },
        "scenarios": items,
    }
