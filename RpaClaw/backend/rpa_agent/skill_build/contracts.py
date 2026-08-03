"""Versioned S3 contracts; none of these models deserialize legacy skill assets."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..contracts.identity import RPA_AGENT_NEXT_NAMESPACE
from ..contracts.models import CoreTrace, Identifier, StrictModel


class SkillBuildInput(StrictModel):
    ref: Identifier
    title: str = Field(min_length=1, max_length=200)
    value_type: Literal["string", "number", "boolean"]
    required: bool


class SkillBuildOutput(StrictModel):
    ref: Identifier
    title: str = Field(min_length=1, max_length=200)


class RuntimeLimits(StrictModel):
    timeout_seconds: int = Field(ge=1, le=3_600)
    allow_network: bool = False


class OutcomeAssertion(StrictModel):
    """A user-declared acceptance condition, never inferred from BrowserEffect."""

    assertion_id: Identifier
    kind: Literal["url_matches", "output_present"]
    expected: str | None = Field(default=None, min_length=1, max_length=2_000)
    output_ref: Identifier | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> "OutcomeAssertion":
        if self.kind == "url_matches":
            if self.expected is None or self.output_ref is not None:
                raise ValueError("next_skill_assertion.url_matches_shape")
        elif self.output_ref is None or self.expected is not None:
            raise ValueError("next_skill_assertion.output_present_shape")
        return self


class SkillBuildConfig(StrictModel):
    """User-owned configuration for one new vNext Skill."""

    schema_namespace: Literal[RPA_AGENT_NEXT_NAMESPACE]
    config_id: Identifier
    skill_id: Identifier
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2_000)
    inputs: list[SkillBuildInput] = Field(default_factory=list)
    outputs: list[SkillBuildOutput] = Field(default_factory=list)
    browser_use_model_ref: str = Field(min_length=1, max_length=256)
    runtime_limits: RuntimeLimits
    outcome_assertions: list[OutcomeAssertion] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_unique_declarations(self) -> "SkillBuildConfig":
        for field_name, key_name in (
            ("inputs", "ref"),
            ("outputs", "ref"),
            ("outcome_assertions", "assertion_id"),
        ):
            values = [getattr(item, key_name) for item in getattr(self, field_name)]
            if len(values) != len(set(values)):
                raise ValueError(f"next_skill_build.{field_name}_unique")
        output_refs = {item.ref for item in self.outputs}
        for assertion in self.outcome_assertions:
            if assertion.kind == "output_present" and assertion.output_ref not in output_refs:
                raise ValueError("next_skill_build.assertion_output_undeclared")
        return self


class CompileDecision(StrictModel):
    trace_id: Identifier
    mode: Literal["playwright", "review_required"]
    reason_codes: list[str] = Field(default_factory=list)


class CompiledPlaywrightStep(StrictModel):
    mode: Literal["playwright"]
    step_id: Identifier
    ordinal: int = Field(ge=1)
    trace: CoreTrace


class CompiledBrowserUseStep(StrictModel):
    mode: Literal["browser_use"]
    step_id: Identifier
    ordinal: int = Field(ge=1)
    instruction: str = Field(min_length=1, max_length=20_000)
    model_ref: str = Field(min_length=1, max_length=256)


CompiledSkillStep = CompiledPlaywrightStep | CompiledBrowserUseStep


class CompiledSkill(StrictModel):
    schema_namespace: Literal[RPA_AGENT_NEXT_NAMESPACE]
    skill_id: Identifier
    config_id: Identifier
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    compiler_version: Literal["rpa-agent-next-s3/0.1"]
    steps: list[CompiledSkillStep]
    config: SkillBuildConfig

    @model_validator(mode="after")
    def _validate_step_order(self) -> "CompiledSkill":
        expected = list(range(1, len(self.steps) + 1))
        actual = [step.ordinal for step in self.steps]
        if actual != expected:
            raise ValueError("next_compiled_skill.step_ordinals_not_contiguous")
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("next_compiled_skill.step_ids_unique")
        return self
