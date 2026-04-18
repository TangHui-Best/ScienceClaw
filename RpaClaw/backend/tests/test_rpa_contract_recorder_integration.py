import json
import sys
import types
import unittest

playwright_module = types.ModuleType("playwright")
async_api_module = types.ModuleType("playwright.async_api")
async_api_module.Page = object
async_api_module.BrowserContext = object
async_api_module.Browser = object
async_api_module.Playwright = object
async_api_module.async_playwright = object
sys.modules.setdefault("playwright", playwright_module)
sys.modules.setdefault("playwright.async_api", async_api_module)

from backend.rpa.contract_models import ArtifactKind, ExecutionStrategy, RuntimePolicy, StepContract
from backend.rpa.contract_pipeline import CommittedStep
from backend.rpa.contract_session import build_contract_skill_files_from_session, session_contract_committed_steps
from backend.rpa.manager import RPASession


class ContractRecorderIntegrationTests(unittest.TestCase):
    def test_session_can_carry_contract_first_committed_steps(self):
        session = RPASession(id="s1", user_id="u1", sandbox_session_id="sandbox")

        self.assertEqual(session.contract_steps, [])
        self.assertEqual(session.contract_blackboard, {})

    def test_route_builds_contract_skill_from_session_steps(self):
        contract = StepContract(
            id="step_1",
            description="Open PRs",
            intent={"goal": "open_prs"},
            inputs={"refs": ["selected_project.url"]},
            target={"type": "url", "url_template": "{selected_project.url}/pulls"},
            operator={"type": "navigate", "execution_strategy": ExecutionStrategy.PRIMITIVE_ACTION},
            outputs={"blackboard_key": None, "schema": None},
            validation={"must": [{"type": "url_contains", "value": "/pulls"}]},
            runtime_policy=RuntimePolicy(requires_runtime_ai=False),
        )
        session = RPASession(
            id="s1",
            user_id="u1",
            sandbox_session_id="sandbox",
            contract_steps=[
                {
                    "contract": contract.model_dump(by_alias=True),
                    "artifact": {
                        "kind": ArtifactKind.PRIMITIVE_ACTION,
                        "action": "goto",
                        "target_url_template": "{selected_project.url}/pulls",
                    },
                    "validation_evidence": {"url": "https://github.com/a/b/pulls"},
                }
            ],
        )

        committed = session_contract_committed_steps(session)
        files = build_contract_skill_files_from_session(session, "skill", "desc")
        manifest = json.loads(files["skill.contract.json"])

        self.assertIsInstance(committed[0], CommittedStep)
        self.assertIn("resolve_template('{selected_project.url}/pulls', board)", files["skill.py"])
        self.assertEqual(manifest["steps"][0]["contract_id"], "step_1")


if __name__ == "__main__":
    unittest.main()
