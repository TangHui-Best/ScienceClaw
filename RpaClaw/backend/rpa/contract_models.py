from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


SUPPORTED_PRIMITIVE_OPERATORS = frozenset({"navigate", "click", "fill", "press", "extract_text"})
SUPPORTED_DETERMINISTIC_OPERATORS = frozenset({"rank_collection_numeric_max", "extract_repeated_records"})
_TEMPLATE_REF = re.compile(r"\{+([^{}]+)\}+")


class ExecutionStrategy(str, Enum):
    PRIMITIVE_ACTION = "primitive_action"
    DETERMINISTIC_SCRIPT = "deterministic_script"
    RUNTIME_AI = "runtime_ai"


class ArtifactKind(str, Enum):
    PRIMITIVE_ACTION = "primitive_action"
    DETERMINISTIC_SCRIPT = "deterministic_script"
    RUNTIME_AI = "runtime_ai"


class FailureClass(str, Enum):
    CONTRACT_INVALID = "contract_invalid"
    SNAPSHOT_STALE = "snapshot_stale"
    ARTIFACT_FAILED = "artifact_failed"
    VALIDATION_FAILED = "validation_failed"


class StepSource(str, Enum):
    MANUAL = "manual"
    AI = "ai"


class PlannerStatus(str, Enum):
    NEXT_STEP = "next_step"
    DONE = "done"
    NEED_USER = "need_user"


class RuntimePolicy(BaseModel):
    requires_runtime_ai: bool = False
    runtime_ai_reason: str = ""
    allow_side_effect: bool = False
    side_effect_reason: str = ""


class ContractIntent(BaseModel):
    goal: str
    business_object: str = ""
    user_visible_summary: str = ""


class ContractInputs(BaseModel):
    refs: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)


class ContractTarget(BaseModel):
    type: str
    value: Optional[Any] = None
    url_template: Optional[str] = None
    collection: Optional[str] = None
    fields: List[str] = Field(default_factory=list)
    locator: Optional[Dict[str, Any]] = None


class ContractOperator(BaseModel):
    type: str
    execution_strategy: ExecutionStrategy
    selection_rule: Optional[Dict[str, Any]] = None


class ContractOutputs(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    blackboard_key: Optional[str] = None
    schema_value: Optional[Any] = Field(default=None, alias="schema")


class ContractValidation(BaseModel):
    must: List[Dict[str, Any]] = Field(default_factory=list)


class StepContract(BaseModel):
    id: str
    source: StepSource = StepSource.AI
    description: str = ""
    intent: ContractIntent
    inputs: ContractInputs = Field(default_factory=ContractInputs)
    target: ContractTarget
    operator: ContractOperator
    outputs: ContractOutputs = Field(default_factory=ContractOutputs)
    validation: ContractValidation = Field(default_factory=ContractValidation)
    runtime_policy: RuntimePolicy = Field(default_factory=RuntimePolicy)
    reserved: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self):
        template_refs = [
            match.group(1).strip()
            for match in _TEMPLATE_REF.finditer(str(self.target.url_template or ""))
            if match.group(1).strip()
        ]
        if template_refs and not self.inputs.refs:
            raise ValueError("templated target.url_template requires inputs.refs")
        if self.target.type == "blackboard_ref" and not self.inputs.refs:
            raise ValueError("blackboard_ref target requires inputs.refs")
        if self.operator.execution_strategy == ExecutionStrategy.PRIMITIVE_ACTION:
            if self.operator.type not in SUPPORTED_PRIMITIVE_OPERATORS:
                raise ValueError(
                    f"primitive_action strategy requires operator.type in {sorted(SUPPORTED_PRIMITIVE_OPERATORS)}"
                )
        if self.operator.execution_strategy == ExecutionStrategy.DETERMINISTIC_SCRIPT:
            if self.operator.type not in SUPPORTED_DETERMINISTIC_OPERATORS:
                raise ValueError(
                    "deterministic_script strategy requires operator.type in "
                    f"{sorted(SUPPORTED_DETERMINISTIC_OPERATORS)}"
                )
            selection_rule = dict(self.operator.selection_rule or {})
            if not self.outputs.blackboard_key:
                raise ValueError("deterministic_script strategy requires outputs.blackboard_key")
            if self.operator.type == "rank_collection_numeric_max":
                required_keys = ("collection_selector", "value_selector", "link_selector")
                missing_keys = [key for key in required_keys if not str(selection_rule.get(key) or "").strip()]
                if missing_keys:
                    raise ValueError(
                        "rank_collection_numeric_max requires selection_rule keys: "
                        + ", ".join(missing_keys)
                    )
            if self.operator.type == "extract_repeated_records":
                row_selector = str(selection_rule.get("row_selector") or "").strip()
                fields = selection_rule.get("fields")
                if not row_selector:
                    raise ValueError("extract_repeated_records requires selection_rule.row_selector")
                if not isinstance(fields, dict) or not fields:
                    raise ValueError("extract_repeated_records requires selection_rule.fields")
                for field_name, field_spec in fields.items():
                    if not isinstance(field_spec, dict):
                        raise ValueError(
                            "extract_repeated_records requires each selection_rule.fields entry to be an object "
                            f"with selector/attribute metadata; invalid field: {field_name}"
                        )
                    selector = str(field_spec.get("selector") or "").strip()
                    if not selector:
                        raise ValueError(
                            "extract_repeated_records requires each selection_rule.fields entry to include selector; "
                            f"invalid field: {field_name}"
                        )
        if self.operator.execution_strategy == ExecutionStrategy.RUNTIME_AI:
            if not self.runtime_policy.requires_runtime_ai:
                raise ValueError("runtime_ai strategy requires runtime_policy.requires_runtime_ai=true")
            if not self.runtime_policy.runtime_ai_reason.strip():
                raise ValueError("runtime_ai strategy requires runtime_ai_reason")
            if not self.outputs.blackboard_key or self.outputs.schema_value is None:
                raise ValueError("runtime_ai strategy requires structured outputs")
            if not _is_json_schema_shape(self.outputs.schema_value):
                raise ValueError("runtime_ai strategy requires outputs.schema to be a JSON schema with type object or array")
        return self


class PlannerEnvelope(BaseModel):
    status: PlannerStatus = PlannerStatus.NEXT_STEP
    current_step: Optional[StepContract] = None
    message: str = ""


def _is_json_schema_shape(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    schema_type = schema.get("type")
    return schema_type in {"object", "array"}
