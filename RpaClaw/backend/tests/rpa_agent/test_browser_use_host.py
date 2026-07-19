from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json

import pytest

from rpa_agent.creation import ControlMode, SkillCreationSession
from rpa_agent.host import BrowserSession, HostBrowserEvent, PlaywrightBrowserSessionPort
from rpa_agent.host.browser_use_agent import normalize_variable_action
from rpa_agent.host.browser_use_agent import (
    RecordingBrowserUseTools,
    build_agent_task,
    build_runtime_agent_backend,
    normalize_allowed_input_action,
    semantic_hints_from_browser_use_node,
)
from rpa_agent.api import AgentInstructionRequest
from rpa_agent.host.scienceclaw_browser import (
    acquire_browser_runtime_lease,
    rewrite_cdp_url,
)


NOW = datetime(2026, 7, 18, tzinfo=timezone.utc)


class _Port:
    context = object()
    main_page = object()
    main_page_runtime_ref = "runtime_main"
    main_frame_runtime_ref = "frame_main"

    def __init__(self) -> None:
        self.callbacks = {}

    def subscribe(self, kind, callback):
        self.callbacks[kind] = callback
        return lambda: None


def _creation() -> SkillCreationSession:
    return SkillCreationSession(
        session_id="creation_host_agent",
        main_runtime_ref="runtime_main",
        fact_buffer_capacity=64,
        fact_ttl=timedelta(seconds=30),
    )


def test_variable_aware_input_resolves_session_value_and_preserves_reference():
    creation = _creation()
    creation.variables.write(
        "采购订单.订单号",
        "PO-2002",
        producer_candidate_id="producer_order",
    )

    invocation = normalize_variable_action(
        "input_variable",
        {"index": 7, "variable_ref": "采购订单.订单号"},
        variables=creation.variables,
    )

    assert invocation.action_name == "input"
    assert invocation.params == {"index": 7, "text": "PO-2002", "clear": True}
    assert invocation.binding_hints == (
        {
            "name": "value",
            "direction": "input",
            "kind_hint": "variable",
            "ref_hint": "采购订单.订单号",
            "sensitive": False,
        },
    )


def test_variable_aware_extract_requires_explicit_valid_ref_and_json_value():
    creation = _creation()

    invocation = normalize_variable_action(
        "extract_variable",
        {
            "variable_ref": "采购订单",
            "value": {"订单号": "PO-2002", "供应商": "乙方供应商"},
        },
        variables=creation.variables,
    )

    assert invocation.action_name == "extract_variable"
    assert invocation.variable_outputs == {
        "采购订单": {"订单号": "PO-2002", "供应商": "乙方供应商"}
    }
    assert invocation.binding_hints[0]["ref_hint"] == "采购订单"

    with pytest.raises(ValueError, match="browser_use_host.variable_ref_invalid"):
        normalize_variable_action(
            "extract_variable",
            {"variable_ref": "采购订单..订单号", "value": "x"},
            variables=creation.variables,
        )


def test_extract_variable_adds_whitelisted_skill_input_bindings_without_values():
    creation = _creation()
    invocation = normalize_variable_action(
        "extract_variable",
        {
            "variable_ref": "采购订单",
            "value": {"订单号": "PO-2002"},
            "input_refs": ["order_no", "business_type"],
        },
        variables=creation.variables,
        allowed_inputs={
            "order_no": "PO-RECORDED-2002",
            "business_type": "自动创建",
        },
    )

    assert invocation.binding_hints == (
        {
            "name": "input.order_no",
            "direction": "input",
            "kind_hint": "skill_input",
            "ref_hint": "order_no",
            "sensitive": False,
        },
        {
            "name": "input.business_type",
            "direction": "input",
            "kind_hint": "skill_input",
            "ref_hint": "business_type",
            "sensitive": False,
        },
        {
            "name": "result",
            "direction": "output",
            "kind_hint": "variable",
            "ref_hint": "采购订单",
            "sensitive": False,
        },
    )
    serialized = json.dumps(
        {"params": invocation.params, "bindings": invocation.binding_hints},
        ensure_ascii=False,
    )
    assert "PO-RECORDED-2002" not in serialized
    assert "自动创建" not in serialized

    for refs, code in (
        (["unknown_input"], "allowed_input_unknown"),
        (["order_no", "order_no"], "extract_input_ref_duplicate"),
        (["bad ref"], "input_ref_invalid"),
    ):
        with pytest.raises(ValueError, match=f"browser_use_host.{code}"):
            normalize_variable_action(
                "extract_variable",
                {
                    "variable_ref": "采购订单",
                    "value": {"订单号": "PO-2002"},
                    "input_refs": refs,
                },
                variables=creation.variables,
                allowed_inputs={"order_no": "PO-RECORDED-2002"},
            )


def test_click_variable_keeps_business_ref_and_discards_recording_value():
    creation = _creation()
    creation.variables.write(
        "采购订单.订单号", "PO-RECORDED-2002", producer_candidate_id="producer_order"
    )

    invocation = normalize_variable_action(
        "click_variable",
        {"index": 19, "variable_ref": "采购订单.订单号"},
        variables=creation.variables,
    )

    assert invocation.action_name == "click"
    assert invocation.params == {"index": 19}
    assert invocation.binding_hints == (
        {
            "name": "row_key",
            "direction": "input",
            "kind_hint": "variable",
            "ref_hint": "采购订单.订单号",
            "sensitive": False,
        },
    )
    assert "PO-RECORDED-2002" not in json.dumps(
        {"params": invocation.params, "bindings": invocation.binding_hints},
        ensure_ascii=False,
    )


def test_click_allowed_input_keeps_only_whitelisted_ref_and_rejects_unknown():
    invocation = normalize_allowed_input_action(
        "click_allowed_input",
        {"index": 5, "input_ref": "business_type"},
        allowed_inputs={"business_type": "自动创建"},
    )

    assert invocation.action_name == "click"
    assert invocation.params == {"index": 5}
    assert invocation.binding_hints == (
        {
            "name": "row_key",
            "direction": "input",
            "kind_hint": "skill_input",
            "ref_hint": "business_type",
            "sensitive": False,
        },
    )
    assert "自动创建" not in json.dumps(
        {"params": invocation.params, "bindings": invocation.binding_hints},
        ensure_ascii=False,
    )

    with pytest.raises(ValueError, match="browser_use_host.allowed_input_unknown"):
        normalize_allowed_input_action(
            "click_allowed_input",
            {"index": 5, "input_ref": "unknown_type"},
            allowed_inputs={"business_type": "自动创建"},
        )


def test_page_activation_and_close_events_apply_to_registered_page_with_source_lock():
    creation = _creation()
    browser = BrowserSession(port=_Port(), creation=creation)

    popup_trigger = creation.observer.start_new_page("runtime_main", "frame_main")
    popup = creation.observer.complete_new_page(
        popup_trigger,
        observed_at=NOW,
        new_page_runtime_ref="runtime_popup",
        initial_url="https://example.test/task/opaque",
    )
    assert creation.pages.apply(popup) == "page_001"

    browser.handle_event(
        HostBrowserEvent(
            kind="page_activated",
            observed_at=NOW,
            source_page_runtime_ref="runtime_main",
            source_frame_runtime_ref="frame_main",
            runtime_page_ref="runtime_popup",
        )
    )
    assert creation.pages.active_page_ref == "page_001"

    browser.handle_event(
        HostBrowserEvent(
            kind="page_closed",
            observed_at=NOW,
            source_page_runtime_ref="runtime_popup",
            source_frame_runtime_ref="frame_popup",
            runtime_page_ref="runtime_popup",
        )
    )
    assert creation.pages.is_closed("page_001") is True
    assert creation.pages.active_page_ref == "main"


@pytest.mark.asyncio
async def test_browser_session_closes_owned_port_resources_once():
    calls = []

    async def cleanup():
        calls.append("cleanup")

    page = object()
    port = PlaywrightBrowserSessionPort(
        context=object(),
        main_page=page,
        main_page_runtime_ref="runtime_main",
        main_frame_runtime_ref="frame_main",
        page_runtime_ref=lambda _page: "runtime_main",
        frame_runtime_ref=lambda _frame: "frame_main",
        frame_path=lambda _page, _frame: (),
        page_main_frame_runtime_ref=lambda _page: "frame_main",
        browser_use_cdp_url="ws://runtime.test/devtools/browser/one",
        cleanup=cleanup,
    )
    browser = BrowserSession(port=port, creation=_creation())

    await browser.aclose(at=NOW)
    await browser.aclose(at=NOW)

    assert calls == ["cleanup"]
    assert port.browser_use_cdp_url == "ws://runtime.test/devtools/browser/one"


def test_cdp_url_rewrites_only_the_runtime_network_location():
    assert rewrite_cdp_url(
        "ws://127.0.0.1:9222/devtools/browser/opaque-token",
        rest_base_url="http://sandbox-runtime:8080",
    ) == "ws://sandbox-runtime:8080/devtools/browser/opaque-token"
    assert rewrite_cdp_url(
        "ws://127.0.0.1:9222/devtools/browser/opaque-token",
        rest_base_url="https://sandbox-runtime.example",
    ).startswith("wss://sandbox-runtime.example/")

    with pytest.raises(ValueError, match="browser_runtime.cdp_url_invalid"):
        rewrite_cdp_url("http://runtime.test/not-websocket", rest_base_url="http://x")


@pytest.mark.asyncio
async def test_runtime_lease_initializes_and_registers_same_cdp_browser():
    calls = []

    class Runtime:
        rest_base_url = "http://sandbox-runtime:8080"

    class Page:
        context = None

    page = Page()

    class Context:
        pages = [page]

    context = Context()
    page.context = context

    class Browser:
        contexts = [context]

    class Registry:
        cdp_url = None

        def get_active_page(self, _ref):
            return None

        def get_cdp_url(self, _ref):
            return self.cdp_url

        async def register(self, ref, registered_page, *, cdp_url=None):
            self.cdp_url = cdp_url
            calls.append(("register", ref, registered_page))

        async def unregister(self, ref, registered_page):
            self.cdp_url = None
            calls.append(("unregister", ref, registered_page))

    class Playwright:
        async def stop(self):
            calls.append(("stop",))

    async def ensure_runtime(ref, owner):
        calls.append(("ensure", ref, owner))
        return Runtime()

    async def fetch_cdp(rest_base_url):
        calls.append(("fetch", rest_base_url))
        return "ws://sandbox-runtime:8080/devtools/browser/opaque-token"

    async def connect(cdp_url):
        calls.append(("connect", cdp_url))
        return Playwright(), Browser()

    lease = await acquire_browser_runtime_lease(
        owner_id="owner-1",
        browser_ref="7browser",
        preview_registry=Registry(),
        ensure_runtime=ensure_runtime,
        fetch_cdp_url=fetch_cdp,
        connect=connect,
    )

    assert lease.page is page
    assert lease.cdp_url.endswith("/devtools/browser/opaque-token")
    await lease.aclose()
    await lease.aclose()
    assert calls == [
        ("ensure", "7browser", "owner-1"),
        ("fetch", "http://sandbox-runtime:8080"),
        ("connect", "ws://sandbox-runtime:8080/devtools/browser/opaque-token"),
        ("register", "7browser", page),
        ("unregister", "7browser", page),
        ("stop",),
    ]


@pytest.mark.asyncio
async def test_runtime_lease_uses_direct_cdp_resolver_without_session_runtime():
    calls = []

    class Registry:
        def get_active_page(self, _ref):
            return None

    async def forbidden_runtime(*_args):
        raise AssertionError("local mode must not ensure a session runtime")

    async def resolve_cdp(ref, owner):
        calls.append((ref, owner))
        return "ws://127.0.0.1:19222/devtools/browser/local"

    async def stop_after_resolve(cdp_url):
        assert cdp_url.endswith("/devtools/browser/local")
        raise RuntimeError("stop_after_direct_resolve")

    with pytest.raises(RuntimeError, match="stop_after_direct_resolve"):
        await acquire_browser_runtime_lease(
            owner_id="owner-1",
            browser_ref="local-session",
            preview_registry=Registry(),
            ensure_runtime=forbidden_runtime,
            resolve_cdp_url=resolve_cdp,
            connect=stop_after_resolve,
        )

    assert calls == [("local-session", "owner-1")]


@pytest.mark.asyncio
async def test_runtime_lease_rejects_existing_page_without_exact_cdp_provenance():
    class Runtime:
        rest_base_url = "http://runtime.test"

    class Registry:
        def get_active_page(self, _ref):
            return object()

        def get_cdp_url(self, _ref):
            return None

    async def ensure_runtime(_ref, _owner):
        return Runtime()

    async def fetch(_rest):
        return "ws://runtime.test/devtools/browser/one"

    with pytest.raises(RuntimeError, match="browser_runtime.preview_cdp_mismatch"):
        await acquire_browser_runtime_lease(
            owner_id="owner-1",
            browser_ref="provenance-check",
            preview_registry=Registry(),
            ensure_runtime=ensure_runtime,
            fetch_cdp_url=fetch,
        )


@pytest.mark.asyncio
async def test_concurrent_runtime_leases_connect_once_and_cleanup_once():
    calls = []

    class Runtime:
        rest_base_url = "http://runtime.test"

    class Page:
        context = None

    page = Page()

    class Context:
        pages = [page]

    context = Context()
    page.context = context

    class Browser:
        contexts = [context]

    class Playwright:
        async def stop(self):
            calls.append("stop")

    class Registry:
        page = None
        cdp_url = None

        def get_active_page(self, _ref):
            return self.page

        def get_cdp_url(self, _ref):
            return self.cdp_url

        async def register(self, _ref, value, *, cdp_url=None):
            self.page = value
            self.cdp_url = cdp_url
            calls.append("register")

        async def unregister(self, _ref, _value):
            self.page = None
            self.cdp_url = None
            calls.append("unregister")

    registry = Registry()

    async def ensure(_ref, _owner):
        return Runtime()

    async def fetch(_rest):
        return "ws://runtime.test/devtools/browser/concurrent"

    async def connect(_cdp):
        calls.append("connect")
        await __import__("asyncio").sleep(0)
        return Playwright(), Browser()

    kwargs = dict(
        owner_id="owner-1",
        browser_ref="concurrent-runtime",
        preview_registry=registry,
        ensure_runtime=ensure,
        fetch_cdp_url=fetch,
        connect=connect,
    )
    first, second = await __import__("asyncio").gather(
        acquire_browser_runtime_lease(**kwargs),
        acquire_browser_runtime_lease(**kwargs),
    )
    assert first.page is second.page is page
    assert calls == ["connect", "register"]

    await __import__("asyncio").gather(
        first.aclose(), first.aclose(), second.aclose(), second.aclose()
    )
    assert calls == ["connect", "register", "unregister", "stop"]


@pytest.mark.asyncio
async def test_recording_tools_accounts_extract_and_commits_explicit_output():
    creation = _creation()
    creation.switch_control(ControlMode.AGENT, at=NOW)

    class Frame:
        pass

    class Page:
        main_frame = Frame()

    page = Page()

    class Port:
        context = type("Context", (), {"pages": [page]})()
        main_page = page

        async def active_page_object(self):
            return page

        def page_runtime_ref(self, _page):
            return "runtime_main"

        def frame_runtime_ref(self, _frame):
            return "frame_main"

        def page_main_frame_runtime_ref(self, _page):
            return "frame_main"

        def resolve_frame_path(self, _page, _frame):
            return ()

        @asynccontextmanager
        async def action_dispatch_scope(self, _target):
            yield

    hosted = type(
        "Hosted",
        (),
        {
            "browser": type("Browser", (), {"creation": creation, "port": Port()})(),
            "owner_id": "owner-1",
        },
    )()
    tools = RecordingBrowserUseTools(hosted=hosted, instruction="提取订单")
    assert "input" not in tools.registry.registry.actions
    assert "input_literal" in tools.registry.registry.actions
    assert "input_variable" in tools.registry.registry.actions
    assert "click_variable" in tools.registry.registry.actions
    assert "switch" in tools.registry.registry.actions
    assert "close" in tools.registry.registry.actions
    action_model = tools.registry.create_action_model(
        include_actions=["extract_variable"]
    )
    action = action_model.model_validate(
        {
            "extract_variable": {
                "variable_ref": "采购订单",
                "value": {"订单号": "PO-2002"},
            }
        }
    )

    result = await tools.act(action, object())

    assert result.error is None
    assert tools.report.actual_action_count == 1
    assert tools.report.invocation_count == 1
    assert len(tools.report.candidate_ids) == 1
    assert creation.variables.read("采购订单") == {"订单号": "PO-2002"}

    class FileSystem:
        def display_file(self, _name):
            return None

        def get_dir(self):
            return "."

    done_model = tools.registry.create_action_model(include_actions=["done"])
    done = done_model.model_validate(
        {"done": {"text": "提取完成", "success": True, "files_to_display": []}}
    )
    done_result = await tools.act(done, object(), file_system=FileSystem())
    assert done_result.is_done is True
    assert tools.report.non_sop[-1].action_name == "done"
    assert tools.report.non_sop[-1].status == "succeeded"

    bound_tools = RecordingBrowserUseTools(
        hosted=hosted,
        instruction="按订单号提取采购订单",
        allowed_inputs={"order_no": "PO-RECORDED-2002"},
    )
    bound_model = bound_tools.registry.create_action_model(
        include_actions=["extract_variable"]
    )
    bound_action = bound_model.model_validate(
        {
            "extract_variable": {
                "variable_ref": "目标采购订单",
                "value": {"订单号": "PO-RECORDED-2002"},
                "input_refs": ["order_no"],
            }
        }
    )
    await bound_tools.act(bound_action, object())
    bound_candidate = creation.candidates[bound_tools.report.candidate_ids[-1]]
    bound_payload = bound_candidate.model_dump(mode="json", exclude_none=True)
    assert bound_payload["binding_hints"] == [
        {
            "name": "input.order_no",
            "direction": "input",
            "kind_hint": "skill_input",
            "ref_hint": "order_no",
            "sensitive": False,
        },
        {
            "name": "result",
            "direction": "output",
            "kind_hint": "variable",
            "ref_hint": "目标采购订单",
            "sensitive": False,
        },
    ]
    assert "PO-RECORDED-2002" not in json.dumps(bound_payload, ensure_ascii=False)

    unknown_action = bound_model.model_validate(
        {
            "extract_variable": {
                "variable_ref": "不应提交",
                "value": {"订单号": "PO-NEVER-COMMIT"},
                "input_refs": ["unknown_input"],
            }
        }
    )
    await bound_tools.act(unknown_action, object())
    unknown_candidate = creation.candidates[bound_tools.report.candidate_ids[-1]]
    assert unknown_candidate.execution.status == "failed"
    with pytest.raises(KeyError, match="session_variable_store.ref_missing"):
        creation.variables.read("不应提交")


@pytest.mark.asyncio
async def test_click_variable_records_agent_binding_and_iframe_scope_without_sample_value():
    creation = _creation()
    creation.variables.write(
        "采购订单.订单号",
        "PO-RECORDED-2002",
        producer_candidate_id="producer_order",
    )
    creation.switch_control(ControlMode.AGENT, at=NOW)

    iframe = type(
        "Node",
        (),
        {
            "tag_name": "iframe",
            "attributes": {"data-testid": "orders-frame"},
            "ax_node": type("Ax", (), {"name": "订单列表"})(),
            "parent_node": None,
        },
    )()
    document = type(
        "Node",
        (),
        {
            "tag_name": "document",
            "attributes": {},
            "ax_node": None,
            "parent_node": iframe,
        },
    )()
    target = type(
        "Node",
        (),
        {
            "tag_name": "button",
            "attributes": {"data-testid": "start-acceptance"},
            "ax_node": type("Ax", (), {"name": "发起验收"})(),
            "parent_node": document,
        },
    )()

    class Page:
        main_frame = object()

    page = Page()

    class Port:
        in_scope = False
        scope_target = None
        context = type("Context", (), {"pages": [page]})()
        main_page = page

        async def active_page_object(self):
            return page

        def page_runtime_ref(self, _page):
            return "runtime_main"

        def frame_runtime_ref(self, _frame):
            return "frame_main"

        def page_main_frame_runtime_ref(self, _page):
            return "frame_main"

        def resolve_frame_path(self, _page, _frame):
            return ()

        async def validate_semantic_target(self, **_kwargs):
            return 0  # repeated row buttons force an Agent Action

        @asynccontextmanager
        async def action_dispatch_scope(self, target):
            self.in_scope = True
            self.scope_target = target
            try:
                yield
            finally:
                self.in_scope = False
                self.scope_target = None

    hosted = type(
        "Hosted",
        (),
        {
            "browser": type("Browser", (), {"creation": creation, "port": Port()})(),
            "owner_id": "owner-1",
        },
    )()
    tools = RecordingBrowserUseTools(hosted=hosted, instruction="按订单号发起验收")

    async def click(*, params, browser_session=None, **_kwargs):
        del params, browser_session
        from browser_use.agent.views import ActionResult

        assert hosted.browser.port.in_scope is True
        assert hosted.browser.port.scope_target.page is page
        assert hosted.browser.port.scope_target.page_runtime_ref == "runtime_main"
        assert hosted.browser.port.scope_target.frame_runtime_ref == "frame_main"
        trigger = creation.observer.start_new_page("runtime_main", "frame_main")
        fact = creation.observer.complete_new_page(
            trigger,
            observed_at=NOW,
            new_page_runtime_ref="runtime_popup_from_click",
            initial_url="https://eval.test/system-b/random",
        )
        creation.pages.apply(fact)
        return ActionResult()

    tools.registry.registry.actions["click"].function = click

    state = type(
        "State",
        (),
        {"dom_state": type("Dom", (), {"selector_map": {19: target}})()},
    )()

    class BrowserUseSession:
        async def get_browser_state_summary(self, *, include_screenshot):
            assert include_screenshot is False
            return state

    action_model = tools.registry.create_action_model(
        include_actions=["click_variable"]
    )
    action = action_model.model_validate(
        {
            "click_variable": {
                "index": 19,
                "variable_ref": "采购订单.订单号",
            }
        }
    )

    await tools.act(action, BrowserUseSession())

    candidate = next(iter(creation.candidates.values()))
    payload = candidate.model_dump(mode="json", exclude_none=True)
    assert payload["scope_hint"]["frame_path"][0]["name"] == "订单列表"
    assert payload["action_hint"]["kind"] == "agent"
    assert payload["binding_hints"] == [
        {
            "name": "row_key",
            "direction": "input",
            "kind_hint": "variable",
            "ref_hint": "采购订单.订单号",
            "sensitive": False,
        }
    ]
    assert "PO-RECORDED-2002" not in json.dumps(payload, ensure_ascii=False)
    assert creation.candidate_has_fact(candidate.candidate_id, "new_page") is True

    clicks = []
    input_tools = RecordingBrowserUseTools(
        hosted=hosted,
        instruction="选择业务类型",
        allowed_inputs={"business_type": "自动创建"},
    )

    async def click_input(*, params, browser_session=None, **_kwargs):
        del browser_session
        from browser_use.agent.views import ActionResult

        clicks.append(params.index)
        return ActionResult()

    input_tools.registry.registry.actions["click"].function = click_input
    input_model = input_tools.registry.create_action_model(
        include_actions=["click_allowed_input"]
    )
    known = input_model.model_validate(
        {"click_allowed_input": {"index": 19, "input_ref": "business_type"}}
    )
    await input_tools.act(known, BrowserUseSession())
    known_candidate = creation.candidates[input_tools.report.candidate_ids[-1]]
    known_payload = known_candidate.model_dump(mode="json", exclude_none=True)
    assert clicks == [19]
    assert known_payload["binding_hints"] == [
        {
            "name": "row_key",
            "direction": "input",
            "kind_hint": "skill_input",
            "ref_hint": "business_type",
            "sensitive": False,
        }
    ]
    assert "自动创建" not in json.dumps(known_payload, ensure_ascii=False)

    unknown = input_model.model_validate(
        {"click_allowed_input": {"index": 20, "input_ref": "unknown_type"}}
    )
    await input_tools.act(unknown, BrowserUseSession())
    unknown_candidate = creation.candidates[input_tools.report.candidate_ids[-1]]
    assert clicks == [19]
    assert unknown_candidate.execution.status == "failed"
    assert unknown_candidate.execution.error.code == "tool_reported_failure"


@pytest.mark.asyncio
async def test_switch_tool_emits_locked_activation_fact_and_stable_switch_hint():
    creation = _creation()
    popup_trigger = creation.observer.start_new_page("runtime_main", "frame_main")
    popup_fact = creation.observer.complete_new_page(
        popup_trigger,
        observed_at=NOW,
        new_page_runtime_ref="runtime_popup",
        initial_url="https://eval.test/system-b/random",
    )
    assert creation.pages.apply(popup_fact) == "page_001"
    creation.switch_control(ControlMode.AGENT, at=NOW)

    class Page:
        def __init__(self, runtime_ref, target_id):
            self.runtime_ref = runtime_ref
            self.target_id = target_id
            self.main_frame = type("Frame", (), {"runtime_ref": "frame_" + runtime_ref})()
            self.context = None

    main = Page("runtime_main", "target-main-AAAA")
    popup = Page("runtime_popup", "target-popup-BBBB")

    class Cdp:
        def __init__(self, page):
            self.page = page

        async def send(self, method):
            assert method == "Target.getTargetInfo"
            return {"targetInfo": {"targetId": self.page.target_id}}

        async def detach(self):
            return None

    class Context:
        pages = [main, popup]

        async def new_cdp_session(self, page):
            return Cdp(page)

    context = Context()
    main.context = popup.context = context

    class Port:
        def __init__(self):
            self.main_page = main
            self.context = context

        async def active_page_object(self):
            return main

        def page_runtime_ref(self, page):
            return page.runtime_ref

        def frame_runtime_ref(self, frame):
            return frame.runtime_ref

        def page_main_frame_runtime_ref(self, page):
            return page.main_frame.runtime_ref

        def resolve_frame_path(self, _page, _frame):
            return ()

        @asynccontextmanager
        async def action_dispatch_scope(self, _target):
            yield

    class Browser:
        def __init__(self):
            self.port = Port()
            self.creation = creation

        def handle_event(self, event):
            observer = creation.observer
            trigger = observer.start_page_activated(
                event.source_page_runtime_ref, event.source_frame_runtime_ref
            )
            fact = observer.complete_page_activated(
                trigger,
                observed_at=event.observed_at,
                page_runtime_ref=event.runtime_page_ref,
            )
            creation.pages.apply(fact)

    hosted = type(
        "Hosted", (), {"browser": Browser(), "owner_id": "owner-1"}
    )()
    tools = RecordingBrowserUseTools(hosted=hosted, instruction="切换到系统B")

    async def switch(*, params, browser_session=None, **_kwargs):
        del params, browser_session
        from browser_use.agent.views import ActionResult

        return ActionResult()

    tools.registry.registry.actions["switch"].function = switch
    model = tools.registry.create_action_model(include_actions=["switch"])
    action = model.model_validate({"switch": {"tab_id": "BBBB"}})

    await tools.act(action, object())

    assert creation.pages.active_page_ref == "page_001"
    candidate_id = tools.report.candidate_ids[0]
    candidate = creation.candidates[candidate_id]
    assert candidate.action_hint.kind == "switch_page"
    assert candidate.action_hint.page_ref == "page_001"
    assert creation.candidate_has_fact(candidate_id, "page_activated") is True


def test_browser_use_node_projects_stable_iframe_scope_and_target_without_index():
    ax = type("Ax", (), {"name": "验收登记"})()
    iframe = type(
        "Node",
        (),
        {
            "tag_name": "iframe",
            "attributes": {"data-testid": "acceptance-frame"},
            "ax_node": ax,
            "parent_node": None,
        },
    )()
    document = type(
        "Node",
        (),
        {
            "tag_name": "document",
            "attributes": {},
            "ax_node": None,
            "parent_node": iframe,
        },
    )()
    target = type(
        "Node",
        (),
        {
            "tag_name": "input",
            "attributes": {
                "data-testid": "acceptance-order-number",
                "placeholder": "采购订单号",
            },
            "ax_node": type("Ax", (), {"name": "采购订单号"})(),
            "parent_node": document,
        },
    )()

    frame_path, target_hint = semantic_hints_from_browser_use_node(target)

    assert frame_path == (
        {
            "name": "验收登记",
            "locators": [
                {"strategy": "test_id", "value": "acceptance-frame", "exact": True}
            ],
        },
    )
    assert target_hint["locators"][0] == {
        "strategy": "test_id",
        "value": "acceptance-order-number",
        "exact": True,
    }
    assert "index" not in target_hint


def test_agent_task_uses_active_popup_page_not_main_page():
    creation = _creation()
    main = type("Page", (), {"url": "https://eval.test/system-a"})()
    popup = type("Page", (), {"url": "https://eval.test/system-b/task?token=secret"})()
    hosted = type(
        "Hosted",
        (),
        {
            "browser": type(
                "Browser",
                (),
                {
                    "creation": creation,
                    "port": type("Port", (), {"main_page": main})(),
                },
            )()
        },
    )()
    request = AgentInstructionRequest(
        instruction="登记验收",
        business_terms=[],
        required_variable_refs=[],
        allowed_inputs={},
        allowed_secret_names=[],
        allowed_data_assets={},
        page_aliases={},
    )

    payload = json.loads(build_agent_task(hosted, request, page=popup))

    assert payload["current_page_state"]["url"] == "https://eval.test/system-b/task"


@pytest.mark.asyncio
async def test_playwright_port_reads_unique_action_specific_semantic_evidence():
    class Locator:
        def __init__(self, count, *, value="", selected=None):
            self._count = count
            self._value = value
            self._selected = selected

        async def count(self):
            return self._count

        async def input_value(self):
            return self._value

        async def evaluate(self, _script):
            return self._selected

    ambiguous = Locator(2)
    input_locator = Locator(1, value="PO-3003")
    select_locator = Locator(
        1, selected={"value": "SUP-B", "label": "乙方供应商"}
    )

    class Page:
        def get_by_test_id(self, value):
            return ambiguous if value == "ambiguous" else input_locator

        def get_by_placeholder(self, value, *, exact):
            assert value == "采购订单号" and exact is True
            return input_locator

        def get_by_label(self, value, *, exact):
            assert value == "供应商" and exact is True
            return select_locator

    page = Page()
    port = PlaywrightBrowserSessionPort(
        context=type("Context", (), {"pages": [page]})(),
        main_page=page,
        main_page_runtime_ref="runtime_main",
        main_frame_runtime_ref="frame_main",
        page_runtime_ref=lambda _page: "runtime_main",
        frame_runtime_ref=lambda _frame: "frame_main",
        frame_path=lambda _page, _frame: (),
        page_main_frame_runtime_ref=lambda _page: "frame_main",
    )
    input_hint = {
        "name": "采购订单号",
        "locators": [
            {"strategy": "test_id", "value": "ambiguous", "exact": True},
            {"strategy": "placeholder", "value": "采购订单号", "exact": True},
        ],
    }
    select_hint = {
        "name": "供应商",
        "locators": [
            {"strategy": "label", "value": "供应商", "exact": True}
        ],
    }

    assert await port.semantic_action_evidence(
        action_name="click",
        page=page,
        frame_path=(),
        target_hint=input_hint,
    ) == {"dispatched": True}
    assert await port.semantic_action_evidence(
        action_name="input",
        page=page,
        frame_path=(),
        target_hint=input_hint,
        expected="PO-3003",
    ) == {"dom_value": "PO-3003"}
    assert await port.semantic_action_evidence(
        action_name="select_dropdown",
        page=page,
        frame_path=(),
        target_hint=select_hint,
        expected="乙方供应商",
    ) == {"selected": "乙方供应商", "selected_value": "SUP-B"}

    with pytest.raises(ValueError, match="semantic_target_not_unique"):
        await port.semantic_action_evidence(
            action_name="click",
            page=page,
            frame_path=(),
            target_hint={
                "name": "ambiguous",
                "locators": [
                    {"strategy": "test_id", "value": "ambiguous", "exact": True}
                ],
            },
        )


@pytest.mark.asyncio
async def test_runtime_agent_backend_returns_only_structured_declared_outputs():
    calls = []

    class Session:
        def __init__(self, **kwargs):
            calls.append(("session", kwargs))

        async def start(self):
            calls.append(("start",))

        async def stop(self):
            calls.append(("stop",))

        async def get_or_create_cdp_session(self, *, target_id, focus):
            calls.append(("focus", target_id, focus))

    class History:
        def is_done(self):
            return True

        def is_successful(self):
            return True

        def get_structured_output(self, model):
            return model.model_validate({"result": {"订单号": "PO-3003"}})

    class Agent:
        def __init__(self, **kwargs):
            calls.append(("agent", kwargs))

        async def run(self, max_steps):
            calls.append(("run", max_steps))
            return History()

    async def model_factory(_owner):
        return object()

    hosted = type(
        "Hosted",
        (),
        {
            "owner_id": "owner-1",
            "browser": type(
                "Browser",
                (),
                {
                    "port": type(
                        "Port",
                        (),
                        {"browser_use_cdp_url": "ws://runtime/devtools/browser/one"},
                    )()
                },
            )(),
        },
    )()
    backend = build_runtime_agent_backend(
        hosted,
        model_factory=model_factory,
        agent_factory=Agent,
        browser_session_factory=Session,
    )

    class CdpSession:
        async def send(self, method):
            assert method == "Target.getTargetInfo"
            return {"targetInfo": {"targetId": "target-runtime-page"}}

        async def detach(self):
            calls.append(("detach",))

    class RuntimeContext:
        async def new_cdp_session(self, _page):
            return CdpSession()

    class RuntimePage:
        context = RuntimeContext()

        async def bring_to_front(self):
            return None

    outputs = await backend(
        scope=RuntimePage(),
        target=None,
        instruction="读取结果",
        inputs={"value": "PO-3003"},
        output_names=("result",),
        required_paths={"result": ("订单号",)},
    )

    assert outputs == {"result": {"订单号": "PO-3003"}}
    assert calls[-1] == ("stop",)


@pytest.mark.asyncio
async def test_default_provider_releases_lease_when_host_page_is_invalid(monkeypatch):
    from backend.route.rpa_agent import _scienceclaw_browser_provider
    from backend.rpa_agent.host import scienceclaw_browser
    from backend.runtime import ownership

    calls = []

    async def owned(_browser_ref, _owner_id):
        return True

    class Lease:
        page = object()  # no context: provider must fail and release
        cdp_url = "ws://runtime.test/devtools/browser/invalid-page"

        async def aclose(self):
            calls.append("close")

    async def acquire(**_kwargs):
        calls.append("acquire")
        return Lease()

    monkeypatch.setattr(ownership, "user_owns_runtime_session", owned)
    monkeypatch.setattr(
        scienceclaw_browser, "acquire_browser_runtime_lease", acquire
    )

    with pytest.raises(RuntimeError, match="browser_host_context_unavailable"):
        await _scienceclaw_browser_provider("owner-1", "7browser")

    assert calls == ["acquire", "close"]
