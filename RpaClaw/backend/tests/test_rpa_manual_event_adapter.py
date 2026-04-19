import unittest

from backend.rpa.contract_models import ExecutionStrategy
from backend.rpa.manual_event_adapter import adapt_manual_event_to_committed_step


class ManualEventAdapterTests(unittest.TestCase):
    def test_manual_click_event_becomes_primitive_contract(self):
        event = {
            "id": "manual-click-1",
            "action": "click",
            "description": "点击 Pull requests",
            "locator_candidates": [
                {
                    "selected": True,
                    "locator": {"method": "role", "role": "link", "name": "Pull requests", "exact": False},
                    "strict_match_count": 1,
                }
            ],
            "validation": {"url_contains": "/pulls"},
            "url": "https://github.com/org/repo",
        }

        committed = adapt_manual_event_to_committed_step(event)

        self.assertEqual(committed.contract.source.value, "manual")
        self.assertEqual(committed.contract.operator.execution_strategy, ExecutionStrategy.PRIMITIVE_ACTION)
        self.assertEqual(committed.artifact["action"], "click")
        self.assertEqual(committed.artifact["locator"]["role"], "link")
        self.assertEqual(committed.validation_evidence["source"], "manual")

    def test_manual_navigation_event_becomes_goto_artifact(self):
        event = {
            "id": "manual-nav-1",
            "action": "navigate",
            "description": "导航到 Pull requests 页面",
            "url": "https://github.com/org/repo/pulls",
        }

        committed = adapt_manual_event_to_committed_step(event)

        self.assertEqual(committed.contract.source.value, "manual")
        self.assertEqual(committed.artifact["action"], "goto")
        self.assertEqual(committed.artifact["target_url_template"], "https://github.com/org/repo/pulls")
        self.assertEqual(committed.contract.validation.must[0]["type"], "url_contains")


if __name__ == "__main__":
    unittest.main()
