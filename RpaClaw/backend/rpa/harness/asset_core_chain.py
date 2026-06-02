from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import HarnessScenarioAsset, HarnessStepCheckpoint
from .skill_replay import _compile_skill as _compile_step_skill
from .stateful_sop import (
    _build_session_from_asset,
    _checkpoint_paths,
    _compile_skill as _compile_full_sop_skill,
    _load_json,
    _run_asset,
)


_REPORT_NAME = "core-chain-report.md"
_MACHINE_REPORT_NAME = "core-chain-full-report.json"
_GENERATED_SKILLS_DIR = "generated_skills"


def run_asset_core_chain_export(
    assets_root: str | Path,
    *,
    asset_ids: set[str] | None = None,
    model_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(assets_root)
    asset_dirs = _selected_asset_dirs(root, asset_ids=asset_ids)

    async def run_all() -> list[dict[str, Any]]:
        return [
            await _export_asset_core_chain(asset_dir, model_config=model_config)
            for asset_dir in asset_dirs
        ]

    items = asyncio.run(run_all()) if asset_dirs else []
    failed = [item for item in items if item.get("status") == "failed"]
    status = "failed" if not items or failed else "passed"
    return {
        "schema_version": "rpa-harness-asset-core-chain-export-v0",
        "summary": {
            "status": status,
            "failure_category": "no-assets-selected" if not items else "",
            "asset_count": len(items),
            "asset_ids": [str(item.get("asset_id") or "") for item in items],
            "failed": len(failed),
        },
        "assets": items,
    }


def _selected_asset_dirs(root: Path, *, asset_ids: set[str] | None) -> list[Path]:
    dirs: list[Path] = []
    for scenario_path in sorted(root.glob("*/scenario.json")):
        asset_dir = scenario_path.parent
        if asset_ids and asset_dir.name not in asset_ids:
            try:
                scenario = HarnessScenarioAsset.model_validate(_load_json(scenario_path))
            except Exception:
                continue
            if scenario.asset_id not in asset_ids:
                continue
        dirs.append(asset_dir)
    return dirs


async def _export_asset_core_chain(
    asset_dir: Path,
    *,
    model_config: dict[str, Any] | None,
) -> dict[str, Any]:
    scenario = HarnessScenarioAsset.model_validate(_load_json(asset_dir / "scenario.json"))
    generated_root = asset_dir / _GENERATED_SKILLS_DIR
    checkpoint_items = _load_checkpoint_items(asset_dir, scenario)
    step_exports = _export_step_skills(asset_dir, generated_root, checkpoint_items)
    full_sop_export = await _export_full_sop_skill(asset_dir, generated_root, scenario, checkpoint_items)
    stateful_report = await _run_asset(asset_dir, scenario, model_config=model_config)
    status = str(stateful_report.get("status") or "failed")
    failure_category = str(stateful_report.get("failure_category") or "")

    asset_report = {
        "asset_id": scenario.asset_id,
        "status": status,
        "failure_category": failure_category,
        "asset_dir": str(asset_dir),
        "reports": {
            "human": _REPORT_NAME,
            "machine": _MACHINE_REPORT_NAME,
        },
        "generated_skills": {
            "full_sop": full_sop_export,
            "steps": step_exports,
        },
        "stateful_sop": stateful_report,
    }
    machine_report = {
        "schema_version": "rpa-harness-asset-core-chain-report-v0",
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "status": status,
            "asset_id": scenario.asset_id,
            "failure_category": failure_category,
        },
        "assets": [asset_report],
    }

    (asset_dir / _MACHINE_REPORT_NAME).write_text(
        json.dumps(machine_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (asset_dir / _REPORT_NAME).write_text(
        _render_asset_core_chain_markdown(asset_report),
        encoding="utf-8",
    )
    return asset_report


def _load_checkpoint_items(
    asset_dir: Path,
    scenario: HarnessScenarioAsset,
) -> list[tuple[Path, HarnessStepCheckpoint]]:
    items: list[tuple[Path, HarnessStepCheckpoint]] = []
    for checkpoint_path in _checkpoint_paths(asset_dir, scenario):
        checkpoint = HarnessStepCheckpoint.model_validate(_load_json(checkpoint_path))
        items.append((checkpoint_path, checkpoint))
    return items


def _export_step_skills(
    asset_dir: Path,
    generated_root: Path,
    checkpoint_items: list[tuple[Path, HarnessStepCheckpoint]],
) -> list[dict[str, Any]]:
    exports: list[dict[str, Any]] = []
    for checkpoint_path, checkpoint in checkpoint_items:
        step_dir = generated_root / "steps" / f"{checkpoint.step_index:03d}"
        step_dir.mkdir(parents=True, exist_ok=True)
        trace_path = asset_dir / checkpoint.action.trace_events_path
        trace_events = _load_json(trace_path)
        if not isinstance(trace_events, list):
            trace_events = []
        metadata = {
            "asset_id": asset_dir.name,
            "scope": "step",
            "step_index": checkpoint.step_index,
            "step_id": checkpoint.step_id,
            "source_checkpoint": _relative_path(checkpoint_path, asset_dir),
            "source_trace_events": checkpoint.action.trace_events_path,
            "trace_count": len([event for event in trace_events if isinstance(event, dict)]),
            "status": "passed",
            "failure_category": "",
        }
        try:
            script = _compile_step_skill(trace_events)
            (step_dir / "skill.py").write_text(script, encoding="utf-8")
            metadata["generated_skill_size"] = len(script)
        except Exception as exc:
            metadata["status"] = "failed"
            metadata["failure_category"] = "step-skill-compile-error"
            metadata["error"] = f"{type(exc).__name__}: {exc}"
            metadata["generated_skill_size"] = 0
        (step_dir / "compile_metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        exports.append(
            {
                **metadata,
                "relative_path": _relative_path(step_dir / "skill.py", asset_dir),
                "metadata_path": _relative_path(step_dir / "compile_metadata.json", asset_dir),
            }
        )
    return exports


async def _export_full_sop_skill(
    asset_dir: Path,
    generated_root: Path,
    scenario: HarnessScenarioAsset,
    checkpoint_items: list[tuple[Path, HarnessStepCheckpoint]],
) -> dict[str, Any]:
    full_sop_dir = generated_root / "full_sop"
    full_sop_dir.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {
        "asset_id": scenario.asset_id,
        "scope": "full_sop",
        "status": "passed",
        "failure_category": "",
        "trace_count": 0,
        "step_count": len(checkpoint_items),
    }
    try:
        session = await _build_session_from_asset(asset_dir, scenario, checkpoint_items)
        metadata["trace_count"] = len(session.traces)
        metadata["runtime_result_keys"] = sorted(session.runtime_results.values.keys())
        failed_step = next((step for step in session.steps if step["status"] == "failed"), None)
        if failed_step:
            metadata["status"] = "failed"
            metadata["failure_category"] = str(failed_step.get("failure_category") or "capture-to-trace-error")
            metadata["error"] = str(failed_step.get("error") or "")
            script = ""
        else:
            script = _compile_full_sop_skill(session.traces)
            (full_sop_dir / "skill.py").write_text(script, encoding="utf-8")
        metadata["generated_skill_size"] = len(script)
    except Exception as exc:
        metadata["status"] = "failed"
        metadata["failure_category"] = "full-sop-skill-compile-error"
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        metadata["generated_skill_size"] = 0
    (full_sop_dir / "compile_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        **metadata,
        "relative_path": _relative_path(full_sop_dir / "skill.py", asset_dir),
        "metadata_path": _relative_path(full_sop_dir / "compile_metadata.json", asset_dir),
    }


def _render_asset_core_chain_markdown(asset_report: dict[str, Any]) -> str:
    stateful = asset_report.get("stateful_sop") if isinstance(asset_report.get("stateful_sop"), dict) else {}
    generated = asset_report.get("generated_skills") if isinstance(asset_report.get("generated_skills"), dict) else {}
    full_sop = generated.get("full_sop") if isinstance(generated.get("full_sop"), dict) else {}
    steps = generated.get("steps") if isinstance(generated.get("steps"), list) else []
    lines = [
        "# RPA Harness Core Chain Report",
        "",
        f"- Asset ID: `{asset_report.get('asset_id') or ''}`",
        f"- Status: `{asset_report.get('status') or ''}`",
        f"- Failure category: `{asset_report.get('failure_category') or ''}`",
        f"- Accepted trace count: `{stateful.get('accepted_trace_count') or 0}`",
        f"- Generated full SOP Skill: `{full_sop.get('relative_path') or ''}`",
        "",
        "## Generated Skills",
        "",
        "| Scope | Step | Status | Path |",
        "| --- | --- | --- | --- |",
        f"| full_sop | - | `{full_sop.get('status') or ''}` | `{full_sop.get('relative_path') or ''}` |",
    ]
    for step in steps:
        lines.append(
            "| step | "
            f"{int(step.get('step_index') or 0):03d} | "
            f"`{step.get('status') or ''}` | "
            f"`{step.get('relative_path') or ''}` |"
        )
    lines.extend(
        [
            "",
            "## Replay",
            "",
            f"- Replay status: `{(stateful.get('replay') or {}).get('status') or ''}`",
            f"- Replay failure: `{(stateful.get('replay') or {}).get('failure_category') or ''}`",
            "",
            "## Notes",
            "",
            "- This report is asset-local evidence for asset -> accepted trace -> TraceSkillCompiler -> generated Skill -> controlled replay.",
            "- Generated files are diagnostic artifacts and do not modify recorded trace, checkpoint, expected signals, or replay assertions.",
        ]
    )
    return "\n".join(lines) + "\n"


def _relative_path(path: Path, asset_dir: Path) -> str:
    try:
        return path.relative_to(asset_dir).as_posix()
    except ValueError:
        return path.as_posix()
