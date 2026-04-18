import json
import unittest

from backend.rpa.contract_compiler import ContractCompiler
from backend.rpa.contract_models import ArtifactKind, ExecutionStrategy, RuntimePolicy, StepContract
from backend.rpa.contract_pipeline import CommittedStep
from backend.rpa.contract_skill_builder import build_contract_skill_files
from backend.rpa.contract_validator import validate_replay_export


def _contract(strategy: ExecutionStrategy, operator_type: str, **overrides):
    payload = {
        "id": overrides.pop("id", "step_1"),
        "description": overrides.pop("description", "Test step"),
        "intent": {"goal": "test"},
        "target": {"type": "page"},
        "operator": {"type": operator_type, "execution_strategy": strategy},
        "outputs": {"blackboard_key": None, "schema": None},
        "validation": {"must": []},
        "runtime_policy": RuntimePolicy(requires_runtime_ai=False),
    }
    payload.update(overrides)
    return StepContract(**payload)


class ContractFullScenarioTests(unittest.TestCase):
    def test_github_trending_max_star_flow_exports_no_runtime_ai_call(self):
        compiler = ContractCompiler()
        contracts = [
            _contract(
                ExecutionStrategy.PRIMITIVE_ACTION,
                "navigate",
                id="open_trending",
                target={"type": "url", "url_template": "https://github.com/trending"},
            ),
            _contract(
                ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "rank_collection_numeric_max",
                id="select_top_repo",
                target={"type": "visible_collection", "collection": "github_trending_repositories"},
                operator={
                    "type": "rank_collection_numeric_max",
                    "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                    "selection_rule": {
                        "collection_selector": "article.Box-row",
                        "value_selector": 'a[href*="/stargazers"]',
                        "link_selector": "h2 a",
                        "url_prefix": "https://github.com",
                    },
                },
                outputs={
                    "blackboard_key": "selected_project",
                    "schema": {"type": "object", "required": ["url"]},
                },
            ),
            _contract(
                ExecutionStrategy.PRIMITIVE_ACTION,
                "navigate",
                id="open_prs",
                inputs={"refs": ["selected_project.url"]},
                target={"type": "url", "url_template": "{selected_project.url}/pulls"},
            ),
        ]
        steps = [
            CommittedStep(contract=contract, artifact=compiler.compile(contract), validation_evidence={})
            for contract in contracts
        ]

        files = build_contract_skill_files("github_trending_prs", "desc", steps)
        manifest = json.loads(files["skill.contract.json"])

        self.assertNotIn("execute_ai_instruction", files["skill.py"])
        self.assertTrue(validate_replay_export([{"contract": s.contract, "artifact": s.artifact} for s in steps], manifest).passed)

    def test_semantic_project_selection_feeds_following_pr_navigation(self):
        compiler = ContractCompiler()
        semantic_contract = _contract(
            ExecutionStrategy.RUNTIME_AI,
            "runtime_semantic_select",
            id="select_skill_project",
            description="Select the GitHub trending project most related to SKILL",
            target={"type": "visible_collection", "collection": "github_trending_repositories"},
            outputs={
                "blackboard_key": "selected_project",
                "schema": {"type": "object", "required": ["url", "reason"]},
            },
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="Requires semantic relevance judgment at execution time",
            ),
        )
        nav_contract = _contract(
            ExecutionStrategy.PRIMITIVE_ACTION,
            "navigate",
            id="open_selected_prs",
            inputs={"refs": ["selected_project.url"]},
            target={"type": "url", "url_template": "{selected_project.url}/pulls"},
        )
        steps = [
            CommittedStep(contract=semantic_contract, artifact=compiler.compile(semantic_contract), validation_evidence={}),
            CommittedStep(contract=nav_contract, artifact=compiler.compile(nav_contract), validation_evidence={}),
        ]

        files = build_contract_skill_files("semantic_prs", "desc", steps)
        manifest = json.loads(files["skill.contract.json"])

        self.assertEqual(manifest["steps"][0]["artifact"]["kind"], "runtime_ai")
        self.assertEqual(manifest["steps"][0]["artifact"]["result_key"], "selected_project")
        self.assertIn("resolve_template('{selected_project.url}/pulls', board)", files["skill.py"])

    def test_cross_page_extraction_and_fill_dataflow_is_preserved(self):
        compiler = ContractCompiler()
        extract_contract = _contract(
            ExecutionStrategy.PRIMITIVE_ACTION,
            "extract_text",
            id="extract_name",
            target={"type": "locator", "locator": {"method": "css", "value": "#customer-name"}},
            outputs={"blackboard_key": "customer_name", "schema": {"type": "string"}},
        )
        fill_contract = _contract(
            ExecutionStrategy.PRIMITIVE_ACTION,
            "fill",
            id="fill_name",
            inputs={"refs": ["customer_name"]},
            target={"type": "locator", "locator": {"method": "css", "value": "#name"}},
        )
        extract_artifact = compiler.compile(extract_contract)
        extract_artifact["result_key"] = "customer_name"
        fill_artifact = compiler.compile(fill_contract)
        fill_artifact["value_template"] = "{customer_name}"
        steps = [
            CommittedStep(contract=extract_contract, artifact=extract_artifact, validation_evidence={}),
            CommittedStep(contract=fill_contract, artifact=fill_artifact, validation_evidence={}),
        ]

        files = build_contract_skill_files("cross_page_fill", "desc", steps)
        manifest = json.loads(files["skill.contract.json"])

        self.assertIn("board.write('customer_name'", files["skill.py"])
        self.assertIn("resolve_template('{customer_name}', board)", files["skill.py"])
        self.assertEqual(manifest["steps"][1]["input_refs"], ["customer_name"])


if __name__ == "__main__":
    unittest.main()
