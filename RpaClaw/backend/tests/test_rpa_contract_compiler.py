import asyncio
import unittest

from backend.rpa.contract_compiler import ContractCompiler
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


class ContractCompilerTests(unittest.TestCase):
    def test_compiles_primitive_navigate_with_blackboard_template(self):
        compiler = ContractCompiler()
        contract = _contract(
            ExecutionStrategy.PRIMITIVE_ACTION,
            "navigate",
            target={"type": "url", "url_template": "{selected_project.url}/pulls"},
            inputs={"refs": ["selected_project.url"]},
            validation={"must": [{"type": "url_contains", "value": "/pulls"}]},
        )

        artifact = compiler.compile(contract)

        self.assertEqual(artifact["kind"], ArtifactKind.PRIMITIVE_ACTION)
        self.assertEqual(artifact["action"], "goto")
        self.assertEqual(artifact["target_url_template"], "{selected_project.url}/pulls")
        self.assertEqual(artifact["input_refs"], ["selected_project.url"])

    def test_compiles_deterministic_numeric_ranking_script(self):
        compiler = ContractCompiler()
        contract = _contract(
            ExecutionStrategy.DETERMINISTIC_SCRIPT,
            "rank_collection_numeric_max",
            target={"type": "visible_collection", "collection": "github_trending_repositories"},
            operator={
                "type": "rank_collection_numeric_max",
                "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "selection_rule": {
                    "collection_selector": "article.Box-row",
                    "value_selector": 'a[href*="/stargazers"]',
                    "link_selector": "h2 a",
                    "url_prefix": "https://github.com",
                },
            },
            outputs={
                "blackboard_key": "selected_project",
                "schema": {"type": "object", "required": ["url"]},
            },
        )

        artifact = compiler.compile(contract)

        self.assertEqual(artifact["kind"], ArtifactKind.DETERMINISTIC_SCRIPT)
        self.assertEqual(artifact["result_key"], "selected_project")
        self.assertIn("async def run(page, board):", artifact["code"])
        self.assertIn("collection_selector = 'article.Box-row'", artifact["code"])
        self.assertIn('"name": title', artifact["code"])
        self.assertIn('"title": title', artifact["code"])
        self.assertNotIn("get_llm_model", artifact["code"])

    def test_numeric_ranking_output_shape_matches_required_name_schema(self):
        compiler = ContractCompiler()
        contract = _contract(
            ExecutionStrategy.DETERMINISTIC_SCRIPT,
            "rank_collection_numeric_max",
            target={"type": "visible_collection", "collection": "github_trending_repositories"},
            operator={
                "type": "rank_collection_numeric_max",
                "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "selection_rule": {
                    "collection_selector": "article.Box-row",
                    "value_selector": 'a[href*="/stargazers"]',
                    "link_selector": "h2 a",
                    "url_prefix": "https://github.com",
                },
            },
            outputs={
                "blackboard_key": "selected_project",
                "schema": {"type": "object", "required": ["name", "url", "score"]},
            },
        )

        artifact = compiler.compile(contract)

        self.assertIn('"name": title', artifact["code"])
        self.assertIn('"score": value', artifact["code"])

    def test_numeric_ranking_script_falls_back_to_issue_href_and_text_when_selectors_miss(self):
        compiler = ContractCompiler()
        contract = _contract(
            ExecutionStrategy.DETERMINISTIC_SCRIPT,
            "rank_collection_numeric_max",
            target={"type": "visible_collection", "collection": "github_issues"},
            operator={
                "type": "rank_collection_numeric_max",
                "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "selection_rule": {
                    "collection_selector": "[data-testid='issue-list-row']",
                    "value_selector": "span[data-testid='issue-number']",
                    "link_selector": "a[data-testid='issue-link']",
                    "url_prefix": "https://github.com",
                },
            },
            outputs={
                "blackboard_key": "latest_issue",
                "schema": {"type": "object", "required": ["name", "url", "score"]},
            },
        )
        artifact = compiler.compile(contract)

        class FakeLocator:
            def __init__(self, elements):
                self.elements = elements

            async def all(self):
                return self.elements

            @property
            def first(self):
                if not self.elements:
                    raise RuntimeError("strict locator matched no elements")
                return self.elements[0]

        class FakeElement:
            def __init__(self, text, href="", children=None):
                self.text = text
                self.href = href
                self.children = children or {}

            def locator(self, selector):
                return FakeLocator(self.children.get(selector, []))

            async def inner_text(self):
                return self.text

            async def get_attribute(self, name):
                return self.href if name == "href" else None

        issue_12 = FakeElement(
            "Bug fix regression #12 opened yesterday",
            children={
                'a[href*="/issues/"], a[href*="/pull/"]': [
                    FakeElement("Bug fix regression", "/ruvnet/RuView/issues/12")
                ]
            },
        )
        issue_15 = FakeElement(
            "Newest feature request #15 opened today",
            children={
                'a[href*="/issues/"], a[href*="/pull/"]': [
                    FakeElement("Newest feature request", "/ruvnet/RuView/issues/15")
                ]
            },
        )

        class FakePage:
            def locator(self, selector):
                if selector == "[data-testid='issue-list-row']":
                    return FakeLocator([])
                if selector == "article.Box-row, .Box-row, div.js-issue-row, [id^='issue_'], [aria-label*='Issue'], [aria-label*='Pull request']":
                    return FakeLocator([issue_12, issue_15])
                return FakeLocator([])

        namespace = {}
        exec(artifact["code"], namespace, namespace)
        result = asyncio.run(namespace["run"](FakePage(), object()))

        self.assertEqual(result["name"], "Newest feature request")
        self.assertEqual(result["url"], "https://github.com/ruvnet/RuView/issues/15")
        self.assertEqual(result["score"], 15.0)

    def test_numeric_ranking_fallback_prefers_issue_number_from_href_over_row_text(self):
        compiler = ContractCompiler()
        contract = _contract(
            ExecutionStrategy.DETERMINISTIC_SCRIPT,
            "rank_collection_numeric_max",
            target={"type": "visible_collection", "collection": "github_issues"},
            operator={
                "type": "rank_collection_numeric_max",
                "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "selection_rule": {
                    "collection_selector": "[data-testid='issue-list-row']",
                    "value_selector": "span[data-testid='issue-number']",
                    "link_selector": "a[data-testid='issue-link']",
                    "url_prefix": "https://github.com",
                },
            },
            outputs={
                "blackboard_key": "latest_issue",
                "schema": {"type": "object", "required": ["name", "url", "score"]},
            },
        )
        artifact = compiler.compile(contract)

        class FakeLocator:
            def __init__(self, elements):
                self.elements = elements

            async def all(self):
                return self.elements

            @property
            def first(self):
                if not self.elements:
                    raise RuntimeError("strict locator matched no elements")
                return self.elements[0]

        class FakeElement:
            def __init__(self, text, href="", children=None):
                self.text = text
                self.href = href
                self.children = children or {}

            def locator(self, selector):
                return FakeLocator(self.children.get(selector, []))

            async def inner_text(self):
                return self.text

            async def get_attribute(self, name):
                return self.href if name == "href" else None

        issue_2_with_comment_count = FakeElement(
            "Old issue 99 comments",
            children={
                'a[href*="/issues/"], a[href*="/pull/"]': [
                    FakeElement("Old issue", "/ruvnet/RuView/issues/2")
                ]
            },
        )
        issue_10 = FakeElement(
            "New issue 1 comment",
            children={
                'a[href*="/issues/"], a[href*="/pull/"]': [
                    FakeElement("New issue", "/ruvnet/RuView/issues/10")
                ]
            },
        )

        class FakePage:
            def locator(self, selector):
                if selector == "[data-testid='issue-list-row']":
                    return FakeLocator([])
                if selector == "article.Box-row, .Box-row, div.js-issue-row, [id^='issue_'], [aria-label*='Issue'], [aria-label*='Pull request']":
                    return FakeLocator([issue_2_with_comment_count, issue_10])
                return FakeLocator([])

        namespace = {}
        exec(artifact["code"], namespace, namespace)
        result = asyncio.run(namespace["run"](FakePage(), object()))

        self.assertEqual(result["name"], "New issue")
        self.assertEqual(result["url"], "https://github.com/ruvnet/RuView/issues/10")
        self.assertEqual(result["score"], 10.0)

    def test_compiles_deterministic_repeated_record_extraction_script(self):
        compiler = ContractCompiler()
        contract = _contract(
            ExecutionStrategy.DETERMINISTIC_SCRIPT,
            "extract_repeated_records",
            target={"type": "visible_collection", "collection": "pull_requests"},
            operator={
                "type": "extract_repeated_records",
                "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "selection_rule": {
                    "row_selector": ".js-issue-row",
                    "limit": 10,
                    "fields": {
                        "title": {"selector": 'a[id^="issue_"]'},
                        "creator": {"selector": 'a[href*="author%3A"]'},
                    },
                },
            },
            outputs={
                "blackboard_key": "pr_list",
                "schema": {
                    "type": "array",
                    "items": {"required": ["title", "creator"]},
                },
            },
        )

        artifact = compiler.compile(contract)

        self.assertEqual(artifact["kind"], ArtifactKind.DETERMINISTIC_SCRIPT)
        self.assertEqual(artifact["result_key"], "pr_list")
        self.assertIn("row_selector = '.js-issue-row'", artifact["code"])
        self.assertIn("fields = {", artifact["code"])
        self.assertIn("AI script returned an empty record array", artifact["code"])

    def test_repeated_record_extraction_can_explicitly_allow_empty_results(self):
        compiler = ContractCompiler()
        contract = _contract(
            ExecutionStrategy.DETERMINISTIC_SCRIPT,
            "extract_repeated_records",
            target={"type": "visible_collection", "collection": "pull_requests"},
            operator={
                "type": "extract_repeated_records",
                "execution_strategy": ExecutionStrategy.DETERMINISTIC_SCRIPT,
                "selection_rule": {
                    "row_selector": ".js-issue-row",
                    "limit": 10,
                    "allow_empty": True,
                    "fields": {
                        "title": {"selector": 'a[id^="issue_"]'},
                    },
                },
            },
            outputs={"blackboard_key": "pr_list", "schema": {"type": "array"}},
        )

        artifact = compiler.compile(contract)

        self.assertIn("allow_empty = True", artifact["code"])

    def test_compiles_runtime_semantic_select_with_structured_output(self):
        compiler = ContractCompiler()
        contract = _contract(
            ExecutionStrategy.RUNTIME_AI,
            "runtime_semantic_select",
            description="打开和 SKILL 最相关的项目",
            intent={"goal": "打开 https://github.com/trending，找到和 SKILL 最相关的项目并打开它"},
            target={"type": "visible_collection", "collection": "github_trending_repositories"},
            outputs={
                "blackboard_key": "selected_project",
                "schema": {
                    "type": "object",
                    "properties": {"repo_url": {"type": "string"}, "reason": {"type": "string"}},
                    "required": ["repo_url", "reason"],
                },
            },
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="Semantic relevance is required",
            ),
        )

        artifact = compiler.compile(contract)

        self.assertEqual(artifact["kind"], ArtifactKind.RUNTIME_AI)
        self.assertEqual(artifact["result_key"], "selected_project")
        self.assertIn("selected_project", artifact["prompt"])
        self.assertIn("repo_url", artifact["prompt"])
        self.assertIn("SKILL", artifact["global_goal"])
        self.assertFalse(artifact["allow_side_effect"])

    def test_compiles_runtime_ai_blackboard_ref_prompt_with_input_refs(self):
        compiler = ContractCompiler()
        contract = _contract(
            ExecutionStrategy.RUNTIME_AI,
            "semantic_filter",
            description="Global SOP text that should not dominate the runtime prompt",
            intent={"goal": "Filter the extracted trending_repos blackboard data to keep only SKILL-related repositories"},
            inputs={"refs": ["trending_repos"]},
            target={"type": "blackboard_ref"},
            outputs={
                "blackboard_key": "skill_repos",
                "schema": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}, "url": {"type": "string"}},
                    },
                },
            },
            runtime_policy=RuntimePolicy(
                requires_runtime_ai=True,
                runtime_ai_reason="Semantic relevance is required",
            ),
        )

        artifact = compiler.compile(contract)

        self.assertEqual(artifact["input_scope"]["mode"], "blackboard_ref")
        self.assertEqual(artifact["input_refs"], ["trending_repos"])
        self.assertIn("trending_repos", artifact["prompt"])
        self.assertIn("Filter the extracted trending_repos blackboard data", artifact["prompt"])


if __name__ == "__main__":
    unittest.main()
