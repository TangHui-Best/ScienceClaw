import unittest

from backend.rpa.blackboard import Blackboard
from backend.rpa.contract_agent import RPAContractAgent
from backend.rpa.contract_executor import ExecutionResult
from backend.rpa.contract_models import ArtifactKind, ExecutionStrategy, RuntimePolicy, StepContract
from backend.rpa.contract_validator import ValidationResult


def _contract():
    return StepContract(
        id="step_1",
        description="Open page",
        intent={"goal": "open_page"},
        target={"type": "url", "url_template": "https://example.com"},
        operator={"type": "navigate", "execution_strategy": ExecutionStrategy.PRIMITIVE_ACTION},
        outputs={"blackboard_key": None, "schema": None},
        validation={"must": [{"type": "url_contains", "value": "example.com"}]},
        runtime_policy=RuntimePolicy(requires_runtime_ai=False),
    )


class ContractAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_step_event_contains_committed_contract_and_display_step(self):
        async def executor(contract, artifact, page, board):
            return ExecutionResult(success=True, evidence={"url": "https://example.com"})

        agent = RPAContractAgent(
            planner=lambda goal, snapshot, board: _contract(),
            compiler=lambda contract: {
                "kind": ArtifactKind.PRIMITIVE_ACTION,
                "action": "goto",
                "target_url_template": "https://example.com",
            },
            executor=executor,
            validator=lambda contract, artifact, result, board, snapshot: ValidationResult(
                passed=True,
                evidence={"url": "https://example.com"},
            ),
            snapshot_builder=lambda page: {"url": "about:blank", "title": ""},
        )

        events = [
            event
            async for event in agent.run(
                session_id="s1",
                page=object(),
                goal="open example",
                board=Blackboard(),
            )
        ]

        committed_event = next(event for event in events if event["event"] == "agent_contract_committed_steps")
        self.assertEqual(committed_event["data"]["contract_steps"][0]["contract"]["id"], "step_1")
        self.assertEqual(committed_event["data"]["display_steps"][0]["action"], "contract_step")

    async def test_failed_step_event_does_not_commit(self):
        agent = RPAContractAgent(
            planner=lambda goal, snapshot, board: _contract(),
            compiler=lambda contract: (_ for _ in ()).throw(ValueError("bad artifact")),
            executor=None,
            validator=None,
            snapshot_builder=lambda page: {"url": "about:blank", "title": ""},
        )

        events = [
            event
            async for event in agent.run(
                session_id="s1",
                page=object(),
                goal="open example",
                board=Blackboard(),
            )
        ]

        self.assertEqual(events[-1]["event"], "agent_aborted")
        self.assertIn("bad artifact", events[-1]["data"]["message"])


if __name__ == "__main__":
    unittest.main()
