from __future__ import annotations

import asyncio
import json
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
                try:
                    await _install_controlled_replay_routes(
                        page,
                        _url_html_map(capture_dir, checkpoint),
                    )
                    await _load_controlled_before_page(page, capture_dir, checkpoint)
                    execute_skill = _load_execute_skill(script)
                    results = await execute_skill(page)
                    if not isinstance(results, dict):
                        results = {"value": results}
                    status, failure_category, actual_output, missing_text = _validate_replay_output(
                        results,
                        expected,
                    )
                except Exception as exc:
                    status = "failed"
                    failure_category = "replay-execution-error"
                    error = f"{type(exc).__name__}: {exc}"
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
                        "output_key": str(expected.state_signals.get("output_key") or ""),
                        "actual_output": actual_output,
                        "missing_text": missing_text,
                        "error": error,
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
