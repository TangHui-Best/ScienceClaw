from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .contract_models import ArtifactKind, FailureClass, StepContract
from .locator_compiler import is_stable_locator_payload


@dataclass(frozen=True)
class ArtifactQualityResult:
    passed: bool
    failure_class: Optional[FailureClass] = None
    failure_type: Optional[str] = None
    message: str = ""
    repair_hint: str = ""


_FORBIDDEN_DETERMINISTIC_SCRIPT_TOKENS = (
    "get_llm_model",
    "execute_ai_instruction",
    "openai",
    "anthropic",
    "langchain",
    ".ainvoke(",
    ".invoke(",
)


def _fail(failure_type: str, message: str, repair_hint: str = "") -> ArtifactQualityResult:
    return ArtifactQualityResult(
        passed=False,
        failure_class=FailureClass.ARTIFACT_FAILED,
        failure_type=failure_type,
        message=message,
        repair_hint=repair_hint,
    )


def _artifact_kind(artifact: Dict[str, Any]) -> str:
    kind = artifact.get("kind")
    if isinstance(kind, ArtifactKind):
        return kind.value
    return str(kind or "")


def _validate_primitive_artifact(artifact: Dict[str, Any]) -> ArtifactQualityResult:
    locator = artifact.get("locator")
    if locator is not None and not is_stable_locator_payload(locator):
        return _fail(
            "unstable_locator",
            "Primitive action artifact uses an unstable locator.",
            "Compile a stable locator payload such as role/name, exact href, or nested scoped locators.",
        )
    return ArtifactQualityResult(passed=True)


def _validate_deterministic_script_artifact(artifact: Dict[str, Any]) -> ArtifactQualityResult:
    code = artifact.get("code")
    if not isinstance(code, str) or not code.strip():
        return _fail("missing_script", "Deterministic script artifact has no code.")

    try:
        ast.parse(code)
    except SyntaxError as exc:
        return _fail(
            "invalid_python",
            f"Deterministic script is not valid Python: {exc.msg}",
            "Regenerate the artifact as Python Playwright code without embedded malformed JavaScript.",
        )

    lowered = code.lower()
    for token in _FORBIDDEN_DETERMINISTIC_SCRIPT_TOKENS:
        if token.lower() in lowered:
            return _fail(
                "llm_call_in_deterministic_script",
                "Deterministic script artifact attempts to call LLM/runtime AI APIs.",
                "Move semantic judgment into a runtime_ai contract, or keep this script purely deterministic.",
            )

    return ArtifactQualityResult(passed=True)


def _validate_runtime_ai_artifact(
    contract: StepContract,
    artifact: Dict[str, Any],
) -> ArtifactQualityResult:
    output_schema = artifact.get("output_schema")
    contract_schema = contract.outputs.schema_value
    if output_schema is None or contract_schema is None or not contract.outputs.blackboard_key:
        return _fail(
            "missing_structured_runtime_ai_output",
            "Runtime AI artifact must declare structured JSON output written to blackboard.",
            "Provide output_schema and contract.outputs.blackboard_key before compiling runtime AI.",
        )
    return ArtifactQualityResult(passed=True)


def validate_artifact_quality(
    contract: StepContract,
    artifact: Dict[str, Any],
) -> ArtifactQualityResult:
    kind = _artifact_kind(artifact)

    if kind == ArtifactKind.PRIMITIVE_ACTION.value:
        return _validate_primitive_artifact(artifact)
    if kind == ArtifactKind.DETERMINISTIC_SCRIPT.value:
        return _validate_deterministic_script_artifact(artifact)
    if kind == ArtifactKind.RUNTIME_AI.value:
        return _validate_runtime_ai_artifact(contract, artifact)

    return _fail("unknown_artifact_kind", f"Unknown artifact kind: {kind}")
