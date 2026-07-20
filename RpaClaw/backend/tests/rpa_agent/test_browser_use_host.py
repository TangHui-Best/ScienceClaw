
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json

import pytest
from browser_use import ChatAnthropic
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.views import ChatInvokeCompletion
from pydantic import BaseModel

from rpa_agent.creation import ControlMode, SkillCreationSession
from rpa_agent.host import BrowserSession, HostBrowserEvent, PlaywrightBrowserSessionPort
from rpa_agent.host.browser_use_agent import (
    _TextFallbackChatAnthropic,
    _execution_guidance,
    _openai_structured_text,
    _validated_json_text,
    _model_for,
    build_agent_task,
    build_runtime_agent_backend,
    execute_browser_use_instruction,
    semantic_hints_from_browser_use_node,
)
from rpa_agent.api import AgentInstructionRequest
from rpa_agent.host.scienceclaw_browser import (
    acquire_browser_runtime_lease,
    rewrite_cdp_url,
)


NOW = datetime(2026, 7, 18, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_anthropic_gateway_alternates_auto_and_forced_schema_protocol(monkeypatch):
    client = _TextFallbackChatAnthropic(
        model="claude-sonnet-4-6",
        api_key="secret-test-only",
        base_url="https://model.example",
    )

    calls = []

    async def invoke(_self, _messages, output_format=None, **_kwargs):
        calls.append((_self._requires_auto_tool_choice(), output_format))
        return object()

    monkeypatch.setattr(ChatAnthropic, "ainvoke", invoke)

    await client.ainvoke([], output_format=dict)
    await client.ainvoke([], output_format=dict)

    assert calls == [(True, dict), (False, dict)]


@pytest.mark.asyncio
async def test_anthropic_gateway_validates_text_json_when_tool_use_is_omitted(
    monkeypatch,
):
    class Result(BaseModel):
        value: int

    client = _TextFallbackChatAnthropic(
        model="claude-sonnet-4-6",
        api_key="secret-test-only",
        base_url="https://model.example",
    )
    calls = []

    async def invoke(_self, messages, output_format=None, **_kwargs):
        calls.append((messages, output_format))
        if output_format is not None:
            raise ModelProviderError(
                message="Expected tool use in response but none found",
                model=_self.name,
            )
        return ChatInvokeCompletion(
            completion='```json\n{"value":7}\n```', usage=None
        )

    monkeypatch.setattr(ChatAnthropic, "ainvoke", invoke)

    result = await client.ainvoke([], output_format=Result)

    assert result.completion == Result(value=7)
    assert len(calls) == 2
    assert calls[1][1] is None
    assert "exact JSON Schema" in calls[1][0][-1].content


def test_openai_compatible_gateway_accepts_only_plain_or_fenced_json():
    assert _validated_json_text('{"ok":true}') == '{"ok":true}'
    assert _validated_json_text('```json\n{"ok":true}\n```') == '{"ok":true}'
    with pytest.raises(ValueError, match="structured_output_invalid"):
        _validated_json_text('Result: {"ok":true}')


def test_openai_compatible_gateway_uses_reasoning_content_when_content_is_blank():
    from types import SimpleNamespace

    message = SimpleNamespace(content="", reasoning_content='{"ok":true}')
    assert _validated_json_text(_openai_structured_text(message)) == '{"ok":true}'

    preferred = SimpleNamespace(
        content='{"source":"content"}',
        reasoning_content='{"source":"reasoning"}',
    )
    assert _openai_structured_text(preferred) == '{"source":"content"}'

    with pytest.raises(ValueError, match="structured_output_invalid"):
        _validated_json_text(
            _openai_structured_text(
                SimpleNamespace(content="", reasoning_content="analysis only")
            )
        )
    with pytest.raises(ValueError, match="structured_output_missing"):
        _openai_structured_text(SimpleNamespace(content="", reasoning_content=""))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "client_name"),
    [("anthropic", "anthropic"), ("openai", "openai"), ("deepseek", "openai")],
)
async def test_model_for_uses_native_anthropic_and_openai_compatible_clients(
    monkeypatch, provider, client_name
):
    from backend import models
    from rpa_agent.host import browser_use_agent

    async def resolve(_owner_id):
        return {
            "provider": provider,
            "model_name": "model-real",
            "api_key": "secret-test-only",
            "base_url": "https://model.example/v1",
        }

    calls = []

    def anthropic_client(**kwargs):
        calls.append(("anthropic", kwargs))
        return object()

    def openai_client(**kwargs):
        calls.append(("openai", kwargs))
        return object()

    monkeypatch.setattr(models, "resolve_default_model_config", resolve)
    monkeypatch.setattr(
        browser_use_agent, "_TextFallbackChatAnthropic", anthropic_client
    )
    monkeypatch.setattr(browser_use_agent, "_TextJSONChatOpenAI", openai_client)

    await _model_for("owner-1")

    assert calls == [
        (
            client_name,
            {
                "model": "model-real",
                "api_key": "secret-test-only",
                "base_url": "https://model.example/v1",
            },
        )
    ]


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

        async def new_page(self):
            return page

        async def close(self):
            calls.append(("close_context",))

    context = Context()
    page.context = context

    class Browser:
        contexts = [context]

        async def new_context(self):
            calls.append(("new_context",))
            return context

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
        ("new_context",),
        ("register", "7browser", page),
        ("unregister", "7browser", page),
        ("close_context",),
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

        async def new_page(self):
            return page

        async def close(self):
            calls.append("close_context")

    context = Context()
    page.context = context

    class Browser:
        contexts = [context]

        async def new_context(self):
            return context

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
    assert calls == ["connect", "register", "unregister", "close_context", "stop"]


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


@pytest.mark.parametrize(
    ("instruction", "expected"),
    [
        ("打开和 skill 最相关的项目", "Do not use global site search."),
        ("获取 star 数", "read the exact repository star counter"),
    ],
)
def test_agent_task_adds_bounded_execution_guidance(instruction, expected):
    creation = _creation()
    page = type("Page", (), {"url": "https://github.com/trending"})()
    hosted = type(
        "Hosted",
        (),
        {
            "browser": type(
                "Browser", (), {"creation": creation, "port": _Port()}
            )()
        },
    )()
    request = AgentInstructionRequest(instruction=instruction)

    payload = json.loads(build_agent_task(hosted, request, page=page))

    assert expected in payload["execution_guidance"]
    assert payload["execution_guidance"] == _execution_guidance(instruction)


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

        async def run(self):
            calls.append(("run",))
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
    agent_kwargs = next(call[1] for call in calls if call[0] == "agent")
    assert "tools" not in agent_kwargs
    assert "controller" not in agent_kwargs
    assert "max_actions_per_step" not in agent_kwargs
    assert "max_history_items" not in agent_kwargs
    assert agent_kwargs["use_vision"] is False
    assert calls[-1] == ("stop",)


@pytest.mark.asyncio
async def test_native_agent_observer_appends_click_as_child_evidence_without_custom_tools():
    calls = []
    observations = []

    class Cdp:
        async def send(self, _method):
            return {"targetInfo": {"targetId": "target-recording"}}

        async def detach(self):
            return None

    class Context:
        async def new_cdp_session(self, _page):
            return Cdp()

    class Page:
        context = Context()
        url = "https://github.com/trending"

    page = Page()

    class Port:
        browser_use_cdp_url = "ws://runtime/devtools/browser/native"
        main_page = page

        async def active_page_object(self):
            return page

        def page_runtime_ref(self, _page):
            return "page_recording"

    class Variables:
        def snapshot(self):
            return {"采购订单": {"订单号": "PO-1"}}

    class Creation:
        variables = Variables()
        pages = type("Pages", (), {"resolve": lambda _self, _runtime: "main"})()

        def attach_ai_observation(self, *, step_id, trace):
            observations.append((step_id, trace))

    hosted = type(
        "Hosted",
        (),
        {
            "owner_id": "owner-1",
            "active_operation_id": "ais_native",
            "browser": type("Browser", (), {"port": Port(), "creation": Creation()})(),
        },
    )()

    class Session:
        def __init__(self, **kwargs):
            calls.append(("session", kwargs))

        async def start(self):
            return None

        async def stop(self):
            return None

        async def get_or_create_cdp_session(self, *, target_id, focus):
            assert target_id == "target-recording" and focus is True

    class Action:
        def model_dump(self, **_kwargs):
            return {"click": {"index": 1}}

    class Result:
        error = None

    class Element:
        tag_name = "button"
        attributes = {"data-testid": "skill-project"}
        parent_node = None
        ax_node = type("Ax", (), {"name": "ui-skills"})()

    item = type(
        "HistoryItem",
        (),
        {
            "model_output": type("Output", (), {"action": [Action()]})(),
            "result": [Result()],
            "state": type("State", (), {"interacted_element": [Element()]})(),
        },
    )()

    class History:
        history = [item]

        def is_done(self):
            return True

        def is_successful(self):
            return True

        def action_names(self):
            return ["click", "done"]

    class NativeAgent:
        def __init__(self, **kwargs):
            calls.append(("agent", kwargs))
            self.history = History()

        async def run(self, *, on_step_end):
            await on_step_end(self)
            return self.history

    async def model_factory(_owner):
        return object()

    report = await execute_browser_use_instruction(
        hosted,
        AgentInstructionRequest(instruction="打开和 skill 最相关的项目"),
        model_factory=model_factory,
        agent_factory=NativeAgent,
        browser_session_factory=Session,
    )

    agent_kwargs = next(call[1] for call in calls if call[0] == "agent")
    assert "tools" not in agent_kwargs and "controller" not in agent_kwargs
    assert agent_kwargs["use_vision"] is False
    assert observations[0][0] == "ais_native"
    assert observations[0][1].action.kind == "click"
    assert observations[0][1].scope.page_ref == "main"
    assert observations[0][1].action.target.name == "ui-skills"
    assert report.actual_action_count == 1


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
