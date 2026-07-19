from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from rpa_agent.contracts import (
    BrowserFact,
    CoreTraceTimeline,
    SettlementResult,
    SkillDefinition,
    SkillManifest,
    TraceCandidate,
    validate_timeline_payload,
)


GOLDEN = Path(__file__).parents[1] / "contracts" / "golden" / "first_e2e"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _timeline() -> dict:
    return _load(GOLDEN / "coretrace.timeline.json")


def test_golden_contracts_load_into_strict_models() -> None:
    timeline = CoreTraceTimeline.model_validate(_timeline())
    definition = SkillDefinition.model_validate(_load(GOLDEN / "skill.definition.json"))
    manifest = SkillManifest.model_validate(
        _load(GOLDEN / "generated-skill" / "skill.manifest.json")
    )

    assert len(timeline.traces) == 24
    assert definition.skill.id == manifest.skill.id
    assert manifest.source.trace_count == len(timeline.traces)


def test_settlement_result_has_no_pending_branch() -> None:
    with pytest.raises(ValidationError, match="accepted|rejected"):
        TypeAdapter(SettlementResult).validate_python(
            {"candidate_id": "cand_1", "status": "pending"}
        )


def test_press_without_target_is_rejected() -> None:
    payload = _timeline()
    payload["traces"][1]["action"] = {"kind": "press"}

    with pytest.raises(ValidationError):
        CoreTraceTimeline.model_validate(payload)


def test_duplicate_sequence_is_rejected_with_stable_message() -> None:
    payload = _timeline()
    payload["traces"][1]["sequence"] = payload["traces"][0]["sequence"]

    with pytest.raises(ValidationError, match="timeline.sequence_duplicate"):
        CoreTraceTimeline.model_validate(payload)


def test_sequence_must_follow_array_order() -> None:
    payload = _timeline()
    payload["traces"][0], payload["traces"][1] = (
        payload["traces"][1],
        payload["traces"][0],
    )

    with pytest.raises(ValidationError, match="timeline.sequence_not_ascending"):
        CoreTraceTimeline.model_validate(payload)


def test_non_main_page_must_be_introduced_by_previous_new_page_effect() -> None:
    payload = _timeline()
    payload["traces"][9]["effects"] = []

    with pytest.raises(ValidationError, match="timeline.page_not_introduced"):
        CoreTraceTimeline.model_validate(payload)


@pytest.mark.parametrize(
    "effects, message",
    [
        ([{"kind": "navigation"}, {"kind": "navigation"}], "effect.kind_duplicate"),
        (
            [{"kind": "dialog", "dialog_type": "alert", "response": "accept"},
             {"kind": "navigation"}],
            "effect.combination_not_allowed",
        ),
    ],
)
def test_effect_whitelist_is_fail_closed(effects: list[dict], message: str) -> None:
    payload = _timeline()
    payload["traces"][1]["effects"] = effects

    with pytest.raises(ValidationError, match=message):
        CoreTraceTimeline.model_validate(payload)


def test_creation_models_are_strict_discriminated_contracts() -> None:
    candidate = TraceCandidate.model_validate(
        {
            "candidate_id": "cand_1",
            "ordinal": 1,
            "origin": "human",
            "scope_hint": {"page_ref": "main", "frame_path": []},
            "action_hint": {"kind": "click", "target_hint": None},
            "binding_hints": [],
            "execution": {
                "status": "succeeded",
                "started_at": datetime.fromisoformat("2026-07-17T10:20:01+08:00"),
                "ended_at": datetime.fromisoformat("2026-07-17T10:20:02+08:00"),
                "output": None,
                "error": None,
            },
        }
    )
    fact = TypeAdapter(BrowserFact).validate_python(
        {
            "fact_id": "fact_1",
            "observed_order": 1,
            "kind": "page_activated",
            "candidate_id": None,
            "observed_at": datetime.fromisoformat("2026-07-17T10:20:02+08:00"),
            "runtime_scope": {"page_runtime_ref": "runtime_page_1"},
        }
    )

    assert candidate.action_hint.kind == "click"
    assert fact.kind == "page_activated"
    with pytest.raises(ValidationError):
        TraceCandidate.model_validate({**candidate.model_dump(), "metadata": {}})


@pytest.mark.parametrize(
    "action_hint",
    [
        {"kind": "fill"},
        {"kind": "navigate", "mode": "url", "target_hint": None},
        {"kind": "unsupported"},
        {"kind": "extract", "mode": "attribute", "target_hint": None},
    ],
)
def test_action_hint_branches_forbid_missing_or_foreign_fields(action_hint: dict) -> None:
    payload = {
        "candidate_id": "cand_1",
        "ordinal": 1,
        "origin": "human",
        "scope_hint": {"page_ref": "main", "frame_path": []},
        "action_hint": action_hint,
        "binding_hints": [],
        "execution": {
            "status": "running",
            "started_at": datetime.now().astimezone(),
            "ended_at": None,
            "error": None,
        },
    }
    with pytest.raises(ValidationError):
        TraceCandidate.model_validate(payload)


@pytest.mark.parametrize(
    "execution",
    [
        {"status": "running", "ended_at": datetime.now().astimezone(), "error": None},
        {"status": "succeeded", "ended_at": None, "error": None},
        {"status": "failed", "ended_at": datetime.now().astimezone(), "error": None},
        {"status": "cancelled", "ended_at": None, "error": None},
    ],
)
def test_execution_state_discriminator_enforces_terminal_shape(execution: dict) -> None:
    payload = {
        "candidate_id": "cand_1",
        "ordinal": 1,
        "origin": "agent",
        "scope_hint": {"page_ref": None, "frame_path": None},
        "action_hint": {"kind": "press"},
        "binding_hints": [],
        "execution": {"started_at": datetime.now().astimezone(), **execution},
    }
    with pytest.raises(ValidationError):
        TraceCandidate.model_validate(payload)


def test_binding_hint_distinguishes_explicit_null_value_from_absence() -> None:
    base = {
        "candidate_id": "cand_1",
        "ordinal": 1,
        "origin": "human",
        "scope_hint": {"page_ref": "main", "frame_path": []},
        "action_hint": {"kind": "close_page"},
        "execution": {
            "status": "succeeded",
            "started_at": datetime.now().astimezone(),
            "ended_at": datetime.now().astimezone(),
            "error": None,
        },
    }
    with pytest.raises(ValidationError, match="binding_hint.value_ref_conflict"):
        TraceCandidate.model_validate(
            {
                **base,
                "binding_hints": [{
                    "name": "value", "direction": "input", "kind_hint": "literal",
                    "value": None, "ref_hint": "input_ref", "sensitive": False,
                }],
            }
        )


def test_hint_lengths_and_names_follow_referenced_core_contracts() -> None:
    base = {
        "candidate_id": "cand_1", "ordinal": 1, "origin": "human",
        "scope_hint": {"page_ref": "main", "frame_path": []},
        "action_hint": {"kind": "fill", "target_hint": None},
        "execution": {
            "status": "running", "started_at": datetime.now().astimezone(),
            "ended_at": None, "error": None,
        },
    }
    with pytest.raises(ValidationError):
        TraceCandidate.model_validate({
            **base,
            "action_hint": {
                "kind": "fill", "target_hint": {"name": "", "locators": []},
            },
            "binding_hints": [],
        })
    with pytest.raises(ValidationError):
        TraceCandidate.model_validate({
            **base,
            "action_hint": {"kind": "fill", "target_hint": None},
            "binding_hints": [{
                "name": "value", "direction": "input", "kind_hint": "skill_input",
                "ref_hint": "a" * 129, "sensitive": False,
            }],
        })
    with pytest.raises(ValidationError):
        TraceCandidate.model_validate({
            **base,
            "action_hint": {"kind": "fill", "target_hint": None},
            "binding_hints": [{
                "name": "value", "direction": "input", "kind_hint": "variable",
                "ref_hint": "业" * 257, "sensitive": False,
            }],
        })
    TraceCandidate.model_validate(
        {
            **base,
            "binding_hints": [{
                "name": "value", "direction": "input", "kind_hint": "variable",
                "ref_hint": "采购订单.订单号", "sensitive": False,
            }],
        }
    )
    with pytest.raises(ValidationError):
        TraceCandidate.model_validate(
            {
                **base,
                "binding_hints": [{
                    "name": "value", "direction": "input", "kind_hint": "skill_input",
                    "ref_hint": "采购订单.订单号", "sensitive": False,
                }],
            }
        )


@pytest.mark.parametrize(
    "fact",
    [
        {
            "kind": "download",
            "detail": {"download_ref": "download_1", "suggested_filename": "x.txt",
                       "status": "completed", "failure_reason": "unexpected"},
        },
        {
            "kind": "download",
            "detail": {"download_ref": "download_1", "suggested_filename": "x.txt",
                       "status": "failed", "failure_reason": None},
        },
        {
            "kind": "dialog",
            "detail": {"dialog_type": "confirm", "response": "accept", "prompt_value": "x"},
        },
    ],
)
def test_browser_fact_detail_state_is_strict(fact: dict) -> None:
    payload = {
        "fact_id": "fact_1",
        "observed_order": 1,
        "candidate_id": "cand_1",
        "observed_at": datetime.now().astimezone(),
        "runtime_scope": {"page_runtime_ref": "runtime_page_1"},
        **fact,
    }
    with pytest.raises(ValidationError):
        TypeAdapter(BrowserFact).validate_python(payload)


def test_browser_fact_runtime_refs_are_identifiers() -> None:
    payload = {
        "fact_id": "fact_1",
        "observed_order": 1,
        "kind": "navigation",
        "candidate_id": None,
        "observed_at": datetime.now().astimezone(),
        "runtime_scope": {"page_runtime_ref": "runtime page"},
        "detail": {"frame_runtime_ref": "runtime frame", "is_main_frame": True, "url": "/"},
    }
    with pytest.raises(ValidationError):
        TypeAdapter(BrowserFact).validate_python(payload)


def _single_trace(action: dict, bindings: list[dict] | None = None, **extra: object) -> dict:
    trace = {
        "trace_id": "trace_1",
        "sequence": 1,
        "scope": {"page_ref": "main", "frame_path": []},
        "action": action,
        "data_bindings": bindings or [],
        "effects": [],
    }
    trace.update(extra)
    return {"schema_version": "core-trace/v0.1", "traces": [trace]}


TARGET = {
    "name": "目标",
    "locators": [{"strategy": "test_id", "value": "target"}],
}


@pytest.mark.parametrize(
    "action, bindings",
    [
        ({"kind": "navigate", "mode": "url"}, []),
        ({"kind": "navigate", "mode": "back"}, [
            {"name": "url", "direction": "input", "kind": "literal", "value": "/x", "sensitive": False}
        ]),
        ({"kind": "fill", "target": TARGET}, []),
        ({"kind": "press", "target": TARGET}, []),
        ({"kind": "select", "target": TARGET}, []),
        ({"kind": "upload", "target": TARGET}, [
            {"name": "file", "direction": "input", "kind": "literal", "value": "C:/x", "sensitive": False}
        ]),
        ({"kind": "extract", "target": TARGET, "mode": "text"}, [
            {"name": "result", "direction": "output", "kind": "data_asset", "ref": "result_file", "sensitive": False}
        ]),
        ({"kind": "click", "target": TARGET}, [
            {"name": "value", "direction": "input", "kind": "literal", "value": "orphan", "sensitive": False}
        ]),
    ],
)
def test_non_agent_action_binding_matrix_is_fail_closed(action: dict, bindings: list[dict]) -> None:
    with pytest.raises(ValidationError, match="binding"):
        CoreTraceTimeline.model_validate(_single_trace(action, bindings))


def test_same_trace_cannot_consume_variable_it_produces() -> None:
    bindings = [
        {"name": "option", "direction": "input", "kind": "variable", "ref": "选择值", "sensitive": False},
        {"name": "result", "direction": "output", "kind": "variable", "ref": "选择值", "sensitive": False},
    ]
    action = {"kind": "agent", "instruction": "读取并更新选择值"}
    with pytest.raises(ValidationError, match="timeline.variable_not_produced"):
        CoreTraceTimeline.model_validate(_single_trace(action, bindings))


def test_optional_core_fields_may_be_omitted_but_not_null() -> None:
    payload = _single_trace({"kind": "scroll", "target": None, "direction": "down", "amount": 1, "unit": "pixel"})
    with pytest.raises(ValidationError):
        CoreTraceTimeline.model_validate(payload)
    wait = {
        "kind": "url_matches", "operator": "exact", "expected": "",
    }
    with pytest.raises(ValidationError):
        CoreTraceTimeline.model_validate(
            _single_trace({"kind": "click", "target": TARGET}, wait_until=[wait])
        )
    table = {
        "kind": "extract",
        "target": TARGET,
        "mode": "table",
        "columns": [{"name": "order_no", "header": None, "index": 0}],
    }
    with pytest.raises(ValidationError):
        CoreTraceTimeline.model_validate(
            _single_trace(table, [_binding("result", kind="variable", direction="output")])
        )


def test_skill_defaults_and_unique_arrays_follow_schema() -> None:
    definition = _load(GOLDEN / "skill.definition.json")
    definition["inputs"][0]["default"] = None
    with pytest.raises(ValidationError):
        SkillDefinition.model_validate(definition)

    manifest = _load(GOLDEN / "generated-skill" / "skill.manifest.json")
    manifest["runtime"]["requirements"].append("playwright")
    with pytest.raises(ValidationError, match="requirements_unique"):
        SkillManifest.model_validate(manifest)

    definition = _load(GOLDEN / "skill.definition.json")
    definition["inputs"].append(copy.deepcopy(definition["inputs"][0]))
    with pytest.raises(ValidationError, match="unique_items"):
        SkillDefinition.model_validate(definition)

    definition = _load(GOLDEN / "skill.definition.json")
    duplicate_key = copy.deepcopy(definition["inputs"][0])
    duplicate_key["title"] = "同业务键的不同声明"
    definition["inputs"].append(duplicate_key)
    with pytest.raises(ValidationError, match="ref_unique"):
        SkillDefinition.model_validate(definition)


def _binding(name: str, *, kind: str = "literal", direction: str = "input") -> dict:
    base = {"name": name, "direction": direction, "kind": kind, "sensitive": False}
    if kind == "literal":
        return {**base, "value": "value"}
    return {**base, "ref": "business_ref"}


@pytest.mark.parametrize(
    "action, bindings",
    [
        ({"kind": "navigate", "mode": "url"}, [_binding("url")]),
        ({"kind": "click", "target": TARGET}, []),
        ({"kind": "fill", "target": TARGET}, [_binding("value")]),
        ({"kind": "press", "target": TARGET}, [_binding("keys")]),
        ({"kind": "select", "target": TARGET}, [_binding("option")]),
        ({"kind": "set_checked", "target": TARGET, "checked": True}, []),
        ({"kind": "hover", "target": TARGET}, []),
        ({"kind": "upload", "target": TARGET}, [_binding("file", kind="data_asset")]),
        ({"kind": "scroll", "direction": "down", "amount": 1, "unit": "pixel"}, []),
        ({"kind": "extract", "target": TARGET, "mode": "text"}, [
            _binding("result", kind="variable", direction="output")
        ]),
        ({"kind": "switch_page", "page_ref": "main"}, []),
        ({"kind": "close_page"}, []),
        ({"kind": "agent", "instruction": "执行一个受控动作"}, [_binding("input")]),
    ],
)
def test_all_core_action_kinds_have_a_valid_semantic_contract(
    action: dict, bindings: list[dict]
) -> None:
    context = (
        {"external_asset_refs": {"business_ref"}}
        if action["kind"] == "upload"
        else None
    )
    if context is None:
        CoreTraceTimeline.model_validate(_single_trace(action, bindings))
    else:
        validate_timeline_payload(
            _single_trace(action, bindings),
            external_asset_refs=context["external_asset_refs"],
        )


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "click", "target": TARGET},
        {"kind": "set_checked", "target": TARGET, "checked": False},
        {"kind": "hover", "target": TARGET},
        {"kind": "scroll", "direction": "down", "amount": 1, "unit": "pixel"},
        {"kind": "switch_page", "page_ref": "main"},
        {"kind": "close_page"},
    ],
)
def test_actions_without_fixed_slots_reject_orphan_bindings(action: dict) -> None:
    with pytest.raises(ValidationError, match="binding.orphan"):
        CoreTraceTimeline.model_validate(_single_trace(action, [_binding("orphan")]))


@pytest.mark.parametrize(
    "trace",
    [
        {
            "action": {
                "kind": "click",
                "target": {
                    **TARGET,
                    "path": [{**TARGET, "filter_binding": "row_key"}],
                },
            },
            "bindings": [_binding("row_key", kind="variable", direction="output")],
        },
        {
            "action": {"kind": "click", "target": TARGET},
            "bindings": [_binding("downloaded", kind="variable", direction="output")],
            "effects": [{"kind": "download", "binding": "downloaded"}],
        },
        {
            "action": {"kind": "click", "target": TARGET},
            "bindings": [_binding("prompt", kind="variable", direction="output")],
            "effects": [{
                "kind": "dialog", "dialog_type": "prompt", "response": "accept",
                "input_binding": "prompt",
            }],
        },
        {
            "action": {"kind": "click", "target": TARGET},
            "bindings": [_binding("expected", kind="variable", direction="output")],
            "wait_until": [{
                "kind": "url_matches", "operator": "contains", "expected_binding": "expected",
            }],
        },
        {
            "action": {"kind": "agent", "instruction": "触发文件下载"},
            "bindings": [_binding("downloaded", kind="data_asset", direction="output")],
            "effects": [{"kind": "download", "binding": "downloaded"}],
        },
    ],
)
def test_binding_endpoints_require_exact_direction_kind_and_single_connection(
    trace: dict,
) -> None:
    payload = _single_trace(trace["action"], trace["bindings"])
    payload["traces"][0]["effects"] = trace.get("effects", [])
    if "wait_until" in trace:
        payload["traces"][0]["wait_until"] = trace["wait_until"]
    with pytest.raises(ValidationError, match="binding"):
        CoreTraceTimeline.model_validate(payload)


def test_prompt_accept_input_binding_is_optional_but_typed_when_present() -> None:
    payload = _single_trace({"kind": "click", "target": TARGET})
    payload["traces"][0]["effects"] = [
        {"kind": "dialog", "dialog_type": "prompt", "response": "accept"}
    ]
    CoreTraceTimeline.model_validate(payload)


def test_input_binding_can_be_reused_by_action_and_wait() -> None:
    payload = _single_trace(
        {"kind": "fill", "target": TARGET},
        [_binding("value")],
        wait_until=[{
            "kind": "url_matches", "operator": "contains", "expected_binding": "value",
        }],
    )
    CoreTraceTimeline.model_validate(payload)


def test_data_asset_input_requires_prior_or_external_producer() -> None:
    upload = _single_trace(
        {"kind": "upload", "target": TARGET},
        [_binding("file", kind="data_asset")],
    )
    with pytest.raises(ValidationError, match="timeline.data_asset_not_produced"):
        CoreTraceTimeline.model_validate(upload)

    validate_timeline_payload(
        upload,
        external_asset_refs={"business_ref"},
    )

    download_then_upload = {
        "schema_version": "core-trace/v0.1",
        "traces": [
            {
                "trace_id": "trace_1", "sequence": 1,
                "scope": {"page_ref": "main", "frame_path": []},
                "action": {"kind": "click", "target": TARGET},
                "data_bindings": [{
                    "name": "downloaded", "direction": "output", "kind": "data_asset",
                    "ref": "downloaded_asset", "sensitive": False,
                }],
                "effects": [{"kind": "download", "binding": "downloaded"}],
            },
            {
                "trace_id": "trace_2", "sequence": 2,
                "scope": {"page_ref": "main", "frame_path": []},
                "action": {"kind": "upload", "target": TARGET},
                "data_bindings": [{
                    "name": "file", "direction": "input", "kind": "data_asset",
                    "ref": "downloaded_asset", "sensitive": False,
                }],
                "effects": [],
            },
        ],
    }
    CoreTraceTimeline.model_validate(download_then_upload)
