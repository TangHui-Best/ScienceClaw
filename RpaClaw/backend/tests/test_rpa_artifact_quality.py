import unittest

from backend.rpa.artifact_quality import validate_artifact_quality
from backend.rpa.contract_models import ArtifactKind, ExecutionStrategy, RuntimePolicy, StepContract


def _contract(strategy: ExecutionStrategy, **overrides):
    payload = {
        "id": "step_1",
        "description": "Test step",
        "intent": {"goal": "test"},
        "target": {"type": "page"},
        "operator": {"type": "noop", "execution_strategy": strategy},
        "outputs": {"blackboard_key": None, "schema": None},
        "validation": {"must": []},
        "runtime_policy": RuntimePolicy(requires_runtime_ai=False),
    }
    payload.update(overrides)
    return StepContract(**payload)


class ArtifactQualityTests(unittest.TestCase):
    def test_rejects_broad_href_click_locator(self):
        contract = _contract(ExecutionStrategy.PRIMITIVE_ACTION)
        result = validate_artifact_quality(
            contract,
            {
                "kind": ArtifactKind.PRIMITIVE_ACTION,
                "action": "click",
                "locator": {"method": "css", "value": 'a[href*="owner/repo"]'},
            },
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, "unstable_locator")

    def test_rejects_invalid_python_script(self):
        contract = _contract(ExecutionStrategy.DETERMINISTIC_SCRIPT)
        result = validate_artifact_quality(
            contract,
            {"kind": ArtifactKind.DETERMINISTIC_SCRIPT, "code": "async def run(page):\n  return ["},
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, "invalid_python")

    def test_rejects_deterministic_script_that_calls_llm(self):
        contract = _contract(ExecutionStrategy.DETERMINISTIC_SCRIPT)
        result = validate_artifact_quality(
            contract,
            {
                "kind": ArtifactKind.DETERMINISTIC_SCRIPT,
                "code": "async def run(page):\n    return await get_llm_model().ainvoke('x')",
            },
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, "llm_call_in_deterministic_script")

    def test_rejects_runtime_ai_without_structured_blackboard_output(self):
        contract = _contract(
            ExecutionStrategy.RUNTIME_AI,
            outputs={"blackboard_key": "selected_project", "schema": {"type": "object"}},
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="Semantic relevance is required",
            ),
        )

        result = validate_artifact_quality(
            contract,
            {
                "kind": ArtifactKind.RUNTIME_AI,
                "prompt": "Pick the most relevant project",
                "output_schema": None,
            },
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, "missing_structured_runtime_ai_output")

    def test_accepts_valid_deterministic_script(self):
        contract = _contract(ExecutionStrategy.DETERMINISTIC_SCRIPT)
        result = validate_artifact_quality(
            contract,
            {
                "kind": ArtifactKind.DETERMINISTIC_SCRIPT,
                "code": "async def run(page, board):\n    return {'items': []}",
            },
        )

        self.assertTrue(result.passed)
        self.assertIsNone(result.failure_type)


if __name__ == "__main__":
    unittest.main()
