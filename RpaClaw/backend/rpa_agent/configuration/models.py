"""录制后 SKILL 配置草稿的严格 v0.1 契约。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..contracts.models import CoreTraceTimeline, SkillDefinition
from ..contracts.validators import validate_timeline_payload


Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9._-]*$")
]
BusinessVariableRef = Annotated[
    str,
    Field(min_length=1, max_length=256, pattern=r"^[^.\s]+(?:\.[^.\s]+)*$"),
]


class DraftModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
    )


class DraftSkill(DraftModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str, Field(min_length=1, max_length=2000)]


class DraftInputBase(DraftModel):
    ref: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    required: bool

    @model_validator(mode="before")
    @classmethod
    def default_cannot_be_explicit_null(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("default", object()) is None:
            raise ValueError("configuration.input_default_null")
        return value


class DraftStringInput(DraftInputBase):
    value_type: Literal["string"]
    default: str | None = None


class DraftNumberInput(DraftInputBase):
    value_type: Literal["number"]
    default: int | float | None = None


class DraftBooleanInput(DraftInputBase):
    value_type: Literal["boolean"]
    default: bool | None = None


DraftInputDefinition = Annotated[
    DraftStringInput | DraftNumberInput | DraftBooleanInput,
    Field(discriminator="value_type"),
]


class DraftSecret(DraftModel):
    ref: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    required: bool


class DraftAssetInput(DraftModel):
    ref: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    required: bool


class DraftOutput(DraftModel):
    name: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    variable_ref: BusinessVariableRef
    value_type: Literal["string", "number", "boolean", "json"]

    @model_validator(mode="after")
    def reject_numeric_path_segments(self) -> "DraftOutput":
        if any(part.isdigit() for part in self.variable_ref.split(".")):
            raise ValueError("configuration.output_variable_ref_numeric_segment")
        return self


class DraftAssetOutput(DraftModel):
    name: Identifier
    title: Annotated[str, Field(min_length=1, max_length=200)]
    asset_ref: Identifier


class BindingPromotion(DraftModel):
    trace_id: Identifier
    binding_name: Identifier
    to_kind: Literal["skill_input", "secret"]
    ref: Identifier


class SkillConfigurationDraft(DraftModel):
    schema_version: Literal["skill-configuration-draft/v0.1"]
    skill: DraftSkill
    inputs: list[DraftInputDefinition] = Field(default_factory=list)
    secrets: list[DraftSecret] = Field(default_factory=list)
    asset_inputs: list[DraftAssetInput] = Field(default_factory=list)
    outputs: list[DraftOutput] = Field(default_factory=list)
    asset_outputs: list[DraftAssetOutput] = Field(default_factory=list)
    binding_promotions: list[BindingPromotion] = Field(default_factory=list)
    stage_2_rules: Annotated[str, Field(min_length=1, max_length=20_000)] | None = None

    @model_validator(mode="after")
    def declarations_and_promotions_are_unambiguous(self) -> "SkillConfigurationDraft":
        _require_unique_key(self.inputs, "ref", "configuration.inputs_ref_unique")
        _require_unique_key(self.secrets, "ref", "configuration.secrets_ref_unique")
        _require_unique_key(
            self.asset_inputs, "ref", "configuration.asset_inputs_ref_unique"
        )
        _require_unique_key(self.outputs, "name", "configuration.outputs_name_unique")
        _require_unique_key(
            self.asset_outputs,
            "name",
            "configuration.asset_outputs_name_unique",
        )

        scalar_input_refs = {item.ref for item in self.inputs}
        secret_refs = {item.ref for item in self.secrets}
        if scalar_input_refs & secret_refs:
            raise ValueError("configuration.declaration_namespace_conflict")

        locations = [
            (promotion.trace_id, promotion.binding_name)
            for promotion in self.binding_promotions
        ]
        if len(locations) != len(set(locations)):
            raise ValueError("configuration.promotion_location_unique")

        for promotion in self.binding_promotions:
            expected_refs = (
                scalar_input_refs
                if promotion.to_kind == "skill_input"
                else secret_refs
            )
            if promotion.ref not in expected_refs:
                raise ValueError(
                    "configuration.promotion_declaration_mismatch:"
                    f"{promotion.trace_id}:{promotion.binding_name}:{promotion.to_kind}:"
                    f"{promotion.ref}"
                )
        return self


@dataclass(frozen=True, slots=True, init=False)
class ConfigurationResult:
    """隔离可变 Pydantic 容器的配置结果值对象。

    CoreTrace/SkillDefinition 顶层模型虽然是 frozen，但其 ``list`` 字段仍可
    被调用方原地修改。这里仅保存已验证契约的规范 JSON；每次读取 property
    都重新验证并返回独立对象，Compiler 获得的快照不会污染后续读取。
    """

    _timeline_json: str
    _skill_definition_json: str
    _external_asset_refs: tuple[str, ...]

    def __init__(
        self,
        *,
        timeline: CoreTraceTimeline,
        skill_definition: SkillDefinition,
        external_asset_refs: set[str] | tuple[str, ...] = (),
    ) -> None:
        refs = tuple(sorted(set(external_asset_refs)))
        timeline_payload = timeline.model_dump(
            mode="python", exclude_unset=True, warnings=False
        )
        definition_payload = skill_definition.model_dump(
            mode="python", exclude_unset=True, warnings=False
        )
        validated_timeline = validate_timeline_payload(
            timeline_payload,
            external_asset_refs=set(refs),
        )
        validated_definition = SkillDefinition.model_validate(definition_payload)
        object.__setattr__(
            self,
            "_timeline_json",
            validated_timeline.model_dump_json(exclude_unset=True, warnings=False),
        )
        object.__setattr__(
            self,
            "_skill_definition_json",
            validated_definition.model_dump_json(exclude_unset=True, warnings=False),
        )
        object.__setattr__(self, "_external_asset_refs", refs)

    @property
    def timeline(self) -> CoreTraceTimeline:
        return validate_timeline_payload(
            json.loads(self._timeline_json),
            external_asset_refs=set(self._external_asset_refs),
        )

    @property
    def skill_definition(self) -> SkillDefinition:
        return SkillDefinition.model_validate_json(self._skill_definition_json)

    def model_dump(
        self,
        *,
        mode: Literal["python", "json"] = "python",
        exclude_unset: bool = True,
    ) -> dict[str, object]:
        return {
            "timeline": self.timeline.model_dump(
                mode=mode,
                exclude_unset=exclude_unset,
                warnings=False,
            ),
            "skill_definition": self.skill_definition.model_dump(
                mode=mode,
                exclude_unset=exclude_unset,
                warnings=False,
            ),
        }

    def model_dump_json(
        self,
        *,
        exclude_unset: bool = True,
        indent: int | None = None,
    ) -> str:
        return json.dumps(
            self.model_dump(mode="json", exclude_unset=exclude_unset),
            ensure_ascii=False,
            indent=indent,
            separators=(",", ":") if indent is None else None,
        )


def _require_unique_key(items: list[object], key: str, error: str) -> None:
    values = [getattr(item, key) for item in items]
    if len(values) != len(set(values)):
        raise ValueError(error)


__all__ = [
    "BindingPromotion",
    "ConfigurationResult",
    "SkillConfigurationDraft",
]
