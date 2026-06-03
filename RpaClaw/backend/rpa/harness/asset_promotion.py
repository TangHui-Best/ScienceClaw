from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from .catalog import build_golden_eligibility_report
from .models import HarnessScenarioAsset


PromotionLevel = Literal["candidate-lite", "candidate", "golden"]

_CANDIDATE_LITE_RUNNER_MODES = [
    "offline_core_chain",
    "skill_replay_e2e",
    "stateful_sop_capture_to_skill",
]
_CANDIDATE_LITE_CORE_COVERAGE = [
    "html_to_raw_snapshot",
    "raw_to_compact_snapshot",
    "planner_action_selection",
    "trace_to_skill",
    "skill_replay",
    "stateful_capture_to_skill",
]


class PromotionError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _scenario_path(assets_root: str | Path, asset_id: str) -> Path:
    return Path(assets_root) / asset_id / "scenario.json"


def _merge_ordered(existing: Any, additions: list[str]) -> list[str]:
    values = [str(value) for value in existing or [] if str(value)]
    for value in additions:
        if value not in values:
            values.append(value)
    return values


def promote_harness_asset(
    assets_root: str | Path,
    asset_id: str,
    level: PromotionLevel,
    *,
    confirm_expected: bool = False,
    confirm_sensitivity: bool = False,
    human_approved_golden: bool = False,
    override_golden_eligibility: bool = False,
) -> dict[str, Any]:
    scenario_path = _scenario_path(assets_root, asset_id)
    if not scenario_path.exists():
        raise PromotionError(f"scenario.json not found for asset {asset_id!r}")

    scenario_payload = _load_json(scenario_path)
    governance = dict(scenario_payload.get("governance") or {})
    human_approved = False
    eligibility_status = "not-required"
    eligibility_reasons: list[str] = []

    if level in {"candidate-lite", "candidate", "golden"}:
        governance["runner_modes"] = _merge_ordered(
            governance.get("runner_modes"),
            _CANDIDATE_LITE_RUNNER_MODES,
        )
        governance["core_chain_coverage"] = _merge_ordered(
            governance.get("core_chain_coverage"),
            _CANDIDATE_LITE_CORE_COVERAGE,
        )

    if level == "golden":
        if not human_approved_golden:
            raise PromotionError("golden promotion requires explicit human approval")
        human_approved = True
        eligibility_report = build_golden_eligibility_report(assets_root, asset_ids={asset_id})
        eligibility_items = {
            item.get("asset_id"): item
            for item in eligibility_report.get("assets", [])
            if isinstance(item, dict)
        }
        eligibility_item = eligibility_items.get(asset_id)
        if eligibility_item is None:
            eligibility_reasons = ["eligibility-not-found"]
        else:
            eligibility_reasons = list(eligibility_item.get("blocking_reasons") or [])
        if confirm_expected and "expected-signals-not-reviewed" in eligibility_reasons:
            eligibility_reasons.remove("expected-signals-not-reviewed")
        if confirm_sensitivity and "sensitivity-not-reviewed" in eligibility_reasons:
            eligibility_reasons.remove("sensitivity-not-reviewed")
        if eligibility_reasons and not override_golden_eligibility:
            raise PromotionError(
                "golden promotion requires eligible active candidate: "
                + ", ".join(eligibility_reasons)
            )
        eligibility_status = "override" if eligibility_reasons else "eligible"

    if level in {"candidate", "golden"}:
        if not confirm_expected:
            raise PromotionError(
                f"{level} promotion requires explicit expected-signal confirmation"
            )
        if not confirm_sensitivity:
            raise PromotionError(
                f"{level} promotion requires explicit sensitivity confirmation"
        )
        governance["expected_signals_reviewed"] = True
        governance["sensitivity_reviewed"] = True
        scenario_payload["asset_status"] = "active"

    governance["promotion_status"] = level
    scenario_payload["governance"] = governance
    HarnessScenarioAsset.model_validate(scenario_payload)
    _write_json(scenario_path, scenario_payload)

    return {
        "schema_version": "rpa-harness-asset-promotion-v0",
        "asset_id": asset_id,
        "promotion_status": level,
        "scenario_path": scenario_path.as_posix(),
        "expected_signals_reviewed": bool(governance.get("expected_signals_reviewed")),
        "sensitivity_reviewed": bool(governance.get("sensitivity_reviewed")),
        "human_approved": human_approved,
        "eligibility_status": eligibility_status,
        "eligibility_reasons": eligibility_reasons,
    }
