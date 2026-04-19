import json
import sys
import types
import unittest
from datetime import datetime, timedelta

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
from backend.rpa.contract_session import (
    apply_session_contract_committed_steps,
    build_contract_skill_files_from_session,
    session_contract_committed_steps,
)
from backend.rpa.manager import RPASession, RPAStep


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

    def test_applying_cumulative_committed_steps_replaces_instead_of_duplicating(self):
        contract = StepContract(
            id="step_1",
            source="ai",
            description="Open PRs",
            intent={"goal": "open_prs"},
            inputs={"refs": []},
            target={"type": "url", "url_template": "https://github.com/a/b/pulls"},
            operator={"type": "navigate", "execution_strategy": ExecutionStrategy.PRIMITIVE_ACTION},
            outputs={"blackboard_key": None, "schema": None},
            validation={"must": []},
            runtime_policy=RuntimePolicy(requires_runtime_ai=False),
        )
        session = RPASession(id="s1", user_id="u1", sandbox_session_id="sandbox")
        payload = {
            "contract": contract.model_dump(by_alias=True),
            "artifact": {
                "kind": ArtifactKind.PRIMITIVE_ACTION,
                "action": "goto",
                "target_url_template": "https://github.com/a/b/pulls",
            },
            "validation_evidence": {},
        }

        apply_session_contract_committed_steps(session, [payload])
        apply_session_contract_committed_steps(session, [payload])

        self.assertEqual(len(session.contract_steps), 1)

    def test_applying_committed_steps_merges_across_multiple_chat_turns(self):
        first_contract = StepContract(
            id="step_select_project",
            source="ai",
            description="Select project",
            intent={"goal": "select_project"},
            inputs={"refs": ["trending_projects"]},
            target={"type": "blackboard_ref"},
            operator={"type": "semantic_select", "execution_strategy": ExecutionStrategy.RUNTIME_AI},
            outputs={
                "blackboard_key": "selected_project",
                "schema": {"type": "object", "required": ["url"]},
            },
            validation={"must": [{"type": "blackboard_key", "key": "selected_project.url"}]},
            runtime_policy=RuntimePolicy(requires_runtime_ai=True, runtime_ai_reason="semantic selection"),
        )
        second_contract = StepContract(
            id="step_extract_prs",
            source="ai",
            description="Extract PRs",
            intent={"goal": "extract_prs"},
            target={"type": "page"},
            operator={
                "type": "extract_repeated_records",
                "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "selection_rule": {
                    "row_selector": "div.js-issue-row",
                    "fields": {"title": {"selector": "a.js-navigation-open"}},
                },
            },
            outputs={
                "blackboard_key": "pr_list",
                "schema": {"type": "array"},
            },
            validation={"must": [{"type": "min_records", "count": 1}]},
            runtime_policy=RuntimePolicy(requires_runtime_ai=False),
        )
        session = RPASession(id="s1", user_id="u1", sandbox_session_id="sandbox")

        apply_session_contract_committed_steps(
            session,
            [
                {
                    "contract": first_contract.model_dump(by_alias=True),
                    "artifact": {
                        "kind": ArtifactKind.RUNTIME_AI,
                        "prompt": "select project",
                        "output_schema": {"type": "object", "required": ["url"]},
                        "result_key": "selected_project",
                    },
                    "validation_evidence": {},
                }
            ],
        )
        apply_session_contract_committed_steps(
            session,
            [
                {
                    "contract": second_contract.model_dump(by_alias=True),
                    "artifact": {
                        "kind": ArtifactKind.DETERMINISTIC_SCRIPT,
                        "result_key": "pr_list",
                        "code": "async def run(page, board):\n    return []",
                    },
                    "validation_evidence": {},
                }
            ],
        )

        self.assertEqual(
            [item["contract"]["id"] for item in session.contract_steps],
            ["step_select_project", "step_extract_prs"],
        )

    def test_applying_committed_steps_replaces_same_output_key_retry(self):
        def contract_payload(step_id: str):
            return StepContract(
                id=step_id,
                source="ai",
                description="Extract PRs",
                intent={"goal": "extract_prs"},
                target={"type": "page"},
                operator={
                    "type": "extract_repeated_records",
                    "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                    "selection_rule": {
                        "row_selector": "div.js-issue-row",
                        "fields": {"title": {"selector": "a.js-navigation-open"}},
                    },
                },
                outputs={"blackboard_key": "pr_list", "schema": {"type": "array"}},
                validation={"must": [{"type": "min_records", "count": 1}]},
                runtime_policy=RuntimePolicy(requires_runtime_ai=False),
            ).model_dump(by_alias=True)

        session = RPASession(id="s1", user_id="u1", sandbox_session_id="sandbox")

        apply_session_contract_committed_steps(
            session,
            [
                {
                    "contract": contract_payload("extract_pr_list_attempt_1"),
                    "artifact": {
                        "kind": ArtifactKind.DETERMINISTIC_SCRIPT,
                        "result_key": "pr_list",
                        "code": "async def run(page, board):\n    return []",
                    },
                    "validation_evidence": {},
                }
            ],
        )
        apply_session_contract_committed_steps(
            session,
            [
                {
                    "contract": contract_payload("extract_pr_list_attempt_2"),
                    "artifact": {
                        "kind": ArtifactKind.DETERMINISTIC_SCRIPT,
                        "result_key": "pr_list",
                        "code": "async def run(page, board):\n    return [{'title': 'fixed'}]",
                    },
                    "validation_evidence": {},
                }
            ],
        )

        self.assertEqual(len(session.contract_steps), 1)
        self.assertEqual(session.contract_steps[0]["contract"]["id"], "extract_pr_list_attempt_2")

    def test_session_contract_committed_steps_keeps_manual_and_ai_step_order(self):
        ai_contract = StepContract(
            id="step_ai",
            source="ai",
            description="打开仓库",
            intent={"goal": "open_repo"},
            inputs={"refs": []},
            target={"type": "url", "url_template": "https://github.com/org/repo"},
            operator={"type": "navigate", "execution_strategy": ExecutionStrategy.PRIMITIVE_ACTION},
            outputs={"blackboard_key": None, "schema": None},
            validation={"must": []},
            runtime_policy=RuntimePolicy(requires_runtime_ai=False),
        )
        session = RPASession(
            id="s1",
            user_id="u1",
            sandbox_session_id="sandbox",
            steps=[
                RPAStep(
                    id="display-ai",
                    action="contract_step",
                    source="ai",
                    description="打开仓库",
                    assistant_diagnostics={"contract_id": "step_ai"},
                ),
                RPAStep(
                    id="manual-click",
                    action="click",
                    source="record",
                    description="点击 Pull requests",
                    locator_candidates=[
                        {
                            "selected": True,
                            "locator": {"method": "role", "role": "link", "name": "Pull requests", "exact": False},
                            "strict_match_count": 1,
                        }
                    ],
                    validation={"url_contains": "/pulls"},
                    url="https://github.com/org/repo",
                ),
            ],
            contract_steps=[
                {
                    "contract": ai_contract.model_dump(by_alias=True),
                    "artifact": {
                        "kind": ArtifactKind.PRIMITIVE_ACTION,
                        "action": "goto",
                        "target_url_template": "https://github.com/org/repo",
                    },
                    "validation_evidence": {},
                }
            ],
        )

        committed = session_contract_committed_steps(session)

        self.assertEqual([step.contract.source.value for step in committed], ["ai", "manual"])
        self.assertEqual(committed[1].artifact["action"], "click")

    def test_build_contract_skill_from_multi_turn_session_preserves_selected_project_dataflow(self):
        select_contract = StepContract(
            id="step_select_project",
            source="ai",
            description="Select the Python-related repo",
            intent={"goal": "select_project"},
            inputs={"refs": ["trending_projects"]},
            target={"type": "blackboard_ref"},
            operator={"type": "semantic_select", "execution_strategy": ExecutionStrategy.RUNTIME_AI},
            outputs={
                "blackboard_key": "selected_project",
                "schema": {"type": "object", "required": ["url"]},
            },
            validation={"must": [{"type": "blackboard_key", "key": "selected_project.url"}]},
            runtime_policy=RuntimePolicy(requires_runtime_ai=True, runtime_ai_reason="semantic relevance"),
        )
        extract_contract = StepContract(
            id="step_extract_prs",
            source="ai",
            description="Collect the first 10 PRs",
            intent={"goal": "extract_prs"},
            target={"type": "page"},
            operator={
                "type": "extract_repeated_records",
                "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "selection_rule": {
                    "row_selector": "div.js-issue-row",
                    "fields": {
                        "title": {"selector": "a.js-navigation-open"},
                        "creator": {"selector": "a[data-hovercard-type='user']"},
                    },
                },
            },
            outputs={
                "blackboard_key": "pr_list",
                "schema": {"type": "array"},
            },
            validation={"must": [{"type": "min_records", "count": 1}]},
            runtime_policy=RuntimePolicy(requires_runtime_ai=False),
        )
        session = RPASession(
            id="s1",
            user_id="u1",
            sandbox_session_id="sandbox",
            steps=[
                RPAStep(
                    id="display-select",
                    action="contract_step",
                    source="ai",
                    description="Select the Python-related repo",
                    assistant_diagnostics={"contract_id": "step_select_project"},
                ),
                RPAStep(
                    id="manual-pulls",
                    action="navigate",
                    source="record",
                    description="导航到 Pull requests 页面",
                    url="https://github.com/openai/openai-agents-python/pulls?q=is%3Apr",
                ),
                RPAStep(
                    id="display-extract",
                    action="contract_step",
                    source="ai",
                    description="Collect the first 10 PRs",
                    assistant_diagnostics={"contract_id": "step_extract_prs"},
                ),
            ],
            contract_steps=[
                {
                    "contract": select_contract.model_dump(by_alias=True),
                    "artifact": {
                        "kind": ArtifactKind.RUNTIME_AI,
                        "prompt": "select project",
                        "output_schema": {"type": "object", "required": ["url"]},
                        "result_key": "selected_project",
                    },
                    "validation_evidence": {},
                },
                {
                    "contract": extract_contract.model_dump(by_alias=True),
                    "artifact": {
                        "kind": ArtifactKind.DETERMINISTIC_SCRIPT,
                        "result_key": "pr_list",
                        "code": "async def run(page, board):\n    return []",
                    },
                    "validation_evidence": {},
                },
            ],
            contract_blackboard={
                "selected_project": {
                    "url": "https://github.com/openai/openai-agents-python",
                    "name": "openai/openai-agents-python",
                }
            },
        )

        files = build_contract_skill_files_from_session(session, "skill", "desc")

        self.assertIn("selected_project", files["skill.py"])
        self.assertIn(
            "resolve_template('{selected_project.url}/pulls?q=is%3Apr', board)",
            files["skill.py"],
        )
        self.assertNotIn(
            "https://github.com/openai/openai-agents-python/pulls?q=is%3Apr",
            files["skill.py"],
        )

    def test_build_contract_skill_orders_late_manual_step_by_event_time(self):
        select_contract = StepContract(
            id="step_select_project",
            source="ai",
            description="Select the Python-related repo",
            intent={"goal": "select_project"},
            target={"type": "page"},
            operator={"type": "semantic_select", "execution_strategy": ExecutionStrategy.RUNTIME_AI},
            outputs={
                "blackboard_key": "selected_python_project",
                "schema": {"type": "object", "required": ["url"]},
            },
            validation={"must": [{"type": "blackboard_key", "key": "selected_python_project.url"}]},
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="semantic selection",
                allow_side_effect=True,
                side_effect_reason="open selected project",
            ),
        )
        extract_contract = StepContract(
            id="step_extract_prs",
            source="ai",
            description="Collect the first 10 PRs",
            intent={"goal": "extract_prs"},
            target={"type": "page"},
            operator={
                "type": "extract_repeated_records",
                "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "selection_rule": {
                    "row_selector": ".js-issue-row",
                    "fields": {
                        "title": {"selector": "a.Link--primary"},
                        "creator": {"selector": "a[data-hovercard-type='user']"},
                    },
                },
            },
            outputs={"blackboard_key": "top10_prs", "schema": {"type": "array"}},
            validation={"must": [{"type": "min_records", "count": 1}]},
            runtime_policy=RuntimePolicy(requires_runtime_ai=False),
        )
        session = RPASession(
            id="s1",
            user_id="u1",
            sandbox_session_id="sandbox",
            steps=[
                RPAStep(
                    id="display-select",
                    action="contract_step",
                    source="ai",
                    description="Select the Python-related repo",
                    timestamp=datetime(2026, 1, 1),
                    assistant_diagnostics={"contract_id": "step_select_project"},
                ),
                RPAStep(
                    id="display-extract",
                    action="contract_step",
                    source="ai",
                    description="Collect the first 10 PRs",
                    timestamp=datetime(2026, 1, 1) + timedelta(seconds=2),
                    assistant_diagnostics={"contract_id": "step_extract_prs"},
                ),
                RPAStep(
                    id="manual-pulls",
                    action="navigate",
                    source="record",
                    description="Navigate to Pull requests",
                    url="https://github.com/openai/openai-agents-python/pulls?q=is%3Apr+sort%3Acreated-desc",
                    timestamp=datetime(2026, 1, 1) + timedelta(seconds=3),
                    event_timestamp_ms=int((datetime(2026, 1, 1) + timedelta(seconds=1)).timestamp() * 1000),
                ),
            ],
            contract_steps=[
                {
                    "contract": select_contract.model_dump(by_alias=True),
                    "artifact": {
                        "kind": ArtifactKind.RUNTIME_AI,
                        "prompt": "select and open project",
                        "output_mode": "act",
                        "allow_side_effect": True,
                        "output_schema": {"type": "object", "required": ["url"]},
                        "result_key": "selected_python_project",
                    },
                    "validation_evidence": {},
                },
                {
                    "contract": extract_contract.model_dump(by_alias=True),
                    "artifact": {
                        "kind": ArtifactKind.DETERMINISTIC_SCRIPT,
                        "result_key": "top10_prs",
                        "code": "async def run(page, board):\n    return []",
                    },
                    "validation_evidence": {},
                },
            ],
            contract_blackboard={
                "selected_python_project": {
                    "url": "https://github.com/openai/openai-agents-python",
                    "name": "openai/openai-agents-python",
                }
            },
        )

        committed = session_contract_committed_steps(session)
        files = build_contract_skill_files_from_session(session, "skill", "desc")
        navigate_index = files["skill.py"].index("resolve_template('{selected_python_project.url}/pulls")
        extract_index = files["skill.py"].index("board.write('top10_prs', _result)")

        self.assertEqual(
            [step.contract.id for step in committed],
            ["step_select_project", "manual-pulls", "step_extract_prs"],
        )
        self.assertLess(navigate_index, extract_index)

    def test_build_contract_skill_preserves_manual_navigation_click_before_later_extract(self):
        select_contract = StepContract(
            id="select_python_related_project",
            source="ai",
            description="Open Python-related project",
            intent={"goal": "open_python_project"},
            target={"type": "page"},
            operator={"type": "semantic_select", "execution_strategy": ExecutionStrategy.RUNTIME_AI},
            outputs={
                "blackboard_key": "selected_python_project",
                "schema": {"type": "object", "required": ["url"]},
            },
            validation={"must": [{"type": "blackboard_key", "key": "selected_python_project.url"}]},
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="semantic relevance",
                allow_side_effect=True,
                side_effect_reason="open selected project",
            ),
        )
        extract_contract = StepContract(
            id="extract_top10_prs",
            source="ai",
            description="Collect the first 10 PRs",
            intent={"goal": "extract_prs"},
            target={"type": "page"},
            operator={
                "type": "extract_repeated_records",
                "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "selection_rule": {
                    "row_selector": ".js-issue-row",
                    "fields": {
                        "title": {"selector": "a.Link--primary"},
                        "creator": {"selector": "a[data-hovercard-type='user']"},
                    },
                },
            },
            outputs={"blackboard_key": "top10_prs", "schema": {"type": "array"}},
            validation={"must": [{"type": "min_records", "count": 1}]},
            runtime_policy=RuntimePolicy(requires_runtime_ai=False),
        )
        selected_url = "https://github.com/openai/openai-agents-python"
        base_time = datetime(2026, 1, 1)
        session = RPASession(
            id="s1",
            user_id="u1",
            sandbox_session_id="sandbox",
            steps=[
                RPAStep(
                    id="display-select",
                    action="contract_step",
                    source="ai",
                    description="Open Python-related project",
                    event_timestamp_ms=int(base_time.timestamp() * 1000),
                    assistant_diagnostics={"contract_id": "select_python_related_project"},
                ),
                RPAStep(
                    id="manual-pulls",
                    action="navigate_click",
                    source="record",
                    description="Click Pull requests and navigate",
                    url=f"{selected_url}/pulls?q=is%3Apr",
                    event_timestamp_ms=int((base_time + timedelta(seconds=1)).timestamp() * 1000),
                    locator_candidates=[
                        {
                            "selected": True,
                            "locator": {"method": "role", "role": "link", "name": "Pull requests", "exact": False},
                        }
                    ],
                    validation={"url_contains": "/pulls"},
                ),
                RPAStep(
                    id="display-extract",
                    action="contract_step",
                    source="ai",
                    description="Collect the first 10 PRs",
                    event_timestamp_ms=int((base_time + timedelta(seconds=2)).timestamp() * 1000),
                    assistant_diagnostics={"contract_id": "extract_top10_prs"},
                ),
            ],
            contract_steps=[
                {
                    "contract": select_contract.model_dump(by_alias=True),
                    "artifact": {
                        "kind": ArtifactKind.RUNTIME_AI,
                        "prompt": "open selected project",
                        "output_mode": "act",
                        "allow_side_effect": True,
                        "output_schema": {"type": "object", "required": ["url"]},
                        "result_key": "selected_python_project",
                    },
                    "validation_evidence": {},
                },
                {
                    "contract": extract_contract.model_dump(by_alias=True),
                    "artifact": {
                        "kind": ArtifactKind.DETERMINISTIC_SCRIPT,
                        "result_key": "top10_prs",
                        "code": "async def run(page, board):\n    return []",
                    },
                    "validation_evidence": {},
                },
            ],
            contract_blackboard={
                "selected_python_project": {
                    "value": selected_url,
                    "url": selected_url,
                    "name": "openai/openai-agents-python",
                }
            },
        )

        committed = session_contract_committed_steps(session)
        files = build_contract_skill_files_from_session(session, "skill", "desc")

        self.assertEqual(
            [step.contract.id for step in committed],
            ["select_python_related_project", "manual-pulls", "extract_top10_prs"],
        )
        navigate_index = files["skill.py"].index("resolve_template('{selected_python_project.url}/pulls")
        extract_index = files["skill.py"].index("board.write('top10_prs', _result)")
        self.assertLess(navigate_index, extract_index)
        self.assertNotIn("selected_python_project.value", files["skill.py"])
        self.assertNotIn(f"{selected_url}/pulls", files["skill.py"])

    def test_build_contract_skill_generalizes_exact_selected_project_navigation(self):
        navigate_contract = StepContract(
            id="navigate_python_project",
            source="ai",
            description="Open selected Python project",
            intent={"goal": "open_selected_project"},
            target={"type": "url", "url_template": "https://github.com/openai/openai-agents-python"},
            operator={"type": "navigate", "execution_strategy": ExecutionStrategy.PRIMITIVE_ACTION},
            outputs={"blackboard_key": None, "schema": None},
            validation={"must": []},
            runtime_policy=RuntimePolicy(requires_runtime_ai=False),
        )
        session = RPASession(
            id="s1",
            user_id="u1",
            sandbox_session_id="sandbox",
            steps=[
                RPAStep(
                    id="display-navigate",
                    action="contract_step",
                    source="ai",
                    description="Open selected Python project",
                    assistant_diagnostics={"contract_id": "navigate_python_project"},
                ),
            ],
            contract_steps=[
                {
                    "contract": navigate_contract.model_dump(by_alias=True),
                    "artifact": {
                        "kind": ArtifactKind.PRIMITIVE_ACTION,
                        "action": "goto",
                        "target_url_template": "https://github.com/openai/openai-agents-python",
                    },
                    "validation_evidence": {},
                }
            ],
            contract_blackboard={
                "selected_python_project": {
                    "url": "https://github.com/openai/openai-agents-python",
                    "name": "openai/openai-agents-python",
                }
            },
        )

        files = build_contract_skill_files_from_session(session, "skill", "desc")

        self.assertIn("resolve_template('{selected_python_project.url}', board)", files["skill.py"])
        self.assertNotIn("resolve_template('https://github.com/openai/openai-agents-python'", files["skill.py"])

    def test_runtime_ai_action_drops_redundant_exact_followup_navigation(self):
        select_contract = StepContract(
            id="select_python_related_project",
            source="ai",
            description="Open Python-related project",
            intent={"goal": "open_python_project"},
            target={"type": "page"},
            operator={"type": "semantic_select", "execution_strategy": ExecutionStrategy.RUNTIME_AI},
            outputs={
                "blackboard_key": "selected_python_project",
                "schema": {"type": "object", "required": ["url"]},
            },
            validation={"must": [{"type": "blackboard_key", "key": "selected_python_project.url"}]},
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="semantic relevance",
                allow_side_effect=True,
                side_effect_reason="open selected project",
            ),
        )
        navigate_contract = StepContract(
            id="navigate_python_project",
            source="ai",
            description="Open selected Python project",
            intent={"goal": "open_selected_project"},
            target={"type": "url", "url_template": "https://github.com/openai/openai-agents-python"},
            operator={"type": "navigate", "execution_strategy": ExecutionStrategy.PRIMITIVE_ACTION},
            outputs={"blackboard_key": None, "schema": None},
            validation={"must": []},
            runtime_policy=RuntimePolicy(requires_runtime_ai=False),
        )
        session = RPASession(
            id="s1",
            user_id="u1",
            sandbox_session_id="sandbox",
            steps=[
                RPAStep(
                    id="display-select",
                    action="contract_step",
                    source="ai",
                    description="Open Python-related project",
                    assistant_diagnostics={"contract_id": "select_python_related_project"},
                ),
                RPAStep(
                    id="display-navigate",
                    action="contract_step",
                    source="ai",
                    description="Open selected Python project",
                    assistant_diagnostics={"contract_id": "navigate_python_project"},
                ),
            ],
            contract_steps=[
                {
                    "contract": select_contract.model_dump(by_alias=True),
                    "artifact": {
                        "kind": ArtifactKind.RUNTIME_AI,
                        "prompt": "open selected project",
                        "output_mode": "act",
                        "output_schema": {"type": "object", "required": ["url"]},
                        "result_key": "selected_python_project",
                        "allow_side_effect": True,
                    },
                    "validation_evidence": {},
                },
                {
                    "contract": navigate_contract.model_dump(by_alias=True),
                    "artifact": {
                        "kind": ArtifactKind.PRIMITIVE_ACTION,
                        "action": "goto",
                        "target_url_template": "https://github.com/openai/openai-agents-python",
                    },
                    "validation_evidence": {},
                },
            ],
            contract_blackboard={
                "selected_python_project": {
                    "url": "https://github.com/openai/openai-agents-python",
                    "name": "openai/openai-agents-python",
                }
            },
        )

        committed = session_contract_committed_steps(session)
        files = build_contract_skill_files_from_session(session, "skill", "desc")

        self.assertEqual([step.contract.id for step in committed], ["select_python_related_project"])
        self.assertNotIn("navigate_python_project", files["skill.py"])


if __name__ == "__main__":
    unittest.main()
