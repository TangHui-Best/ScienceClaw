from __future__ import annotations

import json
import sys
from types import ModuleType
from types import SimpleNamespace

import pytest

from backend.rpa.browser_use_recording_operator import (
    BrowserUseDoneOutput,
    BrowserUseRecordingOperator,
    _build_browser_use_task,
    _focus_browser_use_target,
    _history_model_actions,
    _run_browser_use_agent,
)
from backend.rpa.trace_models import RPATraceType


class _FakePage:
    url = "https://example.test/list"

    async def title(self):
        return "Example List"


class _FakeBrowserUseHistory:
    def model_actions(self):
        return [
            {
                "click_element_by_index": {"index": 3},
                "interacted_element": {"text": "Search"},
            },
            {
                "input_text": {"index": 4, "text": "invoice"},
                "interacted_element": {"text": "Keyword"},
            },
        ]

    def action_results(self):
        return [
            SimpleNamespace(extracted_content=None, long_term_memory="clicked Search"),
            SimpleNamespace(extracted_content="2 rows", long_term_memory="typed invoice"),
        ]

    def extracted_content(self):
        return ["2 rows"]

    def is_done(self):
        return True

    def is_successful(self):
        return True


class _FakeStructuredDoneHistory(_FakeBrowserUseHistory):
    def __init__(self, output: BrowserUseDoneOutput):
        self.output = output

    def model_actions(self):
        return [
            {
                "done": {
                    "success": True,
                    "data": self.output.model_dump(mode="json"),
                }
            }
        ]

    def action_results(self):
        return [
            SimpleNamespace(
                extracted_content=json.dumps(self.output.model_dump(mode="json"), ensure_ascii=False),
                long_term_memory="Task completed",
                is_done=True,
                success=True,
            )
        ]

    def extracted_content(self):
        return [json.dumps(self.output.model_dump(mode="json"), ensure_ascii=False)]

    @property
    def structured_output(self):
        return self.output


class _FakeDOMInteractedElement:
    tag_name = "button"
    x_path = "/html/body/button[1]"
    attributes = {"id": "save-skill", "aria-label": "Save skill"}
    text = "Save skill"
    highlight_index = 7


class _FakeBrowserUseSession:
    def __init__(self):
        self.start_calls = 0
        self.focus_calls = []
        self.agent_focus_target_id = None

    async def start(self):
        self.start_calls += 1

    async def get_or_create_cdp_session(self, target_id=None, focus=True):
        self.focus_calls.append({"target_id": target_id, "focus": focus})
        if focus:
            self.agent_focus_target_id = target_id
        return SimpleNamespace(target_id=target_id)

    async def get_current_page_url(self):
        return "https://example.test/list"

    async def get_current_page_title(self):
        return "Example List"

    async def get_tabs(self):
        return [
            SimpleNamespace(target_id="target-other", url="about:blank", title="Blank"),
            SimpleNamespace(target_id="target-123", url="https://example.test/list", title="Example List"),
        ]


def test_browser_use_model_actions_are_json_safe_when_interacted_element_is_runtime_object():
    class RuntimeObjectHistory:
        def model_actions(self):
            return [
                {
                    "click_element_by_index": {"index": 7},
                    "interacted_element": _FakeDOMInteractedElement(),
                }
            ]

    actions = _history_model_actions(RuntimeObjectHistory())

    assert actions[0]["interacted_element"]["attributes"]["id"] == "save-skill"
    assert actions[0]["interacted_element"]["x_path"] == "/html/body/button[1]"
    json.dumps(actions, ensure_ascii=False)


@pytest.mark.asyncio
async def test_focus_browser_use_target_starts_session_and_focuses_recorded_target():
    session = _FakeBrowserUseSession()

    diagnostics = await _focus_browser_use_target(
        session,
        target_id="target-123",
        expected_url="https://example.test/list",
    )

    assert session.start_calls == 1
    assert session.focus_calls == [{"target_id": "target-123", "focus": True}]
    assert diagnostics["requested_target_id"] == "target-123"
    assert diagnostics["focused_target_id"] == "target-123"
    assert diagnostics["focused_page"]["url"] == "https://example.test/list"
    assert diagnostics["tabs"][1]["target_id"] == "target-123"


@pytest.mark.asyncio
async def test_browser_use_operator_records_semantic_runtime_trace_with_action_history():
    async def fake_runner(**kwargs):
        assert kwargs["instruction"] == "Search invoice rows"
        assert kwargs["cdp_url"] == "ws://127.0.0.1:9222/devtools/browser/test"
        assert kwargs["model_config"]["model_name"] == "Qwen3.6-Max-Preview"
        return _FakeBrowserUseHistory()

    operator = BrowserUseRecordingOperator(
        model_config={"model_name": "Qwen3.6-Max-Preview"},
        cdp_url_resolver=lambda _page, _debug_context: "ws://127.0.0.1:9222/devtools/browser/test",
        browser_use_runner=fake_runner,
    )

    result = await operator.run(
        page=_FakePage(),
        instruction="Search invoice rows",
        runtime_results={"token": "abc"},
        debug_context={"session_id": "sess-1"},
    )

    assert result.success is True
    assert result.trace is not None
    assert result.trace.trace_type == RPATraceType.AI_OPERATION
    assert result.trace.source == "browser_use"
    assert result.trace.ai_execution.language == "browser_use"
    assert result.trace.ai_execution.code == ""
    assert result.trace.signals["runtime_ai"]["preserve"] is True
    assert result.trace.signals["browser_use"]["actions"][0]["click_element_by_index"]["index"] == 3
    assert result.trace.signals["browser_use"]["extracted_content"] == ["2 rows"]
    assert result.output == {"extracted_content": ["2 rows"], "action_count": 2}


@pytest.mark.asyncio
async def test_browser_use_operator_promotes_structured_done_capture_to_stable_runtime_result():
    async def fake_runner(**_kwargs):
        return _FakeStructuredDoneHistory(
            BrowserUseDoneOutput(
                kind="capture",
                key="Reimbursement Info",
                value={"报销人": "张三", "部门编码": "D001"},
            )
        )

    operator = BrowserUseRecordingOperator(
        model_config={"model_name": "test-model"},
        cdp_url_resolver=lambda _page, _debug_context: "ws://127.0.0.1:9222/devtools/browser/test",
        browser_use_runner=fake_runner,
    )

    result = await operator.run(
        page=_FakePage(),
        instruction="捕获报销人、部门编码",
        runtime_results={},
    )

    assert result.success is True
    assert result.output_key == "reimbursement_info"
    assert result.output == {"报销人": "张三", "部门编码": "D001"}
    assert result.trace is not None
    assert result.trace.output_key == "reimbursement_info"
    assert result.trace.output == {"报销人": "张三", "部门编码": "D001"}
    assert result.trace.ai_execution.output == {"报销人": "张三", "部门编码": "D001"}
    assert result.trace.signals["browser_use"]["done_output"] == {
        "kind": "capture",
        "key": "Reimbursement Info",
        "value": {"报销人": "张三", "部门编码": "D001"},
        "message": "",
    }


@pytest.mark.asyncio
async def test_browser_use_operator_deduplicates_recording_key_but_replay_uses_frozen_key():
    async def fake_runner(**_kwargs):
        return _FakeStructuredDoneHistory(
            BrowserUseDoneOutput(
                kind="capture",
                key="reimbursement_info",
                value={"报销人": "张三", "部门编码": "D001"},
            )
        )

    operator = BrowserUseRecordingOperator(
        model_config={"model_name": "test-model"},
        cdp_url_resolver=lambda _page, _debug_context: "ws://127.0.0.1:9222/devtools/browser/test",
        browser_use_runner=fake_runner,
    )

    recording_result = await operator.run(
        page=_FakePage(),
        instruction="再次捕获报销人、部门编码",
        runtime_results={"reimbursement_info": {"报销人": "李四"}},
    )
    replay_result = await operator.run(
        page=_FakePage(),
        instruction="捕获报销人、部门编码",
        runtime_results={},
        output_key="recorded_reimbursement_data",
    )

    assert recording_result.output_key == "reimbursement_info_2"
    assert replay_result.output_key == "recorded_reimbursement_data"
    assert replay_result.output == {"报销人": "张三", "部门编码": "D001"}


@pytest.mark.asyncio
async def test_browser_use_operator_does_not_create_runtime_key_for_structured_done_action():
    async def fake_runner(**_kwargs):
        return _FakeStructuredDoneHistory(
            BrowserUseDoneOutput(
                kind="action",
                message="已点击登录按钮",
            )
        )

    operator = BrowserUseRecordingOperator(
        model_config={"model_name": "test-model"},
        cdp_url_resolver=lambda _page, _debug_context: "ws://127.0.0.1:9222/devtools/browser/test",
        browser_use_runner=fake_runner,
    )

    result = await operator.run(
        page=_FakePage(),
        instruction="点击登录按钮",
        runtime_results={},
    )

    assert result.success is True
    assert result.output_key is None
    assert result.output == {"message": "已点击登录按钮"}
    assert result.trace is not None
    assert result.trace.output_key is None


@pytest.mark.asyncio
async def test_browser_use_operator_preserves_list_value_from_structured_done_capture():
    async def fake_runner(**_kwargs):
        return _FakeStructuredDoneHistory(
            BrowserUseDoneOutput(
                kind="capture",
                key="order_rows",
                value=[{"订单号": "A001"}, {"订单号": "A002"}],
            )
        )

    operator = BrowserUseRecordingOperator(
        model_config={"model_name": "test-model"},
        cdp_url_resolver=lambda _page, _debug_context: "ws://127.0.0.1:9222/devtools/browser/test",
        browser_use_runner=fake_runner,
    )

    result = await operator.run(
        page=_FakePage(),
        instruction="捕获订单列表",
        runtime_results={},
    )

    assert result.success is True
    assert result.output_key == "order_rows"
    assert result.output == [{"订单号": "A001"}, {"订单号": "A002"}]


@pytest.mark.asyncio
async def test_browser_use_operator_passes_recorded_cdp_target_id_to_runner_and_trace():
    async def fake_runner(**kwargs):
        assert kwargs["cdp_target_id"] == "target-123"
        assert kwargs["current_url"] == "https://example.test/list"
        return _FakeBrowserUseHistory()

    operator = BrowserUseRecordingOperator(
        model_config={"model_name": "test-model"},
        cdp_url_resolver=lambda _page, _debug_context: "ws://127.0.0.1:9222/devtools/browser/test",
        browser_use_runner=fake_runner,
    )

    result = await operator.run(
        page=_FakePage(),
        instruction="Fill the visible input",
        runtime_results={},
        debug_context={"cdp_target_id": "target-123"},
    )

    assert result.success is True
    assert result.trace is not None
    browser_use_signal = result.trace.signals["browser_use"]
    assert browser_use_signal["cdp_target_id"] == "target-123"
    assert browser_use_signal["scienceclaw_page"]["url"] == "https://example.test/list"


@pytest.mark.asyncio
async def test_browser_use_operator_does_not_accept_failed_browser_use_history():
    class FailedHistory(_FakeBrowserUseHistory):
        def is_successful(self):
            return False

    async def fake_runner(**_kwargs):
        return FailedHistory()

    operator = BrowserUseRecordingOperator(
        model_config={"model_name": "test-model"},
        cdp_url_resolver=lambda _page, _debug_context: "ws://127.0.0.1:9222/devtools/browser/test",
        browser_use_runner=fake_runner,
    )

    result = await operator.run(
        page=_FakePage(),
        instruction="Search invoice rows",
        runtime_results={},
    )

    assert result.success is False
    assert result.trace is None
    assert "browser-use reported task failure" in result.message


@pytest.mark.asyncio
async def test_browser_use_operator_does_not_accept_history_with_action_errors():
    class ErrorHistory(_FakeBrowserUseHistory):
        def model_actions(self):
            return [{"navigate": {"url": "https://example.test/list"}}]

        def action_results(self):
            return [
                SimpleNamespace(extracted_content="Navigated", long_term_memory="navigation"),
                SimpleNamespace(
                    extracted_content=None,
                    long_term_memory=None,
                    error="Error code: 403 - {'error': {'type': 'insufficient_quota'}}",
                ),
            ]

        def is_successful(self):
            return None

    async def fake_runner(**_kwargs):
        return ErrorHistory()

    operator = BrowserUseRecordingOperator(
        model_config={"model_name": "test-model"},
        cdp_url_resolver=lambda _page, _debug_context: "ws://127.0.0.1:9222/devtools/browser/test",
        browser_use_runner=fake_runner,
    )

    result = await operator.run(
        page=_FakePage(),
        instruction="Search invoice rows",
        runtime_results={},
    )

    assert result.success is False
    assert result.trace is None
    assert "insufficient_quota" in result.message
    assert result.diagnostics[0].raw["browser_use"]["actions"] == [{"navigate": {"url": "https://example.test/list"}}]
    assert "insufficient_quota" in result.diagnostics[0].raw["browser_use"]["action_results"][1]["error"]


@pytest.mark.asyncio
async def test_browser_use_operator_accepts_recovered_history_with_final_success():
    class RecoveredHistory(_FakeBrowserUseHistory):
        def action_results(self):
            return [
                SimpleNamespace(
                    extracted_content=None,
                    long_term_memory=None,
                    error="temporary schema validation error",
                ),
                SimpleNamespace(extracted_content="2 rows", long_term_memory="typed invoice"),
                SimpleNamespace(is_done=True, success=True, extracted_content="done", long_term_memory="done"),
            ]

        def is_successful(self):
            return True

    async def fake_runner(**_kwargs):
        return RecoveredHistory()

    operator = BrowserUseRecordingOperator(
        model_config={"model_name": "test-model"},
        cdp_url_resolver=lambda _page, _debug_context: "ws://127.0.0.1:9222/devtools/browser/test",
        browser_use_runner=fake_runner,
    )

    result = await operator.run(
        page=_FakePage(),
        instruction="Search invoice rows",
        runtime_results={},
    )

    assert result.success is True
    assert result.trace is not None
    assert result.trace.signals["browser_use"]["action_results"][0]["error"] == "temporary schema validation error"


@pytest.mark.asyncio
async def test_browser_use_operator_does_not_accept_navigation_only_without_success_evidence():
    class NavigationOnlyHistory(_FakeBrowserUseHistory):
        def model_actions(self):
            return [{"navigate": {"url": "https://example.test/list"}}]

        def action_results(self):
            return [SimpleNamespace(extracted_content="Navigated", long_term_memory="navigation")]

        def extracted_content(self):
            return ["Navigated"]

        def is_successful(self):
            return None

    async def fake_runner(**_kwargs):
        return NavigationOnlyHistory()

    operator = BrowserUseRecordingOperator(
        model_config={"model_name": "test-model"},
        cdp_url_resolver=lambda _page, _debug_context: "ws://127.0.0.1:9222/devtools/browser/test",
        browser_use_runner=fake_runner,
    )

    result = await operator.run(
        page=_FakePage(),
        instruction="Search invoice rows",
        runtime_results={},
    )

    assert result.success is False
    assert result.trace is None
    assert "initial navigation" in result.message


def test_browser_use_task_keeps_native_agent_semantics_and_only_adds_product_context():
    task = _build_browser_use_task(
        "打开风险最高的订单",
        {"department": "华东"},
        {"label": "异常订单区域"},
    )

    assert "Instruction: 打开风险最高的订单" in task
    assert "Available prior runtime results: {'department': '华东'}" in task
    assert "Selected region context: {'label': '异常订单区域'}" in task
    assert "Use browser-use action schemas exactly" not in task
    assert "evaluate with an IIFE" not in task


def test_browser_use_task_omits_upload_paths_for_non_upload_instruction(monkeypatch):
    monkeypatch.setenv("BROWSER_USE_AVAILABLE_FILE_PATHS", "E:\\RPA-Agent\\ScienceClaw\\.tmp\\rpa-live-upload.txt")

    task = _build_browser_use_task("帮我登录采购验收系统", {}, {})

    assert "Available upload file paths" not in task
    assert "rpa-live-upload.txt" not in task


def test_browser_use_task_includes_upload_paths_for_upload_instruction(monkeypatch):
    monkeypatch.setenv("BROWSER_USE_AVAILABLE_FILE_PATHS", "E:\\RPA-Agent\\ScienceClaw\\.tmp\\rpa-live-upload.txt")

    task = _build_browser_use_task("上传验收附件", {}, {})

    assert "Available upload file paths" in task
    assert "rpa-live-upload.txt" in task


@pytest.mark.asyncio
async def test_browser_use_runner_keeps_host_alive_avoids_planner_overrides_and_detaches(monkeypatch):
    captured = SimpleNamespace(session=None, agent_kwargs=None)

    class FakeBrowserSession(_FakeBrowserUseSession):
        def __init__(self, *, cdp_url, keep_alive):
            super().__init__()
            self.cdp_url = cdp_url
            self.keep_alive = keep_alive
            self.stop_calls = 0
            captured.session = self

        async def stop(self):
            self.stop_calls += 1

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.agent_kwargs = kwargs
            self.task = kwargs["task"]

        async def run(self, *, max_steps):
            assert max_steps == 9
            if "Force runner failure" in self.task:
                raise RuntimeError("runner failed")
            return _FakeBrowserUseHistory()

    class FakeChatOpenAI:
        def __init__(self, **_kwargs):
            pass

    browser_use_module = ModuleType("browser_use")
    browser_use_module.Agent = FakeAgent
    session_module = ModuleType("browser_use.browser.session")
    session_module.BrowserSession = FakeBrowserSession
    chat_module = ModuleType("browser_use.llm.openai.chat")
    chat_module.ChatOpenAI = FakeChatOpenAI
    monkeypatch.setitem(sys.modules, "browser_use", browser_use_module)
    monkeypatch.setitem(sys.modules, "browser_use.browser.session", session_module)
    monkeypatch.setitem(sys.modules, "browser_use.llm.openai.chat", chat_module)

    await _run_browser_use_agent(
        instruction="Open the highest-risk order",
        cdp_url="ws://127.0.0.1:9222/devtools/browser/test",
        model_config={
            "model_name": "test-model",
            "api_key": "test-key",
            "base_url": "https://llm.example.test/v1",
        },
        runtime_results={"department": "华东"},
        region_context={},
        max_steps=9,
        current_url="https://example.test/orders",
        cdp_target_id="target-123",
    )

    assert captured.session.keep_alive is True
    assert captured.session.stop_calls == 1
    assert captured.agent_kwargs["browser_session"] is captured.session
    assert "initial_actions" not in captured.agent_kwargs
    assert "max_actions_per_step" not in captured.agent_kwargs
    assert captured.agent_kwargs["output_model_schema"] is BrowserUseDoneOutput
    assert captured.agent_kwargs["extraction_schema"]["required"] == ["key", "data"]
    assert captured.agent_kwargs["extraction_schema"]["properties"]["data"]["type"] == "object"
    assert "Available prior runtime results: {'department': '华东'}" in captured.agent_kwargs["task"]

    with pytest.raises(RuntimeError, match="runner failed"):
        await _run_browser_use_agent(
            instruction="Force runner failure",
            cdp_url="ws://127.0.0.1:9222/devtools/browser/test",
            model_config={
                "model_name": "test-model",
                "api_key": "test-key",
                "base_url": "https://llm.example.test/v1",
            },
            runtime_results={},
            region_context={},
            max_steps=9,
            current_url="https://example.test/orders",
            cdp_target_id="target-123",
        )

    assert captured.session.keep_alive is True
    assert captured.session.stop_calls == 1
