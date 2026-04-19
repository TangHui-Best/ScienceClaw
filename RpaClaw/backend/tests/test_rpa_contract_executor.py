import unittest

from backend.rpa.blackboard import Blackboard
from backend.rpa.contract_executor import ContractExecutor, ExecutionError
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


class FakePage:
    def __init__(self):
        self.goto_calls = []

    async def goto(self, url, wait_until=None):
        self.goto_calls.append((url, wait_until))

    async def wait_for_load_state(self, state):
        return None


class ContractExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_primitive_navigate_resolves_blackboard_template(self):
        page = FakePage()
        board = Blackboard(values={"selected_project": {"url": "https://github.com/a/b"}})
        contract = _contract(
            ExecutionStrategy.PRIMITIVE_ACTION,
            "navigate",
            target={"type": "url", "url_template": "{selected_project.url}/pulls"},
            inputs={"refs": ["selected_project.url"]},
        )
        artifact = {
            "kind": ArtifactKind.PRIMITIVE_ACTION,
            "action": "goto",
            "target_url_template": "{selected_project.url}/pulls",
        }

        result = await ContractExecutor().execute(contract, artifact, page, board)

        self.assertTrue(result.success)
        self.assertEqual(page.goto_calls[0][0], "https://github.com/a/b/pulls")

    async def test_deterministic_script_writes_blackboard_output(self):
        page = FakePage()
        board = Blackboard()
        contract = _contract(
            ExecutionStrategy.DETERMINISTIC_SCRIPT,
            "extract_repeated_records",
            operator={
                "type": "extract_repeated_records",
                "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "selection_rule": {
                    "row_selector": ".js-issue-row",
                    "fields": {"title": {"selector": "a[id^='issue_']"}},
                },
            },
            outputs={"blackboard_key": "pr_list", "schema": {"type": "array"}},
        )
        artifact = {
            "kind": ArtifactKind.DETERMINISTIC_SCRIPT,
            "result_key": "pr_list",
            "code": "async def run(page, board):\n    return [{'title': 'Fix', 'creator': 'alice'}]",
        }

        result = await ContractExecutor().execute(contract, artifact, page, board)

        self.assertTrue(result.success)
        self.assertEqual(board.resolve_ref("pr_list.0.title"), "Fix")

    async def test_runtime_ai_result_is_schema_validated_and_written(self):
        async def fake_runtime_ai(page, contract, artifact, board):
            return {"url": "https://github.com/a/b", "reason": "semantic match"}

        board = Blackboard()
        contract = _contract(
            ExecutionStrategy.RUNTIME_AI,
            "runtime_semantic_select",
            outputs={
                "blackboard_key": "selected_project",
                "schema": {"type": "object", "required": ["url", "reason"]},
            },
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="Semantic relevance is required",
            ),
        )
        artifact = {
            "kind": ArtifactKind.RUNTIME_AI,
            "result_key": "selected_project",
            "output_schema": {"type": "object", "required": ["url", "reason"]},
            "allow_side_effect": False,
        }

        result = await ContractExecutor(runtime_ai_executor=fake_runtime_ai).execute(
            contract,
            artifact,
            FakePage(),
            board,
        )

        self.assertTrue(result.success)
        self.assertEqual(board.resolve_ref("selected_project.reason"), "semantic match")

    async def test_runtime_ai_prefers_blackboard_value_when_return_value_is_only_text(self):
        async def fake_runtime_ai(page, contract, artifact, board):
            board.write(
                "selected_project",
                {"url": "https://github.com/a/b", "reason": "semantic match"},
            )
            return "semantic match"

        board = Blackboard()
        contract = _contract(
            ExecutionStrategy.RUNTIME_AI,
            "runtime_semantic_select",
            outputs={
                "blackboard_key": "selected_project",
                "schema": {"type": "object", "required": ["url", "reason"]},
            },
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="Semantic relevance is required",
            ),
        )
        artifact = {
            "kind": ArtifactKind.RUNTIME_AI,
            "result_key": "selected_project",
            "output_schema": {"type": "object", "required": ["url", "reason"]},
            "allow_side_effect": False,
        }

        result = await ContractExecutor(runtime_ai_executor=fake_runtime_ai).execute(
            contract,
            artifact,
            FakePage(),
            board,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.output["url"], "https://github.com/a/b")

    async def test_runtime_ai_direct_side_effect_is_rejected_unless_allowed(self):
        async def fake_runtime_ai(page, contract, artifact, board):
            return {"url": "https://github.com/a/b", "action_performed": True}

        contract = _contract(
            ExecutionStrategy.RUNTIME_AI,
            "runtime_semantic_select",
            outputs={
                "blackboard_key": "selected_project",
                "schema": {"type": "object", "required": ["url"]},
            },
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="Semantic relevance is required",
                allow_side_effect=False,
            ),
        )
        artifact = {
            "kind": ArtifactKind.RUNTIME_AI,
            "result_key": "selected_project",
            "output_schema": {"type": "object", "required": ["url"]},
            "allow_side_effect": False,
        }

        with self.assertRaises(ExecutionError):
            await ContractExecutor(runtime_ai_executor=fake_runtime_ai).execute(
                contract,
                artifact,
                FakePage(),
                Blackboard(),
            )


if __name__ == "__main__":
    unittest.main()
