import unittest

from backend.rpa.blackboard import Blackboard
from backend.rpa.contract_agent import RPAContractAgent
from backend.rpa.contract_executor import ExecutionResult
from backend.rpa.contract_models import (
    ArtifactKind,
    ExecutionStrategy,
    PlannerEnvelope,
    PlannerStatus,
    RuntimePolicy,
    StepContract,
)
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
        planner_calls = []

        async def planner(goal, snapshot, board):
            planner_calls.append(snapshot["url"])
            if len(planner_calls) == 1:
                return PlannerEnvelope(status=PlannerStatus.NEXT_STEP, current_step=_contract())
            return PlannerEnvelope(status=PlannerStatus.DONE, message="instruction complete")

        async def executor(contract, artifact, page, board):
            return ExecutionResult(success=True, evidence={"url": "https://example.com"})

        agent = RPAContractAgent(
            planner=planner,
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
        thought_event = next(event for event in events if event["event"] == "agent_thought")
        action_event = next(event for event in events if event["event"] == "agent_action")
        step_done_event = next(event for event in events if event["event"] == "agent_step_done")
        self.assertEqual(committed_event["data"]["contract_steps"][0]["contract"]["id"], "step_1")
        self.assertEqual(committed_event["data"]["display_steps"][0]["action"], "contract_step")
        self.assertEqual(thought_event["data"]["contract_id"], "step_1")
        self.assertEqual(action_event["data"]["description"], "Open page")
        self.assertEqual(step_done_event["data"]["step_count"], 1)
        self.assertEqual(events[-1]["event"], "agent_done")
        self.assertEqual(events[-1]["data"]["step_count"], 1)
        self.assertEqual(events[-1]["data"]["total_steps"], 1)
        self.assertEqual(planner_calls, ["about:blank", "about:blank"])

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
        self.assertIsNotNone(events[-1]["data"]["attempt"])
        self.assertEqual(events[-1]["data"]["attempt"]["contract"]["id"], "step_1")

    async def test_replans_once_after_invalid_contract_feedback(self):
        planner_calls = []

        async def planner(goal, snapshot, board):
            planner_calls.append(goal)
            if len(planner_calls) == 1:
                raise ValueError("unsupported deterministic operator: extract_and_parse")
            if len(planner_calls) == 2:
                return PlannerEnvelope(status=PlannerStatus.NEXT_STEP, current_step=_contract())
            return PlannerEnvelope(status=PlannerStatus.DONE, message="instruction complete")

        agent = RPAContractAgent(
            planner=planner,
            compiler=lambda contract: {
                "kind": ArtifactKind.PRIMITIVE_ACTION,
                "action": "goto",
                "target_url_template": "https://example.com",
            },
            executor=lambda contract, artifact, page, board: ExecutionResult(
                success=True,
                evidence={"url": "https://example.com"},
            ),
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

        self.assertEqual(events[-1]["event"], "agent_done")
        self.assertTrue(any(event["event"] == "agent_contract_committed_steps" for event in events))
        self.assertEqual(len(planner_calls), 3)
        self.assertIn("Previous planner/compiler failure", planner_calls[1])

    async def test_replans_once_after_repairable_execution_failure(self):
        planner_calls = []

        runtime_ai_contract = StepContract(
            id="step_ai",
            description="Classify repos",
            intent={"goal": "Classify extracted repos using semantic reasoning"},
            inputs={"refs": ["trending_repos"]},
            target={"type": "blackboard_ref"},
            operator={"type": "semantic_filter", "execution_strategy": ExecutionStrategy.RUNTIME_AI},
            outputs={
                "blackboard_key": "skill_repos",
                "schema": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["name", "url"],
                    },
                },
            },
            validation={"must": []},
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="Semantic filtering requires runtime meaning",
            ),
        )

        async def planner(goal, snapshot, board):
            planner_calls.append(goal)
            if len(planner_calls) == 1:
                return PlannerEnvelope(status=PlannerStatus.NEXT_STEP, current_step=runtime_ai_contract)
            if len(planner_calls) == 2:
                return PlannerEnvelope(status=PlannerStatus.NEXT_STEP, current_step=_contract())
            return PlannerEnvelope(status=PlannerStatus.DONE, message="instruction complete")

        execution_attempts = {"count": 0}

        async def executor(contract, artifact, page, board):
            execution_attempts["count"] += 1
            if execution_attempts["count"] == 1:
                raise RuntimeError("output does not match array schema")
            return ExecutionResult(success=True, evidence={"url": "https://example.com"})

        agent = RPAContractAgent(
            planner=planner,
            compiler=lambda contract: {
                "kind": ArtifactKind.RUNTIME_AI
                if contract.operator.execution_strategy == ExecutionStrategy.RUNTIME_AI
                else ArtifactKind.PRIMITIVE_ACTION,
                "action": "goto",
                "target_url_template": "https://example.com",
                "output_schema": {"type": "array", "items": {"type": "object", "required": ["name", "url"]}},
                "result_key": "skill_repos",
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
                board=Blackboard(values={"trending_repos": [{"name": "repo", "url": "https://example.com"}]}),
            )
        ]

        self.assertEqual(events[-1]["event"], "agent_done")
        self.assertTrue(any(event["event"] == "agent_contract_committed_steps" for event in events))
        self.assertEqual(len(planner_calls), 3)
        self.assertIn("Previous step execution failed", planner_calls[1])
        self.assertIn("output does not match array schema", planner_calls[1])

    async def test_replans_once_after_repairable_locator_strict_mode_failure(self):
        planner_calls = []

        click_contract = StepContract(
            id="click_pull_requests_tab",
            description="Click Pull requests tab",
            intent={"goal": "Click Pull requests"},
            target={"type": "locator", "locator": {"method": "text", "value": "Pull requests"}},
            operator={"type": "click", "execution_strategy": ExecutionStrategy.PRIMITIVE_ACTION},
            outputs={"blackboard_key": None, "schema": None},
            validation={"must": []},
            runtime_policy=RuntimePolicy(requires_runtime_ai=False),
        )

        async def planner(goal, snapshot, board):
            planner_calls.append(goal)
            if len(planner_calls) == 1:
                return PlannerEnvelope(status=PlannerStatus.NEXT_STEP, current_step=click_contract)
            if len(planner_calls) == 2:
                return PlannerEnvelope(status=PlannerStatus.NEXT_STEP, current_step=_contract())
            return PlannerEnvelope(status=PlannerStatus.DONE, message="instruction complete")

        execution_attempts = {"count": 0}

        async def executor(contract, artifact, page, board):
            execution_attempts["count"] += 1
            if execution_attempts["count"] == 1:
                raise RuntimeError(
                    "Locator.click: Error: strict mode violation: get_by_text(\"Pull requests\") resolved to 3 elements"
                )
            return ExecutionResult(success=True, evidence={"url": "https://example.com"})

        agent = RPAContractAgent(
            planner=planner,
            compiler=lambda contract: {
                "kind": ArtifactKind.PRIMITIVE_ACTION,
                "action": "click" if contract.id == "click_pull_requests_tab" else "goto",
                "target_url_template": "https://example.com",
                "locator": {"method": "text", "value": "Pull requests"},
            },
            executor=executor,
            validator=lambda contract, artifact, result, board, snapshot: ValidationResult(
                passed=True,
                evidence={"url": "https://example.com"},
            ),
            snapshot_builder=lambda page: {"url": "https://github.com/example/repo", "title": "Repo"},
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

        self.assertEqual(events[-1]["event"], "agent_done")
        self.assertEqual(len(planner_calls), 3)
        self.assertIn("strict mode violation", planner_calls[1])

    async def test_need_user_event_stops_without_committing(self):
        agent = RPAContractAgent(
            planner=lambda goal, snapshot, board: PlannerEnvelope(
                status=PlannerStatus.NEED_USER,
                message="请手动点击 Pull requests",
            ),
            compiler=lambda contract: {
                "kind": ArtifactKind.PRIMITIVE_ACTION,
                "action": "goto",
                "target_url_template": "https://example.com",
            },
            executor=lambda contract, artifact, page, board: ExecutionResult(success=True),
            validator=lambda contract, artifact, result, board, snapshot: ValidationResult(passed=True),
            snapshot_builder=lambda page: {"url": "about:blank", "title": ""},
        )

        events = [
            event
            async for event in agent.run(
                session_id="s1",
                page=object(),
                goal="open two pages",
                board=Blackboard(),
            )
        ]

        self.assertEqual(events[-1]["event"], "agent_need_user")
        self.assertEqual(events[-1]["data"]["message"], "请手动点击 Pull requests")
        self.assertFalse(any(event["event"] == "agent_contract_committed_steps" for event in events))

    async def test_committed_events_replace_duplicate_output_key_with_latest_step(self):
        first = StepContract(
            id="extract_pr_list_attempt_1",
            description="Extract PR list",
            intent={"goal": "extract_prs"},
            target={"type": "page"},
            operator={
                "type": "extract_repeated_records",
                "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "selection_rule": {
                    "row_selector": "div.row",
                    "fields": {"title": {"selector": "a.title"}},
                },
            },
            outputs={"blackboard_key": "pr_list", "schema": {"type": "array"}},
            validation={"must": []},
            runtime_policy=RuntimePolicy(requires_runtime_ai=False),
        )
        second = first.model_copy(update={"id": "extract_pr_list_attempt_2"}, deep=True)
        calls = {"count": 0}

        async def planner(goal, snapshot, board):
            calls["count"] += 1
            if calls["count"] == 1:
                return PlannerEnvelope(status=PlannerStatus.NEXT_STEP, current_step=first)
            if calls["count"] == 2:
                return PlannerEnvelope(status=PlannerStatus.NEXT_STEP, current_step=second)
            return PlannerEnvelope(status=PlannerStatus.DONE, message="instruction complete")

        async def executor(contract, artifact, page, board):
            records = [{"title": contract.id}]
            board.write("pr_list", records, schema={"type": "array"})
            return ExecutionResult(success=True, output=records, evidence={"result_key": "pr_list"})

        agent = RPAContractAgent(
            planner=planner,
            compiler=lambda contract: {
                "kind": ArtifactKind.DETERMINISTIC_SCRIPT,
                "code": "async def run(page, board):\n    return []",
                "result_key": "pr_list",
            },
            executor=executor,
            validator=lambda contract, artifact, result, board, snapshot: ValidationResult(passed=True),
            snapshot_builder=lambda page: {"url": "https://github.com/example/repo/pulls", "title": "PRs"},
        )

        events = [
            event
            async for event in agent.run(
                session_id="s1",
                page=object(),
                goal="extract PRs",
                board=Blackboard(),
            )
        ]

        committed_events = [event for event in events if event["event"] == "agent_contract_committed_steps"]
        self.assertEqual(committed_events[-1]["data"]["contract_steps"][0]["contract"]["id"], "extract_pr_list_attempt_2")
        self.assertEqual(len(committed_events[-1]["data"]["display_steps"]), 1)


if __name__ == "__main__":
    unittest.main()
