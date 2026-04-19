from __future__ import annotations

from typing import Any, Dict, Optional

from .contract_pipeline import CommittedStep
from .contract_models import StepContract


def adapt_manual_event_to_committed_step(event: Dict[str, Any]) -> CommittedStep:
    action = str(event.get("action") or "").strip().lower()
    description = str(event.get("description") or action or "manual step").strip()
    step_id = str(event.get("id") or f"manual_{action or 'step'}")

    if action == "navigate":
        url = str(event.get("url") or "").strip()
        contract = StepContract(
            id=step_id,
            source="manual",
            description=description,
            intent={"goal": description},
            target={"type": "url", "url_template": url},
            operator={"type": "navigate", "execution_strategy": "primitive_action"},
            outputs={"blackboard_key": None, "schema": None},
            validation={"must": _infer_navigation_validation(url)},
            runtime_policy={"requires_runtime_ai": False, "runtime_ai_reason": ""},
        )
        artifact = {
            "id": step_id,
            "kind": "primitive_action",
            "description": description,
            "contract_id": step_id,
            "input_refs": [],
            "validation": contract.validation.must,
            "action": "goto",
            "target_url_template": url,
        }
        return CommittedStep(
            contract=contract,
            artifact=artifact,
            validation_evidence={"source": "manual", "action": "navigate", "url": url},
        )

    locator = _select_locator(event)
    contract = StepContract(
        id=step_id,
        source="manual",
        description=description,
        intent={"goal": description},
        target={"type": "locator", "locator": locator},
        operator={"type": action or "click", "execution_strategy": "primitive_action"},
        outputs={"blackboard_key": None, "schema": None},
        validation={"must": _infer_action_validation(event)},
        runtime_policy={"requires_runtime_ai": False, "runtime_ai_reason": ""},
    )
    artifact = {
        "id": step_id,
        "kind": "primitive_action",
        "description": description,
        "contract_id": step_id,
        "input_refs": [],
        "validation": contract.validation.must,
        "action": action or "click",
        "locator": locator,
    }
    return CommittedStep(
        contract=contract,
        artifact=artifact,
        validation_evidence={"source": "manual", "action": action or "click"},
    )


def _select_locator(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    locator_candidates = event.get("locator_candidates")
    if isinstance(locator_candidates, list):
        for candidate in locator_candidates:
            if isinstance(candidate, dict) and candidate.get("selected") and isinstance(candidate.get("locator"), dict):
                return dict(candidate["locator"])
        for candidate in locator_candidates:
            if isinstance(candidate, dict) and isinstance(candidate.get("locator"), dict):
                return dict(candidate["locator"])

    locator = event.get("locator")
    if isinstance(locator, dict):
        return dict(locator)
    target = event.get("target")
    if isinstance(target, str) and target.strip():
        return {"method": "css", "value": target.strip()}
    return None


def _infer_navigation_validation(url: str) -> list[dict[str, Any]]:
    normalized = (url or "").strip()
    if not normalized:
        return []
    if "/" in normalized:
        suffix = "/" + normalized.rstrip("/").split("/")[-1]
        if suffix != "/":
            return [{"type": "url_contains", "value": suffix}]
    return [{"type": "url_contains", "value": normalized}]


def _infer_action_validation(event: Dict[str, Any]) -> list[dict[str, Any]]:
    validation = event.get("validation")
    if isinstance(validation, dict):
        url_contains = validation.get("url_contains")
        if isinstance(url_contains, str) and url_contains.strip():
            return [{"type": "url_contains", "value": url_contains.strip()}]
    return []
