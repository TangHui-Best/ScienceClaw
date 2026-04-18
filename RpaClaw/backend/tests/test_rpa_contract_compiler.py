import unittest

from backend.rpa.contract_compiler import ContractCompiler
from backend.rpa.contract_models import ArtifactKind, ExecutionStrategy, RuntimePolicy, StepContract


def _contract(strategy: ExecutionStrategy, operator_type: str, **overrides):
    payload = {
        "id": "step_1",
        "description": "Test step",
        "intent": {"goal": "test"},
        "target": {"type": "page"},
        "operator": {"type": operator_type, "execution_strategy": strategy},
        "outputs": {"blackboard_key": None, "schema": None},
        "validation": {"must": []},
        "runtime_policy": RuntimePolicy(requires_runtime_ai=False),
    }
    payload.update(overrides)
    return StepContract(**payload)


class ContractCompilerTests(unittest.TestCase):
    def test_compiles_primitive_navigate_with_blackboard_template(self):
        compiler = ContractCompiler()
        contract = _contract(
            ExecutionStrategy.PRIMITIVE_ACTION,
            "navigate",
            target={"type": "url", "url_template": "{selected_project.url}/pulls"},
            inputs={"refs": ["selected_project.url"]},
            validation={"must": [{"type": "url_contains", "value": "/pulls"}]},
        )

        artifact = compiler.compile(contract)

        self.assertEqual(artifact["kind"], ArtifactKind.PRIMITIVE_ACTION)
        self.assertEqual(artifact["action"], "goto")
        self.assertEqual(artifact["target_url_template"], "{selected_project.url}/pulls")
        self.assertEqual(artifact["input_refs"], ["selected_project.url"])

    def test_compiles_deterministic_numeric_ranking_script(self):
        compiler = ContractCompiler()
        contract = _contract(
            ExecutionStrategy.DETERMINISTIC_SCRIPT,
            "rank_collection_numeric_max",
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
        )

        artifact = compiler.compile(contract)

        self.assertEqual(artifact["kind"], ArtifactKind.DETERMINISTIC_SCRIPT)
        self.assertEqual(artifact["result_key"], "selected_project")
        self.assertIn("async def run(page, board):", artifact["code"])
        self.assertIn("collection_selector = 'article.Box-row'", artifact["code"])
        self.assertNotIn("get_llm_model", artifact["code"])

    def test_compiles_deterministic_repeated_record_extraction_script(self):
        compiler = ContractCompiler()
        contract = _contract(
            ExecutionStrategy.DETERMINISTIC_SCRIPT,
            "extract_repeated_records",
            target={"type": "visible_collection", "collection": "pull_requests"},
            operator={
                "type": "extract_repeated_records",
                "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "selection_rule": {
                    "row_selector": ".js-issue-row",
                    "limit": 10,
                    "fields": {
                        "title": {"selector": 'a[id^="issue_"]'},
                        "creator": {"selector": 'a[href*="author%3A"]'},
                    },
                },
            },
            outputs={
                "blackboard_key": "pr_list",
                "schema": {
                    "type": "array",
                    "items": {"required": ["title", "creator"]},
                },
            },
        )

        artifact = compiler.compile(contract)

        self.assertEqual(artifact["kind"], ArtifactKind.DETERMINISTIC_SCRIPT)
        self.assertEqual(artifact["result_key"], "pr_list")
        self.assertIn("row_selector = '.js-issue-row'", artifact["code"])
        self.assertIn("fields = {", artifact["code"])

    def test_compiles_runtime_semantic_select_with_structured_output(self):
        compiler = ContractCompiler()
        contract = _contract(
            ExecutionStrategy.RUNTIME_AI,
            "runtime_semantic_select",
            target={"type": "visible_collection", "collection": "github_trending_repositories"},
            outputs={
                "blackboard_key": "selected_project",
                "schema": {"type": "object", "required": ["url", "reason"]},
            },
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="Semantic relevance is required",
            ),
        )

        artifact = compiler.compile(contract)

        self.assertEqual(artifact["kind"], ArtifactKind.RUNTIME_AI)
        self.assertEqual(artifact["result_key"], "selected_project")
        self.assertEqual(artifact["output_schema"], {"type": "object", "required": ["url", "reason"]})
        self.assertFalse(artifact["allow_side_effect"])


if __name__ == "__main__":
    unittest.main()
