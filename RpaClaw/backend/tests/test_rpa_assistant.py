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

    def test_coerce_to_ai_instruction_normalizes_summary_prompt_to_current_page(self):
        step = ASSISTANT_MODULE.RPAAssistant._coerce_to_ai_instruction(
            "用中文总结当前项目的核心内容",
            {
                "action": "ai_instruction",
                "description": "Summarize repository core content",
                "prompt": "Read the repository description and README file content on the current page. Summarize the core content, purpose, and key features of the 'obra/superpowers' project in Chinese.",
                "instruction_kind": "semantic_extract",
                "output_expectation": {"mode": "extract"},
            },
        )

        self.assertEqual(step["result_key"], "project_summary")
        self.assertNotIn("obra/superpowers", step["prompt"])
        self.assertIn("当前页面", step["prompt"])

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
        self.assertEqual(step_done_events[0]["data"]["step"]["action"], "ai_script")
        self.assertEqual(step_done_events[1]["data"]["step"]["action"], "ai_instruction")
        self.assertEqual(len(recorded_steps_event["data"]["steps"]), 2)
        self.assertEqual(recorded_steps_event["data"]["steps"][0]["action"], "ai_script")
        self.assertEqual(recorded_steps_event["data"]["steps"][1]["action"], "ai_instruction")
        execute_on_page.assert_awaited_once()
        execute_ai_instruction.assert_awaited_once()

    async def test_react_agent_replans_when_ranking_step_is_wrongly_structured_click(self):
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
                    "thought": "use deterministic scripted logic for ranking before clicking",
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
        ) as execute_on_page:
            events = []
            async for event in agent.run(
                session_id="session-replan-ranking",
                page=page,
                goal="打开 trending，找 star 数量最多的项目并点击打开",
                existing_steps=[],
            ):
                events.append(event)

        step_done_events = [event for event in events if event["event"] == "agent_step_done"]
        self.assertEqual(len(step_done_events), 1)
        self.assertEqual(step_done_events[0]["data"]["step"]["action"], "ai_script")
        execute_on_page.assert_awaited_once()

    async def test_react_agent_replans_summary_code_step_into_ai_instruction(self):
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

    def test_ranking_code_step_is_not_forced_into_ai_instruction_by_later_summary_goal(self):
        self.assertFalse(
            ASSISTANT_MODULE._react_step_requires_ai_instruction(
                thought="use deterministic ranking logic to find the maximum star count",
                description="找出 star 数量最多的项目并点击进入",
                structured_intent=None,
                ai_instruction_step=None,
                code="async def run(page):\n    return 'opened top project'",
            )
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

    def test_should_use_react_mode_for_complex_multistep_goal(self):
        self.assertTrue(
            ASSISTANT_MODULE.should_use_react_mode(
                "打开 https://github.com/trending，找最start数量最多的项目，点击进去后总结核心内容。",
                requested_mode="chat",
            )
        )

    def test_should_not_use_react_mode_for_simple_summary_request(self):
        self.assertFalse(
            ASSISTANT_MODULE.should_use_react_mode(
                "总结当前项目内容",
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

    def test_react_step_requires_scripted_logic_for_batch_array_extraction(self):
        requires_script = ASSISTANT_MODULE._react_step_requires_scripted_logic(
            thought="collect the first 10 pull requests and output a strict array of title and author",
            description="Extract title and author for the first 10 pull requests as an array",
            structured_intent={"action": "extract_text"},
        )

        self.assertTrue(requires_script)

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

    def test_system_prompt_includes_ai_instruction_few_shot_examples(self):
        prompt = ASSISTANT_MODULE.SYSTEM_PROMPT

        self.assertIn('User: "总结当前项目的核心信息，并提炼用途、能力和限制"', prompt)
        self.assertIn('"instruction_kind": "semantic_extract"', prompt)
        self.assertIn('User: "根据当前页面展示的信息，判断这条记录是否需要人工复核；如果需要，则打开详情页"', prompt)
        self.assertIn('"instruction_kind": "semantic_decision"', prompt)
        self.assertIn('User: "找到当前页面 star 数量最高的项目并点击打开它"', prompt)
        self.assertIn('Do not use ai_instruction for deterministic ranking, numeric comparison, fixed filtering, or explicit field-based selection', prompt)
        return

        self.assertIn('User: "总结当前项目内容"', prompt)
        self.assertIn('"instruction_kind": "semantic_extract"', prompt)
        self.assertIn('User: "在当前页面中找出最符合规则的一项并点击进入"', prompt)
        self.assertIn('"instruction_kind": "semantic_decision"', prompt)

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
            async for event in assistant.chat("session-1", fake_page, "summarize stars", []):
                events.append(event)

        result_event = next(event for event in events if event["event"] == "result")
        self.assertEqual(result_event["data"]["step"]["action"], "ai_instruction")
        self.assertEqual(
            result_event["data"]["output"],
            "repo-a (12000 stars); repo-b (15000 stars)",
        )
        execute_mock.assert_awaited_once()

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
    def test_summary_ai_instruction_description_is_generic(self):
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

        self.assertEqual(step["description"], "总结当前项目核心内容")
        self.assertNotIn("obra/superpowers", step["prompt"])

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
