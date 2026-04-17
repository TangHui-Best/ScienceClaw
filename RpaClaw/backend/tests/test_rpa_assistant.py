import importlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


ASSISTANT_MODULE = importlib.import_module("backend.rpa.assistant")
ASSISTANT_RUNTIME_MODULE = importlib.import_module("backend.rpa.assistant_runtime")
RUNTIME_AI_INSTRUCTION_MODULE = importlib.import_module("backend.rpa.runtime_ai_instruction")


class _FakeModel:
    def __init__(self, response):
        self._response = response

    async def ainvoke(self, _messages):
        return self._response


class _FakeStreamingModel:
    def __init__(self, chunks):
        self._chunks = chunks

    async def astream(self, _messages):
        for chunk in self._chunks:
            yield chunk


class _FakePage:
    url = "https://example.com"

    async def title(self):
        return "Example"


class _FakeSnapshotFrame:
    def __init__(self, name, url, frame_path, elements=None, child_frames=None):
        self.name = name
        self.url = url
        self._frame_path = frame_path
        self._elements = elements or []
        self.child_frames = child_frames or []

    async def evaluate(self, _script):
        return json.dumps(self._elements)


class _FakeSnapshotPage:
    url = "https://example.com"

    def __init__(self, main_frame):
        self.main_frame = main_frame

    async def title(self):
        return "Example"


class _FakeLocator:
    def __init__(self, text=""):
        self.click_calls = 0
        self.text = text

    async def click(self):
        self.click_calls += 1

    async def inner_text(self):
        return self.text


class _FakeFrameScope:
    def __init__(self):
        self.locator_calls = []
        self.locator_obj = _FakeLocator("Resolved text")

    def locator(self, selector):
        self.locator_calls.append(selector)
        return self.locator_obj

    def frame_locator(self, selector):
        self.locator_calls.append(f"frame:{selector}")
        return self

    def get_by_role(self, role, **kwargs):
        self.locator_calls.append(f"role:{role}:{kwargs.get('name', '')}")
        return self.locator_obj

    def get_by_text(self, value):
        self.locator_calls.append(f"text:{value}")
        return self.locator_obj


class _FakeActionPage(_FakePage):
    def __init__(self):
        self.url = "https://example.com"
        self.scope = _FakeFrameScope()
        self.goto_calls = []
        self.load_state_calls = []
        self.timeout_calls = []

    def frame_locator(self, selector):
        self.scope.locator_calls.append(f"frame:{selector}")
        return self.scope

    def locator(self, selector):
        self.scope.locator_calls.append(selector)
        return self.scope.locator_obj

    def get_by_role(self, role, **kwargs):
        self.scope.locator_calls.append(f"role:{role}:{kwargs.get('name', '')}")
        return self.scope.locator_obj

    def get_by_text(self, value):
        self.scope.locator_calls.append(f"text:{value}")
        return self.scope.locator_obj

    async def goto(self, url):
        self.goto_calls.append(url)
        self.url = url

    async def wait_for_load_state(self, state):
        self.load_state_calls.append(state)

    async def wait_for_timeout(self, timeout_ms):
        self.timeout_calls.append(timeout_ms)


class RPAReActAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_llm_preserves_whitespace_between_stream_chunks(self):
        response_text = 'await page.goto("https://github.com/trending?since=weekly")\n'
        stream_chunks = [
            SimpleNamespace(content="await", additional_kwargs={}),
            SimpleNamespace(content=" page", additional_kwargs={}),
            SimpleNamespace(content='.goto("https://github.com/trending?since=weekly")\n', additional_kwargs={}),
        ]

        with patch.object(
            ASSISTANT_MODULE,
            "get_llm_model",
            return_value=_FakeStreamingModel(stream_chunks),
        ):
            chunks = []
            async for chunk in ASSISTANT_MODULE.RPAReActAgent._stream_llm([]):
                chunks.append(chunk)

        self.assertEqual(chunks, [response_text])

    async def test_stream_llm_extracts_text_from_stream_content_blocks(self):
        response_text = (
            '{"thought":"task done","action":"done","code":"","description":"done","risk":"none","risk_reason":""}'
        )
        stream_chunks = [
            SimpleNamespace(
                content=[
                    {"type": "thinking", "thinking": "inspect the page"},
                    {"type": "text", "text": response_text},
                ],
                additional_kwargs={},
            ),
        ]

        with patch.object(
            ASSISTANT_MODULE,
            "get_llm_model",
            return_value=_FakeStreamingModel(stream_chunks),
        ):
            chunks = []
            async for chunk in ASSISTANT_MODULE.RPAReActAgent._stream_llm([]):
                chunks.append(chunk)

        self.assertEqual(chunks, [response_text])

    async def test_stream_llm_falls_back_to_stream_reasoning_content(self):
        response_text = (
            '{"thought":"task done","action":"done","code":"","description":"done","risk":"none","risk_reason":""}'
        )
        stream_chunks = [
            SimpleNamespace(
                content="",
                additional_kwargs={"reasoning_content": response_text},
            ),
        ]

        with patch.object(
            ASSISTANT_MODULE,
            "get_llm_model",
            return_value=_FakeStreamingModel(stream_chunks),
        ):
            chunks = []
            async for chunk in ASSISTANT_MODULE.RPAReActAgent._stream_llm([]):
                chunks.append(chunk)

        self.assertEqual(chunks, [response_text])

    async def test_stream_llm_extracts_text_from_content_blocks(self):
        response_text = (
            '{"thought":"task done","action":"done","code":"","description":"done","risk":"none","risk_reason":""}'
        )
        fake_response = SimpleNamespace(
            content=[
                {"type": "thinking", "thinking": "inspect the page"},
                {"type": "text", "text": response_text},
            ],
            additional_kwargs={},
        )

        with patch.object(
            ASSISTANT_MODULE,
            "get_llm_model",
            return_value=_FakeModel(fake_response),
        ):
            chunks = []
            async for chunk in ASSISTANT_MODULE.RPAReActAgent._stream_llm([]):
                chunks.append(chunk)

        self.assertEqual(chunks, [response_text])

    async def test_run_falls_back_to_reasoning_content_when_text_is_empty(self):
        response_text = (
            '{"thought":"task done","action":"done","code":"","description":"done","risk":"none","risk_reason":""}'
        )
        fake_response = SimpleNamespace(
            content="",
            additional_kwargs={"reasoning_content": response_text},
        )
        agent = ASSISTANT_MODULE.RPAReActAgent()

        with patch.object(
            ASSISTANT_MODULE,
            "get_llm_model",
            return_value=_FakeModel(fake_response),
        ), patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value={"url": "https://example.com", "title": "Example", "frames": []}),
        ):
            events = []
            async for event in agent.run(
                session_id="session-1",
                page=_FakePage(),
                goal="finish the task",
                existing_steps=[],
            ):
                events.append(event)

        self.assertEqual(
            [event["event"] for event in events],
            ["agent_thought", "agent_done"],
        )

    async def test_react_agent_build_observation_lists_frames_and_collections(self):
        snapshot = {
            "url": "https://example.com",
            "title": "Example",
            "frames": [
                {
                    "frame_hint": "main document",
                    "frame_path": [],
                    "elements": [{"index": 1, "tag": "button", "role": "button", "name": "Search"}],
                    "collections": [],
                },
                {
                    "frame_hint": "iframe title=results",
                    "frame_path": ["iframe[title='results']"],
                    "elements": [{"index": 1, "tag": "a", "role": "link", "name": "Result A"}],
                    "collections": [{"kind": "search_results", "item_count": 2}],
                },
            ],
        }

        content = ASSISTANT_MODULE.RPAReActAgent._build_observation(snapshot, 0)

        self.assertIn("Frame: main document", content)
        self.assertIn("Frame: iframe title=results", content)
        self.assertIn("Collection: search_results (2 items)", content)

    async def test_react_agent_build_observation_lists_snapshot_v2_containers(self):
        snapshot = {
            "url": "https://example.com",
            "title": "Example",
            "frames": [],
            "actionable_nodes": [],
            "content_nodes": [],
            "containers": [
                {
                    "container_id": "table-1",
                    "frame_path": [],
                    "container_kind": "table",
                    "name": "合同列表",
                    "summary": "合同下载列表",
                    "child_actionable_ids": ["a-1", "a-2"],
                    "child_content_ids": ["c-1", "c-2"],
                }
            ],
        }

        content = ASSISTANT_MODULE.RPAReActAgent._build_observation(snapshot, 0)

        self.assertIn("Container: table 合同列表", content)
        self.assertIn("actionable=2", content)
        self.assertIn("content=2", content)

    async def test_react_agent_executes_structured_collection_action_with_frame_context(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://example.com",
            "title": "Example",
            "frames": [
                {
                    "frame_path": ["iframe[title='results']"],
                    "frame_hint": "iframe title=results",
                    "elements": [],
                    "collections": [
                        {
                            "kind": "repeated_items",
                            "frame_path": ["iframe[title='results']"],
                            "container_hint": {"locator": {"method": "css", "value": "main article.card"}},
                            "item_hint": {"role": "link", "locator": {"method": "css", "value": "h2 a"}},
                            "item_count": 2,
                            "items": [
                                {"index": 1, "tag": "a", "role": "link", "name": "Result A"},
                                {"index": 2, "tag": "a", "role": "link", "name": "Result B"},
                            ],
                        }
                    ],
                }
            ],
        }
        responses = [
            json.dumps(
                {
                    "thought": "click the first item",
                    "action": "execute",
                    "operation": "click",
                    "description": "点击列表中的第一个项目",
                    "target_hint": {"role": "link", "name": "item"},
                    "collection_hint": {"kind": "search_results"},
                    "ordinal": "first",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ):
            events = []
            async for event in agent.run(
                session_id="session-1",
                page=page,
                goal="点击列表中的第一个项目",
                existing_steps=[],
            ):
                events.append(event)

        step_done = next(event for event in events if event["event"] == "agent_step_done")
        self.assertEqual(page.scope.locator_calls[0], "frame:iframe[title='results']")
        self.assertEqual(
            json.loads(step_done["data"]["step"]["target"]),
            {
                "method": "collection_item",
                "collection": {"method": "css", "value": "main article.card"},
                "ordinal": "first",
                "item": {"method": "css", "value": "h2 a"},
            },
        )

    async def test_react_agent_persists_ai_instruction_step(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://example.com/project",
            "title": "Project",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "summarize the current project semantically",
                    "action": "execute",
                    "description": "总结当前项目内容",
                    "ai_instruction": {
                        "action": "ai_instruction",
                        "description": "总结当前项目内容",
                        "prompt": "总结当前项目内容",
                        "instruction_kind": "semantic_extract",
                        "input_scope": {"mode": "current_page"},
                        "output_expectation": {"mode": "extract"},
                        "execution_hint": {
                            "requires_dom_snapshot": True,
                            "allow_navigation": False,
                            "max_reasoning_steps": 10,
                        },
                        "result_key": "project_summary",
                    },
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "execute_ai_instruction",
            new=AsyncMock(return_value={"success": True, "output": "项目摘要"}),
        ) as execute_ai_instruction:
            events = []
            async for event in agent.run(
                session_id="session-ai-instruction",
                page=page,
                goal="总结当前项目内容",
                existing_steps=[],
            ):
                events.append(event)

        step_done = next(event for event in events if event["event"] == "agent_step_done")
        self.assertEqual(step_done["data"]["step"]["action"], "ai_instruction")
        self.assertEqual(step_done["data"]["step"]["instruction_kind"], "semantic_extract")
        self.assertEqual(step_done["data"]["output"], "项目摘要")
        execute_ai_instruction.assert_awaited_once()

    async def test_react_agent_persists_ai_script_step_for_code_execution(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://example.com/trending",
            "title": "Trending",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "compare numeric values and click the largest one",
                    "action": "execute",
                    "description": "找到 star 数量最高的项目并点击打开",
                    "code": "async def run(page):\n    return 'clicked'",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(return_value={"success": True, "output": "clicked"}),
        ) as execute_on_page:
            events = []
            async for event in agent.run(
                session_id="session-ai-script",
                page=page,
                goal="找到当前页面 star 数量最高的项目并点击打开它",
                existing_steps=[],
            ):
                events.append(event)

        step_done = next(event for event in events if event["event"] == "agent_step_done")
        self.assertEqual(step_done["data"]["step"]["action"], "ai_script")
        self.assertEqual(step_done["data"]["output"], "clicked")
        execute_on_page.assert_awaited_once()

    async def test_react_agent_follows_ai_script_navigation_target_output(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        page.url = "https://github.com/trending"
        snapshot = {
            "url": "https://github.com/trending",
            "title": "Trending",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "find the repo with the highest stars and open it",
                    "action": "execute",
                    "description": "鎵惧埌 star 鏁伴噺鏈€楂樼殑椤圭洰骞舵墦寮€",
                    "code": "async def run(page):\n    return {'target_url': '/obra/superpowers'}",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "output": '{"target_url": "/obra/superpowers"}',
                    "raw_output": {"target_url": "/obra/superpowers"},
                }
            ),
        ):
            events = []
            async for event in agent.run(
                session_id="session-ai-script-nav",
                page=page,
                goal="鎵撳紑 Trending锛屾壘鍒?star 鏁伴噺鏈€楂樼殑椤圭洰骞舵墦寮€",
                existing_steps=[],
            ):
                events.append(event)

        self.assertIn("https://github.com/obra/superpowers", page.goto_calls)
        self.assertIn("domcontentloaded", page.load_state_calls)

    def test_coerce_to_ai_instruction_preserves_user_summary_rule(self):
        step = ASSISTANT_MODULE.RPAAssistant._coerce_to_ai_instruction(
            "Summarize the current project, focusing on purpose, capabilities, and limitations.",
            {
                "action": "ai_instruction",
                "description": "Summarize repository core content",
                "prompt": "Summarize the current project, focusing on purpose, capabilities, and limitations.",
                "instruction_kind": "semantic_extract",
                "output_expectation": {"mode": "extract"},
            },
        )

        self.assertEqual(step["result_key"], "project_summary")
        self.assertEqual(
            step["prompt"],
            "Summarize the current project, focusing on purpose, capabilities, and limitations.",
        )

    def test_coerce_to_ai_instruction_prefers_user_prompt_for_forced_runtime_rule(self):
        user_message = "把这条规则保存为运行时 AI 指令：根据当前页面内容判断是否需要人工复核。"
        step = ASSISTANT_MODULE.RPAAssistant._coerce_to_ai_instruction(
            user_message,
            {
                "action": "extract_text",
                "description": "保存运行时AI指令",
                "prompt": "保存运行时AI指令",
                "result_key": "runtime_ai_rule",
            },
            prefer_user_prompt=True,
        )

        self.assertEqual(step["prompt"], user_message)

    async def test_react_agent_breaks_complex_goal_into_multiple_step_types(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/trending",
            "title": "Trending",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "first open the repository with deterministic numeric comparison logic",
                    "action": "execute",
                    "description": "找到 star 数量最高的项目并点击打开",
                    "code": "async def run(page):\n    return 'opened top project'",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "now summarize the current project content semantically",
                    "action": "execute",
                    "description": "总结当前项目内容",
                    "ai_instruction": {
                        "description": "总结当前项目内容",
                        "prompt": "总结当前项目内容",
                        "instruction_kind": "semantic_extract",
                        "input_scope": {"mode": "current_page"},
                        "output_expectation": {"mode": "extract"},
                        "execution_hint": {
                            "requires_dom_snapshot": True,
                            "allow_navigation": False,
                            "max_reasoning_steps": 10,
                        },
                        "result_key": "project_summary",
                    },
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(return_value={"success": True, "output": "opened top project"}),
        ) as execute_on_page, patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "execute_ai_instruction",
            new=AsyncMock(return_value={"success": True, "output": "项目摘要"}),
        ) as execute_ai_instruction:
            events = []
            async for event in agent.run(
                session_id="session-complex-goal",
                page=page,
                goal="打开 trending，找最相关的项目，进去后总结核心内容",
                existing_steps=[],
            ):
                events.append(event)

        step_done_events = [event for event in events if event["event"] == "agent_step_done"]
        recorded_steps_event = next(event for event in events if event["event"] == "agent_recorded_steps")
        self.assertEqual(len(step_done_events), 2)
        self.assertEqual(step_done_events[0]["data"]["step"]["action"], "ai_instruction")
        self.assertEqual(step_done_events[1]["data"]["step"]["action"], "ai_instruction")
        self.assertEqual(len(recorded_steps_event["data"]["steps"]), 2)
        self.assertEqual(recorded_steps_event["data"]["steps"][0]["action"], "ai_instruction")
        self.assertEqual(recorded_steps_event["data"]["steps"][1]["action"], "ai_instruction")
        execute_on_page.assert_not_awaited()
        self.assertEqual(execute_ai_instruction.await_count, 2)

    async def test_react_agent_coerces_semantic_relevance_selection_to_ai_instruction(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/trending",
            "title": "Trending",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "use a script to find the project most related to skill and open it",
                    "action": "execute",
                    "description": "Find the project most related to SKILL and open it",
                    "code": "async def run(page):\n    return {'target_url': 'https://github.com/example/skills-repo'}",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(return_value={"success": True, "output": "opened repo"}),
        ) as execute_on_page, patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "execute_ai_instruction",
            new=AsyncMock(return_value={"success": True, "output": "opened repo"}),
        ) as execute_ai_instruction:
            events = []
            async for event in agent.run(
                session_id="session-semantic-relevance",
                page=page,
                goal="Open the project most related to SKILL on the current trending page",
                existing_steps=[],
            ):
                events.append(event)

        step_done = next(event for event in events if event["event"] == "agent_step_done")
        self.assertEqual(step_done["data"]["step"]["action"], "ai_instruction")
        execute_on_page.assert_not_awaited()
        execute_ai_instruction.assert_awaited_once()

    def test_candidate_requires_deterministic_ai_script_for_record_array_ai_instruction(self):
        self.assertTrue(
            ASSISTANT_MODULE.RPAReActAgent._candidate_requires_deterministic_ai_script(
                goal="",
                thought="",
                description="Collect first 10 pull requests into a strict array",
                structured_intent=None,
                ai_instruction_step={
                    "action": "ai_instruction",
                    "description": "Collect first 10 pull requests into a strict array",
                    "prompt": "Extract the first 10 pull requests with title and author and return a strict array.",
                    "result_key": "first_10_prs",
                },
            )
        )

    async def disabled_test_react_agent_accepts_structured_click_when_model_chooses_it(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/trending",
            "title": "Trending",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "the top project is visible so click it directly",
                    "action": "execute",
                    "operation": "click",
                    "description": "点击 star 数量最多的项目",
                    "target_hint": {"role": "link", "name": "obra / superpowers"},
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            ASSISTANT_MODULE,
            "resolve_structured_intent",
            new=Mock(return_value={"action": "click", "target": "obra / superpowers"}),
        ), patch.object(
            ASSISTANT_MODULE,
            "execute_structured_intent",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "output": "clicked target",
                    "step": {"action": "click", "description": "点击 star 数量最多的项目"},
                }
            ),
        ) as execute_structured:
            events = []
            async for event in agent.run(
                session_id="session-structured-click",
                page=page,
                goal="打开 trending，找 star 数量最多的项目并点击打开",
                existing_steps=[],
            ):
                events.append(event)

        step_done_events = [event for event in events if event["event"] == "agent_step_done"]
        self.assertEqual(len(step_done_events), 1)
        self.assertEqual(step_done_events[0]["data"]["step"]["action"], "click")
        execute_structured.assert_awaited_once()

    async def test_react_agent_replans_structured_click_into_ai_script_for_deterministic_selection(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/trending",
            "title": "Trending",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "the top project is visible so click it directly",
                    "action": "execute",
                    "operation": "click",
                    "description": "Click the project with the most stars",
                    "target_hint": {"role": "link", "name": "obra / superpowers"},
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "this is deterministic ranking, so use ai_script",
                    "action": "execute",
                    "description": "Find the project with the most stars and open it",
                    "code": "async def run(page):\n    return {'target_url': '/obra/superpowers'}",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            ASSISTANT_MODULE,
            "resolve_structured_intent",
            new=Mock(return_value={"action": "click", "target": "obra / superpowers"}),
        ), patch.object(
            ASSISTANT_MODULE,
            "execute_structured_intent",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "output": "clicked target",
                    "step": {"action": "click", "description": "Click the project with the most stars"},
                }
            ),
        ) as execute_structured, patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(return_value={"success": True, "output": "opened repo"}),
        ) as execute_script:
            events = []
            async for event in agent.run(
                session_id="session-structured-click-replan",
                page=page,
                goal="Open trending, find the project with the most stars, and open it",
                existing_steps=[],
            ):
                events.append(event)

        step_done_events = [event for event in events if event["event"] == "agent_step_done"]
        self.assertEqual(len(step_done_events), 1)
        self.assertEqual(step_done_events[0]["data"]["step"]["action"], "ai_script")
        execute_structured.assert_not_awaited()
        execute_script.assert_awaited_once()

    async def test_react_agent_reflects_after_repeated_structured_click_without_progress(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/public-apis/public-apis",
            "title": "public-apis/public-apis",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "open the pull requests tab",
                    "action": "execute",
                    "operation": "click",
                    "description": "Click Pull requests tab",
                    "target_hint": {"role": "link", "name": "Pull requests"},
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "click the pull requests tab again",
                    "action": "execute",
                    "operation": "click",
                    "description": "Click Pull requests tab",
                    "target_hint": {"role": "link", "name": "Pull requests"},
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "collect the first 10 pull requests in one deterministic step",
                    "action": "execute",
                    "description": "Collect first 10 pull requests into a strict array",
                    "code": "async def run(page):\n    return {'output': [{'title': 't', 'author': 'a'}]}",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            ASSISTANT_MODULE,
            "resolve_structured_intent",
            new=Mock(return_value={"action": "click", "target": "Pull requests"}),
        ), patch.object(
            ASSISTANT_MODULE,
            "execute_structured_intent",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "output": "",
                    "step": {"action": "click", "description": "Click Pull requests tab"},
                }
            ),
        ) as execute_structured, patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(return_value={"success": True, "output": "strict array"}),
        ) as execute_on_page, patch.object(
            agent,
            "_request_ai_script_candidate",
            new=AsyncMock(
                return_value={
                    "thought": "collect the first 10 pull requests in one deterministic step",
                    "action": "execute",
                    "structured_intent": None,
                    "ai_instruction_step": None,
                    "code": "async def run(page):\n    return {'output': [{'title': 't', 'author': 'a'}]}",
                    "description": "Collect first 10 pull requests into a strict array",
                    "risk": "none",
                    "risk_reason": "",
                    "action_payload": "async def run(page):\n    return {'output': [{'title': 't', 'author': 'a'}]}",
                    "parsed": {"code": "async def run(page):\n    return {'output': [{'title': 't', 'author': 'a'}]}"},
                }
            ),
        ):
            events = []
            async for event in agent.run(
                session_id="session-stall-reflection",
                page=page,
                goal="Open the repo pull requests page and collect the first 10 PRs as a strict array of author and title.",
                existing_steps=[],
            ):
                events.append(event)

        feedback_messages = [
            item["content"]
            for item in agent._history
            if item.get("role") == "user" and "Previous step proposal was rejected." in item.get("content", "")
        ]
        self.assertTrue(any("did not make reliable progress" in message for message in feedback_messages))
        execute_structured.assert_awaited_once()
        execute_on_page.assert_awaited_once()
        step_done_events = [event for event in events if event["event"] == "agent_step_done"]
        self.assertEqual(step_done_events[-1]["data"]["step"]["action"], "ai_script")

    async def test_react_agent_compacts_history_after_successful_step_to_drop_old_snapshot_details(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        trending_snapshot = {
            "url": "https://github.com/trending",
            "title": "Trending",
            "frames": [
                {
                    "frame_hint": "main document",
                    "frame_path": [],
                    "elements": [
                        {"index": 1, "tag": "a", "role": "link", "name": "Apollo-11", "href": "/example/apollo"},
                    ],
                    "collections": [],
                }
            ],
        }
        repo_snapshot = {
            "url": "https://github.com/example/apollo",
            "title": "example/apollo",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "find the top repository and open it",
                    "action": "execute",
                    "description": "Parse star counts and open the top repository",
                    "code": "async def run(page):\n    return {'target_url': 'https://github.com/example/apollo'}",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
        ]
        captured_histories = []

        async def fake_stream(history, _model_config=None):
            captured_histories.append("\n".join(message.get("content", "") for message in history))
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(side_effect=[trending_snapshot, repo_snapshot]),
        ), patch.object(
            agent,
            "_request_ai_script_candidate",
            new=AsyncMock(
                return_value={
                    "thought": "find the top repository and open it",
                    "action": "execute",
                    "structured_intent": None,
                    "ai_instruction_step": None,
                    "code": "async def run(page):\n    return {'target_url': 'https://github.com/example/apollo'}",
                    "description": "Parse star counts and open the top repository",
                    "risk": "none",
                    "risk_reason": "",
                    "action_payload": "async def run(page):\n    return {'target_url': 'https://github.com/example/apollo'}",
                    "parsed": {"code": "async def run(page):\n    return {'target_url': 'https://github.com/example/apollo'}"},
                }
            ),
        ), patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "output": '{"target_url": "https://github.com/example/apollo"}',
                    "raw_output": {"target_url": "https://github.com/example/apollo"},
                }
            ),
        ):
            events = []
            async for event in agent.run(
                session_id="session-history-compaction",
                page=page,
                goal="Open trending, find the top repository, and continue from that repository.",
                existing_steps=[],
            ):
                events.append(event)

        self.assertEqual(page.url, "https://github.com/example/apollo")
        self.assertGreaterEqual(len(captured_histories), 2)
        self.assertIn("Apollo-11", captured_histories[0])
        self.assertNotIn("Apollo-11", captured_histories[1])
        self.assertIn("Completed subtask facts", captured_histories[1])
        self.assertTrue(any(event["event"] == "agent_done" for event in events))

    async def test_react_agent_repairs_ai_script_locally_without_recording_failed_attempt(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/example/repo/pulls",
            "title": "Pull requests",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "extract the first 10 PRs",
                    "action": "execute",
                    "description": "Collect first 10 pull requests into a strict array",
                    "code": "async def run(page):\n    return [{'title': '2', 'author': 'bad'}]",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        repaired_candidate = {
            "thought": "repair locally",
            "action": "execute",
            "structured_intent": None,
            "ai_instruction_step": None,
            "code": "async def run(page):\n    return [{'title': 'Good title', 'author': 'alice'}]",
            "description": "Collect first 10 pull requests into a strict array",
            "risk": "none",
            "risk_reason": "",
            "action_payload": "async def run(page):\n    return [{'title': 'Good title', 'author': 'alice'}]",
            "parsed": {"code": "async def run(page):\n    return [{'title': 'Good title', 'author': 'alice'}]"},
        }

        agent._stream_llm = fake_stream

        execute_side_effect = [
            {
                "success": True,
                "output": json.dumps([{"title": "2", "author": "bad"}]),
                "raw_output": [{"title": "2", "author": "bad"}],
            },
            {
                "success": True,
                "output": json.dumps([{"title": "Good title", "author": "alice"}]),
                "raw_output": [{"title": "Good title", "author": "alice"}],
            },
        ]

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            agent,
            "_request_ai_script_candidate",
            new=AsyncMock(
                return_value={
                    "thought": "extract the first 10 PRs",
                    "action": "execute",
                    "structured_intent": None,
                    "ai_instruction_step": None,
                    "code": "async def run(page):\n    return [{'title': '2', 'author': 'bad'}]",
                    "description": "Collect first 10 pull requests into a strict array",
                    "risk": "none",
                    "risk_reason": "",
                    "action_payload": "async def run(page):\n    return [{'title': '2', 'author': 'bad'}]",
                    "parsed": {"code": "async def run(page):\n    return [{'title': '2', 'author': 'bad'}]"},
                }
            ),
        ), patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(side_effect=execute_side_effect),
        ) as execute_on_page, patch.object(
            agent,
            "_request_ai_script_repair",
            new=AsyncMock(return_value=repaired_candidate),
        ) as repair_step:
            events = []
            async for event in agent.run(
                session_id="session-local-ai-script-repair",
                page=page,
                goal="Collect the first 10 PRs as a strict array of title and author.",
                existing_steps=[],
            ):
                events.append(event)

        repair_step.assert_awaited_once()
        self.assertEqual(execute_on_page.await_count, 2)
        recorded_steps_events = [event for event in events if event["event"] == "agent_recorded_steps"]
        self.assertEqual(len(recorded_steps_events[-1]["data"]["steps"]), 1)
        self.assertEqual(recorded_steps_events[-1]["data"]["steps"][0]["action"], "ai_script")

    async def test_react_agent_reuses_observation_snapshot_for_local_repair_when_page_unchanged(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/example/repo/pulls",
            "title": "Pull requests",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "collect the first 10 PRs",
                    "action": "execute",
                    "step_type": "ai_script",
                    "description": "Collect first 10 pull requests into a strict array",
                    "result_key": "first_10_prs_info",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        generated_candidate = {
            "thought": "generated via dedicated channel",
            "action": "execute",
            "ai_script_plan": {
                "step_type": "ai_script",
                "description": "Collect first 10 pull requests into a strict array",
                "result_key": "first_10_prs_info",
            },
            "structured_intent": None,
            "ai_instruction_step": None,
            "code": "async def run(page):\n    raise RuntimeError('first draft')",
            "description": "Collect first 10 pull requests into a strict array",
            "risk": "none",
            "risk_reason": "",
            "action_payload": "async def run(page):\n    raise RuntimeError('first draft')",
            "parsed": {"result_key": "first_10_prs_info"},
        }
        repaired_candidate = {
            "thought": "repair via dedicated channel",
            "action": "execute",
            "ai_script_plan": generated_candidate["ai_script_plan"],
            "structured_intent": None,
            "ai_instruction_step": None,
            "code": "async def run(page):\n    return [{'title': 'Good title', 'author': 'alice'}]",
            "description": "Collect first 10 pull requests into a strict array",
            "risk": "none",
            "risk_reason": "",
            "action_payload": "async def run(page):\n    return [{'title': 'Good title', 'author': 'alice'}]",
            "parsed": {"result_key": "first_10_prs_info"},
        }

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ) as build_snapshot, patch.object(
            agent,
            "_request_ai_script_candidate",
            new=AsyncMock(return_value=generated_candidate),
        ), patch.object(
            agent,
            "_request_ai_script_repair",
            new=AsyncMock(return_value=repaired_candidate),
        ) as repair_ai_script, patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(
                side_effect=[
                    {"success": False, "error": "first draft failed", "output": ""},
                    {
                        "success": True,
                        "output": json.dumps([{"title": "Good title", "author": "alice"}]),
                        "raw_output": [{"title": "Good title", "author": "alice"}],
                    },
                ]
            ),
        ):
            events = []
            async for event in agent.run(
                session_id="session-reuse-repair-snapshot",
                page=page,
                goal="Collect the first 10 PRs as a strict array of title and author.",
                existing_steps=[],
            ):
                events.append(event)

        repair_ai_script.assert_awaited_once()
        self.assertEqual(build_snapshot.await_count, 2)
        self.assertTrue(any(event["event"] == "agent_done" for event in events))

    async def test_react_agent_routes_ai_script_execution_through_dedicated_generator(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/example/repo/pulls",
            "title": "Pull requests",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "collect the first 10 PRs",
                    "action": "execute",
                    "description": "Collect first 10 pull requests into a strict array",
                    "code": "async def run(page):\n    return [{'title': 'planner draft', 'author': 'planner'}]",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        generated_candidate = {
            "thought": "generated via dedicated channel",
            "action": "execute",
            "structured_intent": None,
            "ai_instruction_step": None,
            "code": "async def run(page):\n    return [{'title': 'Good title', 'author': 'alice'}]",
            "description": "Collect first 10 pull requests into a strict array",
            "risk": "none",
            "risk_reason": "",
            "action_payload": "async def run(page):\n    return [{'title': 'Good title', 'author': 'alice'}]",
            "parsed": {"code": "async def run(page):\n    return [{'title': 'Good title', 'author': 'alice'}]"},
        }

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            agent,
            "_request_ai_script_candidate",
            new=AsyncMock(return_value=generated_candidate),
        ) as generate_ai_script, patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "output": json.dumps([{"title": "Good title", "author": "alice"}]),
                    "raw_output": [{"title": "Good title", "author": "alice"}],
                }
            ),
        ) as execute_on_page:
            events = []
            async for event in agent.run(
                session_id="session-ai-script-generator",
                page=page,
                goal="Collect the first 10 PRs as a strict array of title and author.",
                existing_steps=[],
            ):
                events.append(event)

        generate_ai_script.assert_awaited_once()
        execute_on_page.assert_awaited_once()
        executed_code = execute_on_page.await_args.args[1]
        self.assertIn("Good title", executed_code)
        self.assertNotIn("planner draft", executed_code)
        step_done_events = [event for event in events if event["event"] == "agent_step_done"]
        self.assertEqual(step_done_events[-1]["data"]["step"]["action"], "ai_script")

    async def test_react_agent_generates_ai_script_from_plan_without_planner_code(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/example/repo/pulls",
            "title": "Pull requests",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "collect the first 10 PRs",
                    "action": "execute",
                    "step_type": "ai_script",
                    "description": "Collect first 10 pull requests into a strict array",
                    "result_key": "first_10_prs_info",
                    "collection_hint": {"kind": "list"},
                    "ordinal": "10",
                    "value": "title,author",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        generated_candidate = {
            "thought": "generated via dedicated channel",
            "action": "execute",
            "ai_script_plan": {
                "step_type": "ai_script",
                "description": "Collect first 10 pull requests into a strict array",
                "result_key": "first_10_prs_info",
                "collection_hint": {"kind": "list"},
                "ordinal": "10",
                "value": "title,author",
            },
            "structured_intent": None,
            "ai_instruction_step": None,
            "code": "async def run(page):\n    return [{'title': 'Good title', 'author': 'alice'}]",
            "description": "Collect first 10 pull requests into a strict array",
            "risk": "none",
            "risk_reason": "",
            "action_payload": "async def run(page):\n    return [{'title': 'Good title', 'author': 'alice'}]",
            "parsed": {"result_key": "first_10_prs_info"},
        }

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            agent,
            "_request_ai_script_candidate",
            new=AsyncMock(return_value=generated_candidate),
        ) as generate_ai_script, patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "output": json.dumps([{"title": "Good title", "author": "alice"}]),
                    "raw_output": [{"title": "Good title", "author": "alice"}],
                }
            ),
        ) as execute_on_page:
            events = []
            async for event in agent.run(
                session_id="session-ai-script-no-planner-code",
                page=page,
                goal="Collect the first 10 PRs as a strict array of title and author.",
                existing_steps=[],
            ):
                events.append(event)

        generate_ai_script.assert_awaited_once()
        execute_on_page.assert_awaited_once()
        step_done_events = [event for event in events if event["event"] == "agent_step_done"]
        self.assertEqual(step_done_events[-1]["data"]["step"]["action"], "ai_script")

    async def test_react_agent_keeps_latest_execution_observation_after_history_compaction(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/example/repo/pulls",
            "title": "Pull requests",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "collect the first 10 PRs",
                    "action": "execute",
                    "step_type": "ai_script",
                    "description": "Collect first 10 pull requests into a strict array",
                    "result_key": "first_10_prs_info",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "done because the requested array was produced",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
        ]
        captured_histories = []

        async def fake_stream(history, _model_config=None):
            captured_histories.append("\n".join(message.get("content", "") for message in history))
            yield responses.pop(0)

        generated_candidate = {
            "thought": "generated via dedicated channel",
            "action": "execute",
            "ai_script_plan": {
                "step_type": "ai_script",
                "description": "Collect first 10 pull requests into a strict array",
                "result_key": "first_10_prs_info",
                "script_brief": "Collect at most 10 pull request records.",
                "output_contract": {
                    "type": "array",
                    "required_fields": ["title", "author"],
                    "max_items": 10,
                    "min_items": None,
                },
            },
            "structured_intent": None,
            "ai_instruction_step": None,
            "code": "async def run(page):\n    return [{'title': 'Good title', 'author': 'alice'}]",
            "description": "Collect first 10 pull requests into a strict array",
            "risk": "none",
            "risk_reason": "",
            "action_payload": "async def run(page):\n    return [{'title': 'Good title', 'author': 'alice'}]",
            "parsed": {"result_key": "first_10_prs_info"},
        }

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            agent,
            "_request_ai_script_candidate",
            new=AsyncMock(return_value=generated_candidate),
        ), patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "output": json.dumps([{"title": "Good title", "author": "alice"}]),
                    "raw_output": [{"title": "Good title", "author": "alice"}],
                }
            ),
        ):
            events = []
            async for event in agent.run(
                session_id="session-execution-observation",
                page=page,
                goal="Collect the first 10 PRs as a strict array of title and author.",
                existing_steps=[],
            ):
                events.append(event)

        self.assertGreaterEqual(len(captured_histories), 2)
        second_history = captured_histories[1]
        self.assertIn("Latest execution observation", second_history)
        self.assertIn('"output_type": "array"', second_history)
        self.assertIn('"array_length": 1', second_history)
        self.assertIn('"fields": ["title", "author"]', second_history)
        self.assertIn("Good title", second_history)
        self.assertTrue(any(event["event"] == "agent_done" for event in events))

    async def test_ai_script_generator_rejects_page_evaluate_code(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        snapshot = {
            "url": "https://github.com/example/repo/pulls",
            "title": "Pull requests",
            "frames": [],
        }
        candidate = {
            "thought": "collect records",
            "description": "Collect first 10 pull requests into a strict array",
            "ai_script_plan": {
                "step_type": "ai_script",
                "description": "Collect first 10 pull requests into a strict array",
                "result_key": "first_10_prs_info",
                "script_brief": "Collect at most 10 pull request records.",
                "output_contract": {
                    "type": "array",
                    "required_fields": ["title", "author"],
                    "max_items": 10,
                    "min_items": None,
                },
            },
        }

        async def fake_stream_with_system_prompt(_history, _system_prompt, _model_config=None):
            yield json.dumps(
                {
                    "thought": "use fast JS evaluation",
                    "action": "execute",
                    "description": "Extract using fast JS evaluation",
                    "result_key": "first_10_prs_info",
                    "code": "async def run(page):\n    return await page.evaluate(\"() => []\")",
                }
            )

        agent._stream_llm_with_system_prompt = fake_stream_with_system_prompt

        result = await agent._request_ai_script_candidate_with_prompt(
            goal="Collect the first 10 PRs as a strict array of title and author.",
            snapshot=snapshot,
            candidate=candidate,
            system_prompt=ASSISTANT_MODULE.AI_SCRIPT_GENERATION_SYSTEM_PROMPT,
            model_config=None,
        )

        self.assertIsNone(result)

    async def test_ai_script_generator_preserves_planner_contract_metadata(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        snapshot = {
            "url": "https://github.com/example/repo/pulls",
            "title": "Pull requests",
            "frames": [],
        }
        original_contract = {
            "step_type": "ai_script",
            "description": "Collect all available pull requests as a strict array",
            "result_key": "pr_list",
            "script_brief": (
                "Collect at most 10 pull request records. If fewer matching records exist in the correct scope, "
                "return the records that exist."
            ),
            "output_contract": {
                "type": "array",
                "required_fields": ["title", "creator"],
                "max_items": 10,
                "min_items": None,
            },
            "stable_subpage_hint": "/pulls",
        }
        candidate = {
            "thought": "collect records",
            "description": "Collect all available pull requests as a strict array",
            "ai_script_plan": original_contract,
            "parsed": {"result_key": "pr_list"},
        }

        async def fake_stream_with_system_prompt(_history, _system_prompt, _model_config=None):
            yield json.dumps(
                {
                    "thought": "rewrite the task",
                    "action": "execute",
                    "description": "Navigate to closed PRs if needed",
                    "result_key": "wrong_key",
                    "script_brief": "Navigate to closed PRs if needed",
                    "output_contract": {"type": "unspecified", "required_fields": [], "max_items": None, "min_items": None},
                    "code": "async def run(page):\n    return [{'title': 'Good title', 'creator': 'alice'}]",
                }
            )

        agent._stream_llm_with_system_prompt = fake_stream_with_system_prompt

        result = await agent._request_ai_script_candidate_with_prompt(
            goal="Collect the first 10 PRs as a strict array of title and creator.",
            snapshot=snapshot,
            candidate=candidate,
            system_prompt=ASSISTANT_MODULE.AI_SCRIPT_GENERATION_SYSTEM_PROMPT,
            model_config=None,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["ai_script_plan"], original_contract)
        self.assertEqual(result["parsed"]["result_key"], "pr_list")
        self.assertEqual(result["description"], original_contract["description"])

    async def test_step_local_repair_rejects_ai_instruction_kind_drift(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        snapshot = {
            "url": "https://github.com/example/repo/pulls",
            "title": "Pull requests",
            "frames": [],
        }
        candidate = {
            "description": "Collect PR titles and creators",
            "ai_script_plan": None,
            "structured_intent": None,
            "ai_instruction_step": {
                "action": "ai_instruction",
                "description": "Collect PR titles and creators",
                "prompt": "Extract PR titles and creators from the current page.",
                "instruction_kind": "semantic_extract",
                "input_scope": {"mode": "current_page"},
                "output_expectation": {"mode": "extract"},
                "result_key": "pr_list",
            },
            "code": "",
        }

        async def fake_stream_with_system_prompt(_history, _system_prompt, _model_config=None):
            yield json.dumps(
                {
                    "thought": "switch to script",
                    "action": "execute",
                    "step_type": "ai_script",
                    "description": "Extract PRs then navigate to closed if needed",
                    "result_key": "wrong_key",
                    "code": "async def run(page):\n    return []",
                }
            )

        agent._stream_llm_with_system_prompt = fake_stream_with_system_prompt

        result = await agent._request_step_local_repair(
            goal="Collect PR titles and creators.",
            snapshot=snapshot,
            candidate=candidate,
            failure_reason="syntax error",
            model_config=None,
            force_ai_instruction=False,
        )

        self.assertIsNone(result)

    async def test_step_local_repair_preserves_original_result_key(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        snapshot = {
            "url": "https://github.com/example/repo/issues",
            "title": "Issues",
            "frames": [],
        }
        candidate = {
            "description": "Extract latest issue title",
            "ai_script_plan": None,
            "structured_intent": {
                "action": "extract_text",
                "description": "Extract latest issue title",
                "result_key": "latest_issue_title",
            },
            "ai_instruction_step": None,
            "code": "",
            "parsed": {"result_key": "latest_issue_title"},
        }

        async def fake_stream_with_system_prompt(_history, _system_prompt, _model_config=None):
            yield json.dumps(
                {
                    "thought": "repair selector",
                    "action": "extract_text",
                    "description": "Extract latest issue title",
                    "result_key": "wrong_key",
                    "target_hint": {"role": "link", "name": "First issue"},
                }
            )

        agent._stream_llm_with_system_prompt = fake_stream_with_system_prompt

        result = await agent._request_step_local_repair(
            goal="Extract the latest issue title.",
            snapshot=snapshot,
            candidate=candidate,
            failure_reason="wrong element extracted",
            model_config=None,
            force_ai_instruction=False,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["structured_intent"]["result_key"], "latest_issue_title")
        self.assertEqual(result["parsed"]["result_key"], "latest_issue_title")

    async def test_step_local_repair_rejects_structured_kind_drift(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        snapshot = {
            "url": "https://github.com/example/repo/issues",
            "title": "Issues",
            "frames": [],
        }
        candidate = {
            "description": "Extract latest issue title",
            "ai_script_plan": None,
            "structured_intent": {
                "action": "extract_text",
                "description": "Extract latest issue title",
                "result_key": "latest_issue_title",
            },
            "ai_instruction_step": None,
            "code": "",
            "parsed": {"result_key": "latest_issue_title"},
        }

        async def fake_stream_with_system_prompt(_history, _system_prompt, _model_config=None):
            yield json.dumps(
                {
                    "thought": "switch interpretation",
                    "action": "execute",
                    "step_type": "ai_script",
                    "description": "Search all issues and extract a title",
                    "result_key": "latest_issue_title",
                    "code": "async def run(page):\n    return 'title'",
                }
            )

        agent._stream_llm_with_system_prompt = fake_stream_with_system_prompt

        result = await agent._request_step_local_repair(
            goal="Extract the latest issue title.",
            snapshot=snapshot,
            candidate=candidate,
            failure_reason="wrong element extracted",
            model_config=None,
            force_ai_instruction=False,
        )

        self.assertIsNone(result)

    async def test_react_agent_ai_script_bounded_fail_returns_explainable_payload(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/example/repo/pulls",
            "title": "Pull requests",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "collect the first 10 PRs",
                    "action": "execute",
                    "description": "Collect first 10 pull requests into a strict array",
                    "code": "async def run(page):\n    return []",
                    "risk": "none",
                    "risk_reason": "",
                }
            )
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        generated_candidate = {
            "thought": "generated via dedicated channel",
            "action": "execute",
            "structured_intent": None,
            "ai_instruction_step": None,
            "code": "async def run(page):\n    raise RuntimeError('first draft')",
            "description": "Collect first 10 pull requests into a strict array",
            "risk": "none",
            "risk_reason": "",
            "action_payload": "async def run(page):\n    raise RuntimeError('first draft')",
            "parsed": {"code": "async def run(page):\n    raise RuntimeError('first draft')"},
        }
        repaired_candidate = {
            "thought": "repair via dedicated channel",
            "action": "execute",
            "structured_intent": None,
            "ai_instruction_step": None,
            "code": "async def run(page):\n    raise RuntimeError('second draft')",
            "description": "Collect first 10 pull requests into a strict array",
            "risk": "none",
            "risk_reason": "",
            "action_payload": "async def run(page):\n    raise RuntimeError('second draft')",
            "parsed": {"code": "async def run(page):\n    raise RuntimeError('second draft')"},
        }

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            agent,
            "_request_ai_script_candidate",
            new=AsyncMock(return_value=generated_candidate),
        ) as generate_ai_script, patch.object(
            agent,
            "_request_ai_script_repair",
            new=AsyncMock(return_value=repaired_candidate),
        ) as repair_ai_script, patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(
                side_effect=[
                    {"success": False, "error": "Timeout while locating rows", "output": ""},
                    {"success": False, "error": "Timeout while locating rows", "output": ""},
                ]
            ),
        ):
            events = []
            async for event in agent.run(
                session_id="session-ai-script-bounded-fail",
                page=page,
                goal="Collect the first 10 PRs as a strict array of title and author.",
                existing_steps=[],
            ):
                events.append(event)

        generate_ai_script.assert_awaited_once()
        repair_ai_script.assert_awaited_once()
        aborted_event = [event for event in events if event["event"] == "agent_aborted"][-1]
        self.assertEqual(aborted_event["data"]["failure_kind"], "ai_script")
        self.assertEqual(aborted_event["data"]["bounded_attempts"], 2)
        self.assertTrue(aborted_event["data"]["repair_attempted"])
        self.assertIn("cannot reliably converge", aborted_event["data"]["reason"])
        self.assertIn("Timeout while locating rows", aborted_event["data"]["last_error"])

    async def test_react_agent_ai_instruction_retries_once_with_local_repair(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/example/repo/issues",
            "title": "Issues",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "extract latest issue title semantically",
                    "action": "execute",
                    "description": "Extract the title of the first issue in the list",
                    "ai_instruction": {
                        "description": "Extract the title of the first issue in the list",
                        "prompt": "Extract the title text of the first issue item from the current page.",
                        "instruction_kind": "semantic_extract",
                        "input_scope": {"mode": "current_page"},
                        "output_expectation": {"mode": "extract"},
                        "execution_hint": {
                            "requires_dom_snapshot": True,
                            "allow_navigation": False,
                            "max_reasoning_steps": 5,
                        },
                        "result_key": "latest_issue_title",
                    },
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        repaired_candidate = {
            "thought": "retry the same ai_instruction with corrected runtime planning",
            "action": "execute",
            "ai_script_plan": None,
            "structured_intent": None,
            "ai_instruction_step": {
                "action": "ai_instruction",
                "source": "ai",
                "description": "Extract the title of the first issue in the list",
                "prompt": "Extract the title text of the first issue item from the current page.",
                "instruction_kind": "semantic_extract",
                "input_scope": {"mode": "current_page"},
                "output_expectation": {"mode": "extract"},
                "execution_hint": {
                    "requires_dom_snapshot": True,
                    "allow_navigation": False,
                    "max_reasoning_steps": 5,
                },
                "result_key": "latest_issue_title",
            },
            "code": "",
            "description": "Extract the title of the first issue in the list",
            "risk": "none",
            "risk_reason": "",
            "action_payload": '{"action": "ai_instruction"}',
            "parsed": {"action": "execute"},
        }

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "execute_ai_instruction",
            new=AsyncMock(
                side_effect=[
                    {
                        "success": False,
                        "error": 'expression cannot contain assignment, perhaps you meant "=="? (<ai_instruction>, line 4)',
                        "output": "",
                    },
                    {"success": True, "output": "Latest issue title"},
                ]
            ),
        ) as execute_ai_instruction, patch.object(
            agent,
            "_request_step_local_repair",
            new=AsyncMock(return_value=repaired_candidate),
        ) as request_step_local_repair:
            events = []
            async for event in agent.run(
                session_id="session-ai-instruction-repair",
                page=page,
                goal="Open trending, find the top repo, then extract the latest issue title.",
                existing_steps=[],
            ):
                events.append(event)

        execute_ai_instruction.assert_awaited()
        self.assertEqual(execute_ai_instruction.await_count, 2)
        request_step_local_repair.assert_awaited_once()
        step_done_events = [event for event in events if event["event"] == "agent_step_done"]
        self.assertEqual(step_done_events[-1]["data"]["step"]["action"], "ai_instruction")
        self.assertEqual(step_done_events[-1]["data"]["output"], "Latest issue title")

    async def test_react_agent_rejects_summary_readme_helper_code_from_outer_trace(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/obra/superpowers",
            "title": "obra/superpowers",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "extract README text first and return it",
                    "action": "execute",
                    "description": "总结项目核心内容",
                    "code": "async def run(page):\n    return 'raw README content'",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "use semantic understanding for the summary step",
                    "action": "execute",
                    "description": "总结项目核心内容",
                    "ai_instruction": {
                        "description": "总结项目核心内容",
                        "prompt": "请总结当前 GitHub 项目的核心内容，包括用途、主要能力、技术栈和目标用户。",
                        "instruction_kind": "semantic_extract",
                        "input_scope": {"mode": "current_page"},
                        "output_expectation": {"mode": "extract"},
                        "execution_hint": {
                            "requires_dom_snapshot": True,
                            "allow_navigation": False,
                            "max_reasoning_steps": 10,
                        },
                        "result_key": "project_summary",
                    },
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(return_value={"success": True, "output": "raw README content"}),
        ) as execute_on_page, patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "execute_ai_instruction",
            new=AsyncMock(return_value={"success": True, "output": "项目摘要"}),
        ) as execute_ai_instruction:
            events = []
            async for event in agent.run(
                session_id="session-summary-replan",
                page=page,
                goal="打开 trending，找 star 数量最多的项目，点击进去后总结核心内容",
                existing_steps=[],
            ):
                events.append(event)

        step_done_events = [event for event in events if event["event"] == "agent_step_done"]
        self.assertEqual(len(step_done_events), 1)
        self.assertEqual(step_done_events[0]["data"]["step"]["action"], "ai_instruction")
        execute_on_page.assert_not_awaited()
        execute_ai_instruction.assert_awaited_once()

    async def test_react_agent_distills_readme_detour_out_of_recorded_steps(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/trending",
            "title": "Trending",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "open the trending page first",
                    "action": "execute",
                    "operation": "navigate",
                    "description": "打开 GitHub Trending 页面",
                    "value": "https://github.com/trending",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "use deterministic logic to open the top-star repository",
                    "action": "execute",
                    "description": "找出 star 数量最多的项目并点击进入",
                    "code": "async def run(page):\n    return 'opened top project'",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "open the README page as a fallback",
                    "action": "execute",
                    "operation": "navigate",
                    "description": "点击 README.md 文件查看项目详情",
                    "value": "https://github.com/obra/superpowers/blob/main/README.md",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "extract the README content directly",
                    "action": "execute",
                    "description": "提取 README.md 文件内容",
                    "code": "async def run(page):\n    return 'README content'",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "now summarize the project semantically",
                    "action": "execute",
                    "description": "总结项目核心内容",
                    "ai_instruction": {
                        "description": "总结项目核心内容",
                        "prompt": "请总结当前 GitHub 项目的核心内容",
                        "instruction_kind": "semantic_extract",
                        "input_scope": {"mode": "current_page"},
                        "output_expectation": {"mode": "extract"},
                        "execution_hint": {
                            "requires_dom_snapshot": True,
                            "allow_navigation": False,
                            "max_reasoning_steps": 10,
                        },
                        "result_key": "project_summary",
                    },
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        navigate_result = {
            "success": True,
            "output": "ok",
            "step": {
                "action": "navigate",
                "description": "打开 GitHub Trending 页面",
                "value": "https://github.com/trending",
                "source": "ai",
                "prompt": "打开 GitHub Trending 页面",
            },
        }
        readme_navigate_result = {
            "success": True,
            "output": "ok",
            "step": {
                "action": "navigate",
                "description": "点击 README.md 文件查看项目详情",
                "value": "https://github.com/obra/superpowers/blob/main/README.md",
                "source": "ai",
                "prompt": "点击 README.md 文件查看项目详情",
            },
        }

        async def fake_execute_structured(_page, resolved_intent):
            if resolved_intent.get("action") == "navigate" and "README.md" in str(resolved_intent.get("value")):
                return readme_navigate_result
            return navigate_result

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(side_effect=[
                {"success": True, "output": "opened top project"},
                {"success": True, "output": "README content"},
            ]),
        ), patch.object(
            ASSISTANT_MODULE,
            "execute_structured_intent",
            new=AsyncMock(side_effect=fake_execute_structured),
        ), patch.object(
            ASSISTANT_MODULE,
            "resolve_structured_intent",
            new=lambda _snapshot, intent: intent,
        ), patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "execute_ai_instruction",
            new=AsyncMock(return_value={"success": True, "output": "项目摘要"}),
        ):
            events = []
            async for event in agent.run(
                session_id="session-readme-detour",
                page=page,
                goal="打开 trending，找 star 最多的项目，点击进去后总结核心内容",
                existing_steps=[],
            ):
                events.append(event)

        recorded_steps_event = next(event for event in events if event["event"] == "agent_recorded_steps")
        recorded_steps = recorded_steps_event["data"]["steps"]
        self.assertEqual(len(recorded_steps), 3)
        self.assertEqual(recorded_steps[0]["action"], "navigate")
        self.assertEqual(recorded_steps[1]["action"], "ai_script")
        self.assertEqual(recorded_steps[2]["action"], "ai_instruction")
        self.assertNotIn("README", json.dumps(recorded_steps, ensure_ascii=False))


class RPAAssistantRoutingTests(unittest.TestCase):
    def test_distill_react_recorded_steps_preserves_non_summary_steps_with_goal_like_prompts(self):
        goal_prompt = "打开 https://github.com/trending，找最start数量最多的项目，点击进去后总结核心内容。"
        trace_steps = [
            {
                "action": "navigate",
                "description": "打开 GitHub trending 页面",
                "value": "https://github.com/trending",
                "prompt": goal_prompt,
            },
            {
                "action": "ai_script",
                "description": "找出 star 数量最多的项目并点击进入",
                "prompt": goal_prompt,
                "code": "async def run(page):\n    return 'https://github.com/obra/superpowers'",
            },
            {
                "action": "navigate",
                "description": "导航到 stars 最多的项目 obra/superpowers",
                "value": "https://github.com/obra/superpowers",
                "prompt": goal_prompt,
            },
            {
                "action": "ai_instruction",
                "description": "Extract and summarize the core content of the project",
                "prompt": "阅读当前页面上的项目标题、简介（Description）以及README文档的主要内容。用中文总结该项目的核心目标、主要功能特点、适用场景以及它解决的问题。",
                "instruction_kind": "semantic_extract",
                "result_key": "project_summary",
            },
        ]

        distilled = ASSISTANT_MODULE._distill_react_recorded_steps(goal_prompt, trace_steps)

        self.assertEqual(len(distilled), 4)
        self.assertEqual(
            [step["action"] for step in distilled],
            ["navigate", "ai_script", "navigate", "ai_instruction"],
        )

    def test_summary_helper_readme_step_is_rejected_from_outer_trace(self):
        self.assertTrue(
            ASSISTANT_MODULE._react_step_leaks_summary_helper_to_outer_trace(
                thought="to summarize the core content, I need to read the README file first",
                description="Click on README.md to view the project description",
                structured_intent={"action": "click", "target_hint": {"text": "README.md"}},
                ai_instruction_step=None,
                code="",
            )
        )

    def test_summary_statistics_helper_is_not_rejected_as_semantic_summary(self):
        self.assertFalse(
            ASSISTANT_MODULE._react_step_leaks_summary_helper_to_outer_trace(
                thought="compute summary statistics for the visible rows before continuing",
                description="Read table rows and aggregate counts by status",
                structured_intent={"action": "extract_text", "result_key": "status_counts"},
                ai_instruction_step=None,
                code="",
            )
        )

    def test_distill_react_recorded_steps_drops_followup_navigation_after_act_ai_instruction(self):
        trace_steps = [
            {
                "action": "ai_instruction",
                "description": "Find the project most related to SKILL and open it",
                "prompt": "Find the project most related to SKILL and open it",
                "instruction_kind": "semantic_decision",
                "output_expectation": {"mode": "act"},
                "execution_hint": {"allow_navigation": True},
            },
            {
                "action": "navigate",
                "description": "Navigate to the selected SKILL-related project page",
                "value": "https://github.com/example/skills-repo",
                "prompt": "找到和SKILL最相关的项目打开",
            },
        ]

        distilled = ASSISTANT_MODULE._distill_react_recorded_steps("找到和SKILL最相关的项目打开", trace_steps)

        self.assertEqual(len(distilled), 1)
        self.assertEqual(distilled[0]["action"], "ai_instruction")

    def test_distill_react_recorded_steps_drops_click_helper_when_direct_subpage_navigation_supersedes_it(self):
        trace_steps = [
            {
                "action": "navigate",
                "description": "Open GitHub Trending page",
                "value": "https://github.com/trending",
                "prompt": "goal",
            },
            {
                "action": "ai_script",
                "description": "Open top-star repository",
                "prompt": "goal",
                "value": "async def run(page):\n    return {'target_url': 'https://github.com/dynamic/repo'}",
            },
            {
                "action": "click",
                "description": "Click Pull requests tab",
                "prompt": "goal",
                "target_hint": {"role": "link", "name": "Pull requests"},
            },
            {
                "action": "navigate",
                "description": "Navigate to Pull requests page",
                "prompt": "goal",
                "value": "https://github.com/public-apis/public-apis/pulls",
            },
            {
                "action": "ai_script",
                "description": "Extract first 10 pull requests into strict array",
                "prompt": "goal",
                "value": "async def run(page):\n    return {'pr_list': []}",
            },
        ]

        distilled = ASSISTANT_MODULE._distill_react_recorded_steps("goal", trace_steps)

        self.assertEqual(
            [step["action"] for step in distilled],
            ["navigate", "ai_script", "navigate", "ai_script"],
        )

    def test_normalize_recorded_step_after_success_converts_stable_subpage_click_into_navigation(self):
        step = {
            "action": "click",
            "description": "Click Pull requests tab",
            "prompt": "Open the repository pull requests page",
            "target": '{"method":"role","role":"link","name":"Pull requests 1.3k"}',
            "target_hint": {"role": "link", "name": "Pull requests 1.3k"},
            "assistant_diagnostics": {"selected_locator_kind": "role"},
        }

        normalized = ASSISTANT_MODULE._normalize_recorded_step_after_success(
            step,
            "https://github.com/public-apis/public-apis/pulls",
        )

        self.assertEqual(normalized["action"], "navigate")
        self.assertEqual(normalized["url"], "https://github.com/public-apis/public-apis/pulls")
        self.assertEqual(normalized["value"], "https://github.com/public-apis/public-apis/pulls")
        self.assertEqual(normalized["target"], "")
        self.assertEqual(normalized["assistant_diagnostics"]["selected_locator_kind"], "navigate")

    def test_distill_react_recorded_steps_replaces_prior_extract_text_with_same_result_key(self):
        trace_steps = [
            {
                "action": "navigate",
                "description": "Open issues page",
                "value": "https://github.com/example/repo/issues",
                "prompt": "goal",
            },
            {
                "action": "extract_text",
                "description": "Extract the latest issue title",
                "prompt": "Read the latest issue title",
                "result_key": "latest_issue_title",
                "target": '{"method":"text","value":"Navigation Menu"}',
            },
            {
                "action": "extract_text",
                "description": "Retry extracting the latest issue title from the issue list",
                "prompt": "Read the latest issue title",
                "result_key": "latest_issue_title",
                "target": '{"method":"role","role":"link","name":"Real issue title"}',
            },
        ]

        distilled = ASSISTANT_MODULE._distill_react_recorded_steps("goal", trace_steps)

        self.assertEqual(len(distilled), 2)
        self.assertEqual(distilled[-1]["action"], "extract_text")
        self.assertEqual(
            distilled[-1]["description"],
            "Retry extracting the latest issue title from the issue list",
        )

    def test_ai_script_quality_issue_rejects_sparse_title_author_array(self):
        issue = ASSISTANT_MODULE._ai_script_quality_issue(
            goal="Collect the first 10 PRs as a strict array of title and author",
            description="Extract top 10 PR titles and creators",
            raw_output={
                "pr_list": [
                    {"title": "Good title", "author": "alice"},
                    {"title": "", "author": "bob"},
                    {"title": "2", "author": "carol"},
                    {"title": "Another title", "author": "Unknown"},
                ]
            },
        )

        self.assertIn("low-quality", issue)

    def test_ai_script_quality_issue_does_not_apply_downstream_array_requirements_to_repo_selection_step(self):
        issue = ASSISTANT_MODULE._ai_script_quality_issue(
            goal="Open trending, find the top-star repo, then extract the first 10 PRs as a strict array of title and creator",
            description="Identify the trending repository with the highest star count and return its path",
            raw_output={"target_url": "https://github.com/example/repo"},
        )

        self.assertEqual(issue, "")

    def test_extract_ai_script_plan_enriches_batch_record_constraints(self):
        plan = ASSISTANT_MODULE.RPAReActAgent._extract_ai_script_plan(
            {
                "action": "execute",
                "step_type": "ai_script",
                "description": "Extract title and creator for the first 10 PRs visible on the page into a strict array",
                "result_key": "first_10_prs_info",
            }
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan["output_shape"], "record_array")
        self.assertEqual(plan["record_fields"], ["title", "author"])
        self.assertEqual(plan["item_limit"], 10)
        self.assertEqual(
            plan["output_contract"],
            {
                "type": "array",
                "required_fields": ["title", "author"],
                "max_items": 10,
                "min_items": None,
            },
        )
        self.assertIn("at most 10", plan["script_brief"])
        self.assertIn("return the records that exist", plan["script_brief"])
        self.assertEqual(plan["stable_subpage_hint"], "/pulls")

    def test_extract_ai_script_plan_preserves_all_status_scope(self):
        plan = ASSISTANT_MODULE.RPAReActAgent._extract_ai_script_plan(
            {
                "action": "execute",
                "step_type": "ai_script",
                "description": "Collect the first 10 pull requests",
                "value": "regardless of status",
            }
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan["selection_scope"], "all_states")
        self.assertIn("all states", plan["script_brief"])
        self.assertIn("not a fill-to-quota strategy", plan["script_brief"])

    def test_extract_ai_script_plan_treats_first_n_as_upper_bound_not_required_count(self):
        plan = ASSISTANT_MODULE.RPAReActAgent._extract_ai_script_plan(
            {
                "action": "execute",
                "step_type": "ai_script",
                "description": "Collect the first 10 pull requests with title and creator as a strict array",
                "result_key": "first_10_prs_info",
            }
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan["item_limit"], 10)
        self.assertEqual(plan["output_contract"]["max_items"], 10)
        self.assertIsNone(plan["output_contract"]["min_items"])
        self.assertIn("upper bound", plan["script_brief"])

    def test_structured_result_quality_issue_rejects_batch_extract_text_navigation_chrome(self):
        issue = ASSISTANT_MODULE._structured_result_quality_issue(
            {
                "action": "extract_text",
                "description": "Extract title and creator for the first 10 PRs",
                "prompt": "Collect the first 10 PR titles and creators into a strict array",
                "result_key": "first_10_prs",
            },
            {"success": True, "output": "Navigation Menu"},
        )

        self.assertIn("batch array", issue)

    def test_structured_result_quality_issue_rejects_generic_chrome_for_single_value_title_request(self):
        issue = ASSISTANT_MODULE._structured_result_quality_issue(
            {
                "action": "extract_text",
                "description": "Extract the latest issue title",
                "prompt": "Read the latest issue title from the current list",
                "result_key": "latest_issue_title",
            },
            {"success": True, "output": "Navigation Menu"},
        )

        self.assertIn("field value", issue)

    def test_should_use_react_mode_for_complex_multistep_goal(self):
        self.assertTrue(
            ASSISTANT_MODULE.should_use_react_mode(
                "打开 https://github.com/trending，找最start数量最多的项目，点击进去后总结核心内容。",
                requested_mode="chat",
            )
        )

    def test_should_use_react_mode_for_simple_summary_request_by_default(self):
        self.assertTrue(
            ASSISTANT_MODULE.should_use_react_mode(
                "Summarize the current project",
                requested_mode="chat",
            )
        )

    def test_should_use_react_mode_when_explicitly_requested(self):
        self.assertTrue(
            ASSISTANT_MODULE.should_use_react_mode(
                "总结当前项目内容",
                requested_mode="react",
            )
        )


class RPAReActAgentFailureBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_ai_instruction_request_takes_priority_over_scripted_logic_replan(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/trending",
            "title": "Trending",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "find the highest star project and click it",
                    "action": "execute",
                    "description": "Find the project with the most stars and click it",
                    "operation": "click",
                    "target_hint": {"text": "some project"},
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "the user explicitly wants a runtime AI instruction",
                    "action": "execute",
                    "description": "Save highest-star selection as runtime AI instruction",
                    "ai_instruction": {
                        "description": "Select the highest-star project at runtime",
                        "prompt": "At runtime, inspect the current page and select the project with the most stars.",
                        "instruction_kind": "semantic_decision",
                        "input_scope": {"mode": "current_page"},
                        "output_expectation": {"mode": "act"},
                        "execution_hint": {
                            "requires_dom_snapshot": True,
                            "allow_navigation": True,
                            "max_reasoning_steps": 10,
                        },
                    },
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "execute_ai_instruction",
            new=AsyncMock(return_value={"success": True, "output": "opened"}),
        ):
            events = []
            async for event in agent.run(
                session_id="session-explicit-ai-priority",
                page=page,
                goal="Save this as a runtime AI instruction: choose the project with the most stars; do not expand it into fixed script.",
                existing_steps=[],
            ):
                events.append(event)

        feedback_messages = [
            item["content"]
            for item in agent._history
            if item.get("role") == "user" and "Previous step proposal was rejected" in item.get("content", "")
        ]
        self.assertIn("explicitly requested a runtime AI instruction", feedback_messages[0])
        step_done_events = [event for event in events if event["event"] == "agent_step_done"]
        self.assertEqual(len(step_done_events), 1)
        self.assertEqual(step_done_events[0]["data"]["step"]["action"], "ai_instruction")

    async def test_explicit_ai_instruction_request_keeps_setup_navigation_as_structured_step(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "about:blank",
            "title": "Blank",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "first open GitHub trending so the runtime rule has the correct page context",
                    "action": "navigate",
                    "description": "Open GitHub trending page",
                    "value": "https://github.com/trending",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "now save the runtime rule itself as ai_instruction",
                    "action": "execute",
                    "description": "Save highest-star selection as runtime AI instruction",
                    "ai_instruction": {
                        "description": "Select the highest-star project at runtime",
                        "prompt": "At runtime, inspect the current page and select the project with the most stars.",
                        "instruction_kind": "semantic_decision",
                        "input_scope": {"mode": "current_page"},
                        "output_expectation": {"mode": "act"},
                        "execution_hint": {
                            "requires_dom_snapshot": True,
                            "allow_navigation": True,
                            "max_reasoning_steps": 10,
                        },
                    },
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "execute_ai_instruction",
            new=AsyncMock(return_value={"success": True, "output": "opened"}),
        ):
            events = []
            async for event in agent.run(
                session_id="session-explicit-ai-scaffold",
                page=page,
                goal="Save this as a runtime AI instruction: choose the project with the most stars after opening GitHub trending; do not expand it into fixed script.",
                existing_steps=[],
            ):
                events.append(event)

        step_done_events = [event for event in events if event["event"] == "agent_step_done"]
        self.assertEqual(len(step_done_events), 2)
        self.assertEqual(step_done_events[0]["data"]["step"]["action"], "navigate")
        self.assertEqual(step_done_events[1]["data"]["step"]["action"], "ai_instruction")

    async def test_unified_react_path_preserves_user_prompt_for_explicit_runtime_ai_instruction(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://example.com",
            "title": "Example",
            "frames": [],
        }
        goal = (
            "把这条规则保存为运行时 AI 指令：在当前页面中筛选 star 数量大于 10000 的项目，并总结这些项目的信息。"
            "不要把它展开成固定脚本步骤。"
        )
        responses = [
            json.dumps(
                {
                    "thought": "the user explicitly wants to preserve this as a runtime AI instruction",
                    "action": "execute",
                    "description": "Preserve runtime rule",
                    "ai_instruction": {
                        "description": "Filter projects above 10000 stars and summarize them",
                        "prompt": "Filter high-star projects and summarize them",
                        "instruction_kind": "semantic_extract",
                        "input_scope": {"mode": "current_page"},
                        "output_expectation": {"mode": "extract"},
                        "execution_hint": {
                            "requires_dom_snapshot": True,
                            "allow_navigation": False,
                            "max_reasoning_steps": 10,
                        },
                        "result_key": "high_star_projects_summary",
                    },
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "execute_ai_instruction",
            new=AsyncMock(return_value={"success": True, "output": "runtime summary"}),
        ):
            events = []
            async for event in agent.run(
                session_id="session-unified-react-user-prompt",
                page=page,
                goal=goal,
                existing_steps=[],
            ):
                events.append(event)

        step_done = next(event for event in events if event["event"] == "agent_step_done")
        self.assertEqual(step_done["data"]["step"]["action"], "ai_instruction")
        self.assertEqual(step_done["data"]["step"]["prompt"], goal)

    async def test_react_agent_forwards_model_config_to_runtime_ai_instruction(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://example.com/project",
            "title": "Project",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "summarize the current project semantically",
                    "action": "execute",
                    "description": "Summarize current project",
                    "ai_instruction": {
                        "description": "Summarize current project",
                        "prompt": "Summarize the current project, focusing on purpose and limits.",
                        "instruction_kind": "semantic_extract",
                        "input_scope": {"mode": "current_page"},
                        "output_expectation": {"mode": "extract"},
                        "execution_hint": {
                            "requires_dom_snapshot": True,
                            "allow_navigation": False,
                            "max_reasoning_steps": 10,
                        },
                        "result_key": "project_summary",
                    },
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream
        model_config = {"model_name": "user-model", "api_key": "user-key"}
        execute_mock = AsyncMock(return_value={"success": True, "output": "summary"})

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "execute_ai_instruction",
            new=execute_mock,
        ):
            events = []
            async for event in agent.run(
                session_id="session-model-config",
                page=page,
                goal="Summarize current project",
                existing_steps=[],
                model_config=model_config,
            ):
                events.append(event)

        self.assertTrue(any(event["event"] == "agent_done" for event in events))
        execute_mock.assert_awaited_once()
        self.assertEqual(execute_mock.await_args.kwargs["model_config"], model_config)

    async def test_react_agent_emits_progressive_recorded_steps_after_each_success(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/trending",
            "title": "Trending",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "open the trending page first",
                    "action": "execute",
                    "operation": "navigate",
                    "description": "打开 GitHub Trending 页面",
                    "value": "https://github.com/trending",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "use deterministic logic to open the top-star repository",
                    "action": "execute",
                    "description": "找出 star 数量最多的项目并点击进入",
                    "code": "async def run(page):\n    return 'opened top project'",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        navigate_result = {
            "success": True,
            "output": "ok",
            "step": {
                "action": "navigate",
                "description": "打开 GitHub Trending 页面",
                "value": "https://github.com/trending",
                "source": "ai",
            },
        }

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(return_value={"success": True, "output": "opened top project"}),
        ), patch.object(
            ASSISTANT_MODULE,
            "execute_structured_intent",
            new=AsyncMock(return_value=navigate_result),
        ), patch.object(
            ASSISTANT_MODULE,
            "resolve_structured_intent",
            new=lambda _snapshot, intent: intent,
        ):
            events = []
            async for event in agent.run(
                session_id="session-progressive-recorded-steps",
                page=page,
                goal="打开 trending，找 star 最多的项目并点击进入，然后总结核心内容",
                existing_steps=[],
            ):
                events.append(event)

        progressive_events = [event for event in events if event["event"] == "agent_recorded_steps"]
        self.assertGreaterEqual(len(progressive_events), 3)
        self.assertEqual(len(progressive_events[0]["data"]["steps"]), 1)
        self.assertEqual(len(progressive_events[1]["data"]["steps"]), 2)
        self.assertEqual(len(progressive_events[-1]["data"]["steps"]), 2)

    async def test_react_agent_aborts_when_max_steps_are_exhausted(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        agent.MAX_STEPS = 2
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/trending",
            "title": "Trending",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "use deterministic scripted logic to find the top project",
                    "action": "execute",
                    "description": "找出 star 数量最多的项目并点击进入",
                    "code": "async def run(page):\n    return 'opened top project'",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "thought": "retry the scripted logic",
                    "action": "execute",
                    "description": "找出 star 数量最多的项目并点击进入",
                    "code": "async def run(page):\n    return 'opened top project'",
                    "risk": "none",
                    "risk_reason": "",
                },
                ensure_ascii=False,
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(return_value={"success": False, "error": "timed out", "output": ""}),
        ):
            events = []
            async for event in agent.run(
                session_id="session-exhausted",
                page=page,
                goal="打开 trending，找 star 最多的项目并点击进入，然后总结核心内容",
                existing_steps=[],
            ):
                events.append(event)

        self.assertFalse(any(event["event"] == "agent_done" for event in events))
        aborted_event = next(event for event in events if event["event"] == "agent_aborted")
        self.assertIn("maximum number of planning steps", aborted_event["data"]["reason"])


class RPAAssistantFrameAwareSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_page_snapshot_v2_includes_actionable_content_and_containers(self):
        main = _FakeSnapshotFrame(
            name="main",
            url="https://example.com",
            frame_path=[],
            elements=[{"index": 1, "tag": "button", "role": "button", "name": "Search"}],
        )
        page = _FakeSnapshotPage(main)

        with patch.object(
            ASSISTANT_RUNTIME_MODULE,
            "_extract_frame_snapshot_v2",
            new=AsyncMock(
                return_value={
                    "actionable_nodes": [
                        {
                            "node_id": "act-1",
                            "frame_path": [],
                            "container_id": "table-1",
                            "role": "link",
                            "name": "ContractList20260411124156",
                            "action_kinds": ["click"],
                            "locator": {"method": "role", "role": "link", "name": "ContractList20260411124156"},
                            "locator_candidates": [
                                {
                                    "kind": "role",
                                    "selected": True,
                                    "locator": {
                                        "method": "role",
                                        "role": "link",
                                        "name": "ContractList20260411124156",
                                    },
                                }
                            ],
                            "validation": {"status": "ok"},
                            "bbox": {"x": 10, "y": 20, "width": 120, "height": 24},
                            "center_point": {"x": 70, "y": 32},
                            "is_visible": True,
                            "is_enabled": True,
                            "hit_test_ok": True,
                            "element_snapshot": {"tag": "a", "text": "ContractList20260411124156"},
                        }
                    ],
                    "content_nodes": [
                        {
                            "node_id": "content-1",
                            "frame_path": [],
                            "container_id": "table-1",
                            "semantic_kind": "cell",
                            "text": "已归档",
                            "bbox": {"x": 300, "y": 20, "width": 80, "height": 24},
                            "locator": {"method": "text", "value": "已归档"},
                            "element_snapshot": {"tag": "td", "text": "已归档"},
                        }
                    ],
                    "containers": [
                        {
                            "container_id": "table-1",
                            "frame_path": [],
                            "container_kind": "table",
                            "name": "合同列表",
                            "bbox": {"x": 0, "y": 0, "width": 800, "height": 600},
                            "summary": "合同下载列表",
                            "child_actionable_ids": ["act-1"],
                            "child_content_ids": ["content-1"],
                        }
                    ],
                }
            ),
        ):
            snapshot = await ASSISTANT_MODULE.build_page_snapshot(
                page,
                frame_path_builder=lambda frame: frame._frame_path,
            )

        self.assertIn("actionable_nodes", snapshot)
        self.assertIn("content_nodes", snapshot)
        self.assertIn("containers", snapshot)
        self.assertEqual(snapshot["actionable_nodes"][0]["locator"]["method"], "role")
        self.assertEqual(snapshot["content_nodes"][0]["semantic_kind"], "cell")
        self.assertEqual(snapshot["containers"][0]["container_kind"], "table")

    async def test_build_page_snapshot_includes_iframe_elements_and_collections(self):
        iframe = _FakeSnapshotFrame(
            name="editor",
            url="https://example.com/editor",
            frame_path=["iframe[title='editor']"],
            elements=[
                {"index": 1, "tag": "a", "role": "link", "name": "Quarterly Report"},
                {"index": 2, "tag": "a", "role": "link", "name": "Annual Report"},
            ],
        )
        main = _FakeSnapshotFrame(
            name="main",
            url="https://example.com",
            frame_path=[],
            elements=[{"index": 1, "tag": "button", "role": "button", "name": "Search"}],
            child_frames=[iframe],
        )
        page = _FakeSnapshotPage(main)

        snapshot = await ASSISTANT_MODULE.build_page_snapshot(
            page,
            frame_path_builder=lambda frame: frame._frame_path,
        )

        self.assertEqual(snapshot["title"], "Example")
        self.assertEqual(len(snapshot["frames"]), 2)
        self.assertEqual(snapshot["frames"][1]["frame_path"], ["iframe[title='editor']"])
        self.assertEqual(snapshot["frames"][1]["elements"][0]["name"], "Quarterly Report")
        self.assertEqual(snapshot["frames"][1]["collections"][0]["item_count"], 2)

    async def test_build_page_snapshot_skips_detached_child_frame(self):
        detached = _FakeSnapshotFrame(
            name="detached",
            url="https://example.com/detached",
            frame_path=["iframe[title='detached']"],
            elements=[{"index": 1, "tag": "a", "role": "link", "name": "Detached Link"}],
        )
        main = _FakeSnapshotFrame(
            name="main",
            url="https://example.com",
            frame_path=[],
            elements=[{"index": 1, "tag": "button", "role": "button", "name": "Search"}],
            child_frames=[detached],
        )
        page = _FakeSnapshotPage(main)

        async def flaky_frame_path_builder(frame):
            if frame is detached:
                raise RuntimeError("Frame.frame_element: Frame has been detached.")
            return frame._frame_path

        snapshot = await ASSISTANT_MODULE.build_page_snapshot(
            page,
            frame_path_builder=flaky_frame_path_builder,
        )

        self.assertEqual(len(snapshot["frames"]), 1)
        self.assertEqual(snapshot["frames"][0]["frame_path"], [])

    async def test_detect_collections_builds_structured_template_from_repeated_context(self):
        collections = ASSISTANT_RUNTIME_MODULE._detect_collections(
            [
                {"index": 1, "tag": "a", "role": "link", "name": "Skip to content", "href": "#start-of-content"},
                {
                    "index": 2,
                    "tag": "a",
                    "role": "link",
                    "name": "Item A",
                    "collection_container_selector": "main article.card",
                    "collection_item_selector": "h2 a",
                },
                {
                    "index": 3,
                    "tag": "a",
                    "role": "link",
                    "name": "Item B",
                    "collection_container_selector": "main article.card",
                    "collection_item_selector": "h2 a",
                },
            ],
            [],
        )

        self.assertGreaterEqual(len(collections), 1)
        self.assertEqual(collections[0]["kind"], "repeated_items")
        self.assertEqual(collections[0]["container_hint"]["locator"], {"method": "css", "value": "main article.card"})
        self.assertEqual(collections[0]["item_hint"]["locator"], {"method": "css", "value": "h2 a"})
        self.assertEqual(collections[0]["items"][0]["name"], "Item A")
        self.assertEqual(collections[0]["items"][1]["name"], "Item B")

    async def test_pick_first_item_uses_collection_scope_not_global_page_order(self):
        snapshot = {
            "frames": [
                {
                    "frame_path": [],
                    "elements": [{"name": "Sidebar Link", "role": "link"}],
                    "collections": [],
                },
                {
                    "frame_path": ["iframe[title='results']"],
                    "elements": [],
                    "collections": [
                        {
                            "kind": "search_results",
                            "frame_path": ["iframe[title='results']"],
                            "container_hint": {"role": "list"},
                            "item_hint": {"role": "link"},
                            "items": [
                                {"name": "Result A", "role": "link"},
                                {"name": "Result B", "role": "link"},
                            ],
                        }
                    ],
                },
            ]
        }

        resolved = ASSISTANT_MODULE.resolve_collection_target(
            snapshot,
            {"action": "click", "ordinal": "first"},
        )

        self.assertEqual(resolved["frame_path"], ["iframe[title='results']"])
        self.assertEqual(resolved["resolved_target"]["name"], "Result A")

    async def test_sort_nodes_by_visual_position_orders_top_to_bottom_then_left_to_right(self):
        nodes = [
            {"node_id": "download-2", "name": "文件二", "bbox": {"x": 40, "y": 60, "width": 80, "height": 20}},
            {"node_id": "download-1", "name": "文件一", "bbox": {"x": 20, "y": 20, "width": 80, "height": 20}},
            {"node_id": "download-3", "name": "文件三", "bbox": {"x": 100, "y": 20, "width": 80, "height": 20}},
        ]

        ordered = ASSISTANT_RUNTIME_MODULE._sort_nodes_by_visual_position(nodes)

        self.assertEqual([node["name"] for node in ordered], ["文件一", "文件三", "文件二"])


class RPAAssistantStructuredExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_structured_intent_uses_bbox_order_for_first_match_in_single_pass(self):
        snapshot = {
            "frames": [],
            "actionable_nodes": [
                {
                    "node_id": "download-1",
                    "frame_path": [],
                    "container_id": "table-1",
                    "role": "link",
                    "name": "ContractList20260411124156",
                    "action_kinds": ["click"],
                    "locator": {"method": "text", "value": "ContractList20260411124156"},
                    "locator_candidates": [{"kind": "text", "selected": True, "locator": {"method": "text", "value": "ContractList20260411124156"}}],
                    "validation": {"status": "ok"},
                    "hit_test_ok": True,
                    "is_visible": True,
                    "is_enabled": True,
                    "bbox": {"x": 20, "y": 20, "width": 80, "height": 20},
                },
                {
                    "node_id": "download-2",
                    "frame_path": [],
                    "container_id": "table-1",
                    "role": "link",
                    "name": "ContractList20260411124157",
                    "action_kinds": ["click"],
                    "locator": {"method": "text", "value": "ContractList20260411124157"},
                    "locator_candidates": [{"kind": "text", "selected": True, "locator": {"method": "text", "value": "ContractList20260411124157"}}],
                    "validation": {"status": "ok"},
                    "hit_test_ok": True,
                    "is_visible": True,
                    "is_enabled": True,
                    "bbox": {"x": 20, "y": 60, "width": 80, "height": 20},
                },
            ],
            "content_nodes": [],
            "containers": [
                {
                    "container_id": "table-1",
                    "frame_path": [],
                    "container_kind": "table",
                    "name": "合同列表",
                    "bbox": {"x": 0, "y": 0, "width": 800, "height": 600},
                    "summary": "合同下载列表",
                    "child_actionable_ids": ["download-1", "download-2"],
                    "child_content_ids": [],
                }
            ],
        }

        resolved = ASSISTANT_MODULE.resolve_structured_intent(
            snapshot,
            {
                "action": "click",
                "description": "点击第一个文件下载",
                "prompt": "点击第一个文件下载",
                "target_hint": {"role": "link", "name": "contractlist"},
                "ordinal": "first",
            },
        )

        self.assertEqual(resolved["resolved"]["locator"]["value"], "ContractList20260411124156")
        self.assertEqual(resolved["resolved"]["ordinal"], "first")
        self.assertNotIn("assistant_diagnostics", resolved["resolved"])

    async def test_resolve_structured_intent_prefers_snapshot_locator_bundle_for_actionable_node(self):
        snapshot = {
            "frames": [],
            "actionable_nodes": [
                {
                    "node_id": "download-1",
                    "frame_path": [],
                    "container_id": "table-1",
                    "role": "link",
                    "name": "ContractList20260411124156",
                    "action_kinds": ["click"],
                    "locator": {"method": "text", "value": "ContractList20260411124156"},
                    "locator_candidates": [
                        {
                            "kind": "role",
                            "selected": False,
                            "locator": {"method": "role", "role": "link", "name": "ContractList20260411124156"},
                        },
                        {
                            "kind": "text",
                            "selected": True,
                            "locator": {"method": "text", "value": "ContractList20260411124156"},
                        },
                    ],
                    "validation": {"status": "ok"},
                    "hit_test_ok": True,
                }
            ],
            "content_nodes": [],
            "containers": [],
        }

        resolved = ASSISTANT_MODULE.resolve_structured_intent(
            snapshot,
            {
                "action": "click",
                "description": "点击第一个文件下载",
                "target_hint": {"role": "link", "name": "contractlist"},
            },
        )

        self.assertEqual(resolved["resolved"]["locator"]["method"], "text")
        self.assertTrue(resolved["resolved"]["locator_candidates"][1]["selected"])

    async def test_resolve_structured_intent_extract_text_prefers_content_nodes(self):
        snapshot = {
            "frames": [],
            "actionable_nodes": [
                {
                    "node_id": "button-1",
                    "frame_path": [],
                    "container_id": "card-1",
                    "role": "button",
                    "name": "复制标题",
                    "action_kinds": ["click"],
                    "locator": {"method": "role", "role": "button", "name": "复制标题"},
                    "locator_candidates": [
                        {
                            "kind": "role",
                            "selected": True,
                            "locator": {"method": "role", "role": "button", "name": "复制标题"},
                        }
                    ],
                    "validation": {"status": "ok"},
                    "hit_test_ok": True,
                }
            ],
            "content_nodes": [
                {
                    "node_id": "title-1",
                    "frame_path": [],
                    "container_id": "card-1",
                    "semantic_kind": "heading",
                    "role": "heading",
                    "text": "Quarterly Report",
                    "bbox": {"x": 20, "y": 20, "width": 200, "height": 24},
                    "locator": {"method": "text", "value": "Quarterly Report"},
                    "element_snapshot": {"tag": "h2", "text": "Quarterly Report"},
                }
            ],
            "containers": [],
        }

        resolved = ASSISTANT_MODULE.resolve_structured_intent(
            snapshot,
            {
                "action": "extract_text",
                "description": "提取报表标题",
                "prompt": "提取报表标题",
                "target_hint": {"name": "report title"},
                "result_key": "report_title",
            },
        )

        self.assertEqual(resolved["resolved"]["locator"]["method"], "text")
        self.assertEqual(resolved["resolved"]["content_node"]["semantic_kind"], "heading")

    async def test_execute_structured_click_does_not_mark_local_expansion_in_single_pass_mode(self):
        page = _FakeActionPage()
        intent = {
            "action": "click",
            "description": "点击第一个文件下载",
            "prompt": "点击第一个文件下载",
            "resolved": {
                "frame_path": [],
                "locator": {"method": "text", "value": "ContractList20260411124156"},
                "locator_candidates": [
                    {
                        "kind": "text",
                        "selected": True,
                        "locator": {"method": "text", "value": "ContractList20260411124156"},
                    }
                ],
                "collection_hint": {},
                "item_hint": {},
                "ordinal": "first",
                "selected_locator_kind": "text",
            },
        }

        result = await ASSISTANT_MODULE.execute_structured_intent(page, intent)

        self.assertTrue(result["success"])
        self.assertEqual(page.scope.locator_calls[0], "text:ContractList20260411124156")
        self.assertNotIn("used_local_expansion", result["step"]["assistant_diagnostics"])

    async def test_execute_structured_click_uses_frame_locator_chain(self):
        page = _FakeActionPage()
        intent = {
            "action": "click",
            "description": "点击发送按钮",
            "prompt": "点击发送按钮",
            "resolved": {
                "frame_path": ["iframe[title='editor']"],
                "locator": {"method": "role", "role": "button", "name": "Send"},
                "locator_candidates": [
                    {
                        "kind": "role",
                        "selected": True,
                        "locator": {"method": "role", "role": "button", "name": "Send"},
                    }
                ],
                "selected_locator_kind": "role",
            },
        }

        result = await ASSISTANT_MODULE.execute_structured_intent(page, intent)

        self.assertTrue(result["success"])
        self.assertEqual(page.scope.locator_calls[0], "frame:iframe[title='editor']")
        self.assertEqual(result["step"]["frame_path"], ["iframe[title='editor']"])
        self.assertEqual(result["step"]["source"], "ai")
        self.assertEqual(
            result["step"]["target"],
            '{"method": "role", "role": "button", "name": "Send"}',
        )
        self.assertIn("domcontentloaded", page.load_state_calls)
        self.assertIn(500, page.timeout_calls)

    async def test_execute_structured_click_persists_adaptive_collection_target_for_first_collection_item(self):
        page = _FakeActionPage()
        intent = {
            "action": "click",
            "description": "点击第一个卡片项目",
            "prompt": "点击列表中的第一个项目",
            "resolved": {
                "frame_path": [],
                "locator": {"method": "role", "role": "link", "name": "Item A"},
                "locator_candidates": [
                    {
                        "kind": "role",
                        "selected": True,
                        "locator": {"method": "role", "role": "link", "name": "Item A"},
                    }
                ],
                "collection_hint": {
                    "kind": "repeated_items",
                    "container_hint": {"locator": {"method": "css", "value": "main article.card"}},
                },
                "item_hint": {"role": "link", "locator": {"method": "css", "value": "h2 a"}},
                "ordinal": "first",
                "selected_locator_kind": "role",
            },
        }

        result = await ASSISTANT_MODULE.execute_structured_intent(page, intent)

        self.assertTrue(result["success"])
        self.assertEqual(
            json.loads(result["step"]["target"]),
            {
                "method": "collection_item",
                "collection": {"method": "css", "value": "main article.card"},
                "ordinal": "first",
                "item": {"method": "css", "value": "h2 a"},
            },
        )
        self.assertEqual(result["step"]["collection_hint"]["kind"], "repeated_items")
        self.assertEqual(result["step"]["item_hint"]["locator"], {"method": "css", "value": "h2 a"})
        self.assertEqual(result["step"]["ordinal"], "first")

    async def test_execute_structured_navigate_uses_page_goto(self):
        page = _FakeActionPage()
        intent = {
            "action": "navigate",
            "description": "打开 GitHub Trending 页面",
            "prompt": "打开 GitHub Trending 页面",
            "value": "https://github.com/trending",
            "resolved": {
                "frame_path": [],
                "locator": None,
                "locator_candidates": [],
                "collection_hint": {},
                "item_hint": {},
                "ordinal": None,
                "selected_locator_kind": "navigate",
                "url": "https://github.com/trending",
            },
        }

        result = await ASSISTANT_MODULE.execute_structured_intent(page, intent)

        self.assertTrue(result["success"])
        self.assertEqual(page.goto_calls, ["https://github.com/trending"])
        self.assertEqual(page.load_state_calls, ["domcontentloaded"])
        self.assertEqual(result["step"]["action"], "navigate")
        self.assertEqual(result["step"]["url"], "https://github.com/trending")

    async def test_execute_structured_extract_text_persists_result_key(self):
        page = _FakeActionPage()
        intent = {
            "action": "extract_text",
            "description": "提取最近一条 issue 的标题",
            "prompt": "提取最近一条 issue 的标题",
            "result_key": "latest_issue_title",
            "resolved": {
                "frame_path": [],
                "locator": {"method": "role", "role": "link", "name": "Issue Title"},
                "locator_candidates": [
                    {
                        "kind": "role",
                        "selected": True,
                        "locator": {"method": "role", "role": "link", "name": "Issue Title"},
                    }
                ],
                "collection_hint": {},
                "item_hint": {},
                "ordinal": None,
                "selected_locator_kind": "role",
            },
        }

        result = await ASSISTANT_MODULE.execute_structured_intent(page, intent)

        self.assertTrue(result["success"])
        self.assertEqual(result["output"], "Resolved text")
        self.assertEqual(result["step"]["action"], "extract_text")
        self.assertEqual(result["step"]["result_key"], "latest_issue_title")

    async def test_resolve_structured_intent_prefers_collection_item_inside_iframe(self):
        snapshot = {
            "frames": [
                {
                    "frame_path": [],
                    "frame_hint": "main document",
                    "elements": [{"index": 1, "tag": "a", "role": "link", "name": "Sidebar"}],
                    "collections": [],
                },
                {
                    "frame_path": ["iframe[title='results']"],
                    "frame_hint": "iframe title=results",
                    "elements": [],
                    "collections": [
                        {
                            "kind": "search_results",
                            "frame_path": ["iframe[title='results']"],
                            "container_hint": {"role": "list"},
                            "item_hint": {"role": "link"},
                            "item_count": 2,
                            "items": [
                                {"index": 1, "tag": "a", "role": "link", "name": "Result A"},
                                {"index": 2, "tag": "a", "role": "link", "name": "Result B"},
                            ],
                        }
                    ],
                },
            ]
        }

        resolved = ASSISTANT_MODULE.resolve_structured_intent(
            snapshot,
            {
                "action": "click",
                "description": "点击第一个结果",
                "collection_hint": {"kind": "search_results"},
                "ordinal": "first",
            },
        )

        self.assertEqual(resolved["resolved"]["frame_path"], ["iframe[title='results']"])
        self.assertEqual(resolved["resolved"]["locator"]["method"], "role")
        self.assertEqual(resolved["resolved"]["locator"]["name"], "Result A")

    async def test_resolve_structured_intent_prefers_structured_collection_over_flat_links(self):
        snapshot = {
            "frames": [
                {
                    "frame_path": [],
                    "frame_hint": "main document",
                    "elements": [
                        {"index": 1, "tag": "a", "role": "link", "name": "Skip to content", "href": "#start-of-content"},
                        {"index": 2, "tag": "a", "role": "link", "name": "Homepage", "href": "/"},
                        {"index": 3, "tag": "a", "role": "link", "name": "Item A"},
                        {"index": 4, "tag": "a", "role": "link", "name": "Item B"},
                    ],
                    "collections": [
                        {
                            "kind": "search_results",
                            "frame_path": [],
                            "container_hint": {"role": "list"},
                            "item_hint": {"role": "link"},
                            "item_count": 4,
                            "items": [
                                {"index": 1, "tag": "a", "role": "link", "name": "Skip to content", "href": "#start-of-content"},
                                {"index": 2, "tag": "a", "role": "link", "name": "Homepage", "href": "/"},
                                {"index": 3, "tag": "a", "role": "link", "name": "Item A"},
                                {"index": 4, "tag": "a", "role": "link", "name": "Item B"},
                            ],
                        },
                        {
                            "kind": "repeated_items",
                            "frame_path": [],
                            "container_hint": {"locator": {"method": "css", "value": "main article.card"}},
                            "item_hint": {"role": "link", "locator": {"method": "css", "value": "h2 a"}},
                            "item_count": 2,
                            "items": [
                                {"index": 3, "tag": "a", "role": "link", "name": "Item A"},
                                {"index": 4, "tag": "a", "role": "link", "name": "Item B"},
                            ],
                        },
                    ],
                }
            ]
        }

        resolved = ASSISTANT_MODULE.resolve_structured_intent(
            snapshot,
            {
                "action": "click",
                "description": "点击列表中的第一个项目",
                "prompt": "点击列表中的第一个项目",
                "target_hint": {"role": "link", "name": "item"},
                "collection_hint": {"kind": "search_results"},
                "ordinal": "first",
            },
        )

        self.assertEqual(resolved["resolved"]["locator"]["name"], "Item A")
        self.assertEqual(resolved["resolved"]["collection_hint"]["kind"], "repeated_items")

    async def test_resolve_structured_intent_normalizes_first_ordinal_from_prompt(self):
        snapshot = {
            "frames": [
                {
                    "frame_path": [],
                    "frame_hint": "main document",
                    "elements": [],
                    "collections": [
                        {
                            "kind": "repeated_items",
                            "frame_path": [],
                            "container_hint": {"locator": {"method": "css", "value": "main article.card"}},
                            "item_hint": {"role": "link", "locator": {"method": "css", "value": "h2 a"}},
                            "item_count": 2,
                            "items": [
                                {"index": 1, "tag": "a", "role": "link", "name": "Item A"},
                                {"index": 2, "tag": "a", "role": "link", "name": "Item B"},
                            ],
                        },
                    ],
                }
            ]
        }

        resolved = ASSISTANT_MODULE.resolve_structured_intent(
            snapshot,
            {
                "action": "click",
                "description": "点击列表中的第一个项目",
                "prompt": "点击列表中的第一个项目",
                "target_hint": {"role": "link", "name": "item"},
                "collection_hint": {"kind": "search_results"},
                "ordinal": "25",
            },
        )

        self.assertEqual(resolved["resolved"]["locator"]["name"], "Item A")
        self.assertEqual(resolved["resolved"]["ordinal"], "first")

    async def test_resolve_structured_intent_falls_back_to_direct_target_when_collection_hint_has_no_match(self):
        snapshot = {
            "frames": [
                {
                    "frame_path": [],
                    "frame_hint": "main document",
                    "elements": [
                        {"index": 1, "tag": "input", "role": "textbox", "name": "Search", "placeholder": "Search"}
                    ],
                    "collections": [],
                }
            ]
        }

        resolved = ASSISTANT_MODULE.resolve_structured_intent(
            snapshot,
            {
                "action": "fill",
                "description": "在搜索框中输入关键词",
                "prompt": "在搜索框中输入关键词",
                "target_hint": {"role": "textbox", "name": "search"},
                "collection_hint": {"kind": "cards"},
                "ordinal": "1",
                "value": "github",
            },
        )

        self.assertEqual(resolved["resolved"]["locator"]["method"], "role")
        self.assertEqual(resolved["resolved"]["locator"]["name"], "Search")
        self.assertEqual(resolved["resolved"]["collection_hint"], {})

    async def test_resolve_structured_intent_prefers_primary_collection_items_over_repeated_controls(self):
        snapshot = {
            "frames": [
                {
                    "frame_path": [],
                    "frame_hint": "main document",
                    "elements": [],
                    "collections": [
                        {
                            "kind": "repeated_items",
                            "frame_path": [],
                            "container_hint": {"locator": {"method": "css", "value": "main article.card"}},
                            "item_hint": {"role": "link", "locator": {"method": "css", "value": "div.actions a"}},
                            "item_count": 2,
                            "items": [
                                {"index": 1, "tag": "a", "role": "link", "name": "Star project A"},
                                {"index": 2, "tag": "a", "role": "link", "name": "Star project B"},
                            ],
                        },
                        {
                            "kind": "repeated_items",
                            "frame_path": [],
                            "container_hint": {"locator": {"method": "css", "value": "main article.card"}},
                            "item_hint": {"role": "link", "locator": {"method": "css", "value": "h2 a"}},
                            "item_count": 2,
                            "items": [
                                {"index": 3, "tag": "a", "role": "link", "name": "Project A"},
                                {"index": 4, "tag": "a", "role": "link", "name": "Project B"},
                            ],
                        },
                    ],
                }
            ]
        }

        resolved = ASSISTANT_MODULE.resolve_structured_intent(
            snapshot,
            {
                "action": "click",
                "description": "点击列表中的第一个项目链接",
                "prompt": "点击列表中的第一个项目",
                "target_hint": {"role": "link", "name": "project title link"},
                "collection_hint": {"kind": "search_results"},
                "ordinal": "first",
            },
        )

        self.assertEqual(resolved["resolved"]["locator"]["name"], "Project A")
        self.assertEqual(
            resolved["resolved"]["item_hint"]["locator"],
            {"method": "css", "value": "h2 a"},
        )


class RPAAssistantPromptFormattingTests(unittest.TestCase):
    def test_build_messages_lists_frames_and_collections(self):
        assistant = ASSISTANT_MODULE.RPAAssistant()
        snapshot = {
            "frames": [
                {
                    "frame_hint": "main document",
                    "frame_path": [],
                    "elements": [{"index": 1, "tag": "button", "role": "button", "name": "Search"}],
                    "collections": [],
                },
                {
                    "frame_hint": "iframe title=results",
                    "frame_path": ["iframe[title='results']"],
                    "elements": [{"index": 1, "tag": "a", "role": "link", "name": "Result A"}],
                    "collections": [{"kind": "search_results", "item_count": 2}],
                },
            ]
        }

        messages = assistant._build_messages("点击第一个结果", [], snapshot, [])
        content = messages[-1]["content"]

        self.assertIn("Frame: main document", content)
        self.assertIn("Frame: iframe title=results", content)
        self.assertIn("Collection: search_results (2 items)", content)

    def test_react_system_prompt_requires_explicit_extraction_before_done(self):
        prompt = ASSISTANT_MODULE.REACT_SYSTEM_PROMPT

        self.assertIn("For extraction tasks, use operation=extract_text", prompt)
        self.assertIn('"result_key": "short_ascii_snake_case_key_for_extracted_value"', prompt)
        self.assertIn("Do not mark the task done just because the data is visible on the page.", prompt)
        self.assertIn("Execute the extraction step first and return the extracted value.", prompt)

    def test_react_system_prompt_defines_step_classification_contract(self):
        prompt = ASSISTANT_MODULE.REACT_SYSTEM_PROMPT

        self.assertIn("structured step for atomic browser actions", prompt)
        self.assertIn("runtime page data plus deterministic, encodable rules", prompt)
        self.assertIn("runtime page data plus semantic/business judgment", prompt)
        self.assertIn("Classify by the rule above, not by isolated words", prompt)
        self.assertIn("Mini examples:", prompt)
        self.assertIn('User goal fragment: "Click the Stars tab"', prompt)
        self.assertIn('User goal fragment: "Find the project with the most stars and open it"', prompt)
        self.assertIn('User goal fragment: "Summarize the current project, focusing on purpose, capabilities, and limitations"', prompt)
        self.assertIn("top N items", prompt)
        self.assertIn("strict array", prompt)
        self.assertIn("title/author/status fields", prompt)
        self.assertIn("/issues or /pulls", prompt)
        self.assertIn('"ai_instruction"', prompt)

    def test_stalled_structured_path_reflects_on_repeated_same_action(self):
        structured_intent = {
            "action": "click",
            "target_hint": {"role": "link", "name": "Pull requests"},
        }
        signature = ASSISTANT_MODULE._structured_intent_signature(structured_intent)

        self.assertTrue(
            ASSISTANT_MODULE._should_reflect_on_stalled_structured_path(
                structured_intent,
                last_structured_signature=signature,
                stall_score=1,
            )
        )

    def test_stalled_structured_path_reflects_after_accumulated_failures(self):
        structured_intent = {
            "action": "click",
            "target_hint": {"role": "link", "name": "Issues"},
        }

        self.assertTrue(
            ASSISTANT_MODULE._should_reflect_on_stalled_structured_path(
                structured_intent,
                last_structured_signature="",
                stall_score=2,
            )
        )

    def test_should_force_ai_instruction_only_for_explicit_declarations(self):
        assistant = ASSISTANT_MODULE.RPAAssistant()

        self.assertTrue(assistant._should_force_ai_instruction("把这条规则保存为运行时 AI 指令，不要展开成固定脚本"))
        self.assertTrue(assistant._should_force_ai_instruction("请使用AI指令处理这个步骤"))
        self.assertFalse(assistant._should_force_ai_instruction("总结当前 GitHub 项目的信息"))
        self.assertFalse(assistant._should_force_ai_instruction("找到当前页面 star 数量最高的项目并点击打开它"))


class RPAAssistantAIInstructionTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_returns_ai_instruction_step_for_runtime_semantic_rule(self):
        assistant = ASSISTANT_MODULE.RPAAssistant()
        fake_page = _FakePage()
        structured_json = json.dumps(
            {
                "action": "ai_instruction",
                "description": "Sync table A into table B by matching rows on name",
                "prompt": "Fill table B from table A by matching rows on name, then submit",
                "instruction_kind": "semantic_rule",
                "input_scope": {"mode": "current_page"},
                "output_expectation": {"mode": "act"},
                "execution_hint": {
                    "requires_dom_snapshot": True,
                    "allow_navigation": True,
                    "max_reasoning_steps": 10,
                },
            }
        )

        async def _fake_stream_llm(self, messages, model_config=None):
            yield structured_json

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value={"url": "https://example.com", "title": "Example", "frames": []}),
        ), patch.object(
            ASSISTANT_MODULE.RPAAssistant,
            "_stream_llm",
            new=_fake_stream_llm,
        ):
            events = []
            async for event in assistant.chat("session-1", fake_page, "sync data", []):
                events.append(event)

        result_event = next(event for event in events if event["event"] == "result")
        step = result_event["data"]["step"]

        self.assertEqual(step["action"], "ai_instruction")
        self.assertEqual(step["instruction_kind"], "semantic_rule")
        self.assertEqual(step["input_scope"], {"mode": "current_page"})
        self.assertEqual(step["output_expectation"], {"mode": "act"})
        self.assertEqual(step["execution_hint"]["max_reasoning_steps"], 10)
        self.assertEqual(step["execution_hint"]["planning_timeout_s"], 60.0)
        self.assertNotIn("value", step)

    async def test_chat_executes_ai_instruction_and_returns_runtime_output(self):
        assistant = ASSISTANT_MODULE.RPAAssistant()
        fake_page = _FakePage()
        structured_json = json.dumps(
            {
                "action": "ai_instruction",
                "description": "Summarize high-star projects",
                "prompt": "Summarize projects with more than 10000 stars",
                "instruction_kind": "semantic_extract",
                "input_scope": {"mode": "current_page"},
                "output_expectation": {"mode": "extract"},
                "execution_hint": {
                    "requires_dom_snapshot": True,
                    "allow_navigation": False,
                    "max_reasoning_steps": 10,
                },
                "result_key": "high_star_projects_summary",
            }
        )

        async def _fake_stream_llm(self, messages, model_config=None):
            yield structured_json

        execute_mock = AsyncMock(
            return_value={
                "success": True,
                "output": "repo-a (12000 stars); repo-b (15000 stars)",
            }
        )

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value={"url": "https://example.com", "title": "Example", "frames": []}),
        ), patch.object(
            ASSISTANT_MODULE.RPAAssistant,
            "_stream_llm",
            new=_fake_stream_llm,
        ), patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "execute_ai_instruction",
            new=execute_mock,
        ):
            events = []
            model_config = {"model_name": "user-selected-model", "api_key": "user-key"}
            async for event in assistant.chat(
                "session-1",
                fake_page,
                "summarize stars",
                [],
                model_config=model_config,
            ):
                events.append(event)

        result_event = next(event for event in events if event["event"] == "result")
        self.assertEqual(result_event["data"]["step"]["action"], "ai_instruction")
        self.assertEqual(
            result_event["data"]["output"],
            "repo-a (12000 stars); repo-b (15000 stars)",
        )
        execute_mock.assert_awaited_once()
        self.assertEqual(execute_mock.await_args.kwargs["model_config"], model_config)

    async def test_chat_coerces_explicit_runtime_ai_instruction_requests_from_structured_extract(self):
        assistant = ASSISTANT_MODULE.RPAAssistant()
        fake_page = _FakePage()
        structured_json = json.dumps(
            {
                "action": "extract_text",
                "description": "保存运行时AI指令：筛选star>10000的项目并总结",
                "prompt": "保存运行时AI指令",
                "result_key": "runtime_ai_rule",
                "target_hint": {"name": "Navigation Menu"},
            },
            ensure_ascii=False,
        )
        user_message = (
            "把这条规则保存为运行时 AI 指令：在当前页面中筛选 star 数量大于 10000 的项目，并总结这些项目的信息。"
            "不要把它展开成固定脚本步骤。"
        )

        async def _fake_stream_llm(self, messages, model_config=None):
            yield structured_json

        execute_mock = AsyncMock(
            return_value={
                "success": True,
                "output": "runtime extract result",
            }
        )

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value={"url": "https://example.com", "title": "Example", "frames": []}),
        ), patch.object(
            ASSISTANT_MODULE.RPAAssistant,
            "_stream_llm",
            new=_fake_stream_llm,
        ), patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "execute_ai_instruction",
            new=execute_mock,
        ):
            events = []
            async for event in assistant.chat("session-1", fake_page, user_message, []):
                events.append(event)

        result_event = next(event for event in events if event["event"] == "result")
        step = result_event["data"]["step"]

        self.assertEqual(step["action"], "ai_instruction")
        self.assertEqual(step["prompt"], user_message)
        self.assertEqual(step["instruction_kind"], "semantic_rule")
        self.assertEqual(step["input_scope"], {"mode": "current_page"})
        self.assertEqual(step["output_expectation"], {"mode": "extract"})
        self.assertEqual(step["execution_hint"]["max_reasoning_steps"], 10)
        self.assertEqual(step["execution_hint"]["planning_timeout_s"], 60.0)
        self.assertEqual(result_event["data"]["output"], "runtime extract result")
        execute_mock.assert_awaited_once()
        self.assertNotIn("value", step)


class RPAAssistantSmallPolishTests(unittest.IsolatedAsyncioTestCase):
    def test_summary_ai_instruction_preserves_specific_prompt_constraints(self):
        step = ASSISTANT_MODULE.RPAAssistant._coerce_to_ai_instruction(
            "用中文总结当前项目的核心内容",
            {
                "action": "ai_instruction",
                "description": "Summarize the core content of the obra/superpowers repository",
                "prompt": "Read the repository description and README file content on the current page. Summarize the core content, purpose, and key features of the 'obra/superpowers' project in Chinese.",
                "instruction_kind": "semantic_extract",
                "output_expectation": {"mode": "extract"},
            },
        )

        self.assertEqual(
            step["description"],
            "Summarize the core content of the obra/superpowers repository",
        )
        self.assertIn("obra/superpowers", step["prompt"])

    def test_semantic_decision_act_ai_instruction_forces_navigation_contract(self):
        step = ASSISTANT_MODULE.RPAAssistant._coerce_to_ai_instruction(
            "找到和SKILL最相关的项目打开",
            {
                "action": "ai_instruction",
                "description": "Find the project most related to SKILL from trending repos",
                "prompt": "Scan all repository names and descriptions on the current GitHub trending page and return the repo_path of the top match.",
                "instruction_kind": "semantic_decision",
                "output_expectation": {"mode": "act"},
                "execution_hint": {
                    "requires_dom_snapshot": True,
                    "allow_navigation": False,
                    "max_reasoning_steps": 5,
                },
            },
        )

        self.assertTrue(step["execution_hint"]["allow_navigation"])
        self.assertIn("Complete the requested browser action inside this AI instruction.", step["prompt"])


class RuntimeAIInstructionTests(unittest.IsolatedAsyncioTestCase):
    def test_retryable_execution_error_accepts_assignment_expression_syntax_message(self):
        self.assertTrue(
            RUNTIME_AI_INSTRUCTION_MODULE._is_retryable_execution_error(
                'expression cannot contain assignment, perhaps you meant "=="? (<ai_instruction>, line 4)'
            )
        )

    async def test_execute_ai_instruction_reuses_structured_snapshot_when_page_unchanged(self):
        step = {
            "action": "ai_instruction",
            "description": "Extract two visible fields",
            "prompt": "Extract visible text from the current page.",
            "instruction_kind": "semantic_extract",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"planning_timeout_s": 5},
            "result_key": "visible_text",
        }
        snapshot = {
            "url": "https://example.com/items",
            "title": "Items",
            "frames": [],
        }

        with patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "structured",
                    "actions": [
                        {"action": "extract_text", "target_hint": {"text": "First"}},
                        {"action": "extract_text", "target_hint": {"text": "Second"}},
                    ],
                }
            ),
        ), patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ) as build_snapshot, patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "resolve_structured_intent",
            side_effect=lambda _snapshot, action: action,
        ), patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "execute_structured_intent",
            new=AsyncMock(return_value={"success": True, "output": "ok"}),
        ) as execute_structured_intent, patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "_capture_page_observation",
            new=AsyncMock(return_value={"url": "https://example.com/items", "title": "Items"}),
        ):
            result = await RUNTIME_AI_INSTRUCTION_MODULE.execute_ai_instruction(
                _FakePage(),
                step,
                results={},
            )

        self.assertTrue(result["success"])
        self.assertEqual(execute_structured_intent.await_count, 2)
        self.assertEqual(build_snapshot.await_count, 1)

    async def test_execute_ai_instruction_retries_after_syntax_error_code_plan(self):
        step = {
            "action": "ai_instruction",
            "description": "Extract the title of the first issue in the list",
            "prompt": "Extract the title text of the first issue item from the current page.",
            "instruction_kind": "semantic_extract",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {
                "requires_dom_snapshot": True,
                "allow_navigation": False,
                "max_reasoning_steps": 5,
                "planning_timeout_s": 5,
            },
            "result_key": "latest_issue_title",
        }
        results = {}
        plan_attempts = [
            {"plan_type": "code", "code": "async def run(page, results):\n    return (title = 'bad')"},
            {"plan_type": "code", "code": "async def run(page, results):\n    return {'success': True, 'output': 'Latest issue title'}"},
        ]

        async def fake_plan_ai_instruction(_page, _step, model_config=None):
            return plan_attempts.pop(0)

        with patch.object(
            RUNTIME_AI_INSTRUCTION_MODULE,
            "plan_ai_instruction",
            new=AsyncMock(side_effect=fake_plan_ai_instruction),
        ) as plan_ai_instruction:
            result = await RUNTIME_AI_INSTRUCTION_MODULE.execute_ai_instruction(
                _FakePage(),
                step,
                results,
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["output"], "Latest issue title")
        self.assertEqual(results["latest_issue_title"], "Latest issue title")
        self.assertEqual(plan_ai_instruction.await_count, 2)

    async def test_react_agent_rejects_javascript_code_before_execution(self):
        agent = ASSISTANT_MODULE.RPAReActAgent()
        page = _FakeActionPage()
        snapshot = {
            "url": "https://github.com/trending",
            "title": "Trending",
            "frames": [],
        }
        responses = [
            json.dumps(
                {
                    "thought": "use deterministic scripted logic to find the top repository",
                    "action": "execute",
                    "description": "Parse star counts and open the top repository",
                    "code": "const starLinks = await page.locator('a[href*=\"/stargazers\"]').all();\nreturn '/obra/superpowers';",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "use deterministic python playwright code to find the top repository",
                    "action": "execute",
                    "description": "Parse star counts and open the top repository",
                    "code": "async def run(page):\n    return {'target_url': '/obra/superpowers'}",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": "done",
                    "description": "done",
                    "risk": "none",
                    "risk_reason": "",
                }
            ),
        ]

        async def fake_stream(_history, _model_config=None):
            yield responses.pop(0)

        agent._stream_llm = fake_stream

        with patch.object(
            ASSISTANT_MODULE,
            "build_page_snapshot",
            new=AsyncMock(return_value=snapshot),
        ), patch.object(
            ASSISTANT_MODULE,
            "_execute_on_page",
            new=AsyncMock(
                return_value={
                    "success": True,
                    "output": '{"target_url": "/obra/superpowers"}',
                    "raw_output": {"target_url": "/obra/superpowers"},
                }
            ),
        ) as execute_on_page:
            events = []
            async for event in agent.run(
                session_id="session-js-guard",
                page=page,
                goal="打开 Trending，找出 star 数量最多的项目并打开",
                existing_steps=[],
            ):
                events.append(event)

        thought_events = [event for event in events if event["event"] == "agent_thought"]
        self.assertEqual(len(thought_events), 1)
        self.assertIn("python playwright", thought_events[0]["data"]["text"].lower())
        execute_on_page.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
