import unittest

from backend.rpa.contract_models import ExecutionStrategy
from backend.rpa.contract_planner import (
    CONTRACT_PLANNER_SYSTEM_PROMPT,
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
            "description": "Open GitHub Trending page",
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

        contract = parse_step_contract_response(response)

        self.assertEqual(contract.id, "step_navigate_trending")
        self.assertEqual(contract.intent.goal, "Open GitHub Trending page")
        self.assertEqual(contract.target.type, "url")
        self.assertEqual(contract.operator.type, "navigate")
        self.assertEqual(contract.operator.execution_strategy.value, "primitive_action")
        self.assertEqual(contract.runtime_policy.runtime_ai_reason, "")


if __name__ == "__main__":
    unittest.main()
