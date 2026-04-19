import unittest

from backend.rpa.blackboard import Blackboard
from backend.rpa.contract_executor import ExecutionResult
from backend.rpa.contract_models import ArtifactKind, ExecutionStrategy, RuntimePolicy, StepContract
from backend.rpa.contract_validator import validate_recording_step, validate_replay_export


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
    if strategy == ExecutionStrategy.DETERMINISTIC_SCRIPT:
        payload["outputs"] = {"blackboard_key": "items", "schema": {"type": "array"}}
        if operator_type == "extract_repeated_records":
            payload["operator"] = {
                "type": operator_type,
                "execution_strategy": strategy,
                "selection_rule": {
                    "row_selector": "div.row",
                    "fields": {"title": {"selector": "a.title"}},
                },
            }
    payload.update(overrides)
    return StepContract(**payload)


class ContractValidatorTests(unittest.TestCase):
    def test_empty_record_array_fails_min_records_validation(self):
        contract = _contract(
            ExecutionStrategy.DETERMINISTIC_SCRIPT,
            "extract_repeated_records",
            outputs={"blackboard_key": "pr_list", "schema": {"type": "array"}},
            validation={"must": [{"type": "min_records", "key": "pr_list", "count": 1}]},
        )
        board = Blackboard(values={"pr_list": []})

        result = validate_recording_step(
            contract,
            {"kind": ArtifactKind.DETERMINISTIC_SCRIPT, "code": "async def run(page, board): return []"},
            ExecutionResult(success=True, output=[]),
            board,
            snapshot=None,
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, "min_records")

    def test_generic_navigation_menu_text_fails_validation(self):
        contract = _contract(
            ExecutionStrategy.PRIMITIVE_ACTION,
            "extract_text",
            outputs={"blackboard_key": "summary", "schema": {"type": "string"}},
            validation={"must": [{"type": "not_generic_chrome_text", "key": "summary"}]},
        )
        board = Blackboard(values={"summary": "Navigation Menu"})

        result = validate_recording_step(
            contract,
            {"kind": ArtifactKind.PRIMITIVE_ACTION, "action": "extract_text"},
            ExecutionResult(success=True, output="Navigation Menu"),
            board,
            snapshot=None,
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, "not_generic_chrome_text")

    def test_url_contains_validation_succeeds_from_execution_evidence(self):
        contract = _contract(
            ExecutionStrategy.PRIMITIVE_ACTION,
            "navigate",
            validation={"must": [{"type": "url_contains", "value": "/pulls"}]},
        )

        result = validate_recording_step(
            contract,
            {"kind": ArtifactKind.PRIMITIVE_ACTION, "action": "goto"},
            ExecutionResult(success=True, evidence={"url": "https://github.com/a/b/pulls"}),
            Blackboard(),
            snapshot=None,
        )

        self.assertTrue(result.passed)

    def test_blackboard_key_validation_succeeds(self):
        contract = _contract(
            ExecutionStrategy.RUNTIME_AI,
            "runtime_semantic_select",
            outputs={
                "blackboard_key": "selected_project",
                "schema": {"type": "object", "required": ["url"]},
            },
            validation={"must": [{"type": "blackboard_key", "key": "selected_project.url"}]},
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="Semantic relevance is required",
            ),
        )

        result = validate_recording_step(
            contract,
            {"kind": ArtifactKind.RUNTIME_AI, "output_schema": {"type": "object"}},
            ExecutionResult(success=True),
            Blackboard(values={"selected_project": {"url": "https://github.com/a/b"}}),
            snapshot=None,
        )

        self.assertTrue(result.passed)

    def test_validation_accepts_live_planner_aliases(self):
        contract = _contract(
            ExecutionStrategy.RUNTIME_AI,
            "runtime_semantic_select",
            outputs={
                "blackboard_key": "selected_project",
                "schema": {"type": "object", "required": ["url"]},
            },
            validation={
                "must": [
                    {"type": "key_present", "key": "selected_project.url"},
                    {"type": "url_matches", "pattern": "/pulls"},
                ]
            },
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="Semantic relevance is required",
            ),
        )

        result = validate_recording_step(
            contract,
            {"kind": ArtifactKind.RUNTIME_AI, "output_schema": {"type": "object"}},
            ExecutionResult(success=True, evidence={"url": "https://github.com/a/b/pulls"}),
            Blackboard(values={"selected_project": {"url": "https://github.com/a/b"}}),
            snapshot=None,
        )

        self.assertTrue(result.passed)

    def test_validation_aliases_fail_when_not_satisfied(self):
        contract = _contract(
            ExecutionStrategy.PRIMITIVE_ACTION,
            "navigate",
            validation={
                "must": [
                    {"type": "key_present", "key": "selected_project.url"},
                    {"type": "url_matches", "pattern": "/pulls"},
                ]
            },
        )

        result = validate_recording_step(
            contract,
            {"kind": ArtifactKind.PRIMITIVE_ACTION, "action": "goto"},
            ExecutionResult(success=True, evidence={"url": "https://github.com/a/b"}),
            Blackboard(values={"selected_project": {}}),
            snapshot=None,
        )

        self.assertFalse(result.passed)
        self.assertIn(result.failure_type, {"key_present", "url_matches"})

    def test_replay_validation_catches_missing_input_refs(self):
        contract = _contract(
            ExecutionStrategy.PRIMITIVE_ACTION,
            "navigate",
            inputs={"refs": ["selected_project.url"]},
            target={"type": "url", "url_template": "{selected_project.url}/pulls"},
        )
        result = validate_replay_export(
            committed_steps=[{"contract": contract, "artifact": {"kind": ArtifactKind.PRIMITIVE_ACTION}}],
            exported_manifest={"steps": [{"contract_id": "step_1", "artifact": {"kind": "primitive_action"}}], "blackboard_schema": {}},
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, "missing_input_ref")

    def test_replay_validation_catches_description_only_artifact(self):
        contract = _contract(ExecutionStrategy.DETERMINISTIC_SCRIPT, "extract_repeated_records")

        result = validate_replay_export(
            committed_steps=[{"contract": contract, "artifact": {"kind": ArtifactKind.DETERMINISTIC_SCRIPT}}],
            exported_manifest={
                "steps": [
                    {
                        "contract_id": "step_1",
                        "artifact": {"kind": "deterministic_script", "description": "Extract records"},
                    }
                ],
                "blackboard_schema": {},
            },
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, "description_only_artifact")


if __name__ == "__main__":
    unittest.main()
