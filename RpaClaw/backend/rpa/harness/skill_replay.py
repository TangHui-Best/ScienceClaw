from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag

from playwright.async_api import async_playwright

from backend.rpa.trace_models import RPAAcceptedTrace
from backend.rpa.trace_skill_compiler import TraceSkillCompiler

from .models import HarnessExpectedSignals, HarnessScenarioAsset, HarnessStepCheckpoint


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _asset_id_for_checkpoint(assets_root: Path, checkpoint_path: Path) -> str:
    try:
        return checkpoint_path.relative_to(assets_root).parts[0]
    except Exception:
        return checkpoint_path.parent.parent.parent.name


def _counter_dict(values: list[str]) -> dict[str, int]:
    counter = Counter(value for value in values if value)
    return {key: counter[key] for key in sorted(counter)}


def _asset_is_replay_eligible(asset_dir: Path) -> bool:
    scenario_path = asset_dir / "scenario.json"
    if not scenario_path.exists():
        return False
    try:
        scenario = HarnessScenarioAsset.model_validate(_load_json(scenario_path))
    except Exception:
        return False
    return "skill_replay_e2e" in set(scenario.governance.runner_modes or [])


def _compile_skill(trace_events: list[dict[str, Any]]) -> str:
    traces = [
        RPAAcceptedTrace.model_validate(event)
        for event in trace_events
        if isinstance(event, dict) and event.get("trace_type")
    ]
    return TraceSkillCompiler().generate_script(traces, {}, is_local=True)


def _load_execute_skill(script: str):
    marker = "\ndef _parse_cli_value"
    end = script.index(marker)
    namespace: dict[str, Any] = {"__name__": "rpa_harness_skill_replay_generated"}
    exec(script[:end], namespace)
    return namespace["execute_skill"]


def _output_shape(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {"type": "object", "keys": sorted(str(key) for key in value.keys())}
    if isinstance(value, list):
        return {"type": "array", "length": len(value)}
    if value is None:
        return {"type": "null"}
    return {"type": type(value).__name__}


def _json_contains_text(payload: Any, text: str) -> bool:
    return text in json.dumps(payload, ensure_ascii=False, default=str)


def _normalize_url(url: str) -> str:
    clean, _fragment = urldefrag(str(url or "").strip())
    return clean.rstrip("/")


def _is_http_url(url: str) -> bool:
    return str(url or "").startswith(("http://", "https://"))


def _url_html_map(capture_dir: Path, checkpoint: HarnessStepCheckpoint) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if _is_http_url(checkpoint.before.url):
        mapping[_normalize_url(checkpoint.before.url)] = (
            capture_dir / checkpoint.before.html_path
        ).read_text(encoding="utf-8")
    if checkpoint.after is not None and _is_http_url(checkpoint.after.url):
        mapping[_normalize_url(checkpoint.after.url)] = (
            capture_dir / checkpoint.after.html_path
        ).read_text(encoding="utf-8")
    return mapping


async def _install_controlled_replay_routes(page, url_to_html: dict[str, str]) -> None:
    async def route_handler(route):
        request = route.request
        html = url_to_html.get(_normalize_url(request.url))
        if html is not None and request.resource_type == "document":
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=html,
            )
            return
        if request.resource_type == "document":
            await route.fulfill(
                status=404,
                content_type="text/html; charset=utf-8",
                body="<html><body>RPA Harness replay fixture missing document</body></html>",
            )
            return
        await route.fulfill(status=204, body="")

    await page.route("**/*", route_handler)


def _controlled_download_spec(capture_dir: Path, expected: HarnessExpectedSignals) -> dict[str, Any]:
    signal = expected.state_signals.get("controlled_download")
    if not isinstance(signal, dict):
        return {}
    url = _normalize_url(str(signal.get("url") or ""))
    body_path = str(signal.get("body_path") or "").strip()
    if not url or not body_path:
        return {}
    relative_body = Path(body_path)
    if relative_body.is_absolute():
        raise ValueError("controlled_download.body_path must be relative to the asset directory")
    body_file = (capture_dir / relative_body).resolve()
    asset_dir = capture_dir.resolve()
    try:
        body_file.relative_to(asset_dir)
    except ValueError as exc:
        raise ValueError("controlled_download.body_path must stay inside the asset directory") from exc
    return {
        **signal,
        "url": url,
        "body_file": body_file,
        "filename": str(signal.get("filename") or body_file.name),
        "content_type": str(signal.get("content_type") or "application/octet-stream"),
    }


async def _install_controlled_download_routes(page, download_spec: dict[str, Any]) -> None:
    if not download_spec:
        return
    download_url = _normalize_url(str(download_spec.get("url") or ""))
    body_file = download_spec.get("body_file")
    if not download_url or not isinstance(body_file, Path):
        return

    async def route_handler(route):
        request = route.request
        if _normalize_url(request.url) != download_url:
            await route.fallback()
            return
        filename = str(download_spec.get("filename") or body_file.name).replace('"', "")
        await route.fulfill(
            status=200,
            content_type=str(download_spec.get("content_type") or "application/octet-stream"),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            body=body_file.read_bytes(),
        )

    await page.route("**/*", route_handler)


async def _load_controlled_before_page(
    page,
    capture_dir: Path,
    checkpoint: HarnessStepCheckpoint,
) -> None:
    if _is_http_url(checkpoint.before.url):
        await page.goto(checkpoint.before.url, wait_until="domcontentloaded")
        return
    html = (capture_dir / checkpoint.before.html_path).read_text(encoding="utf-8")
    await page.set_content(html, wait_until="domcontentloaded")


def _validate_replay_output(
    results: dict[str, Any],
    expected: HarnessExpectedSignals,
) -> tuple[str, str, Any, list[str]]:
    signals = expected.state_signals
    output_key = str(signals.get("output_key") or "").strip()
    actual = results.get(output_key) if output_key else None
    if output_key and output_key not in results:
        return "failed", "replay-output-key-missing", actual, []

    expected_shape = signals.get("observed_output_shape")
    if isinstance(expected_shape, dict) and expected_shape:
        if _output_shape(actual) != expected_shape:
            return "failed", "replay-output-shape-mismatch", actual, []

    required_text = [
        text for text in list(signals.get("must_contain_text") or []) if isinstance(text, str)
    ]
    missing_text = [text for text in required_text if not _json_contains_text(actual, text)]
    if missing_text:
        return "failed", "replay-output-missing-signal", actual, missing_text
    return "passed", "", actual, []


def _validate_controlled_download(
    results: dict[str, Any],
    expected: HarnessExpectedSignals,
) -> tuple[str, str, str, Any, dict[str, Any]]:
    signal = expected.state_signals.get("controlled_download")
    if not isinstance(signal, dict) or not signal:
        return "passed", "", "", None, {}

    output_key = str(signal.get("output_key") or "").strip()
    if not output_key:
        filename = str(signal.get("filename") or "file")
        safe_name = "".join(char if char.isalnum() else "_" for char in filename.split(".")[0]) or "file"
        output_key = f"download_{safe_name}"

    actual = results.get(output_key)
    evidence = {
        "output_key": output_key,
        "url": str(signal.get("url") or ""),
        "expected_filename": str(signal.get("filename") or ""),
        "filename": "",
        "path": "",
        "saved_file_exists": False,
        "size_bytes": 0,
        "sha256": "",
        "sha256_verified": False,
    }
    if not isinstance(actual, dict):
        return "failed", "controlled-download-output-missing", output_key, actual, evidence

    path = Path(str(actual.get("path") or ""))
    evidence["filename"] = str(actual.get("filename") or "")
    evidence["path"] = str(path)
    evidence["saved_file_exists"] = path.exists()
    if not path.exists():
        return "failed", "controlled-download-file-missing", output_key, actual, evidence

    body = path.read_bytes()
    evidence["size_bytes"] = len(body)
    evidence["sha256"] = hashlib.sha256(body).hexdigest()
    expected_filename = str(signal.get("filename") or "").strip()
    if expected_filename and evidence["filename"] != expected_filename:
        return "failed", "controlled-download-filename-mismatch", output_key, actual, evidence

    min_size = signal.get("min_size_bytes")
    if min_size is not None and len(body) < int(min_size):
        return "failed", "controlled-download-size-mismatch", output_key, actual, evidence

    expected_sha = str(signal.get("sha256") or "").strip()
    if expected_sha:
        evidence["sha256_verified"] = evidence["sha256"] == expected_sha
        if not evidence["sha256_verified"]:
            return "failed", "controlled-download-sha256-mismatch", output_key, actual, evidence
    else:
        evidence["sha256_verified"] = True

    return "passed", "", output_key, actual, evidence


async def _run_skill_replay_async(
    checkpoint_items: list[tuple[str, Path, HarnessStepCheckpoint, HarnessExpectedSignals, str]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for asset_id, checkpoint_path, checkpoint, expected, script in checkpoint_items:
                page = await browser.new_page()
                page.set_default_timeout(10000)
                page.set_default_navigation_timeout(10000)
                capture_dir = checkpoint_path.parents[2]
                status = "passed"
                failure_category = ""
                actual_output: Any = None
                missing_text: list[str] = []
                error = ""
                controlled_download: dict[str, Any] = {}
                download_output_key = ""
                try:
                    download_spec = _controlled_download_spec(capture_dir, expected)
                    await _install_controlled_replay_routes(
                        page,
                        _url_html_map(capture_dir, checkpoint),
                    )
                    await _install_controlled_download_routes(page, download_spec)
                    await _load_controlled_before_page(page, capture_dir, checkpoint)
                    execute_skill = _load_execute_skill(script)
                    with tempfile.TemporaryDirectory(prefix="rpa-harness-downloads-") as downloads_dir:
                        results = await execute_skill(page, _downloads_dir=downloads_dir)
                        if not isinstance(results, dict):
                            results = {"value": results}
                        status, failure_category, actual_output, missing_text = _validate_replay_output(
                            results,
                            expected,
                        )
                        if status == "passed":
                            (
                                status,
                                failure_category,
                                download_output_key,
                                download_output,
                                controlled_download,
                            ) = _validate_controlled_download(results, expected)
                            if controlled_download:
                                actual_output = download_output
                                missing_text = []
                except Exception as exc:
                    status = "failed"
                    failure_category = "replay-execution-error"
                    error = f"{type(exc).__name__}: {exc}"
                    controlled_download = {}
                finally:
                    await page.close()

                items.append(
                    {
                        "asset_id": asset_id,
                        "step_id": checkpoint.step_id,
                        "step_index": checkpoint.step_index,
                        "step_intent": checkpoint.step_intent,
                        "page_patterns": checkpoint.page_patterns,
                        "status": status,
                        "failure_category": failure_category,
                        "output_key": str(
                            download_output_key
                            if download_output_key
                            else expected.state_signals.get("output_key") or ""
                        ),
                        "actual_output": actual_output,
                        "missing_text": missing_text,
                        "error": error,
                        "controlled_download": controlled_download,
                        "generated_skill_size": len(script),
                    }
                )
        finally:
            await browser.close()
    return items


def run_skill_replay_e2e(
    assets_root: str | Path,
    *,
    asset_ids: set[str] | None = None,
) -> dict[str, Any]:
    root = Path(assets_root)
    checkpoint_items: list[
        tuple[str, Path, HarnessStepCheckpoint, HarnessExpectedSignals, str]
    ] = []
    eligible_asset_ids: set[str] = set()

    for checkpoint_path in sorted(root.glob("*/steps/*/checkpoint.json")):
        asset_id = _asset_id_for_checkpoint(root, checkpoint_path)
        if asset_ids is not None and asset_id not in asset_ids:
            continue
        asset_dir = checkpoint_path.parents[2]
        if not _asset_is_replay_eligible(asset_dir):
            continue
        eligible_asset_ids.add(asset_id)
        checkpoint = HarnessStepCheckpoint.model_validate(_load_json(checkpoint_path))
        capture_dir = checkpoint_path.parents[2]
        trace_events = _load_json(capture_dir / checkpoint.action.trace_events_path)
        if not isinstance(trace_events, list):
            trace_events = []
        expected = HarnessExpectedSignals.model_validate(
            _load_json(capture_dir / checkpoint.expected_path)
        )
        script = _compile_skill(trace_events)
        checkpoint_items.append((asset_id, checkpoint_path, checkpoint, expected, script))

    items = asyncio.run(_run_skill_replay_async(checkpoint_items)) if checkpoint_items else []
    failed = len([item for item in items if item["status"] == "failed"])
    passed = len(items) - failed
    return {
        "schema_version": "rpa-harness-skill-replay-e2e-v0",
        "summary": {
            "status": "failed" if failed else "passed",
            "eligible_capture_count": len(eligible_asset_ids),
            "total": len(items),
            "passed": passed,
            "failed": failed,
            "failure_categories": _counter_dict(
                [str(item.get("failure_category") or "") for item in items]
            ),
        },
        "assets": items,
    }
