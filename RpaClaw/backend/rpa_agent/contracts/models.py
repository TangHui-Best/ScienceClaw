"""RPA Agent v0.1 的严格领域契约。

这些模型只表达正式 Schema 与创建态基线中已经存在的字段。跨 Trace 的
依赖闭合由 :mod:`rpa_agent.contracts.validators` 负责。
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    JsonValue,
    Tag,
    ValidationInfo,
    field_validator,
    model_validator,
)


Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9._-]*$")
]
BusinessVariableRef = Annotated[
    str,
    Field(
        min_length=1,
        max_length=256,
        pattern=r"^[^.\s]+(?:\.[^.\s]+)*$",
    ),
]
NonEmptyString = Annotated[str, Field(min_length=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


# --- CoreTrace locators and targets -------------------------------------------------


class RoleLocator(StrictModel):
    strategy: Literal["role"]
    role: NonEmptyString
    name: NonEmptyString | None = None
    exact: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def name_cannot_be_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("locator.name_null")
        return value


class SemanticValueLocator(StrictModel):
    strategy: Literal["test_id", "label", "placeholder", "text", "title", "alt_text"]
    value: NonEmptyString
    exact: bool = True


class SelectorLocator(StrictModel):
    strategy: Literal["css", "xpath"]
    value: NonEmptyString


LocatorSpec = Annotated[
    RoleLocator | SemanticValueLocator | SelectorLocator, Field(discriminator="strategy")
]


class FrameStep(StrictModel):
    name: NonEmptyString
    locators: Annotated[list[LocatorSpec], Field(min_length=1)]


class TargetPathStep(StrictModel):
    name: NonEmptyString
    locators: Annotated[list[LocatorSpec], Field(min_length=1)]
    index: Annotated[int, Field(ge=0)] | None = None
    filter_text: NonEmptyString | None = None
    filter_binding: Identifier | None = None

    @field_validator("index", "filter_text", "filter_binding", mode="before")
    @classmethod
    def optional_fields_cannot_be_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("target_path.optional_field_null")
        return value

    @model_validator(mode="after")
    def one_filter_source(self) -> "TargetPathStep":
        if self.filter_text is not None and self.filter_binding is not None:
            raise ValueError("target_path.filter_source_conflict")
        return self


class TargetSpec(StrictModel):
    name: NonEmptyString
    path: Annotated[list[TargetPathStep], Field(min_length=1)] | None = None
    locators: Annotated[list[LocatorSpec], Field(min_length=1)]
    index: Annotated[int, Field(ge=0)] | None = None

    @field_validator("path", "index", mode="before")
    @classmethod
    def optional_fields_cannot_be_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("target.optional_field_null")
        return value


class BrowserScope(StrictModel):
    page_ref: Identifier
    frame_path: list[FrameStep]


# --- CoreTrace actions --------------------------------------------------------------


class NavigateAction(StrictModel):
    kind: Literal["navigate"]
    mode: Literal["url", "back", "forward", "reload"]


class ClickAction(StrictModel):
    kind: Literal["click"]
    target: TargetSpec
    button: Literal["left", "right", "middle"] = "left"
    count: Literal[1, 2] = 1


class FillAction(StrictModel):
    kind: Literal["fill"]
    target: TargetSpec


class PressAction(StrictModel):
    kind: Literal["press"]
    target: TargetSpec


class SelectAction(StrictModel):
    kind: Literal["select"]
    target: TargetSpec


class SetCheckedAction(StrictModel):
    kind: Literal["set_checked"]
    target: TargetSpec
    checked: bool


class HoverAction(StrictModel):
    kind: Literal["hover"]
    target: TargetSpec


class UploadAction(StrictModel):
    kind: Literal["upload"]
    target: TargetSpec


class ScrollAction(StrictModel):
    kind: Literal["scroll"]
    target: TargetSpec | None = None
    direction: Literal["up", "down", "left", "right"]
    amount: Annotated[int, Field(ge=1)]
    unit: Literal["pixel", "viewport"]

    @field_validator("target", mode="before")
    @classmethod
    def target_cannot_be_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("action.target_null")
        return value


class ExtractColumn(StrictModel):
    name: Identifier
    header: NonEmptyString | None = None
    index: Annotated[int, Field(ge=0)] | None = None

    @field_validator("header", "index", mode="before")
    @classmethod
    def selector_cannot_be_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("extract.column_selector_null")
        return value

    @model_validator(mode="after")
    def exactly_one_selector(self) -> "ExtractColumn":
        if (self.header is None) == (self.index is None):
            raise ValueError("extract.column_selector_invalid")
        return self


class ExtractAction(StrictModel):
    kind: Literal["extract"]
    target: TargetSpec
    mode: Literal["text", "attribute", "table"]
    attribute: NonEmptyString | None = None
    columns: Annotated[list[ExtractColumn], Field(min_length=1)] | None = None

    @field_validator("attribute", "columns", mode="before")
    @classmethod
    def mode_fields_cannot_be_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("extract.mode_field_null")
        return value

    @model_validator(mode="after")
    def mode_fields(self) -> "ExtractAction":
        if self.mode == "text" and (self.attribute is not None or self.columns is not None):
            raise ValueError("extract.mode_fields_invalid")
        if self.mode == "attribute" and (self.attribute is None or self.columns is not None):
            raise ValueError("extract.mode_fields_invalid")
        if self.mode == "table" and (self.columns is None or self.attribute is not None):
            raise ValueError("extract.mode_fields_invalid")
        return self


class SwitchPageAction(StrictModel):
    kind: Literal["switch_page"]
    page_ref: Identifier


class ClosePageAction(StrictModel):
    kind: Literal["close_page"]


class AgentAction(StrictModel):
    kind: Literal["agent"]
    instruction: NonEmptyString
    target: TargetSpec | None = None

    @field_validator("target", mode="before")
    @classmethod
    def target_cannot_be_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("action.target_null")
        return value


ActionSpec = Annotated[
    NavigateAction
    | ClickAction
    | FillAction
    | PressAction
    | SelectAction
    | SetCheckedAction
    | HoverAction
    | UploadAction
    | ScrollAction
    | ExtractAction
    | SwitchPageAction
    | ClosePageAction
    | AgentAction,
    Field(discriminator="kind"),
]


# --- Bindings, effects and waits ----------------------------------------------------


class LiteralBinding(StrictModel):
    name: Identifier
    direction: Literal["input"]
    kind: Literal["literal"]
    value: str | int | float | bool | None
    sensitive: bool


class SkillInputBinding(StrictModel):
    name: Identifier
    direction: Literal["input"]
    kind: Literal["skill_input"]
    ref: Identifier
    sensitive: bool


class SecretBinding(StrictModel):
    name: Identifier
    direction: Literal["input"]
    kind: Literal["secret"]
    ref: Identifier
    sensitive: Literal[True]


class VariableBinding(StrictModel):
    name: Identifier
    direction: Literal["input", "output"]
    kind: Literal["variable"]
    ref: BusinessVariableRef
    sensitive: bool

    @model_validator(mode="after")
    def reject_numeric_path_segments(self) -> "VariableBinding":
        if any(part.isdigit() for part in self.ref.split(".")):
            raise ValueError("binding.variable_ref_numeric_segment")
        return self


class DataAssetBinding(StrictModel):
    name: Identifier
    direction: Literal["input", "output"]
    kind: Literal["data_asset"]
    ref: Identifier
    sensitive: bool


DataBinding = Annotated[
    LiteralBinding | SkillInputBinding | SecretBinding | VariableBinding | DataAssetBinding,
    Field(discriminator="kind"),
]


class NavigationEffect(StrictModel):
    kind: Literal["navigation"]


class NewPageEffect(StrictModel):
    kind: Literal["new_page"]
    page_ref: Identifier


class DownloadEffect(StrictModel):
    kind: Literal["download"]
    binding: Identifier


class DialogEffect(StrictModel):
    kind: Literal["dialog"]
    dialog_type: Literal["alert", "confirm", "prompt", "beforeunload"]
    response: Literal["accept", "dismiss"]
    input_binding: Identifier | None = None

    @field_validator("input_binding", mode="before")
    @classmethod
    def binding_cannot_be_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("effect.input_binding_null")
        return value

    @model_validator(mode="after")
    def prompt_binding_only(self) -> "DialogEffect":
        if self.dialog_type != "prompt" and self.input_binding is not None:
            raise ValueError("effect.dialog_input_not_prompt")
        return self


BrowserEffect = Annotated[
    NavigationEffect | NewPageEffect | DownloadEffect | DialogEffect,
    Field(discriminator="kind"),
]


class ElementStateWait(StrictModel):
    kind: Literal["element_state"]
    target: TargetSpec
    state: Literal["visible", "hidden", "enabled", "disabled", "checked", "unchecked"]


class ExpectedWait(StrictModel):
    operator: Literal["exact", "contains", "regex"]
    expected: str | None = None
    expected_binding: Identifier | None = None

    @field_validator("expected", "expected_binding", mode="before")
    @classmethod
    def expected_fields_cannot_be_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("wait.expected_null")
        return value

    @model_validator(mode="after")
    def exactly_one_expected(self) -> "ExpectedWait":
        if (self.expected is None) == (self.expected_binding is None):
            raise ValueError("wait.expected_source_invalid")
        return self


class ElementTextWait(ExpectedWait):
    kind: Literal["element_text"]
    target: TargetSpec


class ElementValueWait(ExpectedWait):
    kind: Literal["element_value"]
    target: TargetSpec


class UrlMatchesWait(ExpectedWait):
    kind: Literal["url_matches"]

    @model_validator(mode="after")
    def literal_expected_is_non_empty(self) -> "UrlMatchesWait":
        if self.expected == "":
            raise ValueError("wait.url_expected_empty")
        return self


WaitCondition = Annotated[
    ElementStateWait | ElementTextWait | ElementValueWait | UrlMatchesWait,
    Field(discriminator="kind"),
]


class CoreTrace(StrictModel):
    trace_id: Identifier
    sequence: Annotated[int, Field(ge=1)]
    scope: BrowserScope
    action: ActionSpec
    data_bindings: list[DataBinding]
    effects: list[BrowserEffect]
    wait_until: Annotated[list[WaitCondition], Field(min_length=1)] | None = None

    @field_validator("wait_until", mode="before")
    @classmethod
    def wait_cannot_be_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("trace.wait_until_null")
        return value


class CoreTraceTimeline(StrictModel):
    schema_version: Literal["core-trace/v0.1"]
    traces: list[CoreTrace]

    @model_validator(mode="after")
    def semantic_validation(self, info: ValidationInfo) -> "CoreTraceTimeline":
        from .validators import validate_timeline

        context = info.context if isinstance(info.context, dict) else {}
        validate_timeline(
            self,
            external_asset_refs=set(context.get("external_asset_refs", set())),
        )
        return self


# --- SkillDefinition and SkillManifest ---------------------------------------------


class SkillIdentity(StrictModel):
    id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=200)]
    version: Annotated[
        str,
        Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$"),
    ]
    description: Annotated[str, Field(min_length=1, max_length=2000)]


class InputBase(StrictModel):
    ref: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    required: bool

    @model_validator(mode="before")
    @classmethod
    def default_cannot_be_explicit_null(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("default", object()) is None:
            raise ValueError("skill.input_default_null")
        return value


class StringInput(InputBase):
    value_type: Literal["string"]
    default: str | None = None


class NumberInput(InputBase):
    value_type: Literal["number"]
    default: int | float | None = None


class BooleanInput(InputBase):
    value_type: Literal["boolean"]
    default: bool | None = None


InputDefinition = Annotated[StringInput | NumberInput | BooleanInput, Field(discriminator="value_type")]


class SecretDefinition(StrictModel):
    ref: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    required: bool


class AssetInputDefinition(StrictModel):
    ref: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    required: bool


class OutputDefinition(StrictModel):
    name: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    variable_ref: BusinessVariableRef
    value_type: Literal["string", "number", "boolean", "json"]


class AssetOutputDefinition(StrictModel):
    name: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    asset_ref: Identifier


class CoreTraceDraft(StrictModel):
    """创建期手工动作草稿；不会进入最终时间线或编译产物。"""

    draft_id: Identifier
    capture_state: Literal["capturing", "enriching", "ready", "invalid"]
    partial_scope: BrowserScope | None = None
    partial_action: ActionSpec | None = None
    data_bindings: list[DataBinding] = Field(default_factory=list)
    effects: list[BrowserEffect] = Field(default_factory=list)
    diagnostic_codes: list[NonEmptyString] = Field(default_factory=list)


class PageSummary(StrictModel):
    page_ref: Identifier
    url: str
    title: str


class BrowserScopeHint(StrictModel):
    page_ref: Identifier
    url: str | None = None
    title: str | None = None
    frame_path: list[FrameStep] = Field(default_factory=list)


class NavigationExpectedEffect(StrictModel):
    kind: Literal["navigation"]
    url_pattern: NonEmptyString | None = None


class NewPageExpectedEffect(StrictModel):
    kind: Literal["new_page"]
    page_ref: Identifier
    url_pattern: NonEmptyString | None = None


class DownloadExpectedEffect(StrictModel):
    kind: Literal["download"]
    asset_output_ref: Identifier


class DialogExpectedEffect(StrictModel):
    kind: Literal["dialog"]
    dialog_policy: Literal["accept", "dismiss"]


class FileChooserExpectedEffect(StrictModel):
    kind: Literal["file_chooser"]
    asset_input_ref: Identifier


class PageClosedExpectedEffect(StrictModel):
    kind: Literal["page_closed"]
    page_ref: Identifier


ExpectedEffect = Annotated[
    NavigationExpectedEffect
    | NewPageExpectedEffect
    | DownloadExpectedEffect
    | DialogExpectedEffect
    | FileChooserExpectedEffect
    | PageClosedExpectedEffect,
    Field(discriminator="kind"),
]


class AIExecutionAttempt(StrictModel):
    attempt_id: Identifier
    model_ref: NonEmptyString
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: NonEmptyString | None = None
    observation_trace_refs: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state_shape(self) -> "AIExecutionAttempt":
        if self.status == "queued":
            if self.started_at is not None or self.finished_at is not None or self.error_code is not None:
                raise ValueError("ai.attempt_queued_shape")
        elif self.status == "running":
            if self.started_at is None or self.finished_at is not None or self.error_code is not None:
                raise ValueError("ai.attempt_running_shape")
        elif self.status == "succeeded":
            if self.started_at is None or self.finished_at is None or self.error_code is not None:
                raise ValueError("ai.attempt_succeeded_shape")
        elif self.started_at is None or self.finished_at is None or self.error_code is None:
            raise ValueError("ai.attempt_terminal_shape")
        if len(self.observation_trace_refs) != len(set(self.observation_trace_refs)):
            raise ValueError("ai.attempt_observation_refs_unique")
        return self


class AIExecutionState(StrictModel):
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_summary: str | None = None
    error_code: NonEmptyString | None = None
    error_message: NonEmptyString | None = None
    selected_attempt_id: Identifier | None = None
    attempts: list[AIExecutionAttempt] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state_and_attempts(self) -> "AIExecutionState":
        attempts_by_id = {attempt.attempt_id: attempt for attempt in self.attempts}
        if len(attempts_by_id) != len(self.attempts):
            raise ValueError("ai.execution_attempt_ids_unique")
        if self.status == "queued":
            if self.started_at is not None or self.finished_at is not None:
                raise ValueError("ai.execution_queued_shape")
        elif self.status == "running":
            if self.started_at is None or self.finished_at is not None:
                raise ValueError("ai.execution_running_shape")
        elif self.status == "succeeded":
            if self.started_at is None or self.finished_at is None or self.error_code is not None:
                raise ValueError("ai.execution_succeeded_shape")
        elif (
            self.started_at is None
            or self.finished_at is None
            or self.error_code is None
            or self.error_message is None
        ):
            raise ValueError("ai.execution_terminal_shape")
        if self.selected_attempt_id is not None:
            selected = attempts_by_id.get(self.selected_attempt_id)
            if selected is None:
                raise ValueError("ai.execution_selected_attempt_missing")
            if selected.status != self.status:
                raise ValueError("ai.execution_selected_attempt_status_mismatch")
        return self


class AIInstructionStep(StrictModel):
    step_id: Identifier
    instruction: Annotated[str, Field(min_length=1, max_length=20_000)]
    created_at: datetime
    execution: AIExecutionState
    context_snapshot_ref: Identifier
    observation_trace_refs: list[Identifier] = Field(default_factory=list)
    orphan_effect_refs: list[Identifier] = Field(default_factory=list)
    declared_outputs: list[OutputDefinition] = Field(default_factory=list)
    expected_effects: list[ExpectedEffect] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_selected_attempt_projection(self) -> "AIInstructionStep":
        if len(self.observation_trace_refs) != len(set(self.observation_trace_refs)):
            raise ValueError("ai.observation_trace_refs_unique")
        if len(self.orphan_effect_refs) != len(set(self.orphan_effect_refs)):
            raise ValueError("ai.orphan_effect_refs_unique")
        if self.execution.selected_attempt_id is not None:
            selected = next(
                attempt
                for attempt in self.execution.attempts
                if attempt.attempt_id == self.execution.selected_attempt_id
            )
            if selected.observation_trace_refs != self.observation_trace_refs:
                raise ValueError("ai.execution_selected_attempt_refs_mismatch")
        return self


class FileChooserLifecycleEffect(StrictModel):
    kind: Literal["file_chooser"]
    page_ref: Identifier
    asset_input_ref: Identifier | None = None


class PageActivatedLifecycleEffect(StrictModel):
    kind: Literal["page_activated"]
    page_ref: Identifier


class PageClosedLifecycleEffect(StrictModel):
    kind: Literal["page_closed"]
    page_ref: Identifier


LifecycleEffect = Annotated[
    FileChooserLifecycleEffect | PageActivatedLifecycleEffect | PageClosedLifecycleEffect,
    Field(discriminator="kind"),
]
ObservedEffectPayload = Annotated[
    BrowserEffect | LifecycleEffect,
    Field(discriminator="kind"),
]


class ObservedEffectEnvelope(StrictModel):
    effect_id: Identifier
    session_id: Identifier
    generation: Identifier
    page_ref: Identifier
    occurred_at: datetime
    payload: ObservedEffectPayload
    candidate_item_ids: list[Identifier] = Field(default_factory=list)
    candidate_trace_ids: list[Identifier] = Field(default_factory=list)


RecordingTimelineItem = CoreTrace | AIInstructionStep


class RecordingTimeline(StrictModel):
    schema_version: Literal["recording-timeline/v0.1"]
    session_id: Identifier
    items: list[RecordingTimelineItem]
    observed_traces: dict[Identifier, CoreTrace] = Field(default_factory=dict)
    orphan_effects: dict[Identifier, ObservedEffectEnvelope] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references_and_ownership(self) -> "RecordingTimeline":
        item_ids: list[str] = []
        top_level_trace_ids: set[str] = set()
        for item in self.items:
            item_id = item.trace_id if isinstance(item, CoreTrace) else item.step_id
            item_ids.append(item_id)
            if isinstance(item, CoreTrace):
                top_level_trace_ids.add(item.trace_id)
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("timeline.item_ids_unique")
        observed_ids = set(self.observed_traces)
        if top_level_trace_ids & observed_ids:
            raise ValueError("timeline.trace_ownership_conflict")
        for key, trace in self.observed_traces.items():
            if key != trace.trace_id:
                raise ValueError("timeline.observed_trace_key_mismatch")
        for key, effect in self.orphan_effects.items():
            if key != effect.effect_id:
                raise ValueError("timeline.orphan_effect_key_mismatch")
            if effect.session_id != self.session_id:
                raise ValueError("timeline.orphan_effect_session_mismatch")
        orphan_ids = set(self.orphan_effects)
        for item in self.items:
            if not isinstance(item, AIInstructionStep):
                continue
            if any(ref not in observed_ids for ref in item.observation_trace_refs):
                raise ValueError("timeline.observation_trace_unresolved")
            if any(ref not in orphan_ids for ref in item.orphan_effect_refs):
                raise ValueError("timeline.orphan_effect_unresolved")
        return self


class ReplayAssessment(StrictModel):
    item_id: Identifier
    status: Literal[
        "deterministic_ready", "insufficient_evidence", "needs_confirmation"
    ]
    trace_refs: list[Identifier] = Field(default_factory=list)
    effect_refs: list[Identifier] = Field(default_factory=list)
    issue_codes: list[NonEmptyString] = Field(default_factory=list)
    explanation: NonEmptyString
    assessed_at: datetime
    assessor_version: NonEmptyString


class SkillDefinition(StrictModel):
    schema_version: Literal["skill-definition/v0.1"]
    skill: SkillIdentity
    inputs: list[InputDefinition]
    secrets: list[SecretDefinition]
    asset_inputs: list[AssetInputDefinition]
    outputs: list[OutputDefinition]
    asset_outputs: list[AssetOutputDefinition]
    stage_2_rules: Annotated[str, Field(min_length=1, max_length=20_000)] | None

    @model_validator(mode="after")
    def declarations_are_unique(self) -> "SkillDefinition":
        _validate_skill_declaration_uniqueness(self)
        return self


class RuntimeModelPolicy(StrictModel):
    mode: Literal["runtime_default", "configured_model"]
    model_ref: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_model_ref(self) -> "RuntimeModelPolicy":
        if self.mode == "configured_model" and self.model_ref is None:
            raise ValueError("runtime_model_policy.model_ref_required")
        if self.mode == "runtime_default" and self.model_ref is not None:
            raise ValueError("runtime_model_policy.model_ref_forbidden")
        return self


class ManualFallbackInstruction(StrictModel):
    trace_id: Identifier
    instruction: Annotated[str, Field(min_length=1, max_length=20_000)]
    scope_hint: BrowserScopeHint


class AgentStepConfiguration(StrictModel):
    step_id: Identifier
    output_refs: list[Identifier]
    expected_effects: list[ExpectedEffect]
    allowed_input_refs: list[Identifier]
    allowed_secret_refs: list[Identifier]
    allowed_asset_refs: list[Identifier]
    page_aliases: dict[Identifier, PageSummary]
    business_terms: list[Annotated[str, Field(min_length=1, max_length=256)]]
    model_policy: RuntimeModelPolicy
    timeout_seconds: Annotated[int, Field(ge=1, le=3600)]

    @model_validator(mode="after")
    def validate_unique_refs(self) -> "AgentStepConfiguration":
        for field_name in (
            "output_refs",
            "allowed_input_refs",
            "allowed_secret_refs",
            "allowed_asset_refs",
            "business_terms",
        ):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"agent_step.{field_name}_unique")
        for key, page in self.page_aliases.items():
            if key != page.page_ref:
                raise ValueError("agent_step.page_alias_key_mismatch")
        return self


class CompilationConfiguration(StrictModel):
    skill_definition: SkillDefinition
    manual_fallbacks: dict[Identifier, ManualFallbackInstruction]
    agent_steps: dict[Identifier, AgentStepConfiguration]

    @model_validator(mode="after")
    def validate_mapping_keys(self) -> "CompilationConfiguration":
        for key, fallback in self.manual_fallbacks.items():
            if key != fallback.trace_id:
                raise ValueError("configuration.manual_fallback_key_mismatch")
        for key, step in self.agent_steps.items():
            if key != step.step_id:
                raise ValueError("configuration.agent_step_key_mismatch")
        return self


class PlaywrightSegment(StrictModel):
    mode: Literal["playwright"]
    step_id: Identifier
    ordinal: Annotated[int, Field(ge=1)]
    trace_refs: Annotated[list[Identifier], Field(min_length=1)]
    operations: Annotated[list[CoreTrace], Field(min_length=1)]
    expected_outputs: list[OutputDefinition]
    expected_effects: list[ExpectedEffect]

    @model_validator(mode="after")
    def validate_operation_refs(self) -> "PlaywrightSegment":
        operation_refs = [operation.trace_id for operation in self.operations]
        if operation_refs != self.trace_refs:
            raise ValueError("compiled.playwright_trace_refs_mismatch")
        return self


class AgentSegment(StrictModel):
    mode: Literal["agent"]
    step_id: Identifier
    ordinal: Annotated[int, Field(ge=1)]
    instruction: Annotated[str, Field(min_length=1, max_length=20_000)]
    scope_hint: BrowserScopeHint
    output_refs: list[Identifier]
    expected_effects: list[ExpectedEffect]
    allowed_input_refs: list[Identifier]
    allowed_secret_refs: list[Identifier]
    allowed_asset_refs: list[Identifier]
    page_aliases: dict[Identifier, PageSummary]
    business_terms: list[Annotated[str, Field(min_length=1, max_length=256)]]
    model_policy: RuntimeModelPolicy
    timeout_seconds: Annotated[int, Field(ge=1, le=3600)]


CompiledStep = Annotated[PlaywrightSegment | AgentSegment, Field(discriminator="mode")]


class CompiledSkillPlan(StrictModel):
    schema_version: Literal["compiled-skill/v0.1"]
    skill_id: Identifier
    source_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    steps: list[CompiledStep]

    @model_validator(mode="after")
    def validate_ordinals(self) -> "CompiledSkillPlan":
        expected = list(range(1, len(self.steps) + 1))
        actual = [step.ordinal for step in self.steps]
        if actual != expected:
            raise ValueError("compiled.step_ordinals_not_contiguous")
        return self


class RuntimeContract(StrictModel):
    api_version: Literal["rpa-agent-runtime/0.1"]
    requirements: Annotated[
        list[Literal["playwright", "agent", "data_asset", "download", "upload"]],
        Field(min_length=1),
    ]

    @model_validator(mode="after")
    def requirements_are_unique(self) -> "RuntimeContract":
        if len(self.requirements) != len(set(self.requirements)):
            raise ValueError("runtime.requirements_unique")
        return self


class SourceContract(StrictModel):
    core_trace_schema_version: Literal["core-trace/v0.1"]
    trace_count: Annotated[int, Field(ge=0)]
    timeline_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    compiler_version: Annotated[str, Field(min_length=1, max_length=128)]


class CompilationSourceContract(StrictModel):
    schema_version: Literal["recording-compilation-source/v0.1"]
    recording_timeline_schema_version: Literal["recording-timeline/v0.1"]
    compiler_version: Annotated[str, Field(min_length=1, max_length=128)]
    source_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    item_count: Annotated[int, Field(ge=0)]
    playwright_segment_count: Annotated[int, Field(ge=0)]
    agent_segment_count: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def segment_counts_cover_items(self) -> "CompilationSourceContract":
        if self.playwright_segment_count + self.agent_segment_count != self.item_count:
            raise ValueError("manifest.segment_counts_mismatch")
        return self


class SkillManifest(StrictModel):
    schema_version: Literal["skill-manifest/v0.1", "skill-manifest/v0.2"]
    skill: SkillIdentity
    entrypoint: Annotated[
        str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
    ]
    runtime: RuntimeContract
    inputs: list[InputDefinition]
    secrets: list[SecretDefinition]
    asset_inputs: list[AssetInputDefinition]
    outputs: list[OutputDefinition]
    asset_outputs: list[AssetOutputDefinition]
    source: SourceContract | CompilationSourceContract
    agent_policies: dict[Identifier, AgentStepConfiguration] | None = None

    @model_validator(mode="after")
    def declarations_are_unique(self) -> "SkillManifest":
        _validate_skill_declaration_uniqueness(self)
        return self

    @model_validator(mode="after")
    def source_matches_manifest_version(self) -> "SkillManifest":
        if self.schema_version == "skill-manifest/v0.1":
            if not isinstance(self.source, SourceContract) or self.agent_policies:
                raise ValueError("manifest.v01_source_invalid")
        elif (
            not isinstance(self.source, CompilationSourceContract)
            or self.agent_policies is None
        ):
            raise ValueError("manifest.v02_source_invalid")
        return self


def _validate_skill_declaration_uniqueness(contract: object) -> None:
    for field_name, key_name in (
        ("inputs", "ref"), ("secrets", "ref"), ("asset_inputs", "ref"),
        ("outputs", "name"), ("asset_outputs", "name"),
    ):
        values = getattr(contract, field_name)
        full_items = [item.model_dump_json() for item in values]
        if len(full_items) != len(set(full_items)):
            raise ValueError(f"skill.{field_name}_unique_items")
        keys = [getattr(item, key_name) for item in values]
        if len(keys) != len(set(keys)):
            raise ValueError(f"skill.{field_name}_{key_name}_unique")


# --- Creation-state contracts -------------------------------------------------------


class ScopeHint(StrictModel):
    page_ref: Identifier | None
    frame_path: list[FrameStep] | None


class TargetHint(StrictModel):
    name: NonEmptyString | None
    locators: list[LocatorSpec]
    path: Annotated[list[TargetPathStep], Field(min_length=1)] | None = None
    index: Annotated[int, Field(ge=0)] | None = None

    @field_validator("path", "index", mode="before")
    @classmethod
    def optional_fields_cannot_be_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("target_hint.optional_field_null")
        return value


class NavigateHint(StrictModel):
    kind: Literal["navigate"]
    mode: Literal["url", "back", "forward", "reload"]


class ClickHint(StrictModel):
    kind: Literal["click"]
    target_hint: TargetHint | None
    button: Literal["left", "right", "middle"] = "left"
    count: Literal[1, 2] = 1


class TargetRequiredHint(StrictModel):
    target_hint: TargetHint | None


class FillHint(TargetRequiredHint):
    kind: Literal["fill"]


class PressHint(StrictModel):
    kind: Literal["press"]
    target_hint: TargetHint | None = None


class SelectHint(TargetRequiredHint):
    kind: Literal["select"]


class SetCheckedHint(TargetRequiredHint):
    kind: Literal["set_checked"]
    checked: bool


class HoverHint(TargetRequiredHint):
    kind: Literal["hover"]


class UploadHint(TargetRequiredHint):
    kind: Literal["upload"]


class ScrollHint(StrictModel):
    kind: Literal["scroll"]
    target_hint: TargetHint | None = None
    direction: Literal["up", "down", "left", "right"]
    amount: Annotated[int, Field(ge=1)]
    unit: Literal["pixel", "viewport"]


class ExtractTextHint(TargetRequiredHint):
    kind: Literal["extract"]
    mode: Literal["text"]


class ExtractAttributeHint(TargetRequiredHint):
    kind: Literal["extract"]
    mode: Literal["attribute"]
    attribute: NonEmptyString


class ExtractTableHint(TargetRequiredHint):
    kind: Literal["extract"]
    mode: Literal["table"]
    columns: Annotated[list[ExtractColumn], Field(min_length=1)]


class SwitchPageHint(StrictModel):
    kind: Literal["switch_page"]
    page_ref: Identifier | None


class ClosePageHint(StrictModel):
    kind: Literal["close_page"]


class AgentHint(StrictModel):
    kind: Literal["agent"]
    instruction: NonEmptyString
    target_hint: TargetHint | None = None


class UnsupportedHint(StrictModel):
    kind: Literal["unsupported"]
    unsupported_name: NonEmptyString


def _action_hint_discriminator(value: object) -> str | None:
    kind = value.get("kind") if isinstance(value, dict) else getattr(value, "kind", None)
    if kind == "extract":
        mode = value.get("mode") if isinstance(value, dict) else getattr(value, "mode", None)
        return f"extract:{mode}"
    return kind


ActionHint = Annotated[
    Annotated[NavigateHint, Tag("navigate")]
    | Annotated[ClickHint, Tag("click")]
    | Annotated[FillHint, Tag("fill")]
    | Annotated[PressHint, Tag("press")]
    | Annotated[SelectHint, Tag("select")]
    | Annotated[SetCheckedHint, Tag("set_checked")]
    | Annotated[HoverHint, Tag("hover")]
    | Annotated[UploadHint, Tag("upload")]
    | Annotated[ScrollHint, Tag("scroll")]
    | Annotated[ExtractTextHint, Tag("extract:text")]
    | Annotated[ExtractAttributeHint, Tag("extract:attribute")]
    | Annotated[ExtractTableHint, Tag("extract:table")]
    | Annotated[SwitchPageHint, Tag("switch_page")]
    | Annotated[ClosePageHint, Tag("close_page")]
    | Annotated[AgentHint, Tag("agent")]
    | Annotated[UnsupportedHint, Tag("unsupported")],
    Discriminator(_action_hint_discriminator),
]


class BindingHint(StrictModel):
    name: Identifier
    direction: Literal["input", "output"]
    kind_hint: Literal["literal", "skill_input", "secret", "variable", "data_asset"] | None
    value: JsonValue | None = None
    ref_hint: str | None = None
    sensitive: bool

    @field_validator("ref_hint", mode="before")
    @classmethod
    def ref_hint_cannot_be_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("binding_hint.ref_null")
        return value

    @model_validator(mode="after")
    def value_or_ref(self) -> "BindingHint":
        if "value" in self.model_fields_set and "ref_hint" in self.model_fields_set:
            raise ValueError("binding_hint.value_ref_conflict")
        if self.ref_hint is not None:
            max_length = 256 if self.kind_hint == "variable" else 128
            if len(self.ref_hint) > max_length:
                raise ValueError("binding_hint.ref_invalid")
            pattern = (
                r"^[^.\s]+(?:\.[^.\s]+)*$"
                if self.kind_hint == "variable"
                else r"^[A-Za-z][A-Za-z0-9._-]*$"
            )
            if re.fullmatch(pattern, self.ref_hint) is None:
                raise ValueError("binding_hint.ref_invalid")
            if self.kind_hint == "variable" and any(
                part.isdigit() for part in self.ref_hint.split(".")
            ):
                raise ValueError("binding_hint.ref_invalid")
        return self


class ExecutionError(StrictModel):
    code: NonEmptyString | None
    message: NonEmptyString


class RunningExecution(StrictModel):
    status: Literal["running"]
    started_at: datetime
    ended_at: None
    output: JsonValue | None = None
    error: None


class SucceededExecution(StrictModel):
    status: Literal["succeeded"]
    started_at: datetime
    ended_at: datetime
    output: JsonValue | None = None
    error: None


class FailedExecution(StrictModel):
    status: Literal["failed"]
    started_at: datetime
    ended_at: datetime
    output: JsonValue | None = None
    error: ExecutionError


class CancelledExecution(StrictModel):
    status: Literal["cancelled"]
    started_at: datetime
    ended_at: datetime
    output: JsonValue | None = None
    error: ExecutionError | None


ExecutionState = Annotated[
    RunningExecution | SucceededExecution | FailedExecution | CancelledExecution,
    Field(discriminator="status"),
]


class TraceCandidate(StrictModel):
    candidate_id: Identifier
    ordinal: Annotated[int, Field(ge=1)]
    origin: Literal["human", "agent"]
    scope_hint: ScopeHint
    action_hint: ActionHint
    binding_hints: list[BindingHint]
    execution: ExecutionState


class RuntimeScope(StrictModel):
    page_runtime_ref: Identifier


class NavigationFactDetail(StrictModel):
    frame_runtime_ref: Identifier
    is_main_frame: bool
    url: NonEmptyString


class NewPageFactDetail(StrictModel):
    initial_url: NonEmptyString


class DownloadFactDetail(StrictModel):
    download_ref: Identifier
    suggested_filename: NonEmptyString | None
    status: Literal["completed", "failed"]
    failure_reason: NonEmptyString | None

    @model_validator(mode="after")
    def status_matches_failure_reason(self) -> "DownloadFactDetail":
        if self.status == "completed" and self.failure_reason is not None:
            raise ValueError("download.completed_has_failure_reason")
        if self.status == "failed" and not self.failure_reason:
            raise ValueError("download.failed_missing_failure_reason")
        return self


class DialogFactDetail(StrictModel):
    dialog_type: Literal["alert", "confirm", "prompt", "beforeunload"]
    response: Literal["accept", "dismiss"]
    prompt_value: str | None

    @model_validator(mode="after")
    def prompt_value_only_for_accepted_prompt(self) -> "DialogFactDetail":
        if (self.dialog_type, self.response) != ("prompt", "accept") and self.prompt_value is not None:
            raise ValueError("dialog.prompt_value_not_allowed")
        return self


class BrowserFactBase(StrictModel):
    fact_id: Identifier
    observed_order: Annotated[int, Field(ge=1)]
    candidate_id: Identifier | None
    observed_at: datetime
    runtime_scope: RuntimeScope


class NavigationFact(BrowserFactBase):
    kind: Literal["navigation"]
    detail: NavigationFactDetail


class NewPageFact(BrowserFactBase):
    kind: Literal["new_page"]
    detail: NewPageFactDetail


class DownloadFact(BrowserFactBase):
    kind: Literal["download"]
    detail: DownloadFactDetail


class DialogFact(BrowserFactBase):
    kind: Literal["dialog"]
    detail: DialogFactDetail


class PageActivatedFact(BrowserFactBase):
    kind: Literal["page_activated"]


class PageClosedFact(BrowserFactBase):
    kind: Literal["page_closed"]


BrowserFact = Annotated[
    NavigationFact | NewPageFact | DownloadFact | DialogFact | PageActivatedFact | PageClosedFact,
    Field(discriminator="kind"),
]


class Diagnostic(StrictModel):
    code: Literal[
        "execution_failed", "execution_cancelled", "settlement_timeout", "scope_unresolved",
        "action_not_replayable", "target_unresolved", "binding_unresolved",
        "browser_fact_unresolved", "asset_unavailable",
    ]
    message: NonEmptyString


class AcceptedSettlement(StrictModel):
    candidate_id: Identifier
    status: Literal["accepted"]
    core_trace: CoreTrace


class RejectedSettlement(StrictModel):
    candidate_id: Identifier
    status: Literal["rejected"]
    diagnostic: Diagnostic


SettlementResult = Annotated[
    AcceptedSettlement | RejectedSettlement, Field(discriminator="status")
]
