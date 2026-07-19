from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import importlib.metadata
from pathlib import Path
import runpy
import json
from typing import Any

import pytest

from rpa_agent.browser_use import (
    ActualToolAction,
    BrowserPageState,
    BrowserUseContextRequest,
    BrowserUseInvocationNormalizer,
    BrowserUseRecordingAdapter,
    RecordingCancelledError,
    TargetResolution,
    assert_browser_use_version,
    build_minimal_context,
    normalize_action_result,
    thaw_browser_use_value,
)
from rpa_agent.creation import ControlMode, SkillCreationSession


NOW = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)
TARGET_WITH_INDEXES = {
    "name": "发起验收",
    "index": 88,
    "locators": [{"strategy": "role", "role": "button", "name": "发起验收", "exact": True}],
    "path": [
        {
            "name": "订单行",
            "index": 7,
            "locators": [{"strategy": "role", "role": "row", "name": "PO-1001", "exact": True}],
        }
    ],
}


@dataclass
class DuckActionResult:
    error: str | None = None
    success: bool | None = None
    is_done: bool | None = False
    extracted_content: str | None = None
    long_term_memory: str | None = None
    metadata: dict[str, Any] | None = None


def _session() -> SkillCreationSession:
    session = SkillCreationSession(
        session_id="session_real_boundary",
        main_runtime_ref="runtime_main",
        fact_buffer_capacity=32,
        fact_ttl=timedelta(seconds=10),
    )
    session.switch_control(ControlMode.AGENT, at=NOW)
    return session


def _register_popup(session: SkillCreationSession) -> None:
    trigger = session.observer.start_new_page("runtime_main", "frame_main")
    fact = session.observer.complete_new_page(
        trigger,
        observed_at=NOW,
        new_page_runtime_ref="runtime_popup",
        initial_url="https://system-b.test/form",
    )
    session.pages.apply(fact)


def _normalizer(session: SkillCreationSession) -> BrowserUseInvocationNormalizer:
    return BrowserUseInvocationNormalizer(
        page_registry=session.pages,
        tab_runtime_resolver=lambda tab_id: {
            "aaaa": "runtime_main",
            "bbbb": "runtime_popup",
        }[tab_id],
        main_frame_resolver=lambda runtime_ref: f"frame_{runtime_ref}",
        asset_ref_resolver=lambda path: {
            r"C:\\managed\\acceptance.xlsx": "acceptance_file"
        }[path],
        frame_path_resolver=lambda _page, frame: (
            ()
            if frame == "frame_main"
            else ({
                "name": "验收登记 iframe",
                "locators": [{
                    "strategy": "title",
                    "value": "验收登记",
                    "exact": True,
                }],
            },)
        ),
    )


def _actual_params_classes() -> dict[str, type]:
    views_path = Path(r"E:\RPA-Agent\browser-use\browser_use\tools\views.py")
    return runpy.run_path(str(views_path))


def test_real_0132_param_models_normalize_select_scroll_and_source_index() -> None:
    classes = _actual_params_classes()
    session = _session()
    normalizer = _normalizer(session)

    selected = normalizer.normalize(
        "select_dropdown",
        classes["SelectDropdownOptionAction"](index=12, text="已审批"),
        candidate_id="agent_select_real",
        business_intent="选择审批状态",
        source_page_runtime_ref="runtime_main",
        source_frame_runtime_ref="frame_main",
    )
    scrolled = normalizer.normalize(
        "scroll",
        classes["ScrollAction"](down=False, pages=2.0, index=9),
        candidate_id="agent_scroll_real",
        business_intent="向上滚动两页加载历史订单",
        source_page_runtime_ref="runtime_main",
        source_frame_runtime_ref="frame_main",
        business_required=True,
    )

    assert selected.params == {"option": "已审批"}
    assert selected.source_index == 12
    assert scrolled.params == {
        "direction": "up",
        "amount": 2,
        "unit": "viewport",
        "business_required": True,
    }
    assert scrolled.source_index == 9


def test_real_0132_click_coordinates_are_short_lived_agent_execution_params() -> None:
    classes = _actual_params_classes()
    action = _normalizer(_session()).normalize(
        "click",
        classes["ClickElementAction"](coordinate_x=120, coordinate_y=240),
        candidate_id="agent_coordinate_click",
        business_intent="点击画布中的发起验收图标",
        source_page_runtime_ref="runtime_main",
        source_frame_runtime_ref="frame_main",
    )

    assert action.params == {"coordinate_x": 120, "coordinate_y": 240}
    assert action.source_index is None


def test_invocation_normalizer_resolves_stable_iframe_scope() -> None:
    action = _normalizer(_session()).normalize(
        "input",
        {"index": 3, "text": "PO-1001"},
        candidate_id="agent_iframe_input",
        business_intent="填写验收订单号",
        source_page_runtime_ref="runtime_main",
        source_frame_runtime_ref="frame_iframe",
    )

    assert action.frame_path == ({
        "name": "验收登记 iframe",
        "locators": [{
            "strategy": "title",
            "value": "验收登记",
            "exact": True,
        }],
    },)
    assert "frame_iframe" not in str(action.frame_path)


def test_real_0132_switch_and_close_tab_ids_resolve_through_host_page_registry() -> None:
    classes = _actual_params_classes()
    session = _session()
    _register_popup(session)
    normalizer = _normalizer(session)

    switched = normalizer.normalize(
        "switch",
        classes["SwitchTabAction"](tab_id="bbbb"),
        candidate_id="agent_switch_real",
        business_intent="切换到验收登记页面",
        source_page_runtime_ref="runtime_main",
        source_frame_runtime_ref="frame_main",
    )
    closed = normalizer.normalize(
        "close",
        classes["CloseTabAction"](tab_id="bbbb"),
        candidate_id="agent_close_real",
        business_intent="关闭验收登记页面",
        source_page_runtime_ref="runtime_main",
        source_frame_runtime_ref="frame_main",
    )

    assert switched.runtime_page_ref == "runtime_main"
    assert switched.page_ref == "main"
    assert switched.params == {"page_ref": "page_001"}
    assert closed.runtime_page_ref == "runtime_popup"
    assert closed.page_ref == "page_001"
    assert "tab_id" not in str(switched)
    assert "bbbb" not in str(closed)


def test_upload_real_path_becomes_asset_ref_and_path_never_enters_dto() -> None:
    classes = _actual_params_classes()
    action = _normalizer(_session()).normalize(
        "upload_file",
        classes["UploadFileAction"](
            index=4,
            path=r"C:\\managed\\acceptance.xlsx",
        ),
        candidate_id="agent_upload_real",
        business_intent="上传验收附件",
        source_page_runtime_ref="runtime_main",
        source_frame_runtime_ref="frame_main",
    )

    assert action.params == {"asset_ref": "acceptance_file"}
    assert action.source_index == 4
    assert "C:\\managed" not in str(action)


def test_duck_action_result_uses_only_status_fields_and_provider_evidence() -> None:
    raw = DuckActionResult(
        error=None,
        success=None,
        extracted_content="Typed a secret token=SHOULD-NOT-TRUST",
        long_term_memory="Browser History private payload",
        metadata={"actual_value": "WRONG", "runtime_page_id": "private-tab"},
    )

    normalized = normalize_action_result(
        "input",
        raw,
        evidence={"dom_value": "PO-1001"},
    )

    assert normalized.error is None
    assert normalized.success is None
    assert normalized.data == {"dom_value": "PO-1001"}
    assert "secret" not in str(normalized).lower()
    assert "history" not in str(normalized).lower()
    assert "runtime_page_id" not in str(normalized)
    with pytest.raises(ValueError, match="browser_use_result.evidence_key_forbidden"):
        normalize_action_result("click", raw, evidence={"history": ["private"]})


@pytest.mark.asyncio
async def test_adapter_accepts_duck_action_result_and_requires_unique_target_probe() -> None:
    async def executor(_: ActualToolAction) -> DuckActionResult:
        return DuckActionResult(error=None, success=None)

    async def evidence(_: ActualToolAction, __: object) -> dict[str, Any]:
        return {"dispatched": True}

    for match_count, expected_kind in ((0, "agent"), (1, "click"), (2, "agent")):
        session = _session()
        action = ActualToolAction(
            action_name="click",
            candidate_id=f"agent_probe_{match_count}",
            params={},
            business_intent="点击发起验收",
            runtime_page_ref="runtime_main",
            runtime_frame_ref="frame_main",
            page_ref="main",
            frame_path=(),
            target_hint=TARGET_WITH_INDEXES,
            binding_hints=(),
            source_index=88,
        )
        adapter = BrowserUseRecordingAdapter(
            session=session,
            executor=executor,
            evidence_provider=evidence,
            target_resolver=lambda _: TargetResolution(
                target_hint=TARGET_WITH_INDEXES,
                match_count=match_count,
            ),
            version_provider=lambda: "0.13.2",
            clock=lambda: NOW,
        )
        await adapter.record_round((action,))
        candidate = session.candidates[action.candidate_id]
        assert candidate.action_hint.kind == expected_kind
        # Persistence/settlement serializes optional contract fields with
        # ``exclude_none``; assert no concrete Browser-use DOM index survives.
        dumped = candidate.model_dump(mode="json", exclude_none=True)
        assert "index" not in str(dumped)


@pytest.mark.asyncio
@pytest.mark.parametrize("match_count,expected_kind", [(0, "agent"), (1, "click"), (2, "agent")])
async def test_source_index_is_resolved_to_stable_target_before_mapping(
    match_count: int, expected_kind: str
) -> None:
    session = _session()
    seen_indexes: list[int | None] = []

    async def resolver(action: ActualToolAction) -> TargetResolution:
        seen_indexes.append(action.source_index)
        return TargetResolution(TARGET_WITH_INDEXES, match_count)

    action = ActualToolAction(
        action_name="click",
        candidate_id=f"agent_index_only_{match_count}",
        params={},
        business_intent="点击发起验收",
        runtime_page_ref="runtime_main",
        runtime_frame_ref="frame_main",
        page_ref="main",
        frame_path=(),
        target_hint=None,
        binding_hints=(),
        source_index=12,
    )
    adapter = BrowserUseRecordingAdapter(
        session=session,
        executor=lambda _: DuckActionResult(),
        evidence_provider=lambda *_: {"dispatched": True},
        target_resolver=resolver,
        version_provider=lambda: "0.13.2",
        clock=lambda: NOW,
    )
    await adapter.record_round((action,))

    candidate = session.candidates[action.candidate_id]
    assert seen_indexes == [12]
    assert candidate.action_hint.kind == expected_kind
    persisted = candidate.model_dump(mode="json", exclude_none=True)
    persisted.pop("candidate_id")
    assert "index" not in str(persisted)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "match_count,expected_kind,expects_target",
    [(0, "agent", False), (1, "scroll", True), (2, "agent", False)],
)
async def test_element_scoped_scroll_never_falls_back_to_page_scroll(
    match_count: int,
    expected_kind: str,
    expects_target: bool,
) -> None:
    session = _session()
    action = _normalizer(session).normalize(
        "scroll",
        _actual_params_classes()["ScrollAction"](down=True, pages=1.0, index=9),
        candidate_id=f"agent_element_scroll_{match_count}",
        business_intent="在订单列表内向下滚动一页",
        source_page_runtime_ref="runtime_main",
        source_frame_runtime_ref="frame_main",
    )
    adapter = BrowserUseRecordingAdapter(
        session=session,
        executor=lambda _: DuckActionResult(),
        evidence_provider=lambda *_: {"completed": True},
        target_resolver=lambda _: TargetResolution(TARGET_WITH_INDEXES, match_count),
        version_provider=lambda: "0.13.2",
        clock=lambda: NOW,
    )
    await adapter.record_round((action,))

    candidate = session.candidates[action.candidate_id]
    assert candidate.action_hint.kind == expected_kind
    target = getattr(candidate.action_hint, "target_hint", None)
    assert (target is not None) is expects_target
    persisted = candidate.model_dump(mode="json", exclude_none=True)
    persisted.pop("candidate_id")
    assert "index" not in str(persisted)


@pytest.mark.asyncio
async def test_coordinate_click_executes_once_as_agent_without_target_resolution() -> None:
    session = _session()
    executions = 0
    resolutions = 0
    action = _normalizer(session).normalize(
        "click",
        _actual_params_classes()["ClickElementAction"](
            coordinate_x=120, coordinate_y=240
        ),
        candidate_id="agent_coordinate_execute",
        business_intent="点击画布中的发起验收图标",
        source_page_runtime_ref="runtime_main",
        source_frame_runtime_ref="frame_main",
    )

    async def executor(actual: ActualToolAction) -> DuckActionResult:
        nonlocal executions
        executions += 1
        assert actual.params == {"coordinate_x": 120, "coordinate_y": 240}
        return DuckActionResult()

    async def resolver(_: ActualToolAction) -> TargetResolution:
        nonlocal resolutions
        resolutions += 1
        return TargetResolution(None, 0)

    adapter = BrowserUseRecordingAdapter(
        session=session,
        executor=executor,
        evidence_provider=lambda *_: {"completed": True},
        target_resolver=resolver,
        version_provider=lambda: "0.13.2",
        clock=lambda: NOW,
    )
    await adapter.record_round((action,))

    candidate = session.candidates[action.candidate_id]
    assert executions == 1
    assert resolutions == 0
    assert candidate.action_hint.kind == "agent"
    persisted = candidate.model_dump(mode="json", exclude_none=True)
    persisted.pop("candidate_id")
    serialized = str(persisted)
    assert "coordinate" not in serialized
    assert "index" not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://system.test/orders?token=abc",
        "https://system.test/orders#session",
        "https://system.test/order/550e8400-e29b-41d4-a716-446655440000",
        "https://system.test/open/4f9a8c7d6e5b3a210fedcba987654321",
    ],
)
async def test_dynamic_literal_navigate_downgrades_without_persisting_url(url: str) -> None:
    async def executor(_: ActualToolAction) -> DuckActionResult:
        return DuckActionResult()

    session = _session()
    action = ActualToolAction(
        action_name="navigate",
        candidate_id="agent_dynamic_url",
        params={"url": url},
        business_intent="进入订单页面",
        runtime_page_ref="runtime_main",
        runtime_frame_ref="frame_main",
        page_ref="main",
        frame_path=(),
        target_hint=None,
        binding_hints=(),
        source_index=None,
    )
    adapter = BrowserUseRecordingAdapter(
        session=session,
        executor=executor,
        evidence_provider=lambda *_: {"url_reached": True},
        target_resolver=lambda _: TargetResolution(target_hint=None, match_count=0),
        version_provider=lambda: "0.13.2",
        clock=lambda: NOW,
    )
    await adapter.record_round((action,))

    candidate = session.candidates[action.candidate_id]
    assert candidate.action_hint.kind == "agent"
    assert url not in str(candidate.model_dump(mode="json"))


def test_version_without_repo_checks_distribution_and_never_assumes_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BROWSER_USE_REPO_PATH", raising=False)
    assert assert_browser_use_version(version_provider=lambda: "0.13.2") == "0.13.2"
    with pytest.raises(ValueError, match="browser_use.version_unsupported:0.14.0"):
        assert_browser_use_version(version_provider=lambda: "0.14.0")

    def missing(_: str) -> str:
        raise importlib.metadata.PackageNotFoundError("browser-use")

    monkeypatch.setattr(importlib.metadata, "version", missing)
    with pytest.raises(ValueError, match="browser_use.version_distribution_missing"):
        assert_browser_use_version()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "completed_at",
    [
        datetime(2026, 7, 18, 9, 0),
        NOW - timedelta(seconds=1),
    ],
)
async def test_invalid_completed_at_fails_before_reserve_and_executor(
    completed_at: datetime,
) -> None:
    calls = 0

    async def executor(_: ActualToolAction) -> DuckActionResult:
        nonlocal calls
        calls += 1
        return DuckActionResult()

    session = _session()
    adapter = BrowserUseRecordingAdapter(
        session=session,
        executor=executor,
        evidence_provider=lambda *_: {"dispatched": True},
        target_resolver=lambda action: TargetResolution(action.target_hint, 1),
        version_provider=lambda: "0.13.2",
        clock=lambda: NOW,
    )
    action = ActualToolAction(
        action_name="click",
        candidate_id="agent_bad_time",
        params={},
        business_intent="点击按钮",
        runtime_page_ref="runtime_main",
        runtime_frame_ref="frame_main",
        page_ref="main",
        frame_path=(),
        target_hint=TARGET_WITH_INDEXES,
        binding_hints=(),
        source_index=1,
    )

    with pytest.raises(ValueError, match="browser_use_adapter.completed_at"):
        await adapter.record_round((action,), completed_at=completed_at)
    assert calls == 0
    assert session.outstanding_agent_reservation_count == 0


@pytest.mark.asyncio
async def test_system_exit_registers_failed_candidate_then_propagates_original() -> None:
    async def executor(_: ActualToolAction) -> DuckActionResult:
        raise SystemExit(17)

    session = _session()
    action = ActualToolAction(
        action_name="click",
        candidate_id="agent_system_exit",
        params={},
        business_intent="点击按钮",
        runtime_page_ref="runtime_main",
        runtime_frame_ref="frame_main",
        page_ref="main",
        frame_path=(),
        target_hint=TARGET_WITH_INDEXES,
        binding_hints=(),
        source_index=1,
    )
    adapter = BrowserUseRecordingAdapter(
        session=session,
        executor=executor,
        evidence_provider=lambda *_: {},
        target_resolver=lambda current: TargetResolution(current.target_hint, 1),
        version_provider=lambda: "0.13.2",
        clock=lambda: NOW,
    )

    with pytest.raises(SystemExit, match="17"):
        await adapter.record_round((action,), completed_at=NOW + timedelta(seconds=1))
    assert session.candidates[action.candidate_id].execution.status == "failed"
    assert session.outstanding_agent_reservation_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("clock_failure", ["naive", "raised"])
async def test_post_reserve_clock_failure_finalizes_candidate_and_propagates(
    clock_failure: str,
) -> None:
    calls = 0

    def clock() -> datetime:
        nonlocal calls
        calls += 1
        if calls == 1:
            return NOW
        if clock_failure == "naive":
            return datetime(2026, 7, 18, 9, 0)
        raise RuntimeError("clock backend failed")

    session = _session()
    action = ActualToolAction(
        action_name="click",
        candidate_id=f"agent_clock_{clock_failure}",
        params={},
        business_intent="点击发起验收",
        runtime_page_ref="runtime_main",
        runtime_frame_ref="frame_main",
        page_ref="main",
        frame_path=(),
        target_hint=TARGET_WITH_INDEXES,
        binding_hints=(),
    )
    adapter = BrowserUseRecordingAdapter(
        session=session,
        executor=lambda _: DuckActionResult(),
        evidence_provider=lambda *_: {"dispatched": True},
        target_resolver=lambda current: TargetResolution(current.target_hint, 1),
        version_provider=lambda: "0.13.2",
        clock=clock,
    )

    expected = ValueError if clock_failure == "naive" else RuntimeError
    with pytest.raises(expected):
        await adapter.record_round((action,))
    assert session.candidates[action.candidate_id].execution.status == "failed"
    assert session.outstanding_agent_reservation_count == 0


@pytest.mark.asyncio
async def test_non_sop_cancel_propagates_immutable_partial_accounting() -> None:
    calls = 0

    async def executor(_: ActualToolAction) -> DuckActionResult:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise asyncio.CancelledError()
        return DuckActionResult(is_done=True, success=True)

    session = _session()
    adapter = BrowserUseRecordingAdapter(
        session=session,
        executor=executor,
        evidence_provider=lambda *_: {},
        target_resolver=lambda action: TargetResolution(action.target_hint, 0),
        version_provider=lambda: "0.13.2",
        clock=lambda: NOW,
    )
    actions = tuple(
        ActualToolAction(
            action_name=name,
            candidate_id=f"non_sop_{index}",
            params={},
            business_intent=name,
            runtime_page_ref="runtime_main",
            runtime_frame_ref="frame_main",
            page_ref="main",
            frame_path=(),
            target_hint=None,
            binding_hints=(),
            source_index=None,
        )
        for index, name in enumerate(("wait", "done", "observe"), start=1)
    )

    with pytest.raises(RecordingCancelledError) as captured:
        await adapter.record_round(actions)
    report = captured.value.partial_report
    assert report.invocation_count == 2
    assert report.actual_action_count == 2
    assert [item.status for item in report.non_sop] == ["succeeded", "cancelled"]
    with pytest.raises(Exception):
        report.non_sop[0].status = "mutated"


@pytest.mark.asyncio
async def test_non_sop_system_exit_propagates_original_with_partial_accounting() -> None:
    session = _session()
    action = ActualToolAction(
        action_name="wait",
        candidate_id="non_sop_system_exit",
        params={},
        business_intent="等待页面准备",
        runtime_page_ref="runtime_main",
        runtime_frame_ref="frame_main",
        page_ref="main",
        frame_path=(),
        target_hint=None,
        binding_hints=(),
    )
    adapter = BrowserUseRecordingAdapter(
        session=session,
        executor=lambda _: (_ for _ in ()).throw(SystemExit(23)),
        evidence_provider=lambda *_: {},
        target_resolver=lambda _: TargetResolution(None, 0),
        version_provider=lambda: "0.13.2",
        clock=lambda: NOW,
    )

    with pytest.raises(SystemExit, match="23") as captured:
        await adapter.record_round((action,))
    report = captured.value.browser_use_partial_report
    assert report.invocation_count == 1
    assert report.actual_action_count == 1
    assert [(item.status, item.reason) for item in report.non_sop] == [
        ("failed", "tool_execution_interrupted")
    ]
    with pytest.raises(Exception):
        report.non_sop[0].status = "mutated"


@pytest.mark.asyncio
async def test_blocked_and_unknown_tools_have_explicit_pre_execution_accounting() -> None:
    calls = 0

    async def executor(_: ActualToolAction) -> DuckActionResult:
        nonlocal calls
        calls += 1
        return DuckActionResult()

    session = _session()
    adapter = BrowserUseRecordingAdapter(
        session=session,
        executor=executor,
        evidence_provider=lambda *_: {},
        target_resolver=lambda action: TargetResolution(action.target_hint, 0),
        version_provider=lambda: "0.13.2",
        clock=lambda: NOW,
    )
    actions = tuple(
        ActualToolAction(
            action_name=name,
            candidate_id=f"blocked_{index}",
            params={},
            business_intent=name,
            runtime_page_ref="runtime_main",
            runtime_frame_ref="frame_main",
            page_ref="main",
            frame_path=(),
            target_hint=None,
            binding_hints=(),
            source_index=None,
        )
        for index, name in enumerate(("search", "save_as_pdf", "future_unknown_tool"), start=1)
    )
    report = await adapter.record_round(actions)

    assert calls == 0
    assert report.actual_action_count == 0
    assert [item.action_name for item in report.blocked] == [
        "search", "save_as_pdf", "future_unknown_tool"
    ]
    assert report.invocation_count == 3


def test_context_uses_strong_page_state_secret_names_and_full_safety_filter() -> None:
    session = _session()
    session.variables.write(
        "采购订单.订单号",
        "PO-1001",
        producer_candidate_id="candidate_extract",
    )
    request = BrowserUseContextRequest(
        current_instruction="填写采购订单并发起验收",
        current_page_state=BrowserPageState(
            title="采购订单",
            url="https://system.test/orders",
            interactive_elements=("订单号输入框", "发起验收按钮"),
        ),
        business_terms=("采购订单", "验收登记"),
        required_variable_refs=("采购订单.订单号",),
        allowed_inputs={"acceptance_date": "验收日期"},
        allowed_secret_names=("erp_password",),
        allowed_data_assets={"attachment": "验收附件"},
        page_aliases={"main": "采购系统"},
    )
    context = build_minimal_context(request, variables=session.variables)

    assert context["allowed_secret_names"] == ["erp_password"]
    assert "password" not in str(context).lower().replace("erp_password", "")
    assert context["current_page_state"]["url"] == "https://system.test/orders"

    unsafe_values = [
        r"C:\\Users\\tester\\secret.txt",
        "/tmp/secret.txt",
        "token=abc123",
        "Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",
    ]
    for unsafe in unsafe_values:
        session.variables.write(
            "采购订单.订单号", unsafe, producer_candidate_id="candidate_unsafe"
        )
        with pytest.raises(ValueError, match="browser_use_context.unsafe_content"):
            build_minimal_context(request, variables=session.variables)

    with pytest.raises(ValueError, match="browser_use_context.page_url_unsafe"):
        BrowserPageState(
            title="采购订单",
            url="https://system.test/orders?token=abc",
            interactive_elements=(),
        )


def test_context_rejects_explicit_password_label_and_url_userinfo() -> None:
    session = _session()
    session.variables.write(
        "采购订单.订单号", "password=hunter2", producer_candidate_id="candidate_password"
    )
    request = BrowserUseContextRequest(
        current_instruction="填写采购订单",
        current_page_state=BrowserPageState(
            title="采购订单",
            url="https://system.test/orders",
            interactive_elements=("订单号",),
        ),
        business_terms=("密码策略说明",),
        required_variable_refs=("采购订单.订单号",),
        allowed_inputs={},
        allowed_secret_names=(),
        allowed_data_assets={},
        page_aliases={"main": "采购系统"},
    )
    with pytest.raises(ValueError, match="browser_use_context.unsafe_content"):
        build_minimal_context(request, variables=session.variables)

    with pytest.raises(ValueError, match="browser_use_context.page_url_unsafe"):
        BrowserPageState(
            title="采购订单",
            url="https://alice:hunter2@system.test/orders",
            interactive_elements=(),
        )


def test_adapter_dtos_are_deeply_immutable_and_remain_json_compatible() -> None:
    action = ActualToolAction(
        action_name="click",
        candidate_id="agent_immutable",
        params={"nested": {"items": ["before"]}},
        business_intent="点击发起验收",
        runtime_page_ref="runtime_main",
        runtime_frame_ref="frame_main",
        page_ref="main",
        frame_path=({
            "name": "验收 iframe",
            "locators": [{"strategy": "title", "value": "验收登记", "exact": True}],
        },),
        target_hint=TARGET_WITH_INDEXES,
        binding_hints=({
            "name": "value",
            "direction": "input",
            "kind_hint": "literal",
            "value": {"nested": ["before"]},
            "sensitive": False,
        },),
        source_index=9,
    )
    result = normalize_action_result(
        "extract",
        DuckActionResult(),
        evidence={"variables": {"采购订单.订单号": "PO-1001"}},
    )
    resolution = TargetResolution(TARGET_WITH_INDEXES, 1)

    mutations = (
        lambda: action.params.__setitem__("new", True),
        lambda: action.params["nested"]["items"].append("after"),
        lambda: action.target_hint["locators"][0].__setitem__("name", "篡改"),
        lambda: action.binding_hints[0]["value"]["nested"].append("after"),
        lambda: action.frame_path[0]["locators"].append({}),
        lambda: result.data["variables"].__setitem__("采购订单.订单号", "PO-X"),
        lambda: resolution.target_hint.__setitem__("name", "篡改"),
    )
    for mutate in mutations:
        with pytest.raises(TypeError):
            mutate()

    with pytest.raises(TypeError):
        dict.__setitem__(action.params, "bypass", True)
    with pytest.raises(TypeError):
        list.append(action.params["nested"]["items"], "bypass")
    assert deepcopy(action.params) is not action.params
    json_ready = thaw_browser_use_value(action.params)
    assert json.loads(json.dumps(json_ready, ensure_ascii=False))["nested"]["items"] == ["before"]
    json_ready["nested"]["items"].append("host-only")
    assert action.params["nested"]["items"] == ["before"]
    renormalized = normalize_action_result(
        "extract", DuckActionResult(), evidence=result.data
    )
    assert renormalized.data == result.data
    assert deepcopy(action.params) == action.params
