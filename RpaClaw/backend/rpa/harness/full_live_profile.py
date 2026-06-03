from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from backend.rpa.recording_runtime_agent import Planner

from .live_agent_eval import run_live_agent_eval
from .user_input_replay import run_user_input_replay


_PROFILE = "full-live"
_SCHEMA_VERSION = "rpa-harness-full-live-profile-v1"


def _safe_slug(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "-" for char in value.strip()]
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "event"


def _generated_root(path: str | Path | None) -> Path:
    if path is not None:
        root = Path(path)
        root.mkdir(parents=True, exist_ok=True)
        return root
    return Path(tempfile.mkdtemp(prefix="rpa-harness-full-live-assets-"))


def _assert_generated_root_isolated(source_root: Path, generated_root: Path) -> None:
    source = source_root.resolve()
    generated = generated_root.resolve()
    if source == generated:
        raise ValueError("full-live generated assets root must not equal source assets root")
    try:
        generated.relative_to(source)
    except ValueError:
        return
    raise ValueError("full-live generated assets root must be outside source assets root")


def _string_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, dict):
        for item in value.values():
            values.extend(_string_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_string_values(item))
    elif value not in (None, ""):
        values.append(str(value))
    seen: set[str] = set()
    deduped: list[str] = []
    for item in values:
        if item and item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _read_event_html(assets_root: Path, event: dict[str, Any]) -> tuple[str, str]:
    before_page = event.get("before_page") if isinstance(event.get("before_page"), dict) else {}
    html_path = str(before_page.get("html_path") or "").strip()
    if not html_path:
        raise ValueError("full-live input event is missing before_page.html_path")
    source_root = assets_root.resolve()
    asset_id = str(event.get("asset_id") or "").strip()
    if not asset_id:
        raise ValueError("full-live input event is missing source asset id")
    asset_dir = (source_root / asset_id).resolve()
    try:
        asset_dir.relative_to(source_root)
    except ValueError as exc:
        raise ValueError("full-live source asset id must stay inside source assets root") from exc

    html_relative_path = Path(html_path)
    if html_relative_path.is_absolute():
        raise ValueError("full-live before_page.html_path must be relative to source asset directory")
    html_file = (asset_dir / html_relative_path).resolve()
    try:
        html_file.relative_to(asset_dir)
    except ValueError as exc:
        raise ValueError("full-live before_page.html_path must stay inside source asset directory") from exc
    return html_file.read_text(encoding="utf-8"), html_file.relative_to(source_root).as_posix()


def _merge_region_candidate(target: dict[str, Any], candidate: Any) -> None:
    if not isinstance(candidate, dict):
        return
    for key in (
        "region_id",
        "tab_id",
        "page_url",
        "page_title",
        "inferred_kind",
        "acquisition",
        "frame_path",
        "rect",
        "local_text",
        "dominant_container",
        "locator_candidates",
        "scope_candidates",
        "intersecting_elements",
        "table_summary",
        "list_summary",
        "action_summary",
        "warnings",
    ):
        value = candidate.get(key)
        if value not in (None, "", [], {}) and key not in target:
            target[key] = value
    frame_rect = candidate.get("frame_rect")
    if isinstance(frame_rect, dict) and frame_rect and "rect" not in target:
        target["rect"] = frame_rect


def _runtime_region_context(source_context: dict[str, Any]) -> dict[str, Any]:
    if not source_context:
        return {}
    normalized: dict[str, Any] = {}
    _merge_region_candidate(normalized, source_context)
    _merge_region_candidate(normalized, source_context.get("target_evidence"))
    _merge_region_candidate(normalized, source_context.get("event"))
    _merge_region_candidate(normalized, source_context.get("region_scope"))
    _merge_region_candidate(normalized, source_context.get("signals"))
    evidence = {
        key: value
        for key, value in normalized.items()
        if key
        in {
            "inferred_kind",
            "acquisition",
            "frame_path",
            "rect",
            "local_text",
            "dominant_container",
            "locator_candidates",
            "scope_candidates",
            "intersecting_elements",
            "table_summary",
            "list_summary",
            "action_summary",
            "warnings",
        }
        and value not in (None, "", [], {})
    }
    if evidence:
        normalized["evidence"] = evidence
    return normalized


def _region_acquisition(region_context: Any) -> str:
    if not isinstance(region_context, dict):
        return ""
    for key in ("event", "target_evidence", "signals", "region_scope", "evidence"):
        candidate = region_context.get(key)
        if isinstance(candidate, dict):
            acquisition = str(candidate.get("acquisition") or "").strip()
            if acquisition:
                return acquisition
    return str(region_context.get("acquisition") or "").strip()


def _region_acquisition_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        acquisition = _region_acquisition(event.get("region_context"))
        if acquisition:
            counts[acquisition] = counts.get(acquisition, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _scenario_for_event(assets_root: Path, event: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    html, html_source_path = _read_event_html(assets_root, event)
    asset_id = str(event.get("asset_id") or "")
    step_index = int(event.get("step_index") or 0)
    scenario_id = _safe_slug(f"{asset_id}-step-{step_index}")
    generated_asset_id = f"hcap-live-{scenario_id}"
    before_page = event.get("before_page") if isinstance(event.get("before_page"), dict) else {}
    result_refs = event.get("result_refs") if isinstance(event.get("result_refs"), dict) else {}
    output_key = str(result_refs.get("output_key") or event.get("output_key") or "")
    must_contain = _string_values(result_refs.get("output"))
    source_region_context = event.get("region_context") if isinstance(event.get("region_context"), dict) else {}
    runtime_region_context = _runtime_region_context(source_region_context)
    scenario = {
        "schema_version": "rpa-harness-live-agent-scenario-v0",
        "scenario_id": scenario_id,
        "asset_id": generated_asset_id,
        "instruction": str(event.get("user_instruction") or event.get("step_intent") or ""),
        "url": str(before_page.get("url") or f"https://fixture.local/{scenario_id}"),
        "html": html,
        "title": str(before_page.get("title") or ""),
        "expected": {
            "output_key": output_key,
            "must_contain_text": must_contain,
        },
        "page_patterns": list(event.get("page_patterns") or []),
        "region_context": runtime_region_context,
    }
    fixture = {
        "scenario_id": scenario_id,
        "generated_asset_id": generated_asset_id,
        "source_asset_id": asset_id,
        "source_event_id": str(event.get("event_id") or ""),
        "source_checkpoint_path": str(event.get("checkpoint_path") or ""),
        "source_trace_events_path": str(event.get("trace_events_path") or ""),
        "html_source": "captured-before-html",
        "html_source_path": html_source_path,
        "url": scenario["url"],
        "title": scenario["title"],
        "instruction": scenario["instruction"],
        "source_region_context": source_region_context,
        "runtime_region_context": runtime_region_context,
        "region_context": runtime_region_context,
    }
    return scenario, fixture


def _fixture_build_failure(event: dict[str, Any], exc: Exception) -> dict[str, Any]:
    before_page = event.get("before_page") if isinstance(event.get("before_page"), dict) else {}
    return {
        "source_asset_id": event.get("asset_id", ""),
        "source_event_id": event.get("event_id", ""),
        "source_checkpoint_path": event.get("checkpoint_path", ""),
        "source_trace_events_path": event.get("trace_events_path", ""),
        "before_html_path": str(before_page.get("html_path") or ""),
        "generated_asset_id": "",
        "failure_category": "controlled-fixture-build-failed",
        "error": f"{type(exc).__name__}: {exc}",
        "baseline_role": event.get("baseline_role", ""),
    }


def _select_full_live_events(replay_report: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for event in replay_report.get("replayed_input_events") or []:
        if not isinstance(event, dict):
            continue
        if event.get("status") != "passed":
            continue
        if event.get("event_kind") != "natural_language_instruction":
            continue
        if not str(event.get("user_instruction") or "").strip():
            continue
        events.append(event)
    return events


def _write_scenarios(scenarios_root: Path, scenarios: list[dict[str, Any]]) -> None:
    scenarios_root.mkdir(parents=True, exist_ok=True)
    for scenario in scenarios:
        path = scenarios_root / f"{scenario['scenario_id']}.json"
        path.write_text(json.dumps(scenario, ensure_ascii=False, indent=2), encoding="utf-8")


def _scenario_status_by_asset(live_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("asset_id") or ""): item
        for item in live_report.get("scenarios") or []
        if isinstance(item, dict)
    }


def _generated_trace_ids(generated_assets_root: Path, generated_asset_ids: list[str]) -> list[str]:
    trace_ids: list[str] = []
    for asset_id in generated_asset_ids:
        for trace_path in sorted((generated_assets_root / asset_id / "steps").glob("*/trace_events.json")):
            try:
                payload = json.loads(trace_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict) and item.get("trace_id"):
                        trace_ids.append(str(item["trace_id"]))
    return sorted(set(trace_ids))


def _aggregate_post_capture(live_report: dict[str, Any]) -> dict[str, Any]:
    checks = [item.get("post_capture") or {} for item in live_report.get("scenarios") or [] if isinstance(item, dict)]
    return {
        "warning_count": sum(int(item.get("warning_count") or 0) for item in checks),
        "scenario_count": len(checks),
        "checks": checks,
    }


def _failure_items(live_report: dict[str, Any], events_by_generated_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for item in live_report.get("scenarios") or []:
        if not isinstance(item, dict) or item.get("status") != "failed":
            continue
        generated_asset_id = str(item.get("asset_id") or "")
        event = events_by_generated_id.get(generated_asset_id, {})
        failure_category = str(item.get("failure_category") or "full-live-scenario-failed")
        baseline_role = (
            "warning-only-generated-asset"
            if failure_category == "post-capture-regression-warning"
            else str(event.get("baseline_role") or "")
        )
        failures.append(
            {
                "source_asset_id": event.get("asset_id", ""),
                "source_event_id": event.get("event_id", ""),
                "generated_asset_id": generated_asset_id,
                "failure_category": failure_category,
                "error": item.get("error", ""),
                "baseline_role": baseline_role,
            }
        )
    return failures


def _profile_metadata() -> dict[str, Any]:
    return {
        "name": _PROFILE,
        "execution_mode": "controlled-fixture-recording-runtime-agent",
        "uses_live_planner": True,
        "uses_live_url_oracle": False,
        "uses_outer_agent_ui_control": False,
        "governance_mode": "human-governed-assets",
    }


def _empty_report(
    *,
    assets_root: Path,
    generated_assets_root: Path,
    replay_report: dict[str, Any],
) -> dict[str, Any]:
    selected_events = _select_full_live_events(replay_report)
    return {
        "schema_version": _SCHEMA_VERSION,
        "kind": "full_live_profile",
        "profile": _profile_metadata(),
        "summary": {
            "status": "failed",
            "failure_category": "no-full-live-input-events",
            "source_asset_count": 0,
            "selected_input_event_count": 0,
            "planner_invocation_count": 0,
            "generated_asset_ids": [],
            "generated_trace_ids": [],
            "blocking_failure_count": 0,
            "warning_only_failure_count": 0,
        },
        "interpretation": {
            "verdict": "insufficient evidence",
            "bounded": True,
            "comparison_basis": "single-run",
            "evidence_limits": ["No eligible natural-language input events ran"],
        },
        "source_assets_root": str(assets_root),
        "generated_assets_root": str(generated_assets_root),
        "source_asset_ids": sorted({str(event.get("asset_id") or "") for event in selected_events if event.get("asset_id")}),
        "selected_input_events": [],
        "controlled_fixtures": [],
        "generated_assets": {
            "root": str(generated_assets_root),
            "asset_ids": [],
            "promotion_status": "candidate-lite/profile-artifact",
            "agents_may_promote_automatically": False,
        },
        "post_capture": {"warning_count": 0, "scenario_count": 0, "checks": []},
        "failures": [
            {
                "failure_category": "no-full-live-input-events",
                "error": "No passed natural_language_instruction events were found in the source assets",
            }
        ],
        "user_input_replay": replay_report,
        "trust_limits": [
            "No eligible natural-language input events ran",
            "Full-live profile does not use live URLs as oracle",
            "Generated assets are candidate-lite/profile artifacts only",
            "Agents may explain report facts but cannot promote assets automatically",
        ],
        "governance_boundary": {
            "scripts_execute": True,
            "agents_explain": True,
            "humans_govern": True,
            "candidate_lite_warning_only": True,
            "agents_may_promote_automatically": False,
        },
    }


def _fixture_failure_report(
    *,
    assets_root: Path,
    generated_assets_root: Path,
    replay_report: dict[str, Any],
    selected_events: list[dict[str, Any]],
    fixture_failures: list[dict[str, Any]],
) -> dict[str, Any]:
    source_asset_ids = sorted({str(event.get("asset_id") or "") for event in selected_events if event.get("asset_id")})
    blocking_failures = [
        item
        for item in fixture_failures
        if item.get("baseline_role") not in {"warning-only", "warning-only-generated-asset"}
    ]
    return {
        "schema_version": _SCHEMA_VERSION,
        "kind": "full_live_profile",
        "profile": _profile_metadata(),
        "summary": {
            "status": "failed" if blocking_failures else "passed",
            "failure_category": "controlled-fixture-build-failed" if blocking_failures else "",
            "source_asset_count": len(source_asset_ids),
            "selected_input_event_count": len(selected_events),
            "fixture_build_failure_count": len(fixture_failures),
            "planner_invocation_count": 0,
            "generated_asset_ids": [],
            "generated_trace_ids": [],
            "blocking_failure_count": len(blocking_failures),
            "warning_only_failure_count": len(fixture_failures) - len(blocking_failures),
            "post_capture_warning_count": 0,
        },
        "interpretation": {
            "verdict": "regression" if blocking_failures else "no meaningful change",
            "bounded": True,
            "comparison_basis": "single-run",
            "evidence_limits": ["No controlled full-live fixtures could be built"],
        },
        "source_assets_root": str(assets_root),
        "generated_assets_root": str(generated_assets_root),
        "source_asset_ids": source_asset_ids,
        "selected_input_events": selected_events,
        "controlled_fixtures": [],
        "generated_assets": {
            "root": str(generated_assets_root),
            "asset_ids": [],
            "promotion_status": "candidate-lite/profile-artifact",
            "agents_may_promote_automatically": False,
        },
        "post_capture": {"warning_count": 0, "scenario_count": 0, "checks": []},
        "failures": fixture_failures,
        "user_input_replay": replay_report,
        "trust_limits": [
            "At least one selected input event could not build a controlled fixture",
            "Full-live profile does not use live URLs as oracle",
            "Generated assets are candidate-lite/profile artifacts only",
            "Agents may explain report facts but cannot promote assets automatically",
        ],
        "governance_boundary": {
            "scripts_execute": True,
            "agents_explain": True,
            "humans_govern": True,
            "candidate_lite_warning_only": True,
            "agents_may_promote_automatically": False,
        },
    }


async def run_full_live_profile(
    assets_root: str | Path,
    *,
    generated_assets_root: str | Path | None = None,
    planner: Planner | None = None,
    model_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_root = Path(assets_root)
    output_root = _generated_root(generated_assets_root)
    _assert_generated_root_isolated(source_root, output_root)
    replay_report = run_user_input_replay(source_root)
    selected_events = _select_full_live_events(replay_report)
    if not selected_events:
        return _empty_report(
            assets_root=source_root,
            generated_assets_root=output_root,
            replay_report=replay_report,
        )

    scenarios: list[dict[str, Any]] = []
    fixtures: list[dict[str, Any]] = []
    events_by_generated_id: dict[str, dict[str, Any]] = {}
    fixture_failures: list[dict[str, Any]] = []
    for event in selected_events:
        try:
            scenario, fixture = _scenario_for_event(source_root, event)
        except Exception as exc:
            fixture_failures.append(_fixture_build_failure(event, exc))
            continue
        scenarios.append(scenario)
        fixtures.append(fixture)
        events_by_generated_id[str(fixture["generated_asset_id"])] = event

    if not scenarios:
        return _fixture_failure_report(
            assets_root=source_root,
            generated_assets_root=output_root,
            replay_report=replay_report,
            selected_events=selected_events,
            fixture_failures=fixture_failures,
        )

    with tempfile.TemporaryDirectory(prefix="rpa-harness-full-live-scenarios-") as tmp_dir:
        scenarios_root = Path(tmp_dir)
        _write_scenarios(scenarios_root, scenarios)
        live_report = await run_live_agent_eval(
            scenarios_root=scenarios_root,
            assets_root=output_root,
            planner=planner,
            model_config=model_config,
        )

    generated_asset_ids = [str(fixture["generated_asset_id"]) for fixture in fixtures]
    generated_trace_ids = _generated_trace_ids(output_root, generated_asset_ids)
    post_capture = _aggregate_post_capture(live_report)
    failures = fixture_failures + _failure_items(live_report, events_by_generated_id)
    blocking_failures = [
        item
        for item in failures
        if item.get("baseline_role") not in {"warning-only", "warning-only-generated-asset"}
    ]
    warning_failures = [
        item
        for item in failures
        if item.get("baseline_role") in {"warning-only", "warning-only-generated-asset"}
    ]
    source_asset_ids = sorted({str(event.get("asset_id") or "") for event in selected_events if event.get("asset_id")})
    status = "failed" if blocking_failures else "passed"
    failure_category = str(blocking_failures[0].get("failure_category") or "full-live-profile-failed") if blocking_failures else ""
    planner_invocation_count = int((live_report.get("summary") or {}).get("planner_invocation_count") or 0)
    region_acquisitions = _region_acquisition_counts(selected_events)
    return {
        "schema_version": _SCHEMA_VERSION,
        "kind": "full_live_profile",
        "profile": _profile_metadata(),
        "summary": {
            "status": status,
            "failure_category": failure_category,
            "source_asset_count": len(source_asset_ids),
            "selected_input_event_count": len(selected_events),
            "fixture_build_failure_count": len(fixture_failures),
            "planner_invocation_count": planner_invocation_count,
            "generated_asset_ids": generated_asset_ids,
            "generated_trace_ids": generated_trace_ids,
            "blocking_failure_count": len(blocking_failures),
            "warning_only_failure_count": len(warning_failures),
            "post_capture_warning_count": int(post_capture.get("warning_count") or 0),
            "region_context_event_count": len(
                [event for event in selected_events if event.get("region_context")]
            ),
            "region_acquisitions": region_acquisitions,
        },
        "interpretation": {
            "verdict": "regression" if status == "failed" else "no meaningful change",
            "bounded": True,
            "comparison_basis": "single-run",
            "evidence_limits": [
                "Full-live profile uses controlled fixtures, not live URL oracle",
                "Passing covered inputs does not prove global RPA health",
            ],
        },
        "source_assets_root": str(source_root),
        "generated_assets_root": str(output_root),
        "source_asset_ids": source_asset_ids,
        "selected_input_events": selected_events,
        "controlled_fixtures": fixtures,
        "generated_assets": {
            "root": str(output_root),
            "asset_ids": generated_asset_ids,
            "promotion_status": "candidate-lite/profile-artifact",
            "agents_may_promote_automatically": False,
        },
        "generated_trace_ids": generated_trace_ids,
        "live_agent_eval": live_report,
        "post_capture": post_capture,
        "failures": failures,
        "user_input_replay": replay_report,
        "trust_limits": [
            "Full-live profile does not use live URLs as oracle",
            "Generated assets are candidate-lite/profile artifacts only",
            "candidate-lite assets remain warning-only and not blocking baseline",
            "region_context is passed as generic RecordingRuntimeAgent context",
            "Agents may explain report facts but cannot promote assets automatically",
        ],
        "governance_boundary": {
            "scripts_execute": True,
            "agents_explain": True,
            "humans_govern": True,
            "candidate_lite_warning_only": True,
            "agents_may_promote_automatically": False,
        },
    }


def run_full_live_profile_sync(
    assets_root: str | Path,
    *,
    generated_assets_root: str | Path | None = None,
    planner: Planner | None = None,
    model_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        run_full_live_profile(
            assets_root,
            generated_assets_root=generated_assets_root,
            planner=planner,
            model_config=model_config,
        )
    )


def _format_values(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def render_full_live_profile_summary(
    report: dict[str, Any],
    *,
    machine_report_path: str | Path | None = None,
    lang: str = "en",
) -> str:
    summary = report.get("summary") or {}
    profile = report.get("profile") or {}
    machine_path = str(machine_report_path) if machine_report_path else "not written"
    generated_asset_ids = list(summary.get("generated_asset_ids") or [])
    trust_limits = list(report.get("trust_limits") or [])
    if lang == "zh":
        lines = [
            f"RPA Harness Profile: {profile.get('name', _PROFILE)}",
            f"状态: {summary.get('status', 'unknown')}",
            f"Failure category: {summary.get('failure_category') or 'none'}",
            f"Selected input events: {summary.get('selected_input_event_count', 0)}",
            f"Planner invocations: {summary.get('planner_invocation_count', 0)}",
            f"Generated assets: {_format_values([str(item) for item in generated_asset_ids])}",
            "Governance: Scripts execute; Agents explain; Humans govern",
            f"Machine report: {machine_path}",
        ]
    else:
        lines = [
            f"RPA Harness Profile: {profile.get('name', _PROFILE)}",
            f"Status: {summary.get('status', 'unknown')}",
            f"Failure category: {summary.get('failure_category') or 'none'}",
            f"Selected input events: {summary.get('selected_input_event_count', 0)}",
            f"Planner invocations: {summary.get('planner_invocation_count', 0)}",
            f"Generated assets: {_format_values([str(item) for item in generated_asset_ids])}",
            "Governance: Scripts execute; Agents explain; Humans govern",
            f"Machine report: {machine_path}",
        ]
    if trust_limits:
        lines.append(f"Trust limits: {'; '.join(str(item) for item in trust_limits[:3])}")
    return "\n".join(lines) + "\n"
