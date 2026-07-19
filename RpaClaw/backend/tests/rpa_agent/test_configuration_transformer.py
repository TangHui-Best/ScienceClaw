from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from rpa_agent.configuration import (
    BindingPromotion,
    ConfigurationError,
    SkillConfigurationDraft,
    transform_configuration,
)
from rpa_agent.contracts import CoreTraceTimeline
from rpa_agent.creation import BuildReadiness, ReadinessCode, ReadinessIssue


TARGET = {
    "name": "输入框",
    "locators": [{"strategy": "label", "value": "输入框", "exact": True}],
}


def _fill(trace_id: str, sequence: int, value: str, *, binding_name: str = "value") -> dict:
    return {
        "trace_id": trace_id,
        "sequence": sequence,
        "scope": {"page_ref": "main", "frame_path": []},
        "action": {"kind": "fill", "target": TARGET},
        "data_bindings": [
            {
                "name": binding_name,
                "direction": "input",
                "kind": "literal",
                "value": value,
                "sensitive": False,
            }
        ],
        "effects": [],
    }


def _timeline(*traces: dict) -> dict:
    return {"schema_version": "core-trace/v0.1", "traces": list(traces)}


def _draft(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "schema_version": "skill-configuration-draft/v0.1",
        "skill": {"name": "采购订单验收", "description": "跨系统登记采购订单"},
        "inputs": [],
        "secrets": [],
        "asset_inputs": [],
        "outputs": [],
        "asset_outputs": [],
        "binding_promotions": [],
    }
    payload.update(overrides)
    return payload


def _transform(timeline: object, draft: object):
    return transform_configuration(
        timeline,
        draft,
        skill_id="purchase-order-acceptance",
        skill_version="0.1.0",
    )


def test_same_recorded_value_promotes_to_two_distinct_inputs_by_stable_location() -> None:
    source = _timeline(_fill("trace_a", 10, "same"), _fill("trace_b", 20, "same"))
    draft = _draft(
        inputs=[
            {"ref": "query.first", "title": "第一个值", "value_type": "string", "required": True},
            {"ref": "query.second", "title": "第二个值", "value_type": "string", "required": True},
        ],
        binding_promotions=[
            {"trace_id": "trace_a", "binding_name": "value", "to_kind": "skill_input", "ref": "query.first"},
            {"trace_id": "trace_b", "binding_name": "value", "to_kind": "skill_input", "ref": "query.second"},
        ],
    )

    result = _transform(source, draft)

    bindings = [trace.data_bindings[0] for trace in result.timeline.traces]
    assert [(item.kind, item.ref) for item in bindings] == [
        ("skill_input", "query.first"),
        ("skill_input", "query.second"),
    ]
    assert all("same" not in item.model_dump_json() for item in bindings)


def test_multiple_bindings_may_share_one_declared_input_ref() -> None:
    source = _timeline(_fill("trace_a", 10, "one"), _fill("trace_b", 20, "two"))
    draft = _draft(
        inputs=[{"ref": "shared.value", "title": "共享值", "value_type": "string", "required": True}],
        binding_promotions=[
            {"trace_id": "trace_a", "binding_name": "value", "to_kind": "skill_input", "ref": "shared.value"},
            {"trace_id": "trace_b", "binding_name": "value", "to_kind": "skill_input", "ref": "shared.value"},
        ],
    )

    result = _transform(source, draft)

    assert [trace.data_bindings[0].ref for trace in result.timeline.traces] == [
        "shared.value",
        "shared.value",
    ]
    assert [item.ref for item in result.skill_definition.inputs] == ["shared.value"]


@pytest.mark.parametrize(
    "promotion, message",
    [
        ({"trace_id": "missing", "binding_name": "value", "to_kind": "skill_input", "ref": "query.value"}, "trace_not_found"),
        ({"trace_id": "trace_a", "binding_name": "missing", "to_kind": "skill_input", "ref": "query.value"}, "binding_not_found"),
    ],
)
def test_missing_trace_or_binding_fails_the_whole_transform(promotion: dict, message: str) -> None:
    source = _timeline(_fill("trace_a", 10, "recorded"))
    original = copy.deepcopy(source)
    draft = _draft(
        inputs=[{"ref": "query.value", "title": "查询值", "value_type": "string", "required": True}],
        binding_promotions=[promotion],
    )

    with pytest.raises(ConfigurationError, match=message):
        _transform(source, draft)

    assert source == original


def test_promotion_model_forbids_value_guessing_and_ui_positions() -> None:
    base = {
        "trace_id": "trace_a",
        "binding_name": "value",
        "to_kind": "skill_input",
        "ref": "query.value",
    }
    for forbidden in ("original_value", "array_index", "display_sequence", "locator_text"):
        with pytest.raises(ValidationError):
            SkillConfigurationDraft.model_validate(
                _draft(binding_promotions=[{**base, forbidden: "same"}])
            )


def test_duplicate_or_conflicting_promotions_for_one_location_are_rejected() -> None:
    first = {"trace_id": "trace_a", "binding_name": "value", "to_kind": "skill_input", "ref": "query.value"}
    for second in (
        copy.deepcopy(first),
        {**first, "ref": "query.other"},
        {**first, "to_kind": "secret", "ref": "system.password"},
    ):
        with pytest.raises(ValidationError, match="promotion_location_unique"):
            SkillConfigurationDraft.model_validate(
                _draft(
                    inputs=[
                        {"ref": "query.value", "title": "值", "value_type": "string", "required": True},
                        {"ref": "query.other", "title": "其他值", "value_type": "string", "required": True},
                    ],
                    secrets=[{"ref": "system.password", "title": "密码", "required": True}],
                    binding_promotions=[first, second],
                )
            )


@pytest.mark.parametrize(
    "draft",
    [
        _draft(
            inputs=[{"ref": "query.value", "title": "值", "value_type": "string", "required": True}],
            binding_promotions=[{"trace_id": "trace_a", "binding_name": "value", "to_kind": "secret", "ref": "query.value"}],
        ),
        _draft(
            secrets=[{"ref": "system.password", "title": "密码", "required": True}],
            binding_promotions=[{"trace_id": "trace_a", "binding_name": "value", "to_kind": "skill_input", "ref": "system.password"}],
        ),
        _draft(
            inputs=[{"ref": "query.value", "title": "值", "value_type": "string", "required": True}],
            secrets=[{"ref": "query.value", "title": "同名密码", "required": True}],
        ),
    ],
)
def test_promotion_kind_ref_and_declarations_must_agree(draft: dict) -> None:
    with pytest.raises((ValidationError, ConfigurationError), match="declaration|namespace"):
        _transform(_timeline(_fill("trace_a", 10, "recorded")), draft)


def test_non_literal_or_differently_configured_binding_cannot_be_repromoted() -> None:
    configured = _timeline(_fill("trace_a", 10, "recorded"))
    configured["traces"][0]["data_bindings"][0] = {
        "name": "value",
        "direction": "input",
        "kind": "skill_input",
        "ref": "query.old",
        "sensitive": False,
    }
    draft = _draft(
        inputs=[{"ref": "query.new", "title": "新值", "value_type": "string", "required": True}],
        binding_promotions=[{"trace_id": "trace_a", "binding_name": "value", "to_kind": "skill_input", "ref": "query.new"}],
    )

    with pytest.raises(ConfigurationError, match="binding_conflict"):
        _transform(configured, draft)


def test_pending_readiness_and_invalid_timeline_fail_closed() -> None:
    pending = BuildReadiness(
        ready=False,
        issues=(ReadinessIssue(code=ReadinessCode.CANDIDATE_PENDING, candidate_id="cand_1"),),
        timeline=None,
    )
    with pytest.raises(ConfigurationError, match="timeline_not_ready"):
        _transform(pending, _draft())

    invalid = _timeline(_fill("trace_b", 20, "b"), _fill("trace_a", 10, "a"))
    with pytest.raises(ConfigurationError, match="timeline_invalid"):
        _transform(invalid, _draft())


def test_unpromoted_literal_is_preserved_and_source_is_not_modified() -> None:
    source = _timeline(_fill("trace_a", 10, "fixed"), _fill("trace_b", 20, "recorded"))
    original = copy.deepcopy(source)
    draft = _draft(
        inputs=[{"ref": "query.value", "title": "值", "value_type": "string", "required": True}],
        binding_promotions=[{"trace_id": "trace_b", "binding_name": "value", "to_kind": "skill_input", "ref": "query.value"}],
    )

    result = _transform(source, draft)

    first, second = [trace.data_bindings[0] for trace in result.timeline.traces]
    assert first.kind == "literal" and first.value == "fixed"
    assert second.kind == "skill_input" and second.ref == "query.value"
    assert source == original
    source["traces"][0]["data_bindings"][0]["value"] = "mutated later"
    assert result.timeline.traces[0].data_bindings[0].value == "fixed"


def test_secret_promotion_retains_only_ref_and_marks_binding_sensitive() -> None:
    draft = _draft(
        secrets=[{"ref": "system.password", "title": "系统密码", "required": True}],
        binding_promotions=[{"trace_id": "trace_a", "binding_name": "value", "to_kind": "secret", "ref": "system.password"}],
    )

    result = _transform(_timeline(_fill("trace_a", 10, "Plaintext!")), draft)

    binding = result.timeline.traces[0].data_bindings[0]
    assert binding.model_dump() == {
        "name": "value",
        "direction": "input",
        "kind": "secret",
        "ref": "system.password",
        "sensitive": True,
    }
    serialized = result.model_dump_json()
    assert "Plaintext!" not in serialized


@pytest.mark.parametrize(
    "forbidden",
    [{"default": "S3cr3t-Plain!"}, {"value": "S3cr3t-Plain!"}],
)
def test_draft_never_accepts_secret_plaintext_or_default(forbidden: dict) -> None:
    with pytest.raises(ValidationError) as error:
        SkillConfigurationDraft.model_validate(
            _draft(secrets=[{"ref": "system.password", "title": "密码", "required": True, **forbidden}])
        )
    assert "S3cr3t-Plain!" not in str(error.value)


def test_recorded_value_never_becomes_implicit_default_and_explicit_falsy_defaults_survive() -> None:
    draft = _draft(
        inputs=[
            {"ref": "text.value", "title": "文本", "value_type": "string", "required": False, "default": ""},
            {"ref": "number.value", "title": "数字", "value_type": "number", "required": False, "default": 0},
            {"ref": "boolean.value", "title": "布尔", "value_type": "boolean", "required": False, "default": False},
            {"ref": "without.default", "title": "无默认", "value_type": "string", "required": True},
        ],
        binding_promotions=[
            {"trace_id": "trace_text", "binding_name": "value", "to_kind": "skill_input", "ref": "text.value"},
            {"trace_id": "trace_number", "binding_name": "value", "to_kind": "skill_input", "ref": "number.value"},
            {"trace_id": "trace_boolean", "binding_name": "value", "to_kind": "skill_input", "ref": "boolean.value"},
            {"trace_id": "trace_without", "binding_name": "value", "to_kind": "skill_input", "ref": "without.default"},
        ],
    )

    result = _transform(
        _timeline(
            _fill("trace_text", 10, "recorded value"),
            _fill("trace_number", 20, "recorded value"),
            _fill("trace_boolean", 30, "recorded value"),
            _fill("trace_without", 40, "recorded value"),
        ),
        draft,
    )
    dumped = result.skill_definition.model_dump(mode="python", exclude_unset=True)

    assert dumped["inputs"][0]["default"] == ""
    assert dumped["inputs"][1]["default"] == 0
    assert dumped["inputs"][2]["default"] is False
    assert "default" not in dumped["inputs"][3]
    assert "recorded value" not in result.skill_definition.model_dump_json()


def test_transform_is_idempotent() -> None:
    draft = _draft(
        inputs=[{"ref": "query.value", "title": "值", "value_type": "string", "required": True}],
        binding_promotions=[{"trace_id": "trace_a", "binding_name": "value", "to_kind": "skill_input", "ref": "query.value"}],
    )
    first = _transform(_timeline(_fill("trace_a", 10, "recorded")), draft)

    second = _transform(first.timeline, draft)

    assert second == first


def test_declarations_cover_assets_variable_outputs_and_asset_outputs() -> None:
    traces = [
        {
            "trace_id": "upload",
            "sequence": 10,
            "scope": {"page_ref": "main", "frame_path": []},
            "action": {"kind": "upload", "target": TARGET},
            "data_bindings": [{"name": "file", "direction": "input", "kind": "data_asset", "ref": "source.file", "sensitive": False}],
            "effects": [],
        },
        {
            "trace_id": "agent",
            "sequence": 20,
            "scope": {"page_ref": "main", "frame_path": []},
            "action": {"kind": "agent", "instruction": "生成验收结果"},
            "data_bindings": [{"name": "result", "direction": "output", "kind": "variable", "ref": "验收结果", "sensitive": False}],
            "effects": [],
        },
        {
            "trace_id": "download",
            "sequence": 30,
            "scope": {"page_ref": "main", "frame_path": []},
            "action": {"kind": "click", "target": TARGET},
            "data_bindings": [{"name": "downloaded", "direction": "output", "kind": "data_asset", "ref": "receipt.file", "sensitive": False}],
            "effects": [{"kind": "download", "binding": "downloaded"}],
        },
    ]
    draft = _draft(
        asset_inputs=[{"ref": "source.file", "title": "源文件", "required": True}],
        outputs=[{"name": "acceptance_result", "title": "验收结果", "variable_ref": "验收结果", "value_type": "string"}],
        asset_outputs=[{"name": "receipt", "title": "回执", "asset_ref": "receipt.file"}],
    )

    result = _transform(_timeline(*traces), draft)

    definition = result.skill_definition
    assert [item.ref for item in definition.asset_inputs] == ["source.file"]
    assert [item.variable_ref for item in definition.outputs] == ["验收结果"]
    assert [item.asset_ref for item in definition.asset_outputs] == ["receipt.file"]
    assert definition.stage_2_rules is None
    assert "runtime_requirements" not in definition.model_dump()


@pytest.mark.parametrize(
    "field, declaration",
    [
        ("asset_inputs", {"ref": "missing.file", "title": "不存在输入", "required": True}),
        ("outputs", {"name": "missing", "title": "不存在变量", "variable_ref": "不存在", "value_type": "string"}),
        ("asset_outputs", {"name": "missing", "title": "不存在资产", "asset_ref": "missing.file"}),
    ],
)
def test_declarations_must_resolve_to_timeline_bindings(field: str, declaration: dict) -> None:
    with pytest.raises(ConfigurationError, match="declaration_unresolved"):
        _transform(_timeline(_fill("trace_a", 10, "fixed")), _draft(**{field: [declaration]}))


def test_configured_timeline_changes_only_promoted_binding_and_preserves_trace_shape() -> None:
    source = _timeline(_fill("trace_a", 10, "recorded"))
    source["traces"][0]["wait_until"] = [
        {"kind": "element_state", "target": TARGET, "state": "visible"}
    ]
    draft = _draft(
        inputs=[{"ref": "query.value", "title": "值", "value_type": "string", "required": True}],
        binding_promotions=[{"trace_id": "trace_a", "binding_name": "value", "to_kind": "skill_input", "ref": "query.value"}],
    )

    result = _transform(source, draft)
    before = source["traces"][0]
    after = result.timeline.traces[0].model_dump(mode="python", exclude_unset=True)

    for field in ("trace_id", "sequence", "scope", "action", "effects", "wait_until"):
        assert after[field] == before[field]
    assert after["data_bindings"][0]["name"] == before["data_bindings"][0]["name"]
    assert after["data_bindings"][0]["direction"] == before["data_bindings"][0]["direction"]


def test_skill_definition_is_valid_against_locked_formal_schema() -> None:
    result = _transform(_timeline(_fill("trace_a", 10, "fixed")), _draft())
    schema_path = Path(__file__).parents[1] / "contracts" / "schemas" / "skill-definition-v0.1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(
        result.skill_definition.model_dump(mode="json", exclude_unset=True)
    )


def test_draft_is_strict_frozen_and_forbids_runtime_requirements() -> None:
    with pytest.raises(ValidationError):
        SkillConfigurationDraft.model_validate(_draft(runtime_requirements=["playwright"]))
    draft = SkillConfigurationDraft.model_validate(_draft())
    with pytest.raises(ValidationError):
        draft.skill = draft.skill.model_copy(update={"name": "changed"})


def test_transform_revalidates_a_draft_instance_before_using_its_mutable_containers() -> None:
    promotion = {
        "trace_id": "trace_a",
        "binding_name": "value",
        "to_kind": "skill_input",
        "ref": "query.value",
    }
    draft = SkillConfigurationDraft.model_validate(
        _draft(
            inputs=[{"ref": "query.value", "title": "值", "value_type": "string", "required": True}],
            binding_promotions=[promotion],
        )
    )
    draft.binding_promotions.append(BindingPromotion.model_validate(promotion))

    with pytest.raises(ValidationError, match="promotion_location_unique"):
        _transform(_timeline(_fill("trace_a", 10, "recorded")), draft)


def test_invalid_timeline_error_does_not_echo_sensitive_input_value() -> None:
    unique_secret = "P1-DO-NOT-ECHO-7f92e1"
    source = _timeline(_fill("trace_a", 10, "recorded"))
    source["traces"][0]["data_bindings"][0]["sensitive"] = unique_secret

    with pytest.raises(ConfigurationError) as error:
        _transform(source, _draft())

    assert str(error.value) == "configuration.timeline_invalid"
    assert unique_secret not in str(error.value)
    assert isinstance(error.value.__cause__, ValidationError)


def test_configuration_result_returns_independent_validated_snapshots() -> None:
    source = _timeline(_fill("trace_a", 10, "recorded"))
    original_source = copy.deepcopy(source)
    draft_payload = _draft(
        inputs=[{"ref": "query.value", "title": "值", "value_type": "string", "required": True}],
        binding_promotions=[
            {"trace_id": "trace_a", "binding_name": "value", "to_kind": "skill_input", "ref": "query.value"}
        ],
    )
    original_draft = copy.deepcopy(draft_payload)
    result = _transform(source, draft_payload)
    expected_timeline = result.timeline.model_dump(mode="python", exclude_unset=True)
    expected_definition = result.skill_definition.model_dump(
        mode="python", exclude_unset=True
    )

    leaked_timeline = result.timeline
    leaked_definition = result.skill_definition
    leaked_timeline.traces.clear()
    leaked_definition.inputs.clear()

    assert result.timeline.model_dump(mode="python", exclude_unset=True) == expected_timeline
    assert (
        result.skill_definition.model_dump(mode="python", exclude_unset=True)
        == expected_definition
    )
    assert source == original_source
    assert draft_payload == original_draft
    assert json.loads(result.model_dump_json()) == result.model_dump(mode="json")
