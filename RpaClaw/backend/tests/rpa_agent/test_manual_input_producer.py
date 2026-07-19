from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Callable

import pytest

from backend.rpa_agent.creation import SkillCreationSession
from backend.rpa_agent.host.browser_session import BrowserSession, HostBrowserEvent
from backend.rpa_agent.host.manual_input import (
    ManualInputCommand,
    ManualInputProducer,
    ManualTarget,
)


class FakeBrowserPort:
    main_page_runtime_ref = "runtime_main"
    main_frame_runtime_ref = "frame_main"

    def __init__(self) -> None:
        self.context = object()
        self.main_page = object()
        self.listeners: dict[str, list[Callable[[object], None]]] = defaultdict(list)

    def subscribe(self, kind: str, callback: Callable[[object], None]):
        self.listeners[kind].append(callback)
        return lambda: self.listeners[kind].remove(callback)


class FakeManualPort:
    def __init__(self) -> None:
        self.target = ManualTarget(
            page_runtime_ref="runtime_main",
            frame_runtime_ref="frame_main",
            target_key="query-button",
            target_name="查询",
            target_locators=(
                {"strategy": "role", "role": "button", "name": "查询", "exact": True},
            ),
            interaction_kind="click",
            handle=object(),
        )
        self.order: list[str] = []
        self.value = ""
        self.checked = False
        self.click_count = 0
        self.text_count = 0
        self.click_error: BaseException | None = None
        self.on_click: Callable[[], None] | None = None
        self.read_checked_error: BaseException | None = None

    async def resolve_pointer_target(self, *, x: float, y: float) -> ManualTarget:
        self.order.append(f"resolve:{x}:{y}")
        return self.target

    async def resolve_focused_target(self) -> ManualTarget:
        self.order.append("resolve-focused")
        return self.target

    @asynccontextmanager
    async def action_dispatch_scope(self, target: ManualTarget):
        self.order.append("scope-enter")
        yield
        self.order.append("scope-exit")

    async def click(self, target: ManualTarget) -> None:
        self.order.append("click")
        self.click_count += 1
        if self.on_click is not None:
            self.on_click()
        if self.click_error is not None:
            raise self.click_error

    async def insert_text(self, target: ManualTarget, text: str) -> None:
        self.order.append(f"text:{text}")
        self.text_count += 1
        self.value += text

    async def read_value(self, target: ManualTarget) -> str:
        return self.value

    async def read_checked(self, target: ManualTarget) -> bool:
        if self.read_checked_error is not None:
            raise self.read_checked_error
        return self.checked


def _producer() -> tuple[ManualInputProducer, BrowserSession, FakeManualPort]:
    creation = SkillCreationSession(
        session_id="creation_manual_input",
        main_runtime_ref="runtime_main",
        fact_buffer_capacity=32,
        fact_ttl=timedelta(seconds=30),
    )
    browser = BrowserSession(port=FakeBrowserPort(), creation=creation)
    manual = FakeManualPort()
    producer = ManualInputProducer(browser=browser, port=manual)
    return producer, browser, manual


@pytest.mark.asyncio
async def test_click_reserves_before_playwright_default_action() -> None:
    producer, browser, manual = _producer()
    original_reserve = browser.reserve_manual

    def reserve(**kwargs: object) -> str:
        manual.order.append("reserve")
        return original_reserve(**kwargs)

    browser.reserve_manual = reserve  # type: ignore[method-assign]

    result = await producer.dispatch(
        ManualInputCommand(input_id="input_click_1", kind="click", x=20, y=30)
    )

    assert result.candidate_ids == (result.candidate_id,)
    assert manual.order.index("reserve") < manual.order.index("click")
    assert manual.order.index("scope-enter") < manual.order.index("click")
    assert manual.order.index("click") < manual.order.index("scope-exit")
    trace = browser.creation.accepted_traces[result.candidate_id]
    assert trace.action.kind == "click"


@pytest.mark.asyncio
async def test_editable_click_reserves_and_opens_fill_before_default_action() -> None:
    producer, browser, manual = _producer()
    manual.target = ManualTarget(
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
        target_key="order-number",
        target_name="order number",
        target_locators=(
            {"strategy": "label", "value": "order number", "exact": True},
        ),
        interaction_kind="fill",
        handle=object(),
    )
    original_reserve = browser.reserve_manual

    def reserve(**kwargs: object) -> str:
        manual.order.append("reserve")
        return original_reserve(**kwargs)

    browser.reserve_manual = reserve  # type: ignore[method-assign]

    result = await producer.dispatch(
        ManualInputCommand(input_id="input_focus_1", kind="click", x=20, y=30)
    )

    assert result.candidate_id.startswith("manual_")
    assert result.candidate_ids == ()
    assert manual.order.index("reserve") < manual.order.index("click")
    assert browser.creation.reservation_count == 1

    finalized = browser.finalize_recording(at=datetime.now(timezone.utc))
    assert finalized == (result.candidate_id,)
    candidate = browser.creation.candidates[result.candidate_id]
    assert candidate.execution.status == "cancelled"
    assert result.candidate_id in browser.creation.diagnostics


@pytest.mark.asyncio
async def test_default_action_failure_records_rejected_candidate_and_closes_window() -> None:
    producer, browser, manual = _producer()
    manual.click_error = RuntimeError("playwright click failed")

    with pytest.raises(ValueError, match="manual_input.dispatch_failed"):
        await producer.dispatch(
            ManualInputCommand(input_id="input_click_failed", kind="click", x=1, y=2)
        )

    candidates = tuple(browser.creation.candidates.values())
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.execution.status == "failed"
    assert candidate.candidate_id in browser.creation.diagnostics
    assert browser.creation.reservation_count == 1

    with pytest.raises(ValueError, match="manual_input.dispatch_failed"):
        await producer.dispatch(
            ManualInputCommand(input_id="input_click_failed", kind="click", x=1, y=2)
        )
    assert manual.click_count == 1


@pytest.mark.asyncio
async def test_failed_action_with_real_popup_fact_is_retained_for_confirmation() -> None:
    producer, browser, manual = _producer()
    manual.on_click = lambda: browser.handle_event(
        HostBrowserEvent(
            kind="new_page",
            observed_at=datetime.now(timezone.utc),
            source_page_runtime_ref="runtime_main",
            source_frame_runtime_ref="frame_main",
            runtime_page_ref="runtime_popup",
            detail={"initial_url": "https://example.invalid/random"},
        )
    )
    manual.click_error = RuntimeError("tool reported failure after popup")

    with pytest.raises(ValueError, match="manual_input.dispatch_failed"):
        await producer.dispatch(
            ManualInputCommand(input_id="input_popup_failed", kind="click", x=3, y=4)
        )

    candidate = next(iter(browser.creation.candidates.values()))
    assert candidate.execution.status == "failed"
    assert browser.creation.candidate_has_fact(candidate.candidate_id, "new_page")
    attempt = browser.creation.settlement_attempts[candidate.candidate_id]
    assert attempt.status.value == "needs_confirmation"
    assert attempt.reason == "failed_with_side_effect"
    assert candidate.candidate_id not in browser.creation.diagnostics


@pytest.mark.asyncio
async def test_checkbox_state_read_failure_does_not_leave_open_manual_window() -> None:
    producer, browser, manual = _producer()
    manual.read_checked_error = RuntimeError("element detached after click")
    manual.target = ManualTarget(
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
        target_key="acceptance-confirmed",
        target_name="confirmation",
        target_locators=(
            {"strategy": "role", "role": "checkbox", "name": "confirmation", "exact": True},
        ),
        interaction_kind="set_checked",
        handle=object(),
    )

    with pytest.raises(ValueError, match="manual_input.dispatch_failed"):
        await producer.dispatch(
            ManualInputCommand(input_id="input_checkbox_failed", kind="click", x=8, y=9)
        )

    candidate = next(iter(browser.creation.candidates.values()))
    assert candidate.execution.status == "failed"
    assert candidate.candidate_id in browser.creation.diagnostics
    assert browser.finalize_recording(at=datetime.now(timezone.utc)) == ()


@pytest.mark.asyncio
async def test_duplicate_input_id_does_not_dispatch_twice() -> None:
    producer, _browser, manual = _producer()
    command = ManualInputCommand(input_id="input_click_duplicate", kind="click", x=1, y=2)

    first = await producer.dispatch(command)
    second = await producer.dispatch(command)

    assert second == first
    assert manual.click_count == 1


@pytest.mark.asyncio
async def test_continuous_text_inputs_flush_as_one_fill_candidate_on_target_switch() -> None:
    producer, browser, manual = _producer()
    manual.target = ManualTarget(
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
        target_key="order-number",
        target_name="订单号",
        target_locators=({"strategy": "label", "value": "订单号", "exact": True},),
        interaction_kind="fill",
        handle=object(),
    )

    first = await producer.dispatch(
        ManualInputCommand(input_id="input_text_1", kind="text", text="PO-")
    )
    second = await producer.dispatch(
        ManualInputCommand(input_id="input_text_2", kind="text", text="1001")
    )
    assert first.candidate_ids == ()
    assert second.candidate_ids == ()

    manual.target = ManualTarget(
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
        target_key="query-button",
        target_name="查询",
        target_locators=(
            {"strategy": "role", "role": "button", "name": "查询", "exact": True},
        ),
        interaction_kind="click",
        handle=object(),
    )
    click = await producer.dispatch(
        ManualInputCommand(input_id="input_click_after_fill", kind="click", x=5, y=6)
    )

    traces = sorted(browser.creation.accepted_traces.values(), key=lambda item: item.sequence)
    assert [trace.action.kind for trace in traces] == ["fill", "click"]
    assert traces[0].data_bindings[0].value == "PO-1001"
    assert click.candidate_ids == (click.candidate_id,)


@pytest.mark.asyncio
async def test_checkbox_reads_real_checked_state_and_emits_one_set_checked() -> None:
    producer, browser, manual = _producer()
    manual.checked = True
    manual.target = ManualTarget(
        page_runtime_ref="runtime_main",
        frame_runtime_ref="frame_main",
        target_key="acceptance-confirmed",
        target_name="确认信息",
        target_locators=(
            {"strategy": "role", "role": "checkbox", "name": "确认信息", "exact": True},
        ),
        interaction_kind="set_checked",
        handle=object(),
    )

    result = await producer.dispatch(
        ManualInputCommand(input_id="input_checkbox_1", kind="click", x=8, y=9)
    )

    trace = browser.creation.accepted_traces[result.candidate_id]
    assert trace.action.kind == "set_checked"
    assert trace.action.checked is True


@pytest.mark.asyncio
async def test_same_input_id_with_different_payload_fails_closed() -> None:
    producer, _browser, _manual = _producer()
    await producer.dispatch(
        ManualInputCommand(input_id="input_conflict", kind="click", x=1, y=2)
    )

    with pytest.raises(ValueError, match="manual_input.id_payload_conflict"):
        await producer.dispatch(
            ManualInputCommand(input_id="input_conflict", kind="click", x=2, y=2)
        )
