from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .blackboard import Blackboard
from .contract_executor import ExecutionResult
from .contract_models import ArtifactKind, FailureClass, StepContract


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    failure_class: Optional[FailureClass] = None
    failure_type: Optional[str] = None
    message: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)


_GENERIC_CHROME_TEXT = {
    "navigation menu",
    "skip to content",
    "menu",
    "search",
}


def validate_recording_step(
    contract: StepContract,
    artifact: Dict[str, Any],
    execution_result: ExecutionResult,
    blackboard: Blackboard,
    snapshot: Any,
) -> ValidationResult:
    if not execution_result.success:
        return _fail("execution_failed", "Step execution did not succeed.")

    for rule in contract.validation.must:
        rule_type = rule.get("type")
        if rule_type == "min_records":
            value = _read_value(rule.get("key") or contract.outputs.blackboard_key, blackboard, execution_result)
            min_count = int(rule.get("count") or 1)
            if not isinstance(value, list) or len(value) < min_count:
                return _fail("min_records", f"Expected at least {min_count} records.")

        elif rule_type == "not_generic_chrome_text":
            value = _read_value(rule.get("key") or contract.outputs.blackboard_key, blackboard, execution_result)
            if isinstance(value, str) and value.strip().lower() in _GENERIC_CHROME_TEXT:
                return _fail("not_generic_chrome_text", "Extracted text is generic page chrome.")

        elif rule_type == "url_contains":
            expected = str(rule.get("value") or "")
            observed_url = _observed_url(execution_result, snapshot)
            if expected and expected not in observed_url:
                return _fail("url_contains", f"Observed URL does not contain {expected!r}.")

        elif rule_type == "blackboard_key":
            key = str(rule.get("key") or contract.outputs.blackboard_key or "")
            try:
                blackboard.resolve_ref(key)
            except KeyError:
                return _fail("blackboard_key", f"Missing blackboard key: {key}")

    return ValidationResult(
        passed=True,
        evidence={
            "contract_id": contract.id,
            "artifact_kind": _artifact_kind(artifact),
            "execution_evidence": dict(execution_result.evidence),
        },
    )


def validate_replay_export(
    committed_steps: List[Dict[str, Any]],
    exported_manifest: Dict[str, Any],
) -> ValidationResult:
    manifest_steps = {
        step.get("contract_id"): step
        for step in exported_manifest.get("steps", [])
        if isinstance(step, dict)
    }
    blackboard_schema = exported_manifest.get("blackboard_schema") or {}

    for committed in committed_steps:
        contract = committed.get("contract")
        if not isinstance(contract, StepContract):
            return _fail("invalid_committed_step", "Committed step is missing a StepContract.")

        manifest_step = manifest_steps.get(contract.id)
        if not manifest_step:
            return _fail("missing_export_step", f"Export manifest is missing step {contract.id}.")

        for ref in contract.inputs.refs:
            if not _ref_is_exported(ref, blackboard_schema):
                return _fail("missing_input_ref", f"Export manifest is missing input ref {ref}.")

        artifact = manifest_step.get("artifact") or {}
        if _is_description_only_artifact(artifact):
            return _fail(
                "description_only_artifact",
                f"Exported step {contract.id} has no executable committed artifact.",
            )

    return ValidationResult(passed=True, evidence={"step_count": len(committed_steps)})


def _fail(failure_type: str, message: str) -> ValidationResult:
    return ValidationResult(
        passed=False,
        failure_class=FailureClass.VALIDATION_FAILED,
        failure_type=failure_type,
        message=message,
    )


def _read_value(key: Any, blackboard: Blackboard, execution_result: ExecutionResult) -> Any:
    if isinstance(key, str) and key.strip():
        try:
            return blackboard.resolve_ref(key)
        except KeyError:
            return None
    return execution_result.output


def _observed_url(execution_result: ExecutionResult, snapshot: Any) -> str:
    url = execution_result.evidence.get("url")
    if isinstance(url, str):
        return url
    if isinstance(snapshot, dict):
        return str(snapshot.get("url") or "")
    return str(getattr(snapshot, "url", "") or "")


def _artifact_kind(artifact: Dict[str, Any]) -> str:
    kind = artifact.get("kind")
    if isinstance(kind, ArtifactKind):
        return kind.value
    return str(kind or "")


def _ref_is_exported(ref: str, blackboard_schema: Dict[str, Any]) -> bool:
    if not isinstance(ref, str) or not ref.strip():
        return False
    if ref.startswith("params."):
        return True
    root = ref.split(".", 1)[0]
    return root in blackboard_schema


def _is_description_only_artifact(artifact: Dict[str, Any]) -> bool:
    kind = _artifact_kind(artifact)
    if kind == ArtifactKind.PRIMITIVE_ACTION.value:
        return not artifact.get("action")
    if kind == ArtifactKind.DETERMINISTIC_SCRIPT.value:
        return not artifact.get("code")
    if kind == ArtifactKind.RUNTIME_AI.value:
        return not artifact.get("prompt") or not artifact.get("output_schema")
    return True
