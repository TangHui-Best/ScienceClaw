import unittest

from pydantic import ValidationError

from backend.rpa.contract_models import (
    ArtifactKind,
    ExecutionStrategy,
    FailureClass,
    RuntimePolicy,
    StepContract,
)


class ContractModelTests(unittest.TestCase):
    def test_step_contract_uses_six_core_blocks(self):
        contract = StepContract(
            id="step_1",
            description="Open selected repo PRs",
            intent={"goal": "open_selected_repo_prs", "business_object": "github_repository"},
            inputs={"refs": ["selected_project.url"], "params": {}},
            target={"type": "url", "url_template": "{selected_project.url}/pulls"},
            operator={"type": "navigate", "execution_strategy": ExecutionStrategy.PRIMITIVE_ACTION},
            outputs={"blackboard_key": None, "schema": None},
            validation={"must": [{"type": "url_contains", "value": "/pulls"}]},
            runtime_policy=RuntimePolicy(requires_runtime_ai=False),
        )

        self.assertEqual(contract.operator.execution_strategy, ExecutionStrategy.PRIMITIVE_ACTION)
        self.assertEqual(contract.inputs.refs, ["selected_project.url"])
        self.assertIn('"schema"', contract.model_dump_json(by_alias=True))

    def test_runtime_ai_requires_structured_output_contract(self):
        with self.assertRaises(ValidationError):
            StepContract(
                id="step_ai",
                description="Select semantic project",
                intent={"goal": "select_project"},
                inputs={"refs": [], "params": {"query": "SKILL"}},
                target={"type": "visible_collection", "collection": "github_trending_repositories"},
                operator={"type": "semantic_select", "execution_strategy": ExecutionStrategy.RUNTIME_AI},
                outputs={"blackboard_key": None, "schema": None},
                validation={"must": []},
                runtime_policy=RuntimePolicy(
                    requires_runtime_ai=True,
                    runtime_ai_reason="Semantic relevance is required",
                ),
            )

    def test_failure_class_is_small_routing_surface(self):
        self.assertEqual(FailureClass.ARTIFACT_FAILED.value, "artifact_failed")
        self.assertEqual(ArtifactKind.DETERMINISTIC_SCRIPT.value, "deterministic_script")


if __name__ == "__main__":
    unittest.main()
