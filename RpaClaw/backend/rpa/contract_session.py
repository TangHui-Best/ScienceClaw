from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from .manual_event_adapter import adapt_manual_event_to_committed_step
from .contract_models import StepContract
from .contract_pipeline import CommittedStep
from .contract_skill_builder import build_contract_skill_files


_STABLE_SUBPAGE_SUFFIXES = (
    "/pulls",
    "/issues",
    "/actions",
    "/releases",
    "/wiki",
    "/discussions",
    "/commits",
)


def apply_session_contract_committed_steps(session: Any, committed_payloads: List[Dict[str, Any]]) -> None:
    existing_items = getattr(session, "contract_steps", []) or []
    merged: List[Dict[str, Any]] = []
    index_by_contract_id: Dict[str, int] = {}
    index_by_output_key: Dict[str, int] = {}

    for item in existing_items:
        normalized_item = _normalize_committed_payload(item)
        if normalized_item is None:
            continue
        contract_payload = normalized_item["contract"]
        contract_id = str(contract_payload.get("id") or "").strip()
        if not contract_id:
            continue
        index_by_contract_id[contract_id] = len(merged)
        output_key = _committed_payload_output_key(normalized_item)
        if output_key:
            index_by_output_key[output_key] = len(merged)
        merged.append(normalized_item)

    for item in committed_payloads or []:
        normalized_item = _normalize_committed_payload(item)
        if normalized_item is None:
            continue
        contract_payload = normalized_item["contract"]
        contract_id = str(contract_payload.get("id") or "").strip()
        if not contract_id:
            continue
        existing_index = index_by_contract_id.get(contract_id)
        output_key = _committed_payload_output_key(normalized_item)
        if existing_index is None and output_key:
            existing_index = index_by_output_key.get(output_key)
        if existing_index is None:
            index_by_contract_id[contract_id] = len(merged)
            if output_key:
                index_by_output_key[output_key] = len(merged)
            merged.append(normalized_item)
            continue
        merged[existing_index] = normalized_item
        index_by_contract_id[contract_id] = existing_index
        if output_key:
            index_by_output_key[output_key] = existing_index

    session.contract_steps = merged


def session_contract_committed_steps(session: Any) -> List[CommittedStep]:
    ordered_steps = _ordered_session_steps(getattr(session, "steps", []) or [])
    contract_payloads = getattr(session, "contract_steps", []) or []
    payload_by_contract_id: Dict[str, Dict[str, Any]] = {}
    for item in contract_payloads:
        if not isinstance(item, dict):
            continue
        contract_payload = item.get("contract")
        if not isinstance(contract_payload, dict):
            continue
        contract_id = str(contract_payload.get("id") or "").strip()
        if contract_id:
            payload_by_contract_id[contract_id] = item

    committed_from_steps: List[CommittedStep] = []
    seen_contract_ids: set[str] = set()
    for step in ordered_steps:
        action = getattr(step, "action", "")
        source = getattr(step, "source", "")
        if action == "contract_step" and source == "ai":
            diagnostics = getattr(step, "assistant_diagnostics", {}) or {}
            contract_id = str(diagnostics.get("contract_id") or "").strip()
            payload = payload_by_contract_id.get(contract_id)
            if not payload:
                continue
            committed = _payload_to_committed_step(payload)
            if committed is None:
                continue
            committed_from_steps.append(committed)
            seen_contract_ids.add(contract_id)
            continue
        if source == "record" and action in {
            "navigate",
            "navigate_click",
            "navigate_press",
            "open_tab_click",
            "click",
            "fill",
            "press",
            "extract_text",
        }:
            committed_from_steps.append(adapt_manual_event_to_committed_step(step.model_dump()))

    if committed_from_steps:
        return _drop_redundant_runtime_ai_followup_navigations(
            _generalize_committed_steps_from_blackboard(
                committed_from_steps,
                getattr(session, "contract_blackboard", {}) or {},
            )
        )

    committed: List[CommittedStep] = []
    for item in contract_payloads:
        committed_step = _payload_to_committed_step(item)
        if committed_step is not None:
            committed.append(committed_step)
    return _drop_redundant_runtime_ai_followup_navigations(
        _generalize_committed_steps_from_blackboard(
            committed,
            getattr(session, "contract_blackboard", {}) or {},
        )
    )


def _ordered_session_steps(steps: List[Any]) -> List[Any]:
    indexed_steps = list(enumerate(steps or []))
    return [
        step
        for _, step in sorted(
            indexed_steps,
            key=lambda item: (_step_time_ms(item[1]), item[0]),
        )
    ]


def _step_time_ms(step: Any) -> int:
    event_timestamp_ms = getattr(step, "event_timestamp_ms", None)
    if event_timestamp_ms is not None:
        try:
            event_time = int(event_timestamp_ms)
            if event_time >= 946684800000:
                return event_time
        except Exception:
            pass
    timestamp = getattr(step, "timestamp", None)
    timestamp_fn = getattr(timestamp, "timestamp", None)
    if callable(timestamp_fn):
        try:
            return int(timestamp_fn() * 1000)
        except Exception:
            return 0
    return 0


def _payload_to_committed_step(item: Dict[str, Any]) -> CommittedStep | None:
    if not isinstance(item, dict):
        return None
    contract_payload = item.get("contract")
    artifact = item.get("artifact")
    if not isinstance(contract_payload, dict) or not isinstance(artifact, dict):
        return None
    return CommittedStep(
        contract=StepContract(**contract_payload),
        artifact=dict(artifact),
        validation_evidence=dict(item.get("validation_evidence") or {}),
    )


def _normalize_committed_payload(item: Dict[str, Any]) -> Dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    contract_payload = item.get("contract")
    artifact = item.get("artifact")
    if not isinstance(contract_payload, dict) or not isinstance(artifact, dict):
        return None
    return {
        "contract": dict(contract_payload),
        "artifact": dict(artifact),
        "validation_evidence": dict(item.get("validation_evidence") or {}),
    }


def _committed_payload_output_key(item: Dict[str, Any]) -> str:
    contract_payload = item.get("contract") if isinstance(item, dict) else None
    if not isinstance(contract_payload, dict):
        return ""
    outputs = contract_payload.get("outputs")
    if not isinstance(outputs, dict):
        return ""
    output_key = outputs.get("blackboard_key")
    if isinstance(output_key, str) and output_key.strip():
        return output_key.strip()
    return ""


def _generalize_committed_steps_from_blackboard(
    committed_steps: List[CommittedStep],
    blackboard_values: Dict[str, Any],
) -> List[CommittedStep]:
    url_refs = _collect_blackboard_url_refs(blackboard_values)
    if not url_refs:
        return committed_steps

    generalized: List[CommittedStep] = []
    for step in committed_steps:
        generalized.append(_generalize_committed_step_url(step, url_refs))
    return generalized


def _collect_blackboard_url_refs(values: Dict[str, Any]) -> List[tuple[str, str]]:
    refs: List[tuple[str, str]] = []

    def visit(value: Any, path: List[str]) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, path + [str(key)])
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, path + [str(index)])
            return
        if not isinstance(value, str):
            return
        normalized = value.strip()
        if not normalized.startswith(("http://", "https://")):
            return
        if not path:
            return
        refs.append((".".join(path), normalized.rstrip("/")))

    visit(values, [])
    refs.sort(key=lambda item: (_url_ref_rank(item[0]), -len(item[1]), item[0]))
    return refs


def _url_ref_rank(path: str) -> int:
    terminal = str(path or "").rsplit(".", 1)[-1].strip().lower()
    if terminal == "url":
        return 0
    if terminal in {"target_url", "repo_url", "href"}:
        return 1
    if terminal in {"path", "repo_path"}:
        return 2
    if terminal == "value":
        return 10
    return 5


def _generalize_committed_step_url(
    step: CommittedStep,
    url_refs: List[tuple[str, str]],
) -> CommittedStep:
    artifact_kind = _artifact_kind_value(step.artifact.get("kind"))
    if artifact_kind != "primitive_action":
        return step
    if str(step.artifact.get("action") or "") != "goto":
        return step

    current_template = str(
        step.artifact.get("target_url_template")
        or step.contract.target.url_template
        or ""
    ).strip()
    if not current_template.startswith(("http://", "https://")):
        return step

    replacement = _generalized_url_template(current_template, url_refs)
    if replacement is None or replacement == current_template:
        return step

    contract = step.contract.model_copy(deep=True)
    artifact = deepcopy(step.artifact)
    validation_evidence = deepcopy(step.validation_evidence)

    ref_path, templated_url = replacement
    contract.inputs.refs = list(dict.fromkeys([*contract.inputs.refs, ref_path]))
    contract.target.type = "url"
    contract.target.url_template = templated_url
    artifact["target_url_template"] = templated_url
    validation = list(contract.validation.must or [])
    if not any(rule.get("type") == "url_contains" for rule in validation):
        suffix = templated_url.split("}", 1)[-1]
        suffix_path = suffix.split("?", 1)[0]
        if suffix_path:
            validation.append({"type": "url_contains", "value": suffix_path})
    contract.validation.must = validation

    return CommittedStep(
        contract=contract,
        artifact=artifact,
        validation_evidence=validation_evidence,
    )


def _artifact_kind_value(kind: Any) -> str:
    value = getattr(kind, "value", kind)
    return str(value or "")


def _drop_redundant_runtime_ai_followup_navigations(
    committed_steps: List[CommittedStep],
) -> List[CommittedStep]:
    opened_refs: set[str] = set()
    filtered: List[CommittedStep] = []

    for step in committed_steps:
        if _is_redundant_exact_navigation(step, opened_refs):
            continue
        filtered.append(step)
        ref = _runtime_ai_action_output_ref(step)
        if ref:
            opened_refs.add(ref)

    return filtered


def _runtime_ai_action_output_ref(step: CommittedStep) -> str:
    if _artifact_kind_value(step.artifact.get("kind")) != "runtime_ai":
        return ""
    if not (bool(step.artifact.get("allow_side_effect")) or step.contract.runtime_policy.allow_side_effect):
        return ""
    output_key = step.contract.outputs.blackboard_key or step.artifact.get("result_key")
    if isinstance(output_key, str) and output_key.strip():
        return f"{output_key.strip()}.url"
    return ""


def _is_redundant_exact_navigation(step: CommittedStep, opened_refs: set[str]) -> bool:
    if _artifact_kind_value(step.artifact.get("kind")) != "primitive_action":
        return False
    if str(step.artifact.get("action") or "") != "goto":
        return False
    template = str(step.artifact.get("target_url_template") or step.contract.target.url_template or "").strip()
    if not template.startswith("{") or not template.endswith("}"):
        return False
    ref = template.strip("{} ").strip()
    return ref in opened_refs


def _generalized_url_template(
    absolute_url: str,
    url_refs: List[tuple[str, str]],
) -> tuple[str, str] | None:
    normalized_url = absolute_url.strip()
    if not normalized_url.startswith(("http://", "https://")):
        return None

    for ref_path, repo_url in url_refs:
        if not normalized_url.startswith(repo_url):
            continue
        suffix = normalized_url[len(repo_url):]
        if not suffix:
            return ref_path, f"{{{ref_path}}}"
        if not any(suffix.startswith(candidate) for candidate in _STABLE_SUBPAGE_SUFFIXES):
            continue
        return ref_path, f"{{{ref_path}}}{suffix}"
    return None


def build_contract_skill_files_from_session(
    session: Any,
    skill_name: str,
    description: str,
) -> Dict[str, str]:
    committed_steps = session_contract_committed_steps(session)
    return build_contract_skill_files(skill_name, description, committed_steps)


def has_contract_steps(session: Any) -> bool:
    return bool(session_contract_committed_steps(session))
