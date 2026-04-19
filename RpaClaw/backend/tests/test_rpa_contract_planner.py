import unittest

from backend.rpa.contract_models import ExecutionStrategy
from backend.rpa.contract_planner import (
    CONTRACT_PLANNER_SYSTEM_PROMPT,
    parse_planner_envelope_response,
    parse_step_contract_response,
    parse_step_contracts_response,
)


class ContractPlannerTests(unittest.TestCase):
    def test_prompt_defines_three_execution_strategy_boundaries(self):
        self.assertIn("primitive_action", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("deterministic_script", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("runtime_ai", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("dynamic page data + deterministic rules", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("dynamic page data + runtime semantic judgment", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("rank_collection_numeric_max", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("extract_repeated_records", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("Do not invent operator names", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("Do not use double braces", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("{selected_project.url}", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("target.type=\"blackboard_ref\"", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("Do not extract the same visible list again", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("If the requested deliverable is already present in blackboard", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("do not emit another step that only rewrites the same outputs.blackboard_key", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("Prefer role-based locators with an exact accessible name", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("outputs.schema must be a real JSON schema", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("validation.must", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("min_records", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("current page is already on the required stable subpage", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("rank_collection_numeric_max standard output", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("required fields: name, url, score", CONTRACT_PLANNER_SYSTEM_PROMPT)
        self.assertIn("plan a primitive_action navigate step to that blackboard URL", CONTRACT_PLANNER_SYSTEM_PROMPT)

    def test_parses_fenced_json_step_contract(self):
        text = """
        ```json
        {
          "id": "step_1",
          "description": "Open PRs",
          "intent": {"goal": "open_prs"},
          "inputs": {"refs": ["selected_project.url"]},
          "target": {"type": "url", "url_template": "{selected_project.url}/pulls"},
          "operator": {"type": "navigate", "execution_strategy": "primitive_action"},
          "outputs": {"blackboard_key": null, "schema": null},
          "validation": {"must": [{"type": "url_contains", "value": "/pulls"}]},
          "runtime_policy": {"requires_runtime_ai": false}
        }
        ```
        """

        contract = parse_step_contract_response(text)

        self.assertEqual(contract.operator.execution_strategy, ExecutionStrategy.PRIMITIVE_ACTION)
        self.assertEqual(contract.inputs.refs, ["selected_project.url"])

    def test_runtime_ai_contract_must_have_structured_blackboard_output(self):
        text = {
            "id": "step_ai",
            "description": "Pick project",
            "intent": {"goal": "pick_project"},
            "target": {"type": "visible_collection", "collection": "github_trending_repositories"},
            "operator": {"type": "runtime_semantic_select", "execution_strategy": "runtime_ai"},
            "outputs": {"blackboard_key": None, "schema": None},
            "validation": {"must": []},
            "runtime_policy": {
                "requires_runtime_ai": True,
                "runtime_ai_reason": "Semantic relevance is required"
            }
        }

        with self.assertRaises(ValueError):
            parse_step_contract_response(text)

    def test_runtime_ai_contract_requires_json_schema_shape(self):
        text = {
            "id": "step_ai",
            "description": "Pick project",
            "intent": {"goal": "pick_project"},
            "target": {"type": "page_content"},
            "operator": {"type": "runtime_semantic_select", "execution_strategy": "runtime_ai"},
            "outputs": {"blackboard_key": "selected_project", "schema": {"name": "string", "url": "string"}},
            "validation": {"must": []},
            "runtime_policy": {
                "requires_runtime_ai": True,
                "runtime_ai_reason": "Semantic relevance is required"
            }
        }

        with self.assertRaises(ValueError):
            parse_step_contract_response(text)

    def test_rejects_unsupported_deterministic_operator_type(self):
        text = {
            "id": "extract_trending_repos",
            "description": "Extract repos",
            "intent": {"goal": "extract repos"},
            "target": {"type": "page_data"},
            "operator": {"type": "extract_and_parse", "execution_strategy": "deterministic_script"},
            "outputs": {"blackboard_key": "repos", "schema": {"type": "array"}},
            "validation": {"must": []},
            "runtime_policy": {"requires_runtime_ai": False, "runtime_ai_reason": ""},
        }

        with self.assertRaises(ValueError):
            parse_step_contract_response(text)

    def test_rejects_extract_repeated_records_field_shorthand_strings(self):
        text = {
            "id": "extract_repos",
            "description": "Extract repos",
            "intent": {"goal": "extract repos"},
            "target": {"type": "visible_collection", "collection": "repos"},
            "operator": {
                "type": "extract_repeated_records",
                "execution_strategy": "deterministic_script",
                "selection_rule": {
                    "row_selector": "article.Box-row",
                    "fields": {
                        "repo_name": "h2 a",
                    },
                },
            },
            "outputs": {"blackboard_key": "repos", "schema": {"type": "array"}},
            "validation": {"must": []},
            "runtime_policy": {"requires_runtime_ai": False, "runtime_ai_reason": ""},
        }

        with self.assertRaises(ValueError):
            parse_step_contract_response(text)

    def test_rejects_blackboard_ref_target_without_input_refs(self):
        text = {
            "id": "filter_skill_repos",
            "description": "Filter repos",
            "intent": {"goal": "Filter repos"},
            "target": {"type": "blackboard_ref"},
            "operator": {"type": "semantic_filter", "execution_strategy": "runtime_ai"},
            "outputs": {
                "blackboard_key": "skill_repos",
                "schema": {"type": "array"},
            },
            "validation": {"must": []},
            "runtime_policy": {
                "requires_runtime_ai": True,
                "runtime_ai_reason": "Semantic filtering requires meaning",
            },
        }

        with self.assertRaises(ValueError):
            parse_step_contract_response(text)

    def test_rejects_templated_url_without_input_refs(self):
        text = {
            "id": "open_repo_pulls",
            "description": "Open pulls",
            "intent": {"goal": "Open pulls"},
            "target": {"type": "url", "url_template": "https://github.com{selected_project.url}/pulls"},
            "operator": {"type": "navigate", "execution_strategy": "primitive_action"},
            "outputs": {"blackboard_key": None, "schema": None},
            "validation": {"must": []},
            "runtime_policy": {"requires_runtime_ai": False, "runtime_ai_reason": ""},
        }

        with self.assertRaises(ValueError):
            parse_step_contract_response(text)

    def test_parses_multi_step_sop_contract_response(self):
        response = {
            "steps": [
                {
                    "id": "open",
                    "description": "Open page",
                    "intent": {"goal": "open"},
                    "target": {"type": "url", "url_template": "https://example.com"},
                    "operator": {"type": "navigate", "execution_strategy": "primitive_action"},
                    "outputs": {"blackboard_key": None, "schema": None},
                    "validation": {"must": []},
                    "runtime_policy": {"requires_runtime_ai": False},
                },
                {
                    "id": "extract",
                    "description": "Extract list",
                    "intent": {"goal": "extract"},
                    "target": {"type": "visible_collection", "collection": "items"},
                    "operator": {
                        "type": "extract_repeated_records",
                        "execution_strategy": "deterministic_script",
                        "selection_rule": {
                            "row_selector": ".row",
                            "fields": {"title": {"selector": "a"}},
                        },
                    },
                    "outputs": {"blackboard_key": "items", "schema": {"type": "array"}},
                    "validation": {"must": []},
                    "runtime_policy": {"requires_runtime_ai": False},
                },
            ]
        }

        contracts = parse_step_contracts_response(response)

        self.assertEqual([contract.id for contract in contracts], ["open", "extract"])

    def test_normalizes_live_planner_navigation_shape(self):
        response = {
            "step_id": "step_navigate_trending",
            "target": {
                "url_template": "https://github.com/trending",
                "execution_strategy": "primitive_action",
                "action": "navigate",
            },
            "outputs": {"blackboard_key": None, "schema": None},
            "validation": {"must": [{"type": "url_contains", "value": "github.com/trending"}]},
            "runtime_policy": {
                "requires_runtime_ai": False,
                "runtime_ai_reason": None,
            },
        }

        contract = parse_step_contract_response(response, fallback_goal="打开 https://github.com/trending")

        self.assertEqual(contract.id, "step_navigate_trending")
        self.assertEqual(contract.intent.goal, "打开 https://github.com/trending")
        self.assertEqual(contract.description, "打开 https://github.com/trending")
        self.assertEqual(contract.target.type, "url")
        self.assertEqual(contract.operator.type, "navigate")
        self.assertEqual(contract.operator.execution_strategy.value, "primitive_action")
        self.assertEqual(contract.runtime_policy.runtime_ai_reason, "")

    def test_parses_planner_envelope_next_step(self):
        response = {
            "status": "next_step",
            "current_step": {
                "id": "step_1",
                "description": "打开 https://github.com/trending",
                "intent": {"goal": "打开 https://github.com/trending"},
                "target": {"type": "url", "url_template": "https://github.com/trending"},
                "operator": {"type": "navigate", "execution_strategy": "primitive_action"},
                "outputs": {"blackboard_key": None, "schema": None},
                "validation": {"must": []},
                "runtime_policy": {"requires_runtime_ai": False, "runtime_ai_reason": ""},
            },
        }

        envelope = parse_planner_envelope_response(response)

        self.assertEqual(envelope.status.value, "next_step")
        self.assertIsNotNone(envelope.current_step)
        self.assertEqual(envelope.current_step.source.value, "ai")
        self.assertEqual(envelope.current_step.id, "step_1")

    def test_fallback_goal_strips_repair_feedback_from_description_defaults(self):
        response = {
            "id": "step_1",
            "target": {"url_template": "https://github.com/trending"},
            "operator": {"type": "navigate", "execution_strategy": "primitive_action"},
            "outputs": {"blackboard_key": None, "schema": None},
            "validation": {"must": []},
            "runtime_policy": {"requires_runtime_ai": False, "runtime_ai_reason": ""},
        }

        contract = parse_step_contract_response(
            response,
            fallback_goal=(
                "打开 https://github.com/trending\n\n"
                "Previous planner/compiler failure:\n"
                "strict mode violation"
            ),
        )

        self.assertEqual(contract.description, "打开 https://github.com/trending")
        self.assertEqual(contract.intent.goal, "打开 https://github.com/trending")

    def test_parses_planner_envelope_need_user_without_current_step(self):
        envelope = parse_planner_envelope_response(
            {"status": "need_user", "message": "请手动点击 Pull requests"}
        )

        self.assertEqual(envelope.status.value, "need_user")
        self.assertIsNone(envelope.current_step)
        self.assertEqual(envelope.message, "请手动点击 Pull requests")


if __name__ == "__main__":
    unittest.main()
