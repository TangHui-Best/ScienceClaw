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

    async def test_execute_ai_instruction_normalizes_dict_output_to_json_string(self):
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
            '{"summary": "Repo summary", "language": "Python"}',
        )
        self.assertEqual(
            results["project_summary"],
            '{"summary": "Repo summary", "language": "Python"}',
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
