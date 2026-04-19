import json
import shutil
import unittest
from pathlib import Path

from backend.rpa.contract_models import ArtifactKind, ExecutionStrategy, RuntimePolicy, StepContract
from backend.rpa.contract_pipeline import CommittedStep
from backend.rpa.contract_skill_builder import build_contract_skill_files, write_contract_skill
from backend.rpa.contract_validator import validate_replay_export


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


class ContractSkillBuilderTests(unittest.TestCase):
    def test_writes_skill_contract_json(self):
        step = CommittedStep(
            contract=_contract(ExecutionStrategy.PRIMITIVE_ACTION, "navigate"),
            artifact={"kind": ArtifactKind.PRIMITIVE_ACTION, "action": "goto", "target_url_template": "https://example.com"},
            validation_evidence={"url": "https://example.com"},
        )

        tmp = Path.cwd() / "RpaClaw" / "backend" / "tests" / "_tmp_contract_skill"
        if tmp.exists():
            shutil.rmtree(tmp)

        try:
            write_contract_skill(tmp, "test_skill", "desc", [step])

            self.assertTrue((tmp / "skill.contract.json").exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_skill_py_contains_committed_deterministic_artifact_code(self):
        step = CommittedStep(
            contract=_contract(
                ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "extract_repeated_records",
                outputs={"blackboard_key": "pr_list", "schema": {"type": "array"}},
                validation={"must": [{"type": "min_records", "key": "pr_list", "count": 1}]},
            ),
            artifact={
                "kind": ArtifactKind.DETERMINISTIC_SCRIPT,
                "result_key": "pr_list",
                "code": "async def run(page, board):\n    return [{'title': 'Fix'}]",
            },
            validation_evidence={"records": 1},
        )

        files = build_contract_skill_files("test_skill", "desc", [step])

        self.assertIn("async def run(page, board):", files["skill.py"])
        self.assertIn("board.write('pr_list'", files["skill.py"])
        self.assertIn("_validate_contract_output('step_1'", files["skill.py"])
        self.assertIn("'min_records'", files["skill.py"])

    def test_exported_script_resolves_blackboard_refs_dynamically(self):
        step = CommittedStep(
            contract=_contract(
                ExecutionStrategy.PRIMITIVE_ACTION,
                "navigate",
                inputs={"refs": ["selected_project.url"]},
                target={"type": "url", "url_template": "{selected_project.url}/pulls"},
            ),
            artifact={
                "kind": ArtifactKind.PRIMITIVE_ACTION,
                "action": "goto",
                "target_url_template": "{selected_project.url}/pulls",
            },
            validation_evidence={"url": "https://github.com/a/b/pulls"},
        )

        files = build_contract_skill_files("test_skill", "desc", [step])

        self.assertIn("resolve_template('{selected_project.url}/pulls', board)", files["skill.py"])
        self.assertNotIn("https://github.com/a/b/pulls", files["skill.py"])

    def test_exported_script_does_not_regenerate_from_description(self):
        step = CommittedStep(
            contract=_contract(ExecutionStrategy.DETERMINISTIC_SCRIPT, "extract_repeated_records", description="Extract PRs"),
            artifact={
                "kind": ArtifactKind.DETERMINISTIC_SCRIPT,
                "result_key": "items",
                "code": "async def run(page, board):\n    return []",
            },
            validation_evidence={},
        )

        files = build_contract_skill_files("test_skill", "desc", [step])

        self.assertNotIn("get_llm_model", files["skill.py"])
        self.assertNotIn("Extract PRs", files["skill.py"])

    def test_runtime_ai_act_step_exports_act_mode_and_preserves_runtime_blackboard_value(self):
        contract = _contract(
            ExecutionStrategy.RUNTIME_AI,
            "semantic_select",
            target={"type": "page"},
            outputs={
                "blackboard_key": "selected_python_project",
                "schema": {"type": "object", "required": ["url"]},
            },
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="Semantic relevance must be evaluated at runtime",
                allow_side_effect=True,
                side_effect_reason="The selected project must be opened",
            ),
        )
        step = CommittedStep(
            contract=contract,
            artifact={
                "kind": ArtifactKind.RUNTIME_AI,
                "prompt": "Open the project most related to Python and return name/url/reason.",
                "output_mode": "act",
                "output_schema": {"type": "object", "required": ["url"]},
                "result_key": "selected_python_project",
                "allow_side_effect": True,
            },
            validation_evidence={},
        )

        files = build_contract_skill_files("test_skill", "desc", [step])

        self.assertIn('"mode": "act"', files["skill.py"])
        self.assertIn("_result.get('success') is False", files["skill.py"])
        self.assertIn("if 'selected_python_project' not in board.values:", files["skill.py"])
        self.assertIn("_result.get('output') not in (None, '')", files["skill.py"])
        self.assertIn("execute_ai_instruction(current_page, step=_runtime_step, results=board.values)", files["skill.py"])

    def test_manifest_passes_replay_validation_with_committed_steps(self):
        contract = _contract(
            ExecutionStrategy.PRIMITIVE_ACTION,
            "navigate",
            inputs={"refs": ["selected_project.url"]},
            target={"type": "url", "url_template": "{selected_project.url}/pulls"},
        )
        step = CommittedStep(
            contract=contract,
            artifact={
                "kind": ArtifactKind.PRIMITIVE_ACTION,
                "action": "goto",
                "target_url_template": "{selected_project.url}/pulls",
            },
            validation_evidence={},
        )

        files = build_contract_skill_files("test_skill", "desc", [step])
        manifest = json.loads(files["skill.contract.json"])
        result = validate_replay_export([{"contract": contract, "artifact": step.artifact}], manifest)

        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
