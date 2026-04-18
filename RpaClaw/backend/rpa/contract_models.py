from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    def validate_runtime_ai_contract(self):
        if self.operator.execution_strategy == ExecutionStrategy.RUNTIME_AI:
            if not self.runtime_policy.requires_runtime_ai:
                raise ValueError("runtime_ai strategy requires runtime_policy.requires_runtime_ai=true")
            if not self.runtime_policy.runtime_ai_reason.strip():
                raise ValueError("runtime_ai strategy requires runtime_ai_reason")
            if not self.outputs.blackboard_key or self.outputs.schema_value is None:
                raise ValueError("runtime_ai strategy requires structured outputs")
        return self
