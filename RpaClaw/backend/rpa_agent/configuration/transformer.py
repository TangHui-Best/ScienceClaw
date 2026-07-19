"""从录制态 Timeline 确定性生成配置态 Timeline 与 SkillDefinition。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from ..contracts import CoreTraceTimeline, SkillDefinition, validate_timeline_payload
from ..creation.readiness import BuildReadiness
from .models import ConfigurationResult, SkillConfigurationDraft


class ConfigurationError(ValueError):
    """配置转换的 fail-closed 边界错误。"""


def transform_configuration(
    timeline: CoreTraceTimeline | BuildReadiness | Mapping[str, Any],
    draft: SkillConfigurationDraft | Mapping[str, Any],
    *,
    skill_id: str,
    skill_version: str = "0.1.0",
) -> ConfigurationResult:
    """执行全量验证后一次性返回两个新的契约快照。

    ``skill_id`` 与 ``skill_version`` 是系统管理的版本元数据，不属于业务用户
    编辑的 ``SkillConfigurationDraft``。
    """

    # Pydantic's frozen models prevent attribute reassignment but their list
    # containers are not deeply frozen.  Always round-trip an instance into a
    # new validated snapshot so post-validation list mutation cannot bypass
    # uniqueness or declaration checks.
    draft_payload: object = (
        draft.model_dump(mode="python", exclude_unset=True, warnings=False)
        if isinstance(draft, SkillConfigurationDraft)
        else draft
    )
    parsed_draft = SkillConfigurationDraft.model_validate(draft_payload)
    external_asset_refs = {item.ref for item in parsed_draft.asset_inputs}
    source = _validated_source_timeline(
        timeline,
        external_asset_refs=external_asset_refs,
    )

    payload = source.model_dump(mode="python", exclude_unset=True, warnings=False)
    traces_by_id = {trace["trace_id"]: trace for trace in payload["traces"]}
    for promotion in parsed_draft.binding_promotions:
        trace = traces_by_id.get(promotion.trace_id)
        if trace is None:
            raise ConfigurationError(
                f"configuration.trace_not_found:{promotion.trace_id}"
            )
        binding = next(
            (
                item
                for item in trace["data_bindings"]
                if item["name"] == promotion.binding_name
            ),
            None,
        )
        if binding is None:
            raise ConfigurationError(
                "configuration.binding_not_found:"
                f"{promotion.trace_id}:{promotion.binding_name}"
            )
        replacement = _promoted_binding(binding, promotion.to_kind, promotion.ref)
        binding.clear()
        binding.update(replacement)

    try:
        configured_timeline = validate_timeline_payload(
            payload,
            external_asset_refs=external_asset_refs,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise ConfigurationError("configuration.timeline_invalid") from exc

    _validate_declaration_bindings(configured_timeline, parsed_draft)
    definition_payload = {
        "schema_version": "skill-definition/v0.1",
        "skill": {
            "id": skill_id,
            "name": parsed_draft.skill.name,
            "version": skill_version,
            "description": parsed_draft.skill.description,
        },
        "inputs": [
            item.model_dump(mode="python", exclude_unset=True)
            for item in parsed_draft.inputs
        ],
        "secrets": [item.model_dump(mode="python") for item in parsed_draft.secrets],
        "asset_inputs": [
            item.model_dump(mode="python") for item in parsed_draft.asset_inputs
        ],
        "outputs": [item.model_dump(mode="python") for item in parsed_draft.outputs],
        "asset_outputs": [
            item.model_dump(mode="python") for item in parsed_draft.asset_outputs
        ],
        "stage_2_rules": parsed_draft.stage_2_rules,
    }
    try:
        skill_definition = SkillDefinition.model_validate(definition_payload)
    except (ValidationError, ValueError, TypeError) as exc:
        raise ConfigurationError("configuration.skill_definition_invalid") from exc

    return ConfigurationResult(
        timeline=configured_timeline,
        skill_definition=skill_definition,
        external_asset_refs=external_asset_refs,
    )


def _validated_source_timeline(
    source: CoreTraceTimeline | BuildReadiness | Mapping[str, Any],
    *,
    external_asset_refs: set[str],
) -> CoreTraceTimeline:
    if isinstance(source, BuildReadiness):
        if not source.ready or source.timeline is None or source.issues:
            raise ConfigurationError("configuration.timeline_not_ready")
        candidate: object = source.timeline.model_dump(
            mode="python", exclude_unset=True, warnings=False
        )
    elif isinstance(source, CoreTraceTimeline):
        candidate = source.model_dump(
            mode="python", exclude_unset=True, warnings=False
        )
    elif isinstance(source, Mapping):
        candidate = source
    else:
        raise ConfigurationError("configuration.timeline_invalid:type")

    try:
        return validate_timeline_payload(
            candidate,
            external_asset_refs=external_asset_refs,
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise ConfigurationError("configuration.timeline_invalid") from exc


def _promoted_binding(
    binding: dict[str, Any], to_kind: str, ref: str
) -> dict[str, Any]:
    current_kind = binding["kind"]
    if current_kind == to_kind and binding.get("ref") == ref:
        expected_sensitive = to_kind == "secret" or bool(binding["sensitive"])
        if to_kind == "secret" and binding["sensitive"] is not True:
            raise ConfigurationError("configuration.binding_conflict:secret_sensitive")
        return {
            "name": binding["name"],
            "direction": binding["direction"],
            "kind": to_kind,
            "ref": ref,
            "sensitive": expected_sensitive,
        }
    if current_kind != "literal" or binding["direction"] != "input":
        raise ConfigurationError(
            "configuration.binding_conflict:"
            f"{binding['name']}:{current_kind}:{binding.get('ref', '')}"
        )
    return {
        "name": binding["name"],
        "direction": "input",
        "kind": to_kind,
        "ref": ref,
        "sensitive": True if to_kind == "secret" else bool(binding["sensitive"]),
    }


def _validate_declaration_bindings(
    timeline: CoreTraceTimeline,
    draft: SkillConfigurationDraft,
) -> None:
    declared_inputs = {item.ref for item in draft.inputs}
    declared_secrets = {item.ref for item in draft.secrets}
    declared_asset_inputs = {item.ref for item in draft.asset_inputs}
    declared_outputs = {item.variable_ref for item in draft.outputs}
    declared_asset_outputs = {item.asset_ref for item in draft.asset_outputs}

    used_inputs: set[str] = set()
    used_secrets: set[str] = set()
    consumed_assets: set[str] = set()
    produced_variables: set[str] = set()
    produced_assets: set[str] = set()
    for trace in timeline.traces:
        for binding in trace.data_bindings:
            if binding.kind == "skill_input":
                if binding.ref not in declared_inputs:
                    raise ConfigurationError(
                        f"configuration.binding_declaration_mismatch:skill_input:{binding.ref}"
                    )
                used_inputs.add(binding.ref)
            elif binding.kind == "secret":
                if binding.ref not in declared_secrets:
                    raise ConfigurationError(
                        f"configuration.binding_declaration_mismatch:secret:{binding.ref}"
                    )
                used_secrets.add(binding.ref)
            elif binding.kind == "data_asset":
                if binding.direction == "input":
                    consumed_assets.add(binding.ref)
                else:
                    produced_assets.add(binding.ref)
            elif binding.kind == "variable" and binding.direction == "output":
                produced_variables.add(binding.ref)

    _require_resolved(declared_inputs - used_inputs, "input")
    _require_resolved(declared_secrets - used_secrets, "secret")
    _require_resolved(
        {
            ref
            for ref in declared_asset_inputs
            if ref not in consumed_assets or ref in produced_assets
        },
        "asset_input",
    )
    _require_resolved(
        {
            ref
            for ref in declared_outputs
            if not any(ref == produced or ref.startswith(produced + ".") for produced in produced_variables)
        },
        "output",
    )
    _require_resolved(declared_asset_outputs - produced_assets, "asset_output")


def _require_resolved(refs: set[str], declaration_kind: str) -> None:
    if refs:
        raise ConfigurationError(
            "configuration.declaration_unresolved:"
            f"{declaration_kind}:{','.join(sorted(refs))}"
        )


__all__ = ["ConfigurationError", "transform_configuration"]
