import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from backend.rpa.runtime_ai_instruction import _parse_plan_response_text, execute_ai_instruction


class _FakePage:
    url = "https://example.com"

    def __init__(self):
        self.url = "https://example.com"
        self.goto_calls = []
        self.load_state_calls = []

    async def title(self):
        return "Example"

    async def goto(self, url, wait_until=None):
        self.goto_calls.append((url, wait_until))
        self.url = url

    async def wait_for_load_state(self, state):
        self.load_state_calls.append(state)


class RuntimeAIInstructionTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_ai_instruction_includes_global_goal_in_planner_payload(self):
        captured_messages = {}

        class _CaptureModel:
            async def ainvoke(self, messages):
                captured_messages["messages"] = messages
                return type(
                    "Resp",
                    (),
                    {"content": '{"plan_type":"structured","actions":[{"action":"click"}]}', "additional_kwargs": {}},
                )()

        step = {
            "action": "ai_instruction",
            "prompt": "Extract PR information from the current page",
            "global_goal": "收集当前仓库的前10个pr（无论是什么状态）的信息，要求记录每个pr的创建人和标题，输出严格为数组",
            "instruction_kind": "semantic_extract",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"max_reasoning_steps": 5, "planning_timeout_s": 5},
        }
        page = _FakePage()

        with patch(
            "backend.rpa.runtime_ai_instruction.get_llm_model",
            return_value=_CaptureModel(),
        ), patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ):
            from backend.rpa.runtime_ai_instruction import plan_ai_instruction

            await plan_ai_instruction(page, step, model_config=None)

        user_payload = captured_messages["messages"][1]["content"]
        self.assertIn('"global_goal": "收集当前仓库的前10个pr（无论是什么状态）的信息，要求记录每个pr的创建人和标题，输出严格为数组"', user_payload)

    def test_parse_plan_response_text_accepts_fenced_json(self):
        text = """Here is the plan:

```json
{"plan_type":"structured","actions":[{"action":"extract_text","description":"summarize"}]}
```
"""

        parsed = _parse_plan_response_text(text)

        self.assertEqual(parsed["plan_type"], "structured")
        self.assertEqual(parsed["actions"][0]["action"], "extract_text")

    def test_parse_plan_response_text_accepts_inline_fenced_json(self):
        text = """```json {"plan_type":"code","code":"async def run(page, results):\\n    return {'success': True, 'output': 'ok'}"} ```"""

        parsed = _parse_plan_response_text(text)

        self.assertEqual(parsed["plan_type"], "code")
        self.assertIn("async def run", parsed["code"])

    def test_parse_plan_response_text_raises_clear_error_for_non_json(self):
        with self.assertRaisesRegex(ValueError, "non-JSON response"):
            _parse_plan_response_text("I can help summarize the page, but first let's inspect it.")

    async def test_execute_ai_instruction_accepts_structured_plan(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Click submit",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "act"},
            "execution_hint": {"max_reasoning_steps": 10},
        }
        page = _FakePage()

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "structured",
                    "actions": [
                        {"action": "navigate", "value": "https://example.com/next", "description": "go"}
                    ],
                }
            ),
        ), patch(
            "backend.rpa.runtime_ai_instruction.execute_structured_intent",
            new=AsyncMock(return_value={"success": True, "output": "ok", "action_performed": True}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.resolve_structured_intent",
            return_value={"action": "navigate", "resolved": {"url": "https://example.com/next"}},
        ):
            result = await execute_ai_instruction(page, step, results={})

        self.assertTrue(result["success"])

    async def test_execute_ai_instruction_treats_same_page_structured_action_as_performed(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Open details drawer",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "act"},
            "execution_hint": {"max_reasoning_steps": 10},
        }
        page = _FakePage()

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "structured",
                    "actions": [
                        {"action": "click", "description": "open details"}
                    ],
                }
            ),
        ), patch(
            "backend.rpa.runtime_ai_instruction.execute_structured_intent",
            new=AsyncMock(return_value={"success": True, "output": "opened"}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.resolve_structured_intent",
            return_value={"action": "click", "resolved": {"locator": "button"}},
        ):
            result = await execute_ai_instruction(page, step, results={})

        self.assertTrue(result["success"])
        self.assertTrue(result["action_performed"])

    async def test_execute_ai_instruction_supports_blackboard_ref_extract(self):
        class _BlackboardModel:
            async def ainvoke(self, messages):
                self.messages = messages
                return type(
                    "Resp",
                    (),
                    {
                        "content": (
                            '[{"name":"android-reverse-engineering-skill",'
                            '"url":"https://github.com/SimoneAvogadro/android-reverse-engineering-skill",'
                            '"skill_relevance_reason":"Repository name directly contains skill"}]'
                        ),
                        "additional_kwargs": {},
                    },
                )()

        step = {
            "action": "ai_instruction",
            "prompt": "Find which extracted repos are most related to SKILL",
            "global_goal": "Open the repo most related to SKILL after filtering extracted records",
            "input_scope": {"mode": "blackboard_ref"},
            "input_refs": ["trending_repos"],
            "output_expectation": {
                "mode": "extract",
                "schema": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["name", "url", "skill_relevance_reason"],
                    },
                },
            },
            "execution_hint": {"max_reasoning_steps": 5, "planning_timeout_s": 5},
            "result_key": "skill_repos",
        }
        results = {
            "trending_repos": [
                {
                    "name": "SimoneAvogadro / android-reverse-engineering-skill",
                    "url": "https://github.com/SimoneAvogadro/android-reverse-engineering-skill",
                    "description": "Android reverse engineering skill package",
                }
            ]
        }

        with patch(
            "backend.rpa.runtime_ai_instruction.get_llm_model",
            return_value=_BlackboardModel(),
        ):
            result = await execute_ai_instruction(_FakePage(), step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(result["output"][0]["name"], "android-reverse-engineering-skill")
        self.assertEqual(results["skill_repos"][0]["url"], "https://github.com/SimoneAvogadro/android-reverse-engineering-skill")

    async def test_execute_ai_instruction_uses_two_phase_fast_path_for_semantic_summary_extract(self):
        step = {
            "action": "ai_instruction",
            "prompt": "请总结当前项目的核心内容，包括用途、主要能力和目标用户",
            "instruction_kind": "semantic_extract",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"max_reasoning_steps": 10, "planning_timeout_s": 15},
            "result_key": "project_summary",
        }
        page = _FakePage()
        results = {}

        with patch(
            "backend.rpa.runtime_ai_instruction._acquire_semantic_summary_material",
            new=AsyncMock(return_value="Title: Superpowers\n\nExtracted content:\n[readme] Superpowers is a workflow..."),
        ) as acquire_material, patch(
            "backend.rpa.runtime_ai_instruction._summarize_semantic_summary_material",
            new=AsyncMock(return_value="Superpowers 是一个面向编码代理的软件开发工作流框架。"),
        ) as summarize_material, patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(side_effect=AssertionError("planner should not run for fast-path summary")),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(
            result["output"],
            "Superpowers 是一个面向编码代理的软件开发工作流框架。",
        )
        self.assertEqual(
            results["project_summary"],
            "Superpowers 是一个面向编码代理的软件开发工作流框架。",
        )
        acquire_material.assert_awaited_once()
        summarize_material.assert_awaited_once()

    async def test_execute_ai_instruction_falls_back_to_planner_when_summary_material_is_unavailable(self):
        step = {
            "action": "ai_instruction",
            "prompt": "请总结当前项目的核心内容",
            "instruction_kind": "semantic_extract",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "project_summary",
        }
        page = _FakePage()
        results = {}

        with patch(
            "backend.rpa.runtime_ai_instruction._acquire_semantic_summary_material",
            new=AsyncMock(return_value=""),
        ), patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "code",
                    "code": (
                        "async def run(page, results):\n"
                        "    results['project_summary'] = 'Repo summary'\n"
                        "    return {'success': True, 'output': 'Repo summary'}"
                    ),
                }
            ),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(result["output"], "Repo summary")
        self.assertEqual(results["project_summary"], "Repo summary")

    async def test_execute_ai_instruction_preserves_structured_extract_output(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Select project",
            "instruction_kind": "semantic_select",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {
                "mode": "extract",
                "schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "url": {"type": "string"}},
                },
            },
            "execution_hint": {"max_reasoning_steps": 5},
            "result_key": "selected_project",
        }
        page = _FakePage()
        results = {}
        selected_project = {"name": "owner/repo", "url": "https://github.com/owner/repo"}

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "code",
                    "code": (
                        "async def run(page, results):\n"
                        f"    return {{'success': True, 'output': {selected_project!r}}}"
                    ),
                }
            ),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(result["output"], selected_project)
        self.assertEqual(results["selected_project"], selected_project)

    async def test_execute_ai_instruction_replans_when_extract_output_misses_schema(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Select project",
            "instruction_kind": "semantic_select",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {
                "mode": "extract",
                "schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "url": {"type": "string"}},
                    "required": ["name", "url"],
                },
            },
            "execution_hint": {"max_reasoning_steps": 5},
            "result_key": "selected_project",
        }
        page = _FakePage()
        results = {}
        plan_attempts = [
            {
                "plan_type": "code",
                "code": "async def run(page, results):\n    return {'success': True, 'output': 'owner/repo'}",
            },
            {
                "plan_type": "code",
                "code": (
                    "async def run(page, results):\n"
                    "    return {'success': True, 'output': {'name': 'owner/repo', 'url': 'https://github.com/owner/repo'}}"
                ),
            },
        ]

        async def fake_plan_ai_instruction(_page, _step, model_config=None):
            return plan_attempts.pop(0)

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(side_effect=fake_plan_ai_instruction),
        ) as plan_ai_instruction:
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(result["output"]["url"], "https://github.com/owner/repo")
        self.assertEqual(results["selected_project"]["name"], "owner/repo")
        self.assertEqual(plan_ai_instruction.await_count, 2)

    async def test_execute_ai_instruction_uses_best_effort_summary_when_fast_path_summary_times_out(self):
        step = {
            "action": "ai_instruction",
            "prompt": "请用中文总结当前项目的核心目标、主要功能特点和适用场景",
            "instruction_kind": "semantic_extract",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"max_reasoning_steps": 10, "planning_timeout_s": 5},
            "result_key": "project_summary",
        }
        page = _FakePage()
        results = {}
        extracted_material = (
            "Title: Superpowers\n\n"
            "Meta description: An agentic skills framework and software development methodology.\n\n"
            "Extracted content:\n"
            "[readme] Superpowers is a complete software development workflow for coding agents. "
            "It provides composable skills, structured planning, and execution guidance for teams using AI agents."
        )

        with patch(
            "backend.rpa.runtime_ai_instruction._acquire_semantic_summary_material",
            new=AsyncMock(return_value=extracted_material),
        ), patch(
            "backend.rpa.runtime_ai_instruction._summarize_semantic_summary_material",
            new=AsyncMock(side_effect=asyncio.TimeoutError()),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(side_effect=AssertionError("planner should not run when best-effort summary is available")),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertIn("项目标题：Superpowers", result["output"])
        self.assertIn("简介：An agentic skills framework and software development methodology.", result["output"])
        self.assertEqual(results["project_summary"], result["output"])

    async def test_execute_ai_instruction_rejects_empty_structured_plan_for_act_mode(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Open hermes-agent details when stars are above 50000",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "act"},
            "execution_hint": {"max_reasoning_steps": 10},
        }
        page = _FakePage()

        with patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(return_value={"plan_type": "structured", "actions": []}),
        ):
            result = await execute_ai_instruction(page, step, results={})

        self.assertFalse(result["success"])
        self.assertIn("no executable actions", result["error"].lower())

    async def test_execute_ai_instruction_accepts_code_plan(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Analyze page and click the best matching row",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "act"},
            "execution_hint": {"max_reasoning_steps": 10},
        }
        page = _FakePage()

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "code",
                    "code": (
                        "async def run(page, results):\n"
                        "    return {'success': True, 'output': 'ok', 'action_performed': True}"
                    ),
                }
            ),
        ):
            result = await execute_ai_instruction(page, step, results={})

        self.assertTrue(result["success"])

    async def test_execute_ai_instruction_materializes_navigation_target_for_act_mode(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Open the project most related to SKILL on the current page",
            "instruction_kind": "semantic_decision",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "act"},
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "most_skill_related_project",
        }
        page = _FakePage()
        results = {}

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "code",
                    "code": (
                        "async def run(page, results):\n"
                        "    return {'success': True, 'output': {'repo_path': '/forrestchang/andrej-karpathy-skills'}}"
                    ),
                }
            ),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertTrue(result["action_performed"])
        self.assertEqual(result["navigation_target"], "https://example.com/forrestchang/andrej-karpathy-skills")
        self.assertEqual(page.goto_calls[0][0], "https://example.com/forrestchang/andrej-karpathy-skills")

    async def test_execute_ai_instruction_act_mode_stores_structured_output_for_later_refs(self):
        selected = {
            "name": "openai/openai-agents-python",
            "url": "https://github.com/openai/openai-agents-python",
            "reason": "Python SDK project",
        }
        step = {
            "action": "ai_instruction",
            "prompt": "Open the project most related to Python on the current page",
            "instruction_kind": "semantic_decision",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {
                "mode": "act",
                "schema": {"type": "object", "required": ["name", "url", "reason"]},
            },
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "selected_python_project",
        }
        page = _FakePage()
        results = {}

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "code",
                    "code": (
                        "async def run(page, results):\n"
                        f"    return {{'success': True, 'output': {selected!r}}}"
                    ),
                }
            ),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertTrue(result["action_performed"])
        self.assertEqual(result["output"], selected)
        self.assertEqual(results["selected_python_project"]["url"], selected["url"])
        self.assertEqual(page.goto_calls[0][0], selected["url"])

    async def test_execute_ai_instruction_act_mode_synthesizes_structured_output_from_navigation(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Open the project most related to Python on the current page",
            "instruction_kind": "runtime_ai",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {
                "mode": "act",
                "schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "url": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["name", "url", "reason"],
                },
            },
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "selected_python_project",
        }
        page = _FakePage()
        results = {}

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "code",
                    "code": (
                        "async def run(page, results):\n"
                        "    await page.goto('https://github.com/openai/openai-agents-python')\n"
                        "    return {'success': True, 'output': '', 'action_performed': True}"
                    ),
                }
            ),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(
            results["selected_python_project"]["url"],
            "https://github.com/openai/openai-agents-python",
        )
        self.assertEqual(results["selected_python_project"]["name"], "openai/openai-agents-python")
        self.assertTrue(results["selected_python_project"]["reason"])

    async def test_execute_ai_instruction_structured_navigate_accepts_target_url_alias(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Open the project most related to Python on the current page",
            "instruction_kind": "runtime_ai",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {
                "mode": "act",
                "schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "url": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["name", "url", "reason"],
                },
            },
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "selected_python_project",
        }
        page = _FakePage()
        results = {}

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "structured",
                    "actions": [
                        {
                            "action": "navigate",
                            "target_url": "https://github.com/openai/openai-agents-python",
                            "description": "Open selected Python project",
                        }
                    ],
                }
            ),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(page.goto_calls[0][0], "https://github.com/openai/openai-agents-python")
        self.assertEqual(
            results["selected_python_project"]["url"],
            "https://github.com/openai/openai-agents-python",
        )
        self.assertEqual(results["selected_python_project"]["name"], "openai/openai-agents-python")

    async def test_execute_ai_instruction_replans_act_schema_code_plan_syntax_error_to_structured_navigation(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Open the project most related to Python on the current page",
            "instruction_kind": "semantic_select_and_navigate",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {
                "mode": "act",
                "schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "url": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["name", "url", "reason"],
                },
            },
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "selected_python_project",
        }
        page = _FakePage()
        results = {}
        captured_steps = []

        async def fake_plan_ai_instruction(_page, current_step, model_config=None):
            captured_steps.append(current_step)
            if len(captured_steps) == 1:
                return {
                    "plan_type": "code",
                    "code": (
                        "async def run(page, results):\n"
                        "    selected = {'url': 'https://github.com/openai/openai-agents-python'\n"
                        "    return {'success': True, 'output': selected}"
                    ),
                }
            return {
                "plan_type": "structured",
                "actions": [
                    {
                        "action": "navigate",
                        "target_url": "https://github.com/openai/openai-agents-python",
                    }
                ],
            }

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(side_effect=fake_plan_ai_instruction),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(page.goto_calls[0][0], "https://github.com/openai/openai-agents-python")
        self.assertEqual(results["selected_python_project"]["url"], "https://github.com/openai/openai-agents-python")
        self.assertEqual(len(captured_steps), 2)
        self.assertIn("invalid Python syntax", captured_steps[1]["planning_feedback"])

    async def test_execute_ai_instruction_replans_when_act_mode_only_returns_decision_text(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Open the project most related to SKILL on the current page",
            "instruction_kind": "semantic_decision",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "act"},
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "most_skill_related_project",
        }
        page = _FakePage()
        results = {}
        captured_steps = []

        async def fake_plan_ai_instruction(_page, current_step, model_config=None):
            captured_steps.append(current_step)
            if len(captured_steps) == 1:
                return {
                    "plan_type": "code",
                    "code": (
                        "async def run(page, results):\n"
                        "    return {'success': True, 'output': 'Top match: forrestchang / andrej-karpathy-skills'}"
                    ),
                }
            return {
                "plan_type": "code",
                "code": (
                    "async def run(page, results):\n"
                    "    return {'success': True, 'output': {'repo_path': '/forrestchang/andrej-karpathy-skills'}}"
                ),
            }

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(side_effect=fake_plan_ai_instruction),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertTrue(result["action_performed"])
        self.assertEqual(result["navigation_target"], "https://example.com/forrestchang/andrej-karpathy-skills")
        self.assertEqual(page.goto_calls[0][0], "https://example.com/forrestchang/andrej-karpathy-skills")
        self.assertEqual(len(captured_steps), 2)
        self.assertIn("act mode", captured_steps[1]["planning_feedback"])
        self.assertIn("target_url", captured_steps[1]["planning_feedback"])

    async def test_execute_ai_instruction_replans_when_code_plan_uses_disallowed_token(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Summarize current project information",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "project_summary",
        }
        page = _FakePage()
        results = {}

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                side_effect=[
                    {
                        "plan_type": "code",
                        "code": (
                            "import requests\n"
                            "async def run(page, results):\n"
                            "    return {'success': True, 'output': 'bad'}"
                        ),
                    },
                    {
                        "plan_type": "code",
                        "code": (
                            "async def run(page, results):\n"
                            "    results['project_summary'] = 'Repo summary'\n"
                            "    return {'success': True, 'output': 'Repo summary'}"
                        ),
                    },
                ]
            ),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(results["project_summary"], "Repo summary")
        self.assertEqual(result["output"], "Repo summary")

    async def test_execute_ai_instruction_replans_when_semantic_summary_extract_is_misplanned_as_structured_extract(self):
        step = {
            "action": "ai_instruction",
            "prompt": "总结当前项目的核心信息，并提炼用途、能力和限制",
            "instruction_kind": "semantic_extract",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "project_summary",
        }
        page = _FakePage()
        results = {}

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                side_effect=[
                    {
                        "plan_type": "structured",
                        "actions": [
                            {
                                "action": "extract_text",
                                "description": "read README heading",
                                "target_hint": {"text": "README.md"},
                            }
                        ],
                    },
                    {
                        "plan_type": "code",
                        "code": (
                            "async def run(page, results):\n"
                            "    results['project_summary'] = 'Repo summary'\n"
                            "    return {'success': True, 'output': 'Repo summary'}"
                        ),
                    },
                ]
            ),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(results["project_summary"], "Repo summary")
        self.assertEqual(result["output"], "Repo summary")

    async def test_execute_ai_instruction_replans_when_code_plan_hits_page_evaluate_syntax_error(self):
        step = {
            "action": "ai_instruction",
            "prompt": "总结当前项目内容",
            "instruction_kind": "semantic_extract",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "project_summary",
        }
        page = _FakePage()
        results = {}

        async def fake_execute_code_plan(_page, code, _results):
            if "broken plan" in code:
                return {
                    "success": False,
                    "error": "Page.evaluate: SyntaxError: Invalid or unexpected token",
                    "output": "",
                }
            _results["project_summary"] = "Repo summary"
            return {"success": True, "output": "Repo summary"}

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                side_effect=[
                    {"plan_type": "code", "code": "async def run(page, results):\n    # broken plan"},
                    {
                        "plan_type": "code",
                        "code": (
                            "async def run(page, results):\n"
                            "    results['project_summary'] = 'Repo summary'\n"
                            "    return {'success': True, 'output': 'Repo summary'}"
                        ),
                    },
                ]
            ),
        ), patch(
            "backend.rpa.runtime_ai_instruction._execute_code_plan",
            new=fake_execute_code_plan,
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(results["project_summary"], "Repo summary")
        self.assertEqual(result["output"], "Repo summary")

    async def test_execute_ai_instruction_replans_when_code_plan_has_unterminated_multiline_string(self):
        step = {
            "action": "ai_instruction",
            "prompt": "总结当前项目内容",
            "instruction_kind": "semantic_extract",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "project_summary",
        }
        page = _FakePage()
        results = {}

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                side_effect=[
                    {
                        "plan_type": "code",
                        "code": (
                            "async def run(page, results):\n"
                            "    summary = '''broken\n"
                            "    return {'success': True, 'output': summary}\n"
                        ),
                    },
                    {
                        "plan_type": "code",
                        "code": (
                            "async def run(page, results):\n"
                            "    results['project_summary'] = 'Repo summary'\n"
                            "    return {'success': True, 'output': 'Repo summary'}"
                        ),
                    },
                ]
            ),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(results["project_summary"], "Repo summary")
        self.assertEqual(result["output"], "Repo summary")

    async def test_execute_ai_instruction_normalizes_javascript_literals_in_code_plan(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Summarize current project information",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "project_summary",
        }
        page = _FakePage()
        results = {}

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "code",
                    "code": (
                        "async def run(page, results):\n"
                        "    results['project_summary'] = 'Repo summary'\n"
                        "    return {'success': true, 'output': null, 'action_performed': false}"
                    ),
                }
            ),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(results["project_summary"], "Repo summary")
        self.assertEqual(result["output"], "Repo summary")

    async def test_execute_ai_instruction_rejects_code_plan_without_action_evidence_for_act_mode(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Open hermes-agent details when stars are above 50000",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "act"},
            "execution_hint": {"max_reasoning_steps": 10},
        }
        page = _FakePage()

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "code",
                    "code": "async def run(page, results):\n    return {'success': True, 'output': ''}",
                }
            ),
        ):
            result = await execute_ai_instruction(page, step, results={})

        self.assertFalse(result["success"])
        self.assertIn("no observable action", result["error"].lower())

    async def test_execute_ai_instruction_persists_extract_result_from_code_plan(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Summarize projects with more than 10000 stars",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "filtered_high_star_projects",
        }
        page = _FakePage()
        results = {}

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "code",
                    "code": (
                        "async def run(page, results):\n"
                        "    return {'success': True, 'output': 'repo-a: 12000 stars'}"
                    ),
                }
            ),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(results["filtered_high_star_projects"], "repo-a: 12000 stars")
        self.assertEqual(result["output"], "repo-a: 12000 stars")

    async def test_execute_ai_instruction_uses_result_key_value_when_extract_output_is_empty(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Summarize projects with more than 10000 stars",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "filtered_high_star_projects",
        }
        page = _FakePage()
        results = {}

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "code",
                    "code": (
                        "async def run(page, results):\n"
                        "    results['filtered_high_star_projects'] = 'repo-a: 12000 stars'\n"
                        "    return {'success': True, 'output': ''}"
                    ),
                }
            ),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(results["filtered_high_star_projects"], "repo-a: 12000 stars")
        self.assertEqual(result["output"], "repo-a: 12000 stars")

    async def test_execute_ai_instruction_preserves_dict_output_for_extract(self):
        step = {
            "action": "ai_instruction",
            "prompt": "总结当前项目内容",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "project_summary",
        }
        page = _FakePage()
        results = {}

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "code",
                    "code": (
                        "async def run(page, results):\n"
                        "    return {'success': True, 'output': {'summary': 'Repo summary', 'language': 'Python'}}"
                    ),
                }
            ),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertTrue(result["success"])
        self.assertEqual(
            result["output"],
            {"summary": "Repo summary", "language": "Python"},
        )
        self.assertEqual(
            results["project_summary"],
            {"summary": "Repo summary", "language": "Python"},
        )

    async def test_execute_ai_instruction_returns_explicit_timeout_error_for_code_plan(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Summarize projects with more than 10000 stars",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"max_reasoning_steps": 10},
            "result_key": "filtered_high_star_projects",
        }
        page = _FakePage()
        results = {}

        with patch(
            "backend.rpa.runtime_ai_instruction.build_page_snapshot",
            new=AsyncMock(return_value={"url": page.url, "title": "Example", "frames": []}),
        ), patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(
                return_value={
                    "plan_type": "code",
                    "code": (
                        "import asyncio\n"
                        "async def run(page, results):\n"
                        "    await asyncio.sleep(999)\n"
                    ),
                }
            ),
        ):
            result = await execute_ai_instruction(page, step, results=results)

        self.assertFalse(result["success"])
        self.assertIn("timed out", result["error"])

    async def test_execute_ai_instruction_reports_actual_planning_timeout_budget(self):
        step = {
            "action": "ai_instruction",
            "prompt": "Summarize projects with more than 10000 stars",
            "input_scope": {"mode": "current_page"},
            "output_expectation": {"mode": "extract"},
            "execution_hint": {"max_reasoning_steps": 10, "planning_timeout_s": 60},
        }
        page = _FakePage()

        with patch(
            "backend.rpa.runtime_ai_instruction.plan_ai_instruction",
            new=AsyncMock(side_effect=asyncio.TimeoutError()),
        ):
            result = await execute_ai_instruction(page, step, results={})

        self.assertFalse(result["success"])
        self.assertIn("60s", result["error"])

    async def test_execute_ai_instruction_rejects_unsupported_scope(self):
        step = {
            "action": "ai_instruction",
            "prompt": "use history",
            "input_scope": {"mode": "history_steps"},
            "output_expectation": {"mode": "act"},
            "execution_hint": {"max_reasoning_steps": 10},
        }
        page = _FakePage()

        result = await execute_ai_instruction(page, step, results={})
        self.assertFalse(result["success"])
        self.assertIn("Unsupported input_scope", result["error"])


if __name__ == "__main__":
    unittest.main()
