from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from rpa_agent.browser_use import (
    BROWSER_USE_BASELINE_VERSION,
    ActualToolAction,
    BrowserUseRecordingAdapter as _BrowserUseRecordingAdapter,
    NormalizedActionResult,
    TargetResolution,
    assert_browser_use_version,
)
from rpa_agent.contracts import BrowserScope
from rpa_agent.creation import ControlMode, SettlementAttempt, SettlementAttemptStatus, SkillCreationSession


NOW = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)
TARGET = {
    "name": "订单号",
    "locators": [{"strategy": "label", "value": "订单号", "exact": True}],
}


def _session() -> SkillCreationSession:
    session = SkillCreationSession(
        session_id="session_browser_use",
        main_runtime_ref="runtime_main",
        fact_buffer_capacity=32,
        fact_ttl=timedelta(seconds=10),
    )
    session.switch_control(ControlMode.AGENT, at=NOW)
    return session


def _action(
    name: str,
    *,
    candidate_id: str,
    params: dict[str, Any] | None = None,
    target: dict[str, Any] | None = TARGET,
    bindings: tuple[dict[str, Any], ...] = (),
    intent: str | None = None,
    frame_path: tuple[dict[str, Any], ...] = (),
    runtime_page_ref: str = "runtime_main",
    runtime_frame_ref: str = "frame_main",
    page_ref: str = "main",
) -> ActualToolAction:
    return ActualToolAction(
        action_name=name,
        candidate_id=candidate_id,
        params=params or {},
        business_intent=intent or f"执行 {name}",
        runtime_page_ref=runtime_page_ref,
        runtime_frame_ref=runtime_frame_ref,
        page_ref=page_ref,
        frame_path=frame_path,
        target_hint=target,
        binding_hints=bindings,
    )


def BrowserUseRecordingAdapter(
    *,
    session: SkillCreationSession,
    executor: Any,
) -> _BrowserUseRecordingAdapter:
    """Task 5 tests use explicit trusted host boundaries."""

    async def evidence_provider(
        _: ActualToolAction, result: object
    ) -> dict[str, Any]:
        data = getattr(result, "data", {})
        if not isinstance(data, Mapping):
            return {}
        trusted = {
            "url_reached", "history_changed", "dispatched", "dom_value",
            "selected", "completed", "uploaded_asset_ref",
            "activated_page_ref", "closed_page_ref", "variables",
        }
        return {key: value for key, value in data.items() if key in trusted}

    return _BrowserUseRecordingAdapter(
        session=session,
        executor=executor,
        evidence_provider=evidence_provider,
        target_resolver=lambda action: TargetResolution(
            target_hint=action.target_hint,
            match_count=1 if action.target_hint is not None else 0,
        ),
        version_provider=lambda: BROWSER_USE_BASELINE_VERSION,
        clock=lambda: NOW,
        allowed_extension_actions=frozenset(
            {"new_private_tool", "extract_variable"}
        ),
    )


@pytest.mark.asyncio
async def test_round_records_each_actual_tool_action_and_not_planning_metadata() -> None:
    calls: list[str] = []

    async def executor(action: ActualToolAction) -> NormalizedActionResult:
        calls.append(action.action_name)
        if action.action_name == "click":
            return NormalizedActionResult(data={"dispatched": True})
        return NormalizedActionResult(data={"dom_value": "PO-1001"})

    session = _session()
    adapter = BrowserUseRecordingAdapter(session=session, executor=executor)
    report = await adapter.record_round(
        (
            _action("click", candidate_id="agent_click"),
            _action(
                "input",
                candidate_id="agent_input",
                params={"text": "PO-1001"},
                bindings=(
                    {
                        "name": "value",
                        "direction": "input",
                        "kind_hint": "variable",
                        "ref_hint": "采购订单.订单号",
                        "sensitive": False,
                    },
                ),
            ),
        ),
        planning_metadata={"plan": "先点再填", "thought": "私有推理", "history": ["旧动作"], "summary": "完成"},
    )

    assert calls == ["click", "input"]
    assert report.actual_action_count == 2
    assert report.candidate_ids == ("agent_click", "agent_input")
    assert report.non_sop == ()
    candidates = session.candidates
    assert [candidates[item].ordinal for item in report.candidate_ids] == [1, 2]
    dumped = str([item.model_dump(mode="json") for item in candidates.values()]).lower()
    assert "history" not in dumped
    assert "私有推理" not in dumped
    assert "PO-1001" not in dumped
    assert candidates["agent_input"].binding_hints[0].ref_hint == "采购订单.订单号"
    assert candidates["agent_input"].execution.output is None


@pytest.mark.asyncio
async def test_non_sop_actions_are_explicit_and_action_accounting_is_closed() -> None:
    async def executor(action: ActualToolAction) -> NormalizedActionResult:
        if action.action_name == "done":
            return NormalizedActionResult(is_done=True, success=True)
        return NormalizedActionResult(data={"observed": True})

    actions = tuple(
        _action(name, candidate_id=f"non_sop_{index}", target=None)
        for index, name in enumerate(
            ("done", "wait", "observe", "search_page", "find_elements", "find_text", "dropdown_options"),
            start=1,
        )
    )
    report = await BrowserUseRecordingAdapter(
        session=_session(), executor=executor
    ).record_round(actions)

    assert report.actual_action_count == 7
    assert report.candidate_ids == ()
    assert len(report.non_sop) == 7
    assert {item.action_name for item in report.non_sop} == {item.action_name for item in actions}
    assert all(item.status == "succeeded" for item in report.non_sop)
    assert report.actual_action_count == len(report.candidate_ids) + len(report.non_sop)


@pytest.mark.asyncio
async def test_search_only_scroll_is_explicit_non_sop() -> None:
    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        return NormalizedActionResult(data={"completed": True})

    report = await BrowserUseRecordingAdapter(
        session=_session(), executor=executor
    ).record_round(
        (
            _action(
                "scroll",
                candidate_id="scroll_for_search",
                target=None,
                params={
                    "direction": "down",
                    "amount": 1,
                    "unit": "viewport",
                    "business_required": False,
                },
            ),
        )
    )

    assert report.candidate_ids == ()
    assert report.non_sop[0].action_name == "scroll"
    assert report.non_sop[0].reason == "planning_scroll"


@pytest.mark.asyncio
async def test_unknown_action_never_disappears_and_downgrades_to_agent() -> None:
    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        return NormalizedActionResult(data={"completed": True})

    session = _session()
    report = await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
        (_action("new_private_tool", candidate_id="agent_unknown", target=None, intent="执行业务专用动作"),)
    )

    assert report.actual_action_count == 1
    assert report.candidate_ids == ("agent_unknown",)
    candidate = session.candidates["agent_unknown"]
    assert candidate.action_hint.kind == "agent"
    assert candidate.action_hint.instruction == "执行业务专用动作"


@pytest.mark.asyncio
@pytest.mark.parametrize("action_name", ["search", "write_file", "screenshot", "save_pdf"])
async def test_v1_blocked_tools_have_explicit_accounting_and_never_execute(
    action_name: str,
) -> None:
    calls = 0

    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        nonlocal calls
        calls += 1
        return NormalizedActionResult(data={"completed": True})

    session = _session()
    candidate_id = f"agent_blocked_{action_name}"
    report = await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
        (_action(action_name, candidate_id=candidate_id, target=None),)
    )

    assert report.candidate_ids == ()
    assert calls == 0
    assert [(item.action_name, item.status, item.reason) for item in report.blocked] == [
        (action_name, "blocked", "action_denied")
    ]
    assert candidate_id not in session.candidates


@pytest.mark.asyncio
async def test_error_none_but_success_false_is_failed_and_not_accepted() -> None:
    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        return NormalizedActionResult(success=False, error=None, data={"dispatched": True})

    session = _session()
    await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
        (_action("click", candidate_id="agent_failed"),)
    )
    candidate = session.candidates["agent_failed"]
    assert candidate.execution.status == "failed"

    outcome = session.settle_candidate(
        candidate.candidate_id,
        scope=BrowserScope(page_ref="main", frame_path=[]),
    )
    assert outcome.status == "rejected"
    assert outcome.diagnostic.code == "execution_failed"


@pytest.mark.asyncio
async def test_done_is_done_false_is_explicit_non_sop_failure() -> None:
    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        return NormalizedActionResult(is_done=False, success=None)

    report = await BrowserUseRecordingAdapter(
        session=_session(), executor=executor
    ).record_round((_action("done", candidate_id="done_false", target=None),))

    assert report.non_sop[0].status == "failed"
    assert report.non_sop[0].reason == "done_not_completed"


@pytest.mark.asyncio
async def test_input_dom_value_mismatch_and_extract_without_variable_contract_fail() -> None:
    async def executor(action: ActualToolAction) -> NormalizedActionResult:
        if action.action_name == "input":
            return NormalizedActionResult(data={"dom_value": "OTHER"})
        return NormalizedActionResult(data={"variables": {"采购订单.订单号": "PO-1001"}})

    session = _session()
    report = await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
        (
            _action("input", candidate_id="agent_input_bad", params={"text": "PO-1001"}),
            _action("extract", candidate_id="agent_extract_bad", params={"mode": "text"}),
        )
    )

    assert report.candidate_ids == ("agent_input_bad", "agent_extract_bad")
    assert session.candidates["agent_input_bad"].execution.status == "failed"
    assert session.candidates["agent_extract_bad"].execution.status == "failed"


@pytest.mark.asyncio
async def test_invalid_deterministic_shape_falls_back_without_leaking_reservation() -> None:
    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        return NormalizedActionResult(data={"completed": True})

    session = _session()
    report = await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
        (
            _action(
                "extract",
                candidate_id="agent_invalid_extract_mode",
                params={"mode": "semantic"},
                intent="按业务语义提取订单信息",
            ),
        )
    )

    assert report.candidate_ids == ("agent_invalid_extract_mode",)
    candidate = session.candidates["agent_invalid_extract_mode"]
    assert candidate.action_hint.kind == "agent"
    assert candidate.execution.status == "succeeded"
    assert session.outstanding_agent_reservation_count == 0


@pytest.mark.asyncio
async def test_navigate_missing_expected_url_and_switch_unknown_page_fail_closed() -> None:
    async def executor(action: ActualToolAction) -> NormalizedActionResult:
        if action.action_name == "navigate":
            return NormalizedActionResult(data={"url_reached": True})
        return NormalizedActionResult(data={"activated_page_ref": "page_999"})

    session = _session()
    await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
        (
            _action("navigate", candidate_id="agent_nav_missing", params={}, target=None),
            _action(
                "switch",
                candidate_id="agent_switch_unknown",
                params={"page_ref": "page_999"},
                target=None,
            ),
        )
    )

    assert session.candidates["agent_nav_missing"].execution.status == "failed"
    assert session.candidates["agent_switch_unknown"].execution.status == "failed"


@pytest.mark.asyncio
async def test_dynamic_navigation_keeps_url_for_postcondition_judgement() -> None:
    url = "https://github.com/search?q=skill&type=repositories"

    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        return NormalizedActionResult(data={"url_reached": True})

    session = _session()
    await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
        (
            _action(
                "navigate",
                candidate_id="agent_dynamic_nav",
                params={"url": url},
                target=None,
                intent="查找和 skill 最相关的项目",
            ),
        )
    )

    candidate = session.candidates["agent_dynamic_nav"]
    assert candidate.action_hint.kind == "agent"
    assert candidate.execution.status == "succeeded"


@pytest.mark.asyncio
async def test_tool_exception_with_associated_side_effect_stays_running_for_confirmation() -> None:
    session = _session()

    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        trigger = session.observer.start_new_page("runtime_main", "frame_main")
        fact = session.observer.complete_new_page(
            trigger,
            observed_at=NOW + timedelta(milliseconds=10),
            new_page_runtime_ref="runtime_popup",
            initial_url="https://example.test/random/token",
        )
        session.pages.apply(fact)
        raise TimeoutError("tool timeout after popup")

    with pytest.raises(TimeoutError, match="tool timeout after popup"):
        await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
            (_action("click", candidate_id="agent_popup"),), completed_at=NOW + timedelta(seconds=1)
        )

    candidate = session.candidates["agent_popup"]
    assert candidate.execution.status == "running"
    assert session.fact_buffer.facts()[0].candidate_id == "agent_popup"
    outcome = session.settle_candidate(
        "agent_popup", scope=BrowserScope(page_ref="main", frame_path=[])
    )
    assert isinstance(outcome, SettlementAttempt)
    assert outcome.status is SettlementAttemptStatus.NEEDS_CONFIRMATION


@pytest.mark.asyncio
@pytest.mark.parametrize("effect_kind", ["navigation", "download", "dialog"])
async def test_each_supported_side_effect_survives_tool_exception(effect_kind: str) -> None:
    session = _session()

    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        if effect_kind == "navigation":
            trigger = session.observer.start_navigation("runtime_main", "frame_main")
            fact = session.observer.complete_navigation(
                trigger,
                observed_at=NOW + timedelta(milliseconds=10),
                page_runtime_ref="runtime_main",
                frame_runtime_ref="frame_main",
                is_main_frame=True,
                url="https://example.test/orders",
            )
            session.pages.apply(fact)
        elif effect_kind == "download":
            trigger = session.observer.start_download("runtime_main", "frame_main")
            session.observer.complete_download(
                trigger,
                observed_at=NOW + timedelta(milliseconds=10),
                page_runtime_ref="runtime_main",
                download_ref="download_result",
                status="completed",
                suggested_filename="result.csv",
            )
        else:
            trigger = session.observer.start_dialog("runtime_main", "frame_main")
            session.observer.complete_dialog(
                trigger,
                observed_at=NOW + timedelta(milliseconds=10),
                page_runtime_ref="runtime_main",
                dialog_type="confirm",
                response="accept",
            )
        raise TimeoutError("timeout after side effect")

    candidate_id = f"agent_side_effect_{effect_kind}"
    with pytest.raises(TimeoutError, match="timeout after side effect"):
        await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
            (_action("click", candidate_id=candidate_id),),
            completed_at=NOW + timedelta(seconds=1),
        )

    assert session.candidates[candidate_id].execution.status == "running"
    assert session.fact_buffer.facts()[0].candidate_id == candidate_id
    outcome = session.settle_candidate(
        candidate_id,
        scope=BrowserScope(page_ref="main", frame_path=[]),
    )
    assert isinstance(outcome, SettlementAttempt)
    assert outcome.status is SettlementAttemptStatus.NEEDS_CONFIRMATION


@pytest.mark.asyncio
async def test_cancelled_action_registers_cancelled_candidate_then_propagates() -> None:
    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        raise asyncio.CancelledError()

    session = _session()
    adapter = BrowserUseRecordingAdapter(session=session, executor=executor)
    with pytest.raises(asyncio.CancelledError):
        await adapter.record_round(
            (_action("click", candidate_id="agent_cancelled"),),
            completed_at=NOW + timedelta(seconds=1),
        )

    candidate = session.candidates["agent_cancelled"]
    assert candidate.execution.status == "cancelled"
    assert candidate.execution.error.code == "action_cancelled"
    assert candidate.execution.error.message == "Browser action was cancelled."
    assert session.outstanding_agent_reservation_count == 0
    session.switch_control(ControlMode.HUMAN, at=NOW + timedelta(seconds=2))
    assert session.control_mode is ControlMode.HUMAN


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"mode": "attribute"},
        {"mode": "table", "columns": [{"name": "订单号"}]},
    ],
)
async def test_malformed_extract_is_agent_fallback_without_reservation_leak(
    params: dict[str, Any],
) -> None:
    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        return NormalizedActionResult(data={"completed": True})

    session = _session()
    await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
        (
            _action(
                "extract",
                candidate_id=f"agent_malformed_{params['mode']}",
                params=params,
                intent="提取订单业务字段",
            ),
        )
    )

    candidate = next(iter(session.candidates.values()))
    assert candidate.action_hint.kind == "agent"
    assert candidate.execution.status == "succeeded"
    assert session.outstanding_agent_reservation_count == 0


@pytest.mark.asyncio
async def test_late_side_effect_in_closed_tail_changes_settlement_to_confirmation() -> None:
    session = _session()
    trigger_holder: list[Any] = []

    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        trigger_holder.append(session.observer.start_navigation("runtime_main", "frame_main"))
        raise TimeoutError("tool returned before navigation completed")

    with pytest.raises(TimeoutError, match="tool returned before navigation completed"):
        await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
            (_action("click", candidate_id="agent_late_navigation"),),
            completed_at=NOW + timedelta(seconds=1),
        )
    assert session.candidates["agent_late_navigation"].execution.status == "failed"

    fact = session.observer.complete_navigation(
        trigger_holder[0],
        observed_at=NOW + timedelta(seconds=2),
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
        is_main_frame=True,
        url="https://example.test/late",
    )
    session.pages.apply(fact)
    assert fact.candidate_id == "agent_late_navigation"
    outcome = session.settle_candidate(
        "agent_late_navigation",
        scope=BrowserScope(page_ref="main", frame_path=[]),
    )
    assert isinstance(outcome, SettlementAttempt)
    assert outcome.status is SettlementAttemptStatus.NEEDS_CONFIRMATION


@pytest.mark.asyncio
async def test_page_closed_fact_is_preserved_when_close_tool_raises() -> None:
    session = _session()

    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        trigger = session.observer.start_page_closed("runtime_main", "frame_main")
        fact = session.observer.complete_page_closed(
            trigger,
            observed_at=NOW + timedelta(milliseconds=10),
            page_runtime_ref="runtime_main",
        )
        session.pages.apply(fact)
        raise TimeoutError("close timed out after page closed")

    with pytest.raises(TimeoutError, match="close timed out after page closed"):
        await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
            (_action("close", candidate_id="agent_close_side_effect", target=None),),
            completed_at=NOW + timedelta(seconds=1),
        )

    assert session.candidates["agent_close_side_effect"].execution.status == "running"
    outcome = session.settle_candidate(
        "agent_close_side_effect",
        scope=BrowserScope(page_ref="main", frame_path=[]),
    )
    assert isinstance(outcome, SettlementAttempt)
    assert outcome.status is SettlementAttemptStatus.NEEDS_CONFIRMATION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "params", "target", "bindings", "result_data", "expected_kind"),
    [
        ("navigate", {"url": "https://example.test/orders"}, None, (), {"url_reached": True}, "navigate"),
        ("go_back", {}, None, (), {"history_changed": True}, "navigate"),
        ("click", {}, TARGET, (), {"dispatched": True}, "click"),
        ("input", {"text": "PO-1"}, TARGET, (), {"dom_value": "PO-1"}, "fill"),
        ("select_dropdown", {"option": "已审批"}, TARGET, (), {"selected": "已审批"}, "select"),
        ("scroll", {"direction": "down", "amount": 1, "unit": "viewport", "business_required": True}, None, (), {"completed": True}, "scroll"),
        ("upload_file", {"asset_ref": "acceptance_file"}, TARGET, (), {"uploaded_asset_ref": "acceptance_file"}, "upload"),
        ("switch", {"page_ref": "main"}, None, (), {"activated_page_ref": "main"}, "switch_page"),
        ("close", {}, None, (), {"closed_page_ref": "main"}, "close_page"),
        ("send_keys", {"keys": "Enter"}, TARGET, (), {"dispatched": True}, "press"),
        ("evaluate", {}, None, (), {"completed": True}, "agent"),
    ],
)
async def test_mapping_matrix(
    name: str,
    params: dict[str, Any],
    target: dict[str, Any] | None,
    bindings: tuple[dict[str, Any], ...],
    result_data: dict[str, Any],
    expected_kind: str,
) -> None:
    session = _session()

    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        if name == "switch":
            trigger = session.observer.start_page_activated("runtime_main", "frame_main")
            fact = session.observer.complete_page_activated(
                trigger,
                observed_at=NOW + timedelta(milliseconds=10),
                page_runtime_ref="runtime_main",
            )
            session.pages.apply(fact)
        elif name == "close":
            trigger = session.observer.start_page_closed("runtime_main", "frame_main")
            fact = session.observer.complete_page_closed(
                trigger,
                observed_at=NOW + timedelta(milliseconds=10),
                page_runtime_ref="runtime_main",
            )
            session.pages.apply(fact)
        return NormalizedActionResult(data=result_data)

    candidate_id = f"agent_{name}"
    await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
        (_action(name, candidate_id=candidate_id, params=params, target=target, bindings=bindings),)
    )

    candidate = session.candidates[candidate_id]
    assert candidate.action_hint.kind == expected_kind
    assert candidate.execution.status == "succeeded"


@pytest.mark.asyncio
async def test_extract_mapping_and_real_settlement_acceptance() -> None:
    binding = {
        "name": "result",
        "direction": "output",
        "kind_hint": "variable",
        "ref_hint": "采购订单.订单号",
        "sensitive": False,
    }

    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        return NormalizedActionResult(data={"variables": {"采购订单.订单号": "PO-1001"}})

    session = _session()
    await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
        (_action("extract", candidate_id="agent_extract", params={"mode": "text"}, bindings=(binding,)),)
    )
    candidate = session.candidates["agent_extract"]
    assert candidate.action_hint.kind == "extract"
    assert candidate.execution.status == "succeeded"

    outcome = session.settle_candidate(
        "agent_extract", scope=BrowserScope(page_ref="main", frame_path=[])
    )
    assert outcome.status == "accepted"
    assert outcome.core_trace.action.kind == "extract"
    assert outcome.core_trace.data_bindings[0].ref == "采购订单.订单号"
    assert session.variables.read("采购订单.订单号") == "PO-1001"


@pytest.mark.asyncio
async def test_extract_variable_with_visible_target_maps_to_explicit_extract_trace() -> None:
    binding = {
        "name": "result",
        "direction": "output",
        "kind_hint": "variable",
        "ref_hint": "github.repository.stars",
        "sensitive": False,
    }

    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        return NormalizedActionResult(
            data={"variables": {"github.repository.stars": 5267}}
        )

    session = _session()
    await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
        (
            _action(
                "extract_variable",
                candidate_id="agent_extract_star_count",
                params={
                    "index": 7,
                    "mode": "text",
                    "variable_ref": "github.repository.stars",
                    "value": 5267,
                },
                bindings=(binding,),
                intent="获取当前项目的 Star 数",
            ),
        )
    )

    candidate = session.candidates["agent_extract_star_count"]
    assert candidate.action_hint.kind == "extract"
    assert candidate.execution.status == "succeeded"
    outcome = session.settle_candidate(
        "agent_extract_star_count",
        scope=BrowserScope(page_ref="main", frame_path=[]),
    )
    assert outcome.status == "accepted"
    assert outcome.core_trace.action.kind == "extract"
    assert outcome.core_trace.data_bindings[0].ref == "github.repository.stars"


@pytest.mark.asyncio
async def test_evaluate_agent_action_requires_and_writes_declared_variable_outputs() -> None:
    binding = {
        "name": "result",
        "direction": "output",
        "kind_hint": "variable",
        "ref_hint": "采购订单.供应商",
        "sensitive": False,
    }

    async def executor(action: ActualToolAction) -> NormalizedActionResult:
        variables = (
            {"采购订单.供应商": "甲供应商"}
            if action.candidate_id == "agent_evaluate_ok"
            else {}
        )
        return NormalizedActionResult(data={"variables": variables})

    session = _session()
    await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
        (
            _action(
                "evaluate",
                candidate_id="agent_evaluate_ok",
                target=None,
                bindings=(binding,),
            ),
            _action(
                "evaluate",
                candidate_id="agent_evaluate_missing",
                target=None,
                bindings=(binding,),
            ),
        )
    )

    assert session.candidates["agent_evaluate_ok"].execution.status == "succeeded"
    assert session.variables.read("采购订单.供应商") == "甲供应商"
    assert session.candidates["agent_evaluate_missing"].execution.status == "failed"


@pytest.mark.asyncio
async def test_variable_outputs_commit_atomically_or_candidate_becomes_failed() -> None:
    bindings = (
        {
            "name": "order_result",
            "direction": "output",
            "kind_hint": "variable",
            "ref_hint": "采购订单.订单号",
            "sensitive": False,
        },
        {
            "name": "conflicting_result",
            "direction": "output",
            "kind_hint": "variable",
            "ref_hint": "标量.子项",
            "sensitive": False,
        },
    )

    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        return NormalizedActionResult(
            data={
                "variables": {
                    "采购订单.订单号": "PO-SHOULD-NOT-WRITE",
                    "标量.子项": "conflict",
                }
            }
        )

    session = _session()
    session.variables.write("标量", "existing", producer_candidate_id="candidate_existing")
    await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
        (
            _action(
                "evaluate",
                candidate_id="agent_output_conflict",
                target=None,
                bindings=bindings,
            ),
        )
    )

    assert session.candidates["agent_output_conflict"].execution.status == "failed"
    assert session.candidates["agent_output_conflict"].execution.error.code == "variable_output_commit_failed"
    assert session.variables.read("标量") == "existing"
    with pytest.raises(KeyError, match="session_variable_store.ref_missing"):
        session.variables.read("采购订单.订单号")
    assert session.outstanding_agent_reservation_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "params", "target"),
    [
        ("click", {"coordinate_x": 10, "coordinate_y": 20, "index": 42}, None),
        ("send_keys", {"keys": "Enter"}, None),
        ("evaluate", {"code": "document.title"}, None),
        ("extract", {"mode": "semantic"}, None),
    ],
)
async def test_unstable_actions_become_one_agent_action_without_private_identifiers(
    name: str, params: dict[str, Any], target: dict[str, Any] | None
) -> None:
    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        return NormalizedActionResult(data={"completed": True})

    session = _session()
    candidate_id = f"agent_unstable_{name}"
    await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
        (_action(name, candidate_id=candidate_id, params=params, target=target, intent="完成当前业务操作"),)
    )

    payload = session.candidates[candidate_id].model_dump(mode="json")
    assert payload["action_hint"] == {"kind": "agent", "instruction": "完成当前业务操作", "target_hint": None}
    serialized = str(payload).lower()
    assert "coordinate_x" not in serialized
    assert "index" not in serialized
    assert "runtime_main" not in serialized
    assert "document.title" not in serialized


@pytest.mark.asyncio
async def test_frame_scope_is_stable_and_executor_exception_consumes_reservation() -> None:
    frame = {
        "name": "验收表单 iframe",
        "locators": [{"strategy": "title", "value": "验收登记", "exact": True}],
    }

    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        raise RuntimeError("secret=TOP-SECRET token=random-token")

    session = _session()
    with pytest.raises(RuntimeError, match="secret=TOP-SECRET"):
        await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
            (_action("click", candidate_id="agent_iframe", frame_path=(frame,)),)
        )

    candidate = session.candidates["agent_iframe"]
    assert candidate.scope_hint.page_ref == "main"
    assert candidate.scope_hint.frame_path[0].name == "验收表单 iframe"
    assert candidate.execution.status == "failed"
    assert candidate.execution.error.code == "tool_execution_exception"
    assert candidate.execution.error.message == "Browser action execution failed."
    assert "TOP-SECRET" not in str(candidate.model_dump(mode="json"))
    assert "random-token" not in str(candidate.model_dump(mode="json"))
    assert session.outstanding_agent_reservation_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runtime_page_ref", "page_ref", "error"),
    [
        ("runtime_unknown", "main", "runtime_page_unknown"),
        ("runtime_main", "page_999", "page_ref_mismatch"),
    ],
)
async def test_adapter_reuses_registered_host_page_scope_before_execution(
    runtime_page_ref: str,
    page_ref: str,
    error: str,
) -> None:
    calls = 0

    async def executor(_: ActualToolAction) -> NormalizedActionResult:
        nonlocal calls
        calls += 1
        return NormalizedActionResult(data={"dispatched": True})

    session = _session()
    with pytest.raises(ValueError, match=f"browser_use_adapter.{error}"):
        await BrowserUseRecordingAdapter(session=session, executor=executor).record_round(
            (
                _action(
                    "click",
                    candidate_id=f"agent_scope_{error}",
                    runtime_page_ref=runtime_page_ref,
                    page_ref=page_ref,
                ),
            )
        )

    assert calls == 0
    assert session.outstanding_agent_reservation_count == 0


def test_browser_use_version_gate_reads_local_metadata_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixtures = Path(__file__).with_name("fixtures")
    good = fixtures / "browser_use_good"
    assert assert_browser_use_version(good) == BROWSER_USE_BASELINE_VERSION == "0.13.2"

    bad = fixtures / "browser_use_bad"
    with pytest.raises(ValueError, match="browser_use.version_unsupported:0.14.0"):
        assert_browser_use_version(bad)

    monkeypatch.delenv("BROWSER_USE_REPO_PATH", raising=False)
    assert assert_browser_use_version(version_provider=lambda: "0.13.2") == "0.13.2"


def test_normalized_dtos_reject_non_json_values_and_copy_inputs() -> None:
    params = {"nested": ["before"]}
    action = _action("click", candidate_id="agent_copy", params=params)
    params["nested"][0] = "after"
    assert action.params == {"nested": ["before"]}

    with pytest.raises(ValueError, match="browser_use_adapter.not_json_safe"):
        _action("click", candidate_id="agent_bad", params={"bad": object()})

    with pytest.raises(ValueError, match="browser_use_adapter.local_asset_path_forbidden"):
        _action(
            "upload_file",
            candidate_id="agent_upload_path",
            params={
                "asset_ref": "acceptance_file",
                "file_path": r"C:\\Users\\tester\\Downloads\\acceptance.xlsx",
            },
        )
