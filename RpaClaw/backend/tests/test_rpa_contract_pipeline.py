import unittest

from backend.rpa.blackboard import Blackboard
from backend.rpa.contract_executor import ExecutionError, ExecutionResult
from backend.rpa.contract_models import ArtifactKind, ExecutionStrategy, FailureClass, RuntimePolicy, StepContract
from backend.rpa.contract_pipeline import ContractPipeline
from backend.rpa.contract_validator import ValidationResult


def _contract():
    return StepContract(
        id="step_1",
        description="Collect PRs",
        intent={"goal": "collect_prs"},
        target={"type": "visible_collection", "collection": "pull_requests"},
        operator={"type": "extract_repeated_records", "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT},
        outputs={"blackboard_key": "pr_list", "schema": {"type": "array"}},
        validation={"must": [{"type": "min_records", "key": "pr_list", "count": 1}]},
        runtime_policy=RuntimePolicy(requires_runtime_ai=False),
    )


class ContractPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_attempt_commits_contract_artifact_and_evidence(self):
        contract = _contract()
        artifact = {"kind": ArtifactKind.DETERMINISTIC_SCRIPT, "code": "async def run(page, board): return []"}

        async def executor(contract, artifact, page, board):
            board.write("pr_list", [{"title": "Fix"}])
            return ExecutionResult(success=True, output=[{"title": "Fix"}])

        pipeline = ContractPipeline(
            planner=lambda goal, snapshot, board: contract,
            compiler=lambda contract: artifact,
            executor=executor,
            validator=lambda contract, artifact, result, board, snapshot: ValidationResult(
                passed=True,
                evidence={"records": 1},
            ),
        )

        result = await pipeline.run_step("collect prs", page=object(), snapshot={}, board=Blackboard())

        self.assertTrue(result.success)
        self.assertEqual(len(pipeline.committed_steps), 1)
        self.assertIs(pipeline.committed_steps[0].contract, contract)
        self.assertEqual(pipeline.committed_steps[0].artifact, artifact)
        self.assertEqual(pipeline.committed_steps[0].validation_evidence, {"records": 1})

    async def test_artifact_failure_records_attempt_and_does_not_commit(self):
        pipeline = ContractPipeline(
            planner=lambda goal, snapshot, board: _contract(),
            compiler=lambda contract: (_ for _ in ()).throw(ValueError("bad artifact")),
            executor=None,
            validator=None,
        )

        result = await pipeline.run_step("collect prs", page=object(), snapshot={}, board=Blackboard())

        self.assertFalse(result.success)
        self.assertEqual(result.failure_class, FailureClass.ARTIFACT_FAILED)
        self.assertEqual(len(pipeline.attempts), 1)
        self.assertEqual(len(pipeline.committed_steps), 0)

    async def test_validation_failure_does_not_commit(self):
        async def executor(contract, artifact, page, board):
            return ExecutionResult(success=True, output=[])

        pipeline = ContractPipeline(
            planner=lambda goal, snapshot, board: _contract(),
            compiler=lambda contract: {"kind": ArtifactKind.DETERMINISTIC_SCRIPT, "code": "x"},
            executor=executor,
            validator=lambda contract, artifact, result, board, snapshot: ValidationResult(
                passed=False,
                failure_class=FailureClass.VALIDATION_FAILED,
                failure_type="min_records",
                message="empty list",
            ),
        )

        result = await pipeline.run_step("collect prs", page=object(), snapshot={}, board=Blackboard())

        self.assertFalse(result.success)
        self.assertEqual(result.failure_class, FailureClass.VALIDATION_FAILED)
        self.assertEqual(len(pipeline.committed_steps), 0)

    async def test_snapshot_stale_failure_requests_recapture_without_committing(self):
        async def executor(contract, artifact, page, board):
            return ExecutionResult(success=True)

        pipeline = ContractPipeline(
            planner=lambda goal, snapshot, board: _contract(),
            compiler=lambda contract: {"kind": ArtifactKind.PRIMITIVE_ACTION, "action": "click"},
            executor=executor,
            validator=lambda contract, artifact, result, board, snapshot: ValidationResult(
                passed=False,
                failure_class=FailureClass.SNAPSHOT_STALE,
                failure_type="snapshot_stale",
                message="page changed",
            ),
        )

        result = await pipeline.run_step("click", page=object(), snapshot={"snapshot_id": "old"}, board=Blackboard())

        self.assertFalse(result.success)
        self.assertTrue(result.recapture_required)
        self.assertEqual(len(pipeline.committed_steps), 0)


if __name__ == "__main__":
    unittest.main()
